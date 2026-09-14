import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from trade_rag.contracts import Actor, QueryRequest
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline
import trade_rag.server as rag_server


def build(tmp_path: Path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    channel = WebChannel(MessageBus())
    channel._knowledge_repository = repository
    channel._knowledge_pipeline = RagPipeline()
    channel._app = FastAPI()
    channel._register_routes()
    return repository, channel, TestClient(channel._app)


def test_import_v3_counts_match_actual_splitter_and_duplicate(tmp_path: Path):
    repository, _, client = build(tmp_path)
    content = ("# Shipping\n\nDDP Madrid guidance. " * 80).encode()
    first = client.post("/api/knowledge/import", content=content, headers={"X-File-Name": "guide.md"})
    second = client.post("/api/knowledge/import", content=content, headers={"X-File-Name": "copy.md"})
    assert first.status_code == 200 and second.json()["duplicate"] is True
    entry = repository.get_document(first.json()["document_id"])
    document = repository.load_published()[0]
    parents, children = repository.splitter.split(document)
    assert entry["schema_version"] == "knowledge-import-v4"
    assert entry["source_hash"]
    assert entry["parse_status"] == "ready" and entry["chunk_status"] == "ready"
    assert (entry["parent_count"], entry["child_count"]) == (len(parents), len(children))
    assert entry["index_status"] == "ready"
    listing = client.get("/api/knowledge/documents").json()
    assert listing["total"] == 1
    assert listing["summary"]["parent_count"] == len(parents)
    assert "stored_name" not in json.dumps(listing)


def test_knowledge_is_internal_by_default_and_requires_explicit_public_classification(tmp_path: Path):
    repository, _, client = build(tmp_path)
    imported = client.post(
        "/api/knowledge/import",
        content=b"Customer-visible product guide",
        headers={"X-File-Name": "guide.md"},
    )
    assert imported.status_code == 200
    document_id = imported.json()["document_id"]
    assert imported.json()["classification"] == "internal"
    assert repository.load_published()[0].classification == "internal"

    published = client.patch(
        f"/api/knowledge/documents/{document_id}/classification",
        json={"classification": "public"},
    )
    assert published.status_code == 200
    assert repository.load_published()[0].classification == "public"

    rejected = client.patch(
        f"/api/knowledge/documents/{document_id}/classification",
        json={"classification": "secret"},
    )
    assert rejected.status_code == 400


def test_v1_manifest_is_lazily_upgraded_without_fabricated_zero(tmp_path: Path):
    root = tmp_path / "knowledge"
    docs = root / "documents"
    docs.mkdir(parents=True)
    (docs / "legacy.md").write_text("# Legacy\n\nUseful content", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"schema_version": "knowledge-import-v1", "documents": [{
        "document_id": "web-legacy", "version": 1, "original_name": "legacy.md", "stored_name": "legacy.md",
        "content_hash": "legacy", "content_type": "text/markdown", "status": "published",
        "business_unit_id": "default", "allowed_roles": []
    }]}), encoding="utf-8")
    repository = KnowledgeRepository(root)
    items, _, _ = repository.list_documents()
    assert items[0]["parent_count"] > 0 and items[0]["child_count"] > 0
    assert json.loads(repository.manifest_path.read_text(encoding="utf-8"))["schema_version"] == "knowledge-import-v4"


def test_missing_v1_source_marks_failed_not_zero(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"schema_version": "knowledge-import-v1", "documents": [{
        "document_id": "web-missing", "version": 1, "original_name": "missing.md", "stored_name": "missing.md",
        "content_hash": "missing", "content_type": "text/markdown", "status": "published"
    }]}), encoding="utf-8")
    item = KnowledgeRepository(root).list_documents()[0][0]
    assert item["index_status"] == "failed"
    assert item["parent_count"] is None and item["child_count"] is None


def test_delete_removes_both_indexes_moves_source_and_survives_restart(tmp_path: Path):
    repository, channel, client = build(tmp_path)
    imported = client.post("/api/knowledge/import", content=b"SKU-Z DDP Madrid knowledge", headers={"X-File-Name": "shipping.md"}).json()
    document = repository.load_published()[0]
    channel._knowledge_pipeline.index(document)
    actor = Actor("local")
    assert channel._knowledge_pipeline.query(QueryRequest("SKU-Z Madrid", actor))["citations"]
    response = client.delete(f"/api/knowledge/documents/{imported['document_id']}")
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert client.get("/api/knowledge/documents").json()["items"] == []
    deleted = client.get("/api/knowledge/documents?include_deleted=true").json()["items"]
    assert len(deleted) == 1 and deleted[0]["status"] == "revoked"
    assert not channel._knowledge_pipeline.query(QueryRequest("SKU-Z Madrid", actor))["citations"]
    assert list(repository.trash_dir.iterdir())
    assert repository.load_published() == []
    restarted = KnowledgeRepository(repository.root)
    assert restarted.load_published() == []


def test_delete_failure_stays_unsearchable_and_retryable(tmp_path: Path):
    repository, _, _ = build(tmp_path)
    entry = repository.import_bytes("guide.md", b"safe knowledge")
    result = repository.revoke(entry["document_id"], delete_index=lambda *_: (_ for _ in ()).throw(RuntimeError()))
    assert result["status"] == "revoke_pending" and result["index_status"] == "failed"
    assert repository.load_published() == []
    retried = repository.retry_revoke(entry["document_id"], delete_index=lambda *_: {"deleted": 1})
    assert retried["status"] == "revoked" and retried["index_status"] == "withdrawn"


def test_reimport_after_revoke_creates_a_new_active_record(tmp_path: Path):
    repository, _, client = build(tmp_path)
    content = b"reimportable local knowledge"
    first = client.post(
        "/api/knowledge/import", content=content, headers={"X-File-Name": "guide.md"}
    ).json()
    assert client.delete(f"/api/knowledge/documents/{first['document_id']}").json()["status"] == "revoked"

    second = client.post(
        "/api/knowledge/import", content=content, headers={"X-File-Name": "guide.md"}
    ).json()
    assert second["duplicate"] is False
    assert second["document_id"] == f"{first['document_id']}-v2"
    assert second["status"] == "published"
    visible = client.get("/api/knowledge/documents").json()["items"]
    history = client.get("/api/knowledge/documents?include_deleted=true").json()["items"]
    assert [item["document_id"] for item in visible] == [second["document_id"]]
    assert {item["status"] for item in history} == {"published", "revoked"}
    assert repository.load_published()[0].document_id == second["document_id"]


def test_legacy_reused_document_id_revokes_the_active_row_not_old_history(tmp_path: Path):
    repository, _, client = build(tmp_path)
    content = b"legacy duplicate id knowledge"
    first = client.post(
        "/api/knowledge/import", content=content, headers={"X-File-Name": "guide.md"}
    ).json()
    assert client.delete(f"/api/knowledge/documents/{first['document_id']}").status_code == 200
    second = client.post(
        "/api/knowledge/import", content=content, headers={"X-File-Name": "guide.md"}
    ).json()

    manifest = json.loads(repository.manifest_path.read_text(encoding="utf-8"))
    active = next(row for row in manifest["documents"] if row["status"] == "published")
    active["document_id"] = first["document_id"]
    repository._write_manifest(manifest)

    assert repository.get_document(first["document_id"])["status"] == "published"
    response = client.delete(f"/api/knowledge/documents/{first['document_id']}")
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert client.get("/api/knowledge/documents").json()["items"] == []
    history = client.get("/api/knowledge/documents?include_deleted=true").json()["items"]
    assert len(history) == 2 and {row["status"] for row in history} == {"revoked"}


def test_store_delete_is_document_and_version_scoped(tmp_path: Path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    first = repository.import_bytes("a.md", b"alpha unique knowledge")
    second = repository.import_bytes("b.md", b"beta unique knowledge")
    pipeline = RagPipeline()
    for document in repository.load_published():
        pipeline.index(document)
    deleted = pipeline.delete_by_document(first["document_id"], 1)
    assert deleted["semantic_deleted"] > 0 and deleted["keyword_deleted"] > 0
    assert all(entry.source.document_id == second["document_id"] for entry in pipeline.store._entries.values())


def test_mcp_reconcile_removes_revoked_document_from_existing_process(tmp_path: Path, monkeypatch):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    entry = repository.import_bytes("guide.md", b"withdraw this unique knowledge")
    pipeline = RagPipeline()
    monkeypatch.setattr(rag_server, "repository", repository)
    monkeypatch.setattr(rag_server, "pipeline", pipeline)
    monkeypatch.setattr(rag_server, "indexed_hashes", set())
    assert rag_server._refresh_imported_knowledge() == 1
    repository.revoke(entry["document_id"], delete_index=lambda *_: None)
    assert rag_server._refresh_imported_knowledge() == 0
    assert pipeline.store._entries == {}
