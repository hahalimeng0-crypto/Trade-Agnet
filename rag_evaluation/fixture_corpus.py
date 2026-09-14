from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime

from trade_rag.contracts import CanonicalDocument, DocumentStatus
from trade_rag.pipeline import RagPipeline
from trade_rag.stores import InMemoryVectorStore


def load_fixture_pipeline(path: str | Path) -> RagPipeline:
    """Build an isolated, deterministic pipeline from de-identified JSONL documents."""
    # MockEmbedding validates isolation and plumbing, not semantic quality. Give
    # deterministic keyword evidence the larger local-fixture weight; real-model
    # gates must run separately and are never marked production-ready here.
    pipeline = RagPipeline(store=InMemoryVectorStore(), semantic_weight=0.3)
    seen: set[str] = set()
    for line_number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        try:
            row = json.loads(raw)
            document_id = str(row["document_id"])
            if document_id in seen:
                raise ValueError("duplicate document_id")
            seen.add(document_id)
            content = str(row["content"])
            document = CanonicalDocument(
                document_id=document_id,
                version=int(row.get("version", 1)),
                source_uri=f"fixture://{document_id}",
                title=str(row.get("title", document_id)),
                content=content,
                content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                location=str(row.get("location", "section:fixture")),
                language=str(row.get("language", "und")),
                business_unit_id=str(row.get("business_unit_id", "default")),
                allowed_roles=frozenset(str(value) for value in row.get("allowed_roles", [])),
                classification=str(row.get("classification", "internal")),
                status=DocumentStatus(str(row.get("status", "published"))),
                expires_at=(datetime.fromisoformat(str(row["expires_at"]).replace("Z", "+00:00"))
                            if row.get("expires_at") else None),
                parser_version="evaluation-fixture-v1",
                metadata={"evaluation_fixture": True},
            )
            pipeline.index(document)
        except Exception as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not seen:
        raise ValueError("fixture corpus is empty")
    return pipeline
