"""Customer-visible adapter over the existing enterprise knowledge RAG."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from trade_rag.contracts import Actor, QueryRequest
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline

from .context import CustomerAccessContext


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class PermissionAwareRagRetriever:
    """Enforces customer ACLs before retrieval and validates citations afterwards."""

    def __init__(
        self, pipeline: RagPipeline | None = None,
        repository: KnowledgeRepository | None = None, public_memory_store=None,
    ) -> None:
        self.pipeline = pipeline or RagPipeline()
        self.repository = repository or KnowledgeRepository()
        self.public_memory_store = public_memory_store

    @staticmethod
    def _document_visible(
        detail: dict[str, Any], context: CustomerAccessContext,
        product_skus: tuple[str, ...],
    ) -> bool:
        if detail.get("classification") != "public" or detail.get("status") != "published":
            return False
        if str(detail.get("business_unit_id") or "default") != context.principal.tenant_id:
            return False
        roles = {str(value) for value in detail.get("allowed_roles") or ()}
        if roles and "customer" not in roles:
            return False
        metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
        visibility = str(metadata.get("visibility") or "customer_public")
        if visibility not in {"public", "customer_public"}:
            return False
        tagged_skus = {str(value).upper() for value in metadata.get("product_skus") or ()}
        if product_skus and tagged_skus and not (tagged_skus & set(product_skus)):
            return False
        now = datetime.now(timezone.utc)
        effective_from = _parse_time(metadata.get("effective_from"))
        effective_until = _parse_time(metadata.get("effective_until"))
        return not ((effective_from and effective_from > now)
                   or (effective_until and effective_until <= now))

    async def search(
        self, context: CustomerAccessContext, query: str, *,
        product_skus: tuple[str, ...] = (), top_k: int = 3,
    ) -> dict[str, Any]:
        if context.principal.roles != frozenset({"customer"}):
            raise PermissionError("customer_rag_role_invalid")
        normalized_skus = tuple(sorted({value.strip().upper() for value in product_skus if value.strip()}))
        request = QueryRequest(
            query=query.strip()[:500],
            actor=Actor(
                actor_id=context.principal.user_id,
                roles=frozenset({"customer"}),
                business_unit_id=context.principal.tenant_id,
            ),
            top_k=max(1, min(int(top_k), 5)),
        )
        result = await asyncio.to_thread(self.pipeline.query, request)
        citations = []
        for citation in result.get("citations", []):
            if not isinstance(citation, dict):
                return {"status": "NO_EVIDENCE", "answer": "", "citations": []}
            try:
                detail = self.repository.get_document(str(citation.get("document_id") or ""))
            except Exception:
                return {"status": "NO_EVIDENCE", "answer": "", "citations": []}
            if not self._document_visible(detail, context, normalized_skus):
                return {"status": "NO_EVIDENCE", "answer": "", "citations": []}
            metadata = detail.get("metadata") if isinstance(detail.get("metadata"), dict) else {}
            tagged_skus = {
                str(value).upper() for value in metadata.get("product_skus") or ()
                if str(value).strip()
            }
            citations.append({
                "document_id": str(citation.get("document_id") or ""),
                "version": int(citation.get("version") or 1),
                "source": str(detail.get("title") or detail.get("original_name") or "public_knowledge"),
                "location": str(citation.get("location") or ""),
                "product_skus": sorted(tagged_skus),
            })
        answer = str(result.get("answer") or "") if citations else ""
        memory_rows = (
            self.public_memory_store.search(query, top_k=3)
            if self.public_memory_store is not None else []
        )
        if memory_rows:
            answer = "\n".join([answer, *memory_rows]).strip()
        return {
            "status": "ANSWERED" if answer else str(result.get("status") or "NO_EVIDENCE"),
            "answer": answer,
            "citations": citations,
        }
