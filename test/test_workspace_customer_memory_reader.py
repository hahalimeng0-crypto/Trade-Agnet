import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from agent.internal_langgraph_agent import NanoClawEmployeeAgentAdapter
from agent.memory_runtime.errors import MemoryAccessDenied
from agent.memory_runtime.models import ActorContext
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from agent.memory_runtime.services.customer_reader import (
    CustomerMemoryAccessAudit,
    CustomerMemoryReader,
    ReadonlyCustomerMemoryStore,
)
from agent.memory_runtime.stores.sqlite import CustomerSQLiteMemoryStore
from agent.tools.read_customer_memory import ReadCustomerMemoryTool
from agent.tools.registry import ToolRegistry


def seed_customer_memory(path: Path, *, tenant="tenant-a", account="account-a"):
    store = CustomerSQLiteMemoryStore(path)
    service = CustomerMemoryService(store)
    customer = service.actor(tenant, account)
    consent = service.grant_consent(
        customer, purpose="customer_support", categories=("semantic",), expires_at=None,
    )
    candidate = service.create_candidate(
        customer,
        content="Hamburg destination; private free-form detail must not leave the main store",
        summary="Customer prefers Hamburg as destination",
        memory_type="semantic", purpose="customer_support",
        source_refs=("message-a",), conversation_id=None,
        confidence=.9, importance=.7,
    )
    active = service.activate_candidate(
        customer, candidate.memory_id, consent.consent_record_id, candidate.version,
    )
    store.connection.close()
    return active


def workspace_actor(*, tenant="tenant-a", roles=("customer_memory_reader",)):
    return ActorContext(
        "workspace_operator", "operator-a", tenant, frozenset(roles), True,
    )


def reader_for(tmp_path: Path):
    customer_db = tmp_path / "customer_data.db"
    active = seed_customer_memory(customer_db)
    audit = CustomerMemoryAccessAudit(sqlite3.connect(":memory:", check_same_thread=False))
    reader = CustomerMemoryReader(ReadonlyCustomerMemoryStore(customer_db), audit, max_top_k=3)
    return active, reader, audit


def test_workspace_reader_returns_minimized_result_and_content_free_audit(tmp_path):
    active, reader, audit = reader_for(tmp_path)
    results = reader.search_for_workspace(
        workspace_actor(), customer_account_id="account-a",
        purpose="customer_support", query="Hamburg destination", top_k=3,
    )
    assert [item.memory_id for item in results] == [active.memory_id]
    assert results[0].summary == "Customer prefers Hamburg as destination"
    assert not hasattr(results[0], "content")
    assert not hasattr(results[0], "source_refs")
    rows = audit.rows()
    assert rows[0]["operator_id"] == "operator-a"
    assert rows[0]["outcome"] == "allowed"
    assert json.loads(rows[0]["returned_memory_ids_json"]) == [active.memory_id]
    assert "private free-form detail" not in json.dumps(rows)


def test_missing_role_is_denied_and_security_event_is_audited(tmp_path):
    _, reader, audit = reader_for(tmp_path)
    with pytest.raises(MemoryAccessDenied):
        reader.search_for_workspace(
            workspace_actor(roles=()), customer_account_id="account-a",
            purpose="customer_support", query="Hamburg", top_k=3,
        )
    row = audit.rows()[0]
    assert row["outcome"] == "denied"
    assert row["error_code"] == "memory_scope_denied"
    assert row["returned_memory_ids_json"] == "[]"


def test_wrong_tenant_and_unapproved_purpose_never_return_memory(tmp_path):
    _, reader, audit = reader_for(tmp_path)
    assert reader.search_for_workspace(
        workspace_actor(tenant="tenant-b"), customer_account_id="account-a",
        purpose="customer_support", query="Hamburg", top_k=3,
    ) == []
    with pytest.raises(MemoryAccessDenied):
        reader.search_for_workspace(
            workspace_actor(), customer_account_id="account-a",
            purpose="marketing", query="Hamburg", top_k=3,
        )
    assert [row["outcome"] for row in audit.rows()] == ["allowed", "denied"]


def test_customer_database_connection_is_physically_query_only(tmp_path):
    customer_db = tmp_path / "customer_data.db"
    seed_customer_memory(customer_db)
    store = ReadonlyCustomerMemoryStore(customer_db)
    assert not hasattr(store, "create_candidate")
    with pytest.raises(sqlite3.OperationalError):
        store.connection.execute("DELETE FROM customer_memory_item")


def test_audit_failure_fails_closed_instead_of_returning_unlogged_memory(tmp_path):
    customer_db = tmp_path / "customer_data.db"
    seed_customer_memory(customer_db)

    class FailingAudit:
        def record(self, *_args, **_kwargs):
            raise OSError("audit unavailable")

    reader = CustomerMemoryReader(
        ReadonlyCustomerMemoryStore(customer_db), FailingAudit(), max_top_k=3,
    )
    with pytest.raises(OSError, match="audit unavailable"):
        reader.search_for_workspace(
            workspace_actor(), customer_account_id="account-a",
            purpose="customer_support", query="Hamburg", top_k=3,
        )


def test_internal_tool_schema_identity_boundary_and_subagent_exclusion(tmp_path):
    _, reader, _ = reader_for(tmp_path)
    tool = ReadCustomerMemoryTool(reader, workspace_actor())
    properties = tool.parameters["properties"]
    assert "operator_id" not in properties
    assert "tenant_id" not in properties
    assert "top_k" not in properties
    payload = json.loads(asyncio.run(tool.execute(
        customer_account_id="account-a", purpose="customer_support", query="Hamburg",
    )))
    assert payload["status"] == "ANSWERED"
    assert payload["classification"] == "internal_only"
    assert payload["authority"] == "supporting_memory_only"

    registry = ToolRegistry()
    registry.register(tool)
    assert registry.inheritable_tools() == []


def test_workspace_agent_registers_reader_only_when_enabled(tmp_path):
    (tmp_path / "identity.md").write_text("WORKSPACE", encoding="utf-8")
    customer_db = tmp_path / "workspace" / "customer_data" / "customer_data.db"
    seed_customer_memory(customer_db)
    config = SimpleNamespace(
        api_key="test-only", base_url="https://example.invalid/v1", model="test-model",
        models={}, workspace=str(tmp_path), max_iterations=2, identity_file="identity.md",
        workspace_customer_memory_read_enabled=True,
        workspace_operator_id="operator-a", workspace_operator_tenant_id="tenant-a",
        customer_data_database_path="workspace/customer_data/customer_data.db",
        memory_recall_top_k=3, workspace_memory_enabled=False,
    )
    reader = CustomerMemoryReader(
        ReadonlyCustomerMemoryStore(customer_db),
        CustomerMemoryAccessAudit(tmp_path / "workspace" / "memory" / "audit.db"),
        max_top_k=3,
    )
    actor = ActorContext(
        "workspace_operator", "operator-a", "tenant-a",
        frozenset({"customer_memory_reader"}), True,
    )
    agent = main.build_agent(
        config, "cli:operator-a", customer_memory_reader=reader,
        workspace_actor=actor,
    )
    assert isinstance(agent, NanoClawEmployeeAgentAdapter)
    assert "read_customer_memory" in agent.tools.list_tools()
    assert "read_customer_memory" not in {
        tool.name for tool in agent.tools.inheritable_tools()
    }
