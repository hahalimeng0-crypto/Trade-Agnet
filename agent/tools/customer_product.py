"""Controlled business tools exposed to the customer product Agent."""

from __future__ import annotations

import json
from typing import Any

from agent.customer_product.service import ProductQueryService
from agent.tools.base import Tool


class _CustomerProductTool(Tool):
    allow_subagent_inheritance = False

    def __init__(self, service: ProductQueryService) -> None:
        self.service = service

    @staticmethod
    def _payload(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class SearchProductsTool(_CustomerProductTool):
    @property
    def name(self) -> str:
        return "search_products"

    @property
    def description(self) -> str:
        return (
            "Search only published products by keyword, category, color, size, or use case. "
            "Identity and customer level are injected by the server and must not be supplied."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "maxLength": 120},
                "category": {"type": "string", "maxLength": 60},
                "color": {"type": "string", "maxLength": 40},
                "size": {"type": "string", "maxLength": 40},
                "use_case": {"type": "string", "maxLength": 160},
                "quantity": {"type": "integer", "minimum": 1, "maximum": 100000000},
                "region": {"type": "string", "maxLength": 32},
                "currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "additionalProperties": False,
        }

    async def execute(self, **kwargs: Any) -> str:
        return self._payload(await self.service.search_products(**kwargs))


class GetProductDetailsTool(_CustomerProductTool):
    @property
    def name(self) -> str:
        return "get_product_details"

    @property
    def description(self) -> str:
        return (
            "Get allowlisted customer-visible details for one to five known SKUs, including "
            "applicable price status, stock band, MOQ, lead time, and public documents."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skus": {
                    "type": "array", "minItems": 1, "maxItems": 5,
                    "items": {"type": "string", "minLength": 1, "maxLength": 60},
                },
                "quantity": {"type": "integer", "minimum": 1, "maximum": 100000000},
                "region": {"type": "string", "maxLength": 32},
                "currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
                "include_documents": {"type": "boolean", "default": True},
            },
            "required": ["skus"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs: Any) -> str:
        return self._payload(await self.service.get_product_details(**kwargs))


class CompareProductsTool(_CustomerProductTool):
    @property
    def name(self) -> str:
        return "compare_products"

    @property
    def description(self) -> str:
        return (
            "Compare two to five known published SKUs at one query time. The backend aligns "
            "MySQL facts and permission-filtered public RAG evidence; do not calculate values yourself."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skus": {
                    "type": "array", "minItems": 2, "maxItems": 5,
                    "uniqueItems": True,
                    "items": {"type": "string", "minLength": 1, "maxLength": 60},
                },
                "quantity": {"type": "integer", "minimum": 1, "maximum": 100000000},
                "region": {"type": "string", "maxLength": 32},
                "currency": {"type": "string", "pattern": "^[A-Za-z]{3}$"},
            },
            "required": ["skus"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs: Any) -> str:
        return self._payload(await self.service.compare_products(**kwargs))
