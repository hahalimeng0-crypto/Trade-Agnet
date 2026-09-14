from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

from trade_rag.config import RagVectorConfig
from trade_rag.contracts import Actor, CanonicalDocument, ChildChunk, DocumentStatus
from trade_rag.milvus_admin import bootstrap_auth
from trade_rag.milvus_admin import MilvusCollectionManager
from trade_rag.milvus_store import MilvusStore, collection_name
from trade_rag.stores import InMemoryVectorStore
from trade_rag.vector_store import create_vector_store


def _config(**overrides):
    values = dict(
        backend="milvus", dimensions=64, milvus_uri="http://127.0.0.1:19530",
        milvus_token="app:secret", milvus_database="nanoclaw_vector_docker",
        milvus_alias="trade_knowledge_active", milvus_connect_timeout_seconds=2,
    )
    values.update(overrides)
    return RagVectorConfig(**values)


def _document(document_id="m3-doc", *, version=1, status=DocumentStatus.PUBLISHED,
              roles=frozenset({"sales"}), business_unit="trade", expires_at=None):
    return CanonicalDocument(
        document_id, version, f"sample://{document_id}", "M3 Fixture", "fixture",
        f"hash-{document_id}-{version}", business_unit_id=business_unit,
        allowed_roles=roles, status=status, expires_at=expires_at,
    )


def _children(document_id="m3-doc"):
    return [
        ChildChunk("m3-child-b", "m3-parent", document_id, "beta", "page-2", "hash-b"),
        ChildChunk("m3-child-a", "m3-parent", document_id, "alpha", "page-1", "hash-a"),
    ]


class FakeMilvusClient:
    def __init__(self):
        self.calls = []
        self.rows = {"trade_knowledge_v1": [], "trade_knowledge_v2": []}

    def describe_alias(self, alias):
        return {"collection_name": "trade_knowledge_v1"}

    def describe_collection(self, name):
        return {"fields": [{"name": "embedding", "params": {"dim": 64}}]}

    def get_load_state(self, name):
        return {"state": "Loaded"}

    def upsert(self, name, rows):
        self.calls.append(("upsert", name, rows))

    def flush(self, name):
        self.calls.append(("flush", name))

    def search(self, *args, **kwargs):
        self.calls.append(("search", args, kwargs))
        base = {
            "document_id": "m3-doc", "document_version": 1, "parent_id": "m3-parent",
            "child_text": "fixture", "child_location": "p1", "child_content_hash": "h",
            "child_metadata": {}, "source_uri": "sample://m3", "source_title": "M3",
            "source_content_hash": "source-h", "content_type": "text/markdown",
            "source_location": "", "language": "und", "business_unit_id": "trade",
            "allowed_roles": ["sales"], "classification": "internal",
            "document_status": "published", "expires_at_epoch_ms": 0,
            "parser_version": "stdlib-1", "source_metadata": {},
            "embedding_model_id": "mock-hash-v1",
        }
        return [[
            {"distance": 0.75, "entity": {**base, "child_id": "m3-child-b"}},
            {"distance": 0.75, "entity": {**base, "child_id": "m3-child-a"}},
        ]]

    def list_collections(self):
        return list(self.rows)

    def query(self, name, **kwargs):
        return list(self.rows[name])

    def delete(self, name, **kwargs):
        self.rows[name] = []


def test_memory_factory_does_not_import_milvus_adapter():
    sys.modules.pop("trade_rag.milvus_store", None)
    store = create_vector_store(RagVectorConfig("memory", 64))
    assert isinstance(store, InMemoryVectorStore)
    assert "trade_rag.milvus_store" not in sys.modules


def test_milvus_config_and_generation_fail_closed():
    with pytest.raises(ValueError, match="missing Milvus configuration"):
        RagVectorConfig("milvus", 64).validate()
    with pytest.raises(ValueError, match="COLLECTION_ALIAS"):
        _config(milvus_alias="user_supplied").validate()
    for invalid in (0, -1, True, "1"):
        with pytest.raises(ValueError, match="positive integer"):
            collection_name(invalid)
    with pytest.raises(ValueError, match="missing Milvus bootstrap"):
        bootstrap_auth(uri="", root_password="", app_user="", app_password="")


def test_milvus_validates_batch_before_rpc_and_sorts_ties():
    fake = FakeMilvusClient()
    store = MilvusStore(_config(), client=fake)
    children = _children()
    with pytest.raises(ValueError, match="embedding_count_mismatch"):
        store.upsert(children, _document(), [[1.0] * 64])
    with pytest.raises(ValueError, match="embedding_dimension_mismatch"):
        store.upsert(children, _document(), [[1.0] * 63, [1.0] * 64])
    assert fake.calls == []

    vectors = [[1.0] * 64, [0.0] * 64]
    assert store.upsert(children, _document(), vectors) == 2
    hits = store.search(vectors[0], Actor("sales", frozenset({"sales"}), "trade"))
    assert [hit.child.child_id for hit in hits] == ["m3-child-a", "m3-child-b"]
    expression = next(call[2]["filter"] for call in fake.calls if call[0] == "search")
    assert 'business_unit_id == "trade"' in expression
    assert "ARRAY_CONTAINS_ANY" in expression
    assert 'document_status in ["approved", "published"]' in expression


def test_milvus_entity_preserves_image_ocr_metadata():
    store = MilvusStore(_config(), client=FakeMilvusClient())
    child = ChildChunk(
        "image-child", "image-parent", "m3-doc", "SKU image text", "page:2#image:3", "h",
        {"block_type": "image", "image_id": "img-3", "image_index": 3,
         "page_number": 2, "page_image_index": 1, "ocr_confidence": 0.95},
    )
    entity = store._entity(child, _document(), [0.0] * 64)
    assert entity["child_metadata"] == child.metadata


def test_withdrawal_propagates_and_returns_unique_logical_children():
    fake = FakeMilvusClient()
    fake.rows["trade_knowledge_v1"] = [{"child_id": "same"}, {"child_id": "one"}]
    fake.rows["trade_knowledge_v2"] = [{"child_id": "same"}, {"child_id": "two"}]
    store = MilvusStore(_config(), client=fake)
    assert store.delete_by_document("m3-doc", 1) == 3
    assert all(not rows for rows in fake.rows.values())


def test_expired_filter_uses_server_controlled_cutoff():
    fake = FakeMilvusClient()
    store = MilvusStore(_config(), client=fake)
    expression = store._search_filter(Actor("public", frozenset(), "trade"))
    assert "is_public == true" in expression
    assert "expires_at_epoch_ms >" in expression
    expired = _document(expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    entity = store._entity(_children()[0], expired, [0.0] * 64)
    assert entity["expires_at_epoch_ms"] > 0


@pytest.mark.skipif(os.environ.get("NANOCLAW_TEST_MILVUS") != "1",
                    reason="requires isolated Docker Milvus")
def test_live_milvus_contract_alias_rollback_and_withdrawal():
    from trade_rag.config import load_rag_vector_config
    from trade_rag.embeddings import MockEmbeddingProvider
    from trade_rag.vector_store import create_vector_store
    from pymilvus import MilvusClient

    config = load_rag_vector_config()
    root = os.environ["RAG_MILVUS_ADMIN_TOKEN"]
    admin = MilvusClient(uri=config.milvus_uri, token=root,
                         db_name=config.milvus_database, timeout=10)
    manager = MilvusCollectionManager(admin)
    store = None
    completed = False
    try:
        manager.create_generation(2)
        manager.activate_generation(1)
        store = create_vector_store(config)
        actor = Actor("sales", frozenset({"sales"}), "trade")
        denied_role = Actor("finance", frozenset({"finance"}), "trade")
        denied_unit = Actor("sales", frozenset({"sales"}), "other")
        embedder = MockEmbeddingProvider(64)
        children = _children()
        vectors = embedder.embed([child.text for child in children])
        assert store.upsert(children, _document(), vectors) == 2
        manager.activate_generation(2)
        assert store.upsert(children, _document(), vectors) == 2
        assert [row.child.child_id for row in store.search(vectors[1], actor)] == [
            "m3-child-a", "m3-child-b"
        ]
        assert store.search(vectors[1], denied_role) == []
        assert store.search(vectors[1], denied_unit) == []
        manager.activate_generation(1)
        assert store.search(vectors[1], actor)
        draft = ChildChunk("m3-draft", "m3-parent", "m3-draft", "draft", "p1", "h")
        expired = ChildChunk("m3-expired", "m3-parent", "m3-expired", "expired", "p1", "h")
        store.upsert([draft], _document("m3-draft", status=DocumentStatus.DRAFT),
                     embedder.embed([draft.text]))
        store.upsert([expired], _document("m3-expired", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
                     embedder.embed([expired.text]))
        assert all(row.child.document_id not in {"m3-draft", "m3-expired"}
                   for row in store.search(vectors[1], actor))
        assert store.delete_by_document("m3-doc", 1) == 2
        assert store.delete_by_document("m3-draft") == 1
        assert store.delete_by_document("m3-expired") == 1
        manager.activate_generation(2)
        assert store.search(vectors[1], actor) == []
        completed = True
    finally:
        if completed:
            manager.activate_generation(2)
            manager.drop_generation(1)
        admin.close()
