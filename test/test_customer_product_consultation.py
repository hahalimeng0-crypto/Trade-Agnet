import asyncio
import json
from types import SimpleNamespace

import pytest

import main
from agent.access_control.models import Principal
from agent.customer_product.cache import InMemoryProductCache
from agent.customer_product.context import CustomerContextBinding
from agent.customer_product.rag import PermissionAwareRagRetriever
from agent.customer_product.service import ProductQueryError, ProductQueryService
from agent.customer_product.shipping import SFInternationalProvider
from agent.tools.customer_product import (
    CompareProductsTool,
    GetProductDetailsTool,
    SearchProductsTool,
)
from providers.base import LLMResponse, ToolCallRequest
from trade_rag.chunking import ParentChildSplitter
from trade_rag.contracts import CanonicalDocument, DocumentStatus


class PublicRag:
    async def search(self, context, query, *, product_skus=(), top_k=3):
        return {
            "status": "ANSWERED",
            "answer": f"public information for {','.join(product_skus)}",
            "citations": [{"document_id": "public-doc", "version": 2, "source": "manual"}],
        }


def product(sku: str, *, price: float, inventory: int, specification: str):
    return SimpleNamespace(
        sku=sku,
        name_en=f"Product {sku}",
        name_cn="",
        category="widget",
        specification=specification,
        unit="pcs",
        moq=100,
        price_usd=price,
        weight_kg=1.25,
        package_info="10 pcs/carton",
        inventory=inventory,
        lead_time_days=15,
        active=True,
        updated_at="2026-08-25T00:00:00Z",
    )


def binding(*, account="customer-a", level="standard", tenant="default"):
    value = CustomerContextBinding(
        customer_level=level,
        default_tenant=tenant,
        default_region="GLOBAL",
        default_currency="USD",
    )
    principal = Principal(account, tenant, account, frozenset({"customer"}))
    value.bind({
        "_principal": principal.to_trusted_dict(),
        "tenant_id": tenant,
        "account_id": account,
        "language": "zh",
        # These user/request values are deliberately untrusted and ignored.
        "role": "admin",
        "customer_level": "internal-vip",
    })
    return value


def service(*, access=None, cache=None, level="standard"):
    return ProductQueryService(
        access or binding(level=level),
        cache or InMemoryProductCache(),
        PublicRag(),
        cache_ttl_seconds=300,
        data_version="test-v1",
        rate_limit_per_minute=100,
    )


def test_context_uses_only_server_verified_principal_and_configured_customer_level():
    access = binding(level="gold")
    current = access.require()
    assert current.principal.roles == frozenset({"customer"})
    assert current.customer_level == "gold"
    assert current.account_id == "customer-a"

    bad = CustomerContextBinding()
    principal = Principal("employee-a", "default", "employee", frozenset({"employee"}))
    with pytest.raises(ValueError, match="customer_principal_role_invalid"):
        bad.bind({"_principal": principal.to_trusted_dict(), "role": "customer"})


def test_tools_expose_no_identity_or_customer_tier_arguments():
    tools = [SearchProductsTool(service()), GetProductDetailsTool(service()), CompareProductsTool(service())]
    for tool in tools:
        properties = set(tool.parameters["properties"])
        assert not properties & {"tenant_id", "account_id", "customer_id", "role", "customer_level"}
        assert tool.parameters["additionalProperties"] is False
        assert tool.allow_subagent_inheritance is False


def test_details_return_only_customer_fields_and_stock_band(monkeypatch):
    item = product("A100", price=12.34, inventory=9876, specification="Blue 20 cm")
    monkeypatch.setattr("agent.customer_product.service.database.get_product_by_sku", lambda sku: item)

    result = asyncio.run(service().get_product_details(
        skus=["A100"], quantity=500, include_documents=False,
    ))
    row = result["products"][0]
    assert row["price"]["amount"] == "12.34"
    assert row["inventory_status"] == "in_stock"
    assert "inventory" not in row
    assert "cost" not in row
    assert "margin" not in row
    assert "9876" not in json.dumps(result)
    assert result["queried_at"]


def test_use_case_search_does_not_return_unrelated_catalog_rows(monkeypatch):
    monkeypatch.setattr(
        "agent.customer_product.service.database.list_products",
        lambda **kwargs: pytest.fail("use-case-only search must not list arbitrary products"),
    )
    monkeypatch.setattr(
        "agent.customer_product.service.database.get_product_by_sku",
        lambda sku: pytest.fail("untagged knowledge must not invent a product mapping"),
    )
    result = asyncio.run(service().search_products(use_case="outdoor installation"))
    assert result["status"] == "answered"
    assert result["results"] == []
    assert result["warnings"] == ["knowledge_not_linked_to_published_sku"]


def test_compare_aligns_mysql_fields_and_public_rag_without_exact_stock(monkeypatch):
    products = {
        "A100": product("A100", price=12.34, inventory=9876, specification="Blue"),
        "B200": product("B200", price=15.00, inventory=4321, specification="Red"),
    }
    monkeypatch.setattr(
        "agent.customer_product.service.database.get_product_by_sku",
        lambda sku: products.get(sku),
    )
    current = service()
    result = asyncio.run(current.compare_products(skus=["A100", "B200"], quantity=500))
    assert result["status"] == "answered"
    assert [row["sku"] for row in result["products"]] == ["A100", "B200"]
    assert {row["field"] for row in result["differences"]} == {
        "specification", "weight", "price", "inventory_status", "moq", "lead_time", "package_info",
    }
    payload = json.dumps(result)
    assert "9876" not in payload and "4321" not in payload
    assert all(row["documents"]["citations"] for row in result["products"])
    with pytest.raises(ProductQueryError, match="2_to_5"):
        asyncio.run(current.compare_products(skus=["A100"]))


def test_cache_isolated_by_customer_level(monkeypatch):
    calls = 0
    item = product("A100", price=12.34, inventory=500, specification="Blue")

    def lookup(sku):
        nonlocal calls
        calls += 1
        return item

    monkeypatch.setattr("agent.customer_product.service.database.get_product_by_sku", lookup)
    cache = InMemoryProductCache()
    standard = service(access=binding(level="standard"), cache=cache)
    gold = service(access=binding(level="gold"), cache=cache)
    first = asyncio.run(standard.get_product_details(skus=["A100"], include_documents=False))
    second = asyncio.run(standard.get_product_details(skus=["A100"], include_documents=False))
    third = asyncio.run(gold.get_product_details(skus=["A100"], include_documents=False))
    assert first["cache_status"] == "miss"
    assert second["cache_status"] == "hit"
    assert third["cache_status"] == "miss"
    assert calls == 2


def test_permission_aware_rag_rejects_internal_citation():
    class Pipeline:
        def query(self, request):
            assert request.actor.roles == frozenset({"customer"})
            assert request.actor.business_unit_id == "default"
            return {
                "status": "HIGH_CONFIDENCE",
                "answer": "internal margin is 40 percent",
                "citations": [{"document_id": "internal-doc", "version": 1, "location": "p1"}],
            }

    class Repository:
        def get_document(self, document_id):
            return {
                "document_id": document_id,
                "classification": "internal",
                "status": "published",
                "business_unit_id": "default",
                "allowed_roles": ["employee"],
            }

    retriever = PermissionAwareRagRetriever(pipeline=Pipeline(), repository=Repository())
    result = asyncio.run(retriever.search(binding().require(), "show product details"))
    assert result == {"status": "NO_EVIDENCE", "answer": "", "citations": []}


def test_chunking_inherits_document_permission_metadata():
    document = CanonicalDocument(
        document_id="doc-a",
        version=3,
        source_uri="kb://doc-a",
        title="A100 manual",
        content="A100 public instructions. " * 30,
        content_hash="hash",
        language="zh-CN",
        business_unit_id="tenant-a",
        allowed_roles=frozenset({"customer"}),
        classification="public",
        status=DocumentStatus.PUBLISHED,
        metadata={
            "visibility": "customer_public",
            "product_skus": ["A100"],
            "effective_from": "2026-08-01T00:00:00Z",
        },
    )
    parents, children = ParentChildSplitter(parent_chars=120, child_chars=60).split(document)
    for chunk in [*parents, *children]:
        assert chunk.metadata["tenant_id"] == "tenant-a"
        assert chunk.metadata["visibility"] == "customer_public"
        assert chunk.metadata["allowed_roles"] == ("customer",)
        assert chunk.metadata["classification"] == "public"
        assert chunk.metadata["document_status"] == "published"
        assert chunk.metadata["product_skus"] == ("A100",)


def test_shipping_provider_is_a_disabled_placeholder():
    provider = SFInternationalProvider()
    assert provider.available is False
    with pytest.raises(RuntimeError, match="not_implemented"):
        asyncio.run(provider.estimate({"destination": "DE"}))


def test_langchain_customer_agent_runs_the_controlled_tool_loop(tmp_path, monkeypatch):
    (tmp_path / "customer_identity.md").write_text("Use only controlled product tools.", encoding="utf-8")
    config = SimpleNamespace(
        api_key="test-only",
        base_url="https://example.invalid/v1",
        model="test-model",
        models={},
        workspace=str(tmp_path),
        max_iterations=4,
        identity_file="identity.md",
        customer_identity_file="customer_identity.md",
        customer_session_dir="workspace/customer_sessions",
        customer_memory_enabled=False,
        customer_memory_file="workspace/customer_memory/PUBLIC_MEMORY.md",
        customer_product_langchain_enabled=True,
    )
    item = product("A100", price=12.34, inventory=9876, specification="Blue")
    monkeypatch.setattr("agent.customer_product.service.database.get_product_by_sku", lambda sku: item)
    agent = main.build_customer_agent(config, "customer_portal:anonymous:langchain")
    calls = []

    async def chat(*, messages, tools, model=None):
        calls.append((messages, tools, model))
        assert {row["function"]["name"] for row in tools} == {
            "search_products", "get_product_details", "compare_products",
        }
        if len(calls) == 1:
            return LLMResponse(
                tool_calls=[ToolCallRequest(
                    id="details-1",
                    name="get_product_details",
                    arguments={"skus": ["A100"], "quantity": 500, "include_documents": False},
                )],
                finish_reason="tool_calls",
            )
        assert any(
            row.get("role") == "tool" and "inventory_status" in str(row.get("content"))
            for row in messages
        )
        assert "9876" not in json.dumps(messages)
        return LLMResponse(content="A100 is in stock; the exact quantity is not disclosed.")

    monkeypatch.setattr(agent.provider, "chat", chat)
    agent.set_request_context({"channel": "customer_portal", "language": "en"})
    response = asyncio.run(agent.run("Please check 500 units of A100."))
    assert response.startswith("A100 is in stock")
    assert len(calls) == 2
    assert type(agent._langchain_graph).__name__ == "CompiledStateGraph"
