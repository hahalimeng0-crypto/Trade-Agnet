"""Deterministic product queries used by the customer-facing Agent tools."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from agent.business import database

from .cache import ProductCache
from .context import CustomerAccessContext, CustomerContextBinding
from .rag import PermissionAwareRagRetriever


class ProductQueryError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _bounded_text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


class ProductQueryService:
    def __init__(
        self, context_binding: CustomerContextBinding, cache: ProductCache,
        rag: PermissionAwareRagRetriever, *, cache_ttl_seconds: int = 300,
        data_version: str = "products-v1", rate_limit_per_minute: int = 60,
    ) -> None:
        self.context_binding = context_binding
        self.cache = cache
        self.rag = rag
        self.cache_ttl_seconds = max(1, int(cache_ttl_seconds))
        self.data_version = data_version.strip() or "products-v1"
        self.rate_limit_per_minute = max(1, int(rate_limit_per_minute))

    def _context(self) -> CustomerAccessContext:
        return self.context_binding.require()

    async def _rate_limit(self, context: CustomerAccessContext, operation: str) -> None:
        subject = f"{context.principal.tenant_id}:{context.account_id}:{operation}"
        if not await self.cache.allow(subject, self.rate_limit_per_minute, 60):
            raise ProductQueryError("customer_product_rate_limit_exceeded")

    def _cache_key(
        self, context: CustomerAccessContext, operation: str, payload: dict[str, Any],
    ) -> str:
        scope = {
            "tenant_id": context.principal.tenant_id,
            "role": "customer",
            "customer_level": context.customer_level,
            "region": payload.get("region") or context.default_region,
            "currency": payload.get("currency") or context.default_currency,
            "sku": payload.get("sku") or payload.get("skus") or "",
            "data_version": self.data_version,
            "operation": operation,
            "payload": payload,
        }
        raw = json.dumps(scope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _inventory_status(product, quantity: int | None) -> str:
        available = max(0, int(getattr(product, "inventory", 0) or 0))
        if quantity is not None and quantity > available:
            return "insufficient_for_requested_quantity"
        if available <= 0:
            return "out_of_stock"
        moq = max(1, int(getattr(product, "moq", 1) or 1))
        return "limited" if available <= max(10, moq * 2) else "in_stock"

    @staticmethod
    def _price(
        product, context: CustomerAccessContext, region: str, currency: str,
    ) -> dict[str, Any]:
        if not context.authenticated:
            return {"status": "confirmation_required"}
        if currency != "USD" or region not in {"GLOBAL", ""}:
            return {
                "status": "confirmation_required",
                "reason": "regional_price_not_configured",
            }
        value = Decimal(str(getattr(product, "price_usd", 0) or 0))
        if value <= 0:
            return {"status": "confirmation_required"}
        return {
            "status": "available",
            "amount": format(value.quantize(Decimal("0.01")), "f"),
            "currency": "USD",
            "region": "GLOBAL",
            "customer_level": context.customer_level,
        }

    def _public_product(
        self, product, context: CustomerAccessContext, *, quantity: int | None,
        region: str, currency: str, queried_at: str,
    ) -> dict[str, Any]:
        return {
            "sku": str(product.sku),
            "name": str(product.name_en or product.name_cn),
            "category": str(product.category),
            "specification": str(product.specification or "unknown"),
            "unit": str(product.unit),
            "moq": int(product.moq),
            "weight": (
                {"value": str(Decimal(str(product.weight_kg))), "unit": "kg"}
                if Decimal(str(getattr(product, "weight_kg", 0) or 0)) > 0 else "unknown"
            ),
            "package_info": str(getattr(product, "package_info", "") or "unknown"),
            "price": self._price(product, context, region, currency),
            "inventory_status": self._inventory_status(product, quantity),
            "requested_quantity": quantity,
            "lead_time": {"value": int(product.lead_time_days), "unit": "day"},
            "updated_at": str(getattr(product, "updated_at", "") or queried_at),
        }

    @staticmethod
    def _normalize_scope(
        context: CustomerAccessContext, region: str, currency: str,
    ) -> tuple[str, str]:
        normalized_region = _bounded_text(region or context.default_region, 32).upper()
        normalized_currency = _bounded_text(currency or context.default_currency, 3).upper()
        if not normalized_region or not normalized_currency.isalpha() or len(normalized_currency) != 3:
            raise ProductQueryError("customer_product_scope_invalid")
        return normalized_region, normalized_currency

    async def search_products(
        self, *, keyword: str = "", category: str = "", color: str = "",
        size: str = "", use_case: str = "", quantity: int | None = None,
        region: str = "", currency: str = "", limit: int = 5,
    ) -> dict[str, Any]:
        context = self._context()
        await self._rate_limit(context, "search")
        keyword = _bounded_text(keyword, 120)
        category = _bounded_text(category, 60)
        color = _bounded_text(color, 40)
        size = _bounded_text(size, 40)
        use_case = _bounded_text(use_case, 160)
        if not any((keyword, category, color, size, use_case)):
            raise ProductQueryError("customer_product_search_condition_required")
        if quantity is not None and not 1 <= int(quantity) <= 100_000_000:
            raise ProductQueryError("customer_product_quantity_invalid")
        limit = max(1, min(int(limit), 10))
        region, currency = self._normalize_scope(context, region, currency)
        payload = {
            "keyword": keyword, "category": category, "color": color, "size": size,
            "use_case": use_case, "quantity": quantity, "region": region,
            "currency": currency, "limit": limit,
        }
        cache_key = self._cache_key(context, "search", payload)
        if cached := await self.cache.get(cache_key):
            return {**cached, "cache_status": "hit"}
        queried_at = _utc_now()
        knowledge = {"status": "NOT_REQUESTED", "answer": "", "citations": []}
        if use_case:
            knowledge = await self.rag.search(
                context, f"{use_case} 适用场景 产品选择", top_k=3,
            )
        structured_search = any((keyword, category, color, size))
        if structured_search:
            products = await asyncio.to_thread(
                database.list_products, category=category, keyword=keyword, limit=limit * 2,
            )
        else:
            # A semantic document must explicitly identify its products. Never
            # fill a use-case-only search with unrelated catalog rows.
            tagged_skus = tuple(dict.fromkeys(
                str(sku).upper()
                for citation in knowledge.get("citations", [])
                for sku in citation.get("product_skus", [])
                if str(sku).strip()
            ))[:limit]
            products = await asyncio.gather(*(
                asyncio.to_thread(database.get_product_by_sku, sku) for sku in tagged_skus
            ))
        filters = tuple(value.casefold() for value in (color, size) if value)
        rows = []
        for product in products:
            if not product or not product.active:
                continue
            searchable = " ".join((product.specification or "", product.name_en or "",
                                   product.name_cn or "")).casefold()
            if any(value not in searchable for value in filters):
                continue
            rows.append(self._public_product(
                product, context, quantity=quantity, region=region,
                currency=currency, queried_at=queried_at,
            ))
            if len(rows) >= limit:
                break
        knowledge_answered = knowledge.get("status") == "ANSWERED" and bool(knowledge.get("answer"))
        result = {
            "status": "answered" if rows or knowledge_answered else "unknown",
            "results": rows,
            "total": len(rows),
            "knowledge": knowledge,
            "warnings": (
                ["knowledge_not_linked_to_published_sku"]
                if use_case and not structured_search and knowledge_answered and not rows else []
            ),
            "queried_at": queried_at,
            "data_version": self.data_version,
            "cache_status": "miss",
        }
        await self.cache.set(cache_key, result, self.cache_ttl_seconds)
        return result

    async def get_product_details(
        self, *, skus: list[str], quantity: int | None = None,
        region: str = "", currency: str = "", include_documents: bool = True,
    ) -> dict[str, Any]:
        context = self._context()
        await self._rate_limit(context, "details")
        normalized = tuple(dict.fromkeys(
            _bounded_text(value, 60).upper() for value in skus if _bounded_text(value, 60)
        ))
        if not 1 <= len(normalized) <= 5:
            raise ProductQueryError("customer_product_sku_count_invalid")
        if quantity is not None and not 1 <= int(quantity) <= 100_000_000:
            raise ProductQueryError("customer_product_quantity_invalid")
        region, currency = self._normalize_scope(context, region, currency)
        payload = {
            "skus": normalized, "quantity": quantity, "region": region,
            "currency": currency, "include_documents": bool(include_documents),
        }
        cache_key = self._cache_key(context, "details", payload)
        if cached := await self.cache.get(cache_key):
            return {**cached, "cache_status": "hit"}
        queried_at = _utc_now()
        products = await asyncio.gather(*(
            asyncio.to_thread(database.get_product_by_sku, sku) for sku in normalized
        ))
        rows, missing = [], []
        for sku, product in zip(normalized, products):
            if product is None or not product.active:
                missing.append(sku)
                continue
            row = self._public_product(
                product, context, quantity=quantity, region=region,
                currency=currency, queried_at=queried_at,
            )
            if include_documents:
                row["documents"] = await self.rag.search(
                    context,
                    f"{sku} 产品说明书 公开认证 FAQ 使用方法 适用场景 注意事项",
                    product_skus=(sku,), top_k=3,
                )
            rows.append(row)
        result = {
            "status": "answered" if rows else "unknown",
            "products": rows,
            "missing_skus": missing,
            "queried_at": queried_at,
            "data_version": self.data_version,
            "cache_status": "miss",
        }
        await self.cache.set(cache_key, result, self.cache_ttl_seconds)
        return result

    async def compare_products(
        self, *, skus: list[str], quantity: int | None = None,
        region: str = "", currency: str = "",
    ) -> dict[str, Any]:
        context = self._context()
        await self._rate_limit(context, "compare")
        normalized = tuple(dict.fromkeys(
            _bounded_text(value, 60).upper() for value in skus if _bounded_text(value, 60)
        ))
        if not 2 <= len(normalized) <= 5:
            raise ProductQueryError("customer_product_compare_requires_2_to_5_skus")
        if quantity is not None and not 1 <= int(quantity) <= 100_000_000:
            raise ProductQueryError("customer_product_quantity_invalid")
        region, currency = self._normalize_scope(context, region, currency)
        payload = {
            "skus": normalized, "quantity": quantity,
            "region": region, "currency": currency,
        }
        cache_key = self._cache_key(context, "compare", payload)
        if cached := await self.cache.get(cache_key):
            return {**cached, "cache_status": "hit"}
        queried_at = _utc_now()
        products = await asyncio.gather(*(
            asyncio.to_thread(database.get_product_by_sku, sku) for sku in normalized
        ))
        rows, missing = [], []
        for sku, product in zip(normalized, products):
            if product is None or not product.active:
                missing.append(sku)
                continue
            row = self._public_product(
                product, context, quantity=quantity, region=region,
                currency=currency, queried_at=queried_at,
            )
            row["documents"] = await self.rag.search(
                context,
                f"{sku} 产品差异 适用场景 公开认证 使用说明 兼容性 注意事项",
                product_skus=(sku,), top_k=3,
            )
            rows.append(row)
        if len(rows) < 2:
            status = "unknown"
            differences: list[dict[str, Any]] = []
        else:
            status = "answered"
            fields = (
                "specification", "weight", "price", "inventory_status",
                "moq", "lead_time", "package_info",
            )
            differences = [{
                "field": field,
                "values": {row["sku"]: row[field] for row in rows},
            } for field in fields]
        result = {
            "status": status,
            "products": rows,
            "differences": differences,
            "missing_skus": missing,
            "queried_at": queried_at,
            "data_version": self.data_version,
            "warnings": (["fewer_than_two_visible_products"] if len(rows) < 2 else []),
            "cache_status": "miss",
        }
        await self.cache.set(cache_key, result, self.cache_ttl_seconds)
        return result
