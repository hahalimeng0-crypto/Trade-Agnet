from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from pdf_fixture_factory import build_fixture

from trade_rag.config import RagKeywordConfig, RagVectorConfig
from trade_rag.contracts import (
    Actor,
    CanonicalDocument,
    ChildChunk,
    DocumentStatus,
    ParentChunk,
)
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline
from trade_rag.sqlite_index import reconcile_sqlite_index
from trade_rag.sqlite_store import (
    SqliteKeywordStore,
    SqliteParentStore,
    SqliteVectorStore,
)
from trade_rag.vector_runtime import ManagedVectorStore, VectorBackendUnavailable


def _configs(path):
    return (
        RagVectorConfig("sqlite", 64, sqlite_path=str(path)),
        RagKeywordConfig("sqlite", sqlite_path=str(path)),
    )


def _document(document_id="sqlite-doc", *, status=DocumentStatus.PUBLISHED,
              roles=frozenset({"sales"}), unit="trade", expires_at=None, title="报价流程"):
    return CanonicalDocument(
        document_id, 1, f"sample://{document_id}", title, "source", f"hash-{document_id}",
        business_unit_id=unit, allowed_roles=roles, status=status, expires_at=expires_at,
    )


def _rows(document_id="sqlite-doc", suffix=""):
    parent = ParentChunk(
        f"parent-{document_id}", document_id, f"外贸 报价 审批 流程 {suffix}",
        "section:quote", f"parent-hash-{document_id}", {"kind": "parent"},
    )
    child = ChildChunk(
        f"child-{document_id}", parent.parent_id, document_id,
        f"外贸 报价 审批 流程 {suffix}", "section:quote", f"child-hash-{document_id}",
        {"kind": "child"},
    )
    return parent, child


def _close(*stores):
    for store in stores:
        delegate = getattr(store, "_delegate", store)
        close = getattr(delegate, "close", None)
        if close:
            close()


def test_sqlite_vec_bm25_parent_and_ids_survive_restart(tmp_path):
    path = tmp_path / "rag.db"
    vector_config, keyword_config = _configs(path)
    document = _document()
    parent, child = _rows()
    embedding = [1.0] + [0.0] * 63
    actor = Actor("seller", frozenset({"sales"}), "trade")

    vector = SqliteVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    assert parents.upsert([parent], document) == 1
    assert vector.upsert([child], document, [embedding]) == 1
    assert keyword.upsert([child], document) == 1
    _close(vector, keyword, parents)

    vector = SqliteVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    try:
        semantic = vector.search(embedding, actor)
        lexical = keyword.search("报价审批", actor)
        restored_parent = parents.get(parent.parent_id, actor)
        assert [hit.child.child_id for hit in semantic] == [child.child_id]
        assert [hit.child.child_id for hit in lexical] == [child.child_id]
        assert lexical[0].retrieval_source == "keyword"
        assert semantic[0].source.allowed_roles == frozenset({"sales"})
        assert restored_parent == parent
    finally:
        _close(vector, keyword, parents)


def test_sqlite_server_side_acl_status_expiry_and_bm25_ranking(tmp_path):
    path = tmp_path / "rag.db"
    vector_config, keyword_config = _configs(path)
    vector = SqliteVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    embedding = [1.0] + [0.0] * 63
    documents = [
        _document("allowed", title="报价 报价 审批"),
        _document("allowed-weak", title="普通 指南"),
        _document("denied-role", roles=frozenset({"finance"})),
        _document("denied-unit", unit="other"),
        _document("draft", status=DocumentStatus.DRAFT),
        _document("expired", expires_at=datetime.now(timezone.utc) - timedelta(days=1)),
    ]
    try:
        for document in documents:
            parent, child = _rows(document.document_id, "报价")
            parents.upsert([parent], document)
            vector.upsert([child], document, [embedding])
            keyword.upsert([child], document)
        actor = Actor("seller", frozenset({"sales"}), "trade")
        assert {hit.child.document_id for hit in vector.search(embedding, actor)} == {
            "allowed", "allowed-weak",
        }
        keyword_ids = [hit.child.document_id for hit in keyword.search("报价审批", actor)]
        assert keyword_ids == ["allowed", "allowed-weak"]
        assert parents.get("parent-denied-role", actor) is None
    finally:
        _close(vector, keyword, parents)


def test_sqlite_upsert_version_delete_and_fail_closed_without_memory_fallback(tmp_path):
    path = tmp_path / "rag.db"
    vector_config, keyword_config = _configs(path)
    vector = SqliteVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    document = _document()
    parent, child = _rows()
    embedding = [1.0] + [0.0] * 63
    try:
        assert vector.upsert([child], document, [embedding]) == 1
        assert vector.upsert([child], document, [embedding]) == 1
        assert keyword.upsert([child], document) == 1
        assert parents.upsert([parent], document) == 1
        assert vector.delete_by_document(document.document_id, 2) == 0
        assert vector.delete_by_document(document.document_id, 1) == 1
        assert keyword.delete_by_document(document.document_id, 1) == 1
        assert parents.delete_by_document(document.document_id, 1) == 1
    finally:
        _close(vector, keyword, parents)

    with pytest.raises(RuntimeError, match="model_or_schema_mismatch"):
        SqliteVectorStore(vector_config, model_id="different-model")

    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a sqlite database")
    managed = ManagedVectorStore(
        RagVectorConfig("sqlite", 64, sqlite_path=str(broken)), retry_seconds=0,
    )
    with pytest.raises(VectorBackendUnavailable):
        managed.search(embedding, Actor("seller"))
    assert managed._delegate is None


def test_sqlite_reconcile_is_dry_run_idempotent_and_removes_revoked(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    active = repository.import_bytes("active.md", "出口 报价 指南".encode("utf-8"))
    stale = repository.import_bytes("stale.md", "撤回 报价 指南".encode("utf-8"))
    path = tmp_path / "rag.db"
    vector_config, keyword_config = _configs(path)
    managed = ManagedVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    pipeline = RagPipeline(store=managed, keyword_store=keyword, parent_store=parents)
    try:
        preview = reconcile_sqlite_index(repository, pipeline)
        assert preview["mode"] == "dry_run" and preview["documents_to_index"] == 2
        first = reconcile_sqlite_index(repository, pipeline, apply=True)
        assert first["indexed_chunks"] == first["active_chunks"] > 0
        indexed = repository.get_document(active["document_id"])
        assert indexed["index_status"] == "indexed"
        assert indexed["indexed_count"] == indexed["child_count"]
        assert reconcile_sqlite_index(repository, pipeline)["documents_to_index"] == 0

        repository.revoke(stale["document_id"], delete_index=lambda *_args: None)
        preview = reconcile_sqlite_index(repository, pipeline)
        assert preview["stale_documents"] == 1
        reconcile_sqlite_index(repository, pipeline, apply=True)
        final = reconcile_sqlite_index(repository, pipeline)
        assert final["stale_documents"] == 0 and final["documents_to_index"] == 0
        actor = Actor("seller", business_unit_id="default")
        hits = managed.search([1.0] + [0.0] * 63, actor)
        assert all(hit.child.document_id != stale["document_id"] for hit in hits)
        assert (active["document_id"], 1) in managed._delegate.db.state()
    finally:
        _close(managed, keyword, parents)


def test_pdf_http_import_persists_files_manifest_and_all_sqlite_indexes(tmp_path):
    fixture_manifest = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    case = next(row for row in fixture_manifest["cases"] if row["id"] == "text_bilingual")
    payload = build_fixture(case)
    repository = KnowledgeRepository(tmp_path / "knowledge")
    vector_config, keyword_config = _configs(tmp_path / "rag.db")
    managed = ManagedVectorStore(vector_config)
    keyword = SqliteKeywordStore(keyword_config)
    parents = SqliteParentStore(vector_config)
    pipeline = RagPipeline(store=managed, keyword_store=keyword, parent_store=parents)
    channel = WebChannel(MessageBus(), knowledge_pipeline=pipeline)
    channel._knowledge_repository = repository
    channel._app = FastAPI()
    channel._register_routes()
    try:
        with TestClient(channel._app) as client:
            response = client.post(
                "/api/knowledge/import", content=payload,
                headers={"X-File-Name": "acceptance.pdf", "Content-Type": "application/pdf"},
            )
            assert response.status_code == 202, response.text
            imported = response.json()
            deadline = time.monotonic() + 15
            while True:
                detail = client.get(
                    f"/api/knowledge/documents/{imported['document_id']}"
                ).json()
                if detail["index_status"] in {"indexed", "failed"}:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError("asynchronous PDF indexing timed out")
                time.sleep(0.02)
            listing = client.get("/api/knowledge/documents").json()
            imported = detail
        assert listing["total"] == 1
        assert listing["items"][0]["document_id"] == imported["document_id"]
        assert imported["index_status"] == "indexed"
        assert repository.manifest_path.is_file()
        assert len(list(repository.documents_dir.glob("*.pdf"))) == 1
        assert len(list(repository.parsed_dir.glob("*.parsed.json"))) == 1
        database = managed._delegate.db.connection
        assert database.execute("SELECT count(*) FROM rag_child_vec").fetchone()[0] > 0
        assert database.execute("SELECT count(*) FROM rag_child_fts").fetchone()[0] > 0
        assert database.execute("SELECT count(*) FROM rag_parent").fetchone()[0] > 0
    finally:
        _close(managed, keyword, parents)
