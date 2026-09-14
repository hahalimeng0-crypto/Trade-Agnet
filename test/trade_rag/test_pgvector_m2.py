from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from trade_rag.config import RagVectorConfig, load_rag_vector_config
from trade_rag.contracts import Actor, CanonicalDocument, ChildChunk, DocumentStatus
from trade_rag.embeddings import MockEmbeddingProvider
from trade_rag.pgvector_migration import _assert_m2_target, check
from trade_rag.pgvector_store import PgvectorStore
from trade_rag.stores import InMemoryVectorStore
from trade_rag.vector_store import create_vector_store


def _config(**overrides) -> RagVectorConfig:
    values = {
        "backend": "pgvector", "dimensions": 64, "host": "127.0.0.1",
        "port": 5433, "database": "nanoclaw_vector_docker", "user": "rag",
        "password": "test-only", "sslmode": "disable", "connect_timeout_seconds": 2,
    }
    values.update(overrides)
    return RagVectorConfig(**values)


def _document(document_id="m2-doc", *, version=1, status=DocumentStatus.PUBLISHED,
              roles=frozenset({"sales"}), business_unit="trade", expires_at=None):
    return CanonicalDocument(
        document_id, version, f"sample://{document_id}", "M2 Fixture", "fixture",
        f"hash-{document_id}-{version}", business_unit_id=business_unit,
        allowed_roles=roles, status=status, expires_at=expires_at,
    )


def _children(document_id="m2-doc"):
    return [
        ChildChunk("m2-child-b", "m2-parent", document_id, "beta", "page-2", "hash-b"),
        ChildChunk(
            "m2-child-a", "m2-parent", document_id, "alpha", "page-1", "hash-a",
            {"block_type": "image", "image_id": "img-a", "image_index": 1,
             "page_number": 1, "page_image_index": 1, "ocr_confidence": 0.99},
        ),
    ]


def test_memory_factory_does_not_import_pgvector_store():
    sys.modules.pop("trade_rag.pgvector_store", None)
    store = create_vector_store(RagVectorConfig("memory", 64))
    assert isinstance(store, InMemoryVectorStore)
    assert "trade_rag.pgvector_store" not in sys.modules


def test_pgvector_validates_before_connecting_and_migration_target_is_restricted():
    store = PgvectorStore(_config())
    children = _children()
    with pytest.raises(ValueError, match="embedding_count_mismatch"):
        store.upsert(children, _document(), [[1.0] * 64])
    with pytest.raises(ValueError, match="embedding_dimension_mismatch"):
        store.upsert(children, _document(), [[1.0] * 63, [1.0] * 64])
    with pytest.raises(ValueError, match="embedding_dimension_mismatch"):
        store.search([1.0] * 63, Actor("actor"))
    with pytest.raises(ValueError, match="loopback"):
        _assert_m2_target(_config(host="database.example"))
    with pytest.raises(ValueError, match="nanoclaw_vector_docker"):
        _assert_m2_target(_config(database="other"))


def test_memory_store_tie_order_is_deterministic():
    store = InMemoryVectorStore()
    children = _children()
    vector = [1.0] + [0.0] * 63
    store.upsert(children, _document(), [vector, vector])
    result = store.search(vector, Actor("sales", frozenset({"sales"}), "trade"))
    assert [row.child.child_id for row in result] == ["m2-child-a", "m2-child-b"]


def test_memory_store_preserves_image_ocr_metadata_and_withdrawal():
    store = InMemoryVectorStore()
    metadata = {"block_type": "image", "image_id": "img-1", "image_index": 1,
                "page_number": 4, "page_image_index": 2, "ocr_confidence": 0.91}
    child = ChildChunk(
        "image-child", "image-parent", "m2-doc", "invoice total", "page:4#image:1",
        "image-hash", metadata,
    )
    vector = [1.0] + [0.0] * 63
    assert store.upsert([child], _document(), [vector]) == 1
    hit = store.search(vector, Actor("sales", frozenset({"sales"}), "trade"))[0]
    assert hit.child.metadata == metadata
    assert store.delete_by_document("m2-doc", 1) == 1
    assert store.search(vector, Actor("sales", frozenset({"sales"}), "trade")) == []


@pytest.mark.skipif(os.environ.get("NANOCLAW_TEST_PGVECTOR") != "1",
                    reason="requires isolated Docker pgvector")
def test_live_pgvector_contract_and_cleanup():
    config = load_rag_vector_config()
    assert check(config)["ready"] is True
    store = create_vector_store(config)
    embedder = MockEmbeddingProvider(64)
    actor = Actor("sales", frozenset({"sales"}), "trade")
    denied_role = Actor("finance", frozenset({"finance"}), "trade")
    denied_unit = Actor("sales", frozenset({"sales"}), "other")
    document_ids = ["m2-doc", "m2-draft", "m2-expired"]
    try:
        for document_id in document_ids:
            store.delete_by_document(document_id)
        children = _children()
        vectors = embedder.embed([child.text for child in children])
        assert store.upsert(children, _document(), vectors) == 2
        assert store.upsert(children, _document(), vectors) == 2
        hits = store.search(vectors[1], actor)
        assert hits[0].child.child_id == "m2-child-a"
        assert hits[0].child.metadata["image_index"] == 1
        assert store.search(vectors[1], denied_role) == []
        assert store.search(vectors[1], denied_unit) == []

        draft_child = ChildChunk("m2-draft-child", "m2-parent", "m2-draft", "draft", "p1", "h")
        expired_child = ChildChunk("m2-expired-child", "m2-parent", "m2-expired", "expired", "p1", "h")
        store.upsert([draft_child], _document("m2-draft", status=DocumentStatus.DRAFT),
                     embedder.embed([draft_child.text]))
        store.upsert([expired_child], _document(
            "m2-expired", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
            embedder.embed([expired_child.text]))
        assert all(hit.child.document_id not in {"m2-draft", "m2-expired"}
                   for hit in store.search(vectors[1], actor, 30))

        assert store.delete_by_document("m2-doc", 2) == 0
        assert store.delete_by_document("m2-doc", 1) == 2
        assert store.delete_by_document("m2-doc", 1) == 0
    finally:
        for document_id in document_ids:
            store.delete_by_document(document_id)
