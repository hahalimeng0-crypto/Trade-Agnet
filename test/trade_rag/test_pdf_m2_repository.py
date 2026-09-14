import hashlib
import json
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from pdf_fixture_factory import build_fixture
from trade_rag.knowledge_repository import KnowledgeRepository

FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def _web_client(repository: KnowledgeRepository):
    channel = WebChannel(MessageBus())
    channel._knowledge_repository = repository
    channel._app = FastAPI()
    channel._register_routes()
    return TestClient(channel._app)


def _wait_for_terminal(client: TestClient, document_id: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.get(f"/api/knowledge/documents/{document_id}").json()
        if item["status"] == "review_required" or item["index_status"] in {"indexed", "failed"}:
            return item
        time.sleep(0.02)
    raise AssertionError("PDF ingestion did not reach a terminal state")


def test_pdf_import_persists_v3_source_and_parse_artifact_and_survives_restart(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    payload = build_fixture(_cases()["text_bilingual"])
    imported = repository.import_bytes("贸易指南.pdf", payload, content_type="application/pdf")

    assert imported["schema_version"] == "knowledge-import-v4"
    assert imported["source_hash"] == hashlib.sha256(payload).hexdigest()
    assert imported["source_hash"] != imported["content_hash"]
    assert imported["parse_status"] == "ready"
    assert imported["chunk_status"] == "ready" and imported["index_status"] == "pending"
    assert imported["ingestion_route"] == "index" and imported["status"] == "published"
    assert repository.load_published() == []
    source = repository.documents_dir / imported["source_stored_name"]
    parsed = repository.parsed_dir / imported["parsed_stored_name"]
    assert source.read_bytes() == payload and parsed.is_file()

    restarted = KnowledgeRepository(repository.root)
    result = restarted.load_parsed_result(imported["document_id"])
    assert result.pages == 2
    assert "中英贸易知识" in result.content
    assert restarted.get_document(imported["document_id"])["source_hash"] == imported["source_hash"]


def test_pdf_duplicate_uses_source_hash_while_same_text_different_binary_keeps_provenance(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    payload = build_fixture(_cases()["text_english"])
    first = repository.import_bytes("guide.pdf", payload)
    duplicate = repository.import_bytes("copy.pdf", payload)
    variant = repository.import_bytes("variant.pdf", payload + b"\n% synthetic provenance variant")

    assert duplicate["duplicate"] is True and duplicate["document_id"] == first["document_id"]
    assert variant["duplicate"] is False and variant["document_id"] != first["document_id"]
    assert variant["source_hash"] != first["source_hash"]
    assert variant["content_hash"] == first["content_hash"]
    assert len(repository.list_documents()[0]) == 2


def test_scan_and_mixed_pdf_are_persisted_for_review_but_never_loaded_for_rag(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    cases = _cases()
    scanned = repository.import_bytes("scan.pdf", build_fixture(cases["scanned_only"]))
    mixed = repository.import_bytes("mixed.pdf", build_fixture(cases["mixed_text_scan"]))

    assert scanned["status"] == "review_required"
    assert scanned["parse_status"] == "needs_ocr" and scanned["needs_ocr"] is True
    assert scanned["last_error_code"] == "pdf_needs_ocr"
    assert mixed["status"] == "review_required"
    assert mixed["parse_status"] == "ready" and mixed["ingestion_route"] == "review_required"
    assert repository.load_published() == []
    assert repository.list_documents()[2]["needs_ocr_count"] == 1


def test_pdf_import_rolls_back_both_artifacts_when_artifact_or_manifest_write_fails(tmp_path, monkeypatch):
    payload = build_fixture(_cases()["text_english"])
    repository = KnowledgeRepository(tmp_path / "artifact-failure")
    original_write = repository._write_bytes_atomic

    def fail_parsed(directory, name, content):
        if directory == repository.parsed_dir:
            raise OSError("simulated parsed write failure")
        return original_write(directory, name, content)

    monkeypatch.setattr(repository, "_write_bytes_atomic", fail_parsed)
    with pytest.raises(OSError):
        repository.import_bytes("guide.pdf", payload)
    assert not list(repository.documents_dir.glob("*"))
    assert not repository.manifest_path.exists()

    repository = KnowledgeRepository(tmp_path / "manifest-failure")
    monkeypatch.setattr(repository, "_write_manifest", lambda _manifest: (_ for _ in ()).throw(OSError("simulated")))
    with pytest.raises(OSError):
        repository.import_bytes("guide.pdf", payload)
    assert not list(repository.documents_dir.glob("*"))
    assert not list(repository.parsed_dir.glob("*"))
    assert not repository.manifest_path.exists()


def test_v2_manifest_upgrade_is_backed_up_idempotent_and_restart_safe(tmp_path):
    root = tmp_path / "knowledge"
    documents = root / "documents"
    documents.mkdir(parents=True)
    (documents / "legacy.md").write_text("# Legacy\n\nSafe content", encoding="utf-8")
    original = {"schema_version": "knowledge-import-v2", "documents": [{
        "document_id": "legacy-doc", "version": 1, "original_name": "legacy.md",
        "stored_name": "legacy.md", "content_hash": "old", "content_type": "text/markdown",
        "business_unit_id": "default", "allowed_roles": [], "status": "published",
        "index_status": "ready", "parent_count": 1, "child_count": 1,
    }]}
    (root / "manifest.json").write_text(json.dumps(original), encoding="utf-8")

    repository = KnowledgeRepository(root)
    item = repository.list_documents()[0][0]
    manifest = json.loads(repository.manifest_path.read_text(encoding="utf-8"))
    backup = root / "manifest.v2.backup.json"
    assert manifest["schema_version"] == "knowledge-import-v4"
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    assert item["source_hash"] and item["parse_status"] == "ready" and item["chunk_status"] == "ready"
    backup_before = backup.read_bytes()
    assert KnowledgeRepository(root).load_published()[0].document_id == "legacy-doc"
    assert backup.read_bytes() == backup_before


def test_parsed_artifact_tampering_is_detected_and_pdf_revoke_moves_both_files(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    payload = build_fixture(_cases()["text_english"])
    imported = repository.import_bytes("guide.pdf", payload)
    parsed = repository.parsed_dir / imported["parsed_stored_name"]
    parsed.write_bytes(parsed.read_bytes() + b" ")
    with pytest.raises(RuntimeError, match="knowledge_parsed_artifact_invalid"):
        repository.load_parsed_result(imported["document_id"])

    parsed.write_bytes(json.dumps(
        json.loads(parsed.read_text(encoding="utf-8")), ensure_ascii=False, indent=2
    ).encode("utf-8") + b"\n")
    manifest = json.loads(repository.manifest_path.read_text(encoding="utf-8"))
    entry = manifest["documents"][0]
    entry["parsed_hash"] = hashlib.sha256(parsed.read_bytes()).hexdigest()
    repository._write_manifest(manifest)
    revoked = repository.revoke(imported["document_id"], delete_index=lambda *_: None)
    assert revoked["status"] == "revoked"
    assert len(list(repository.trash_dir.iterdir())) == 2
    assert not list(repository.documents_dir.glob("*")) and not list(repository.parsed_dir.glob("*"))


def test_v3_source_tampering_is_not_silently_rehashed(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    imported = repository.import_bytes("guide.pdf", build_fixture(_cases()["text_english"]))
    original_hash = imported["source_hash"]
    source = repository.documents_dir / imported["source_stored_name"]
    source.write_bytes(source.read_bytes() + b"tampered")

    item = repository.list_documents()[0][0]
    assert item["source_hash"] == original_hash
    assert item["parse_status"] == "failed" and item["chunk_status"] == "failed"
    assert item["index_status"] == "failed"
    assert item["last_error_code"] == "knowledge_source_integrity_failed"
    manifest = json.loads(repository.manifest_path.read_text(encoding="utf-8"))
    assert manifest["documents"][0]["source_hash"] == original_hash


def test_web_pdf_import_returns_quality_metadata_without_private_paths(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    client = _web_client(repository)
    payload = build_fixture(_cases()["text_english"])
    response = client.post(
        "/api/knowledge/import",
        content=payload,
        headers={"X-File-Name": "guide.pdf", "Content-Type": "application/pdf"},
    )
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["status"] == "draft" and accepted["parse_status"] in {"pending", "running"}
    body = _wait_for_terminal(client, accepted["document_id"])
    assert body["content_type"] == "application/pdf"
    assert body["parser"] == "pdfplumber" and body["pages"] == 2
    assert body["parse_status"] == "ready" and body["chunk_status"] == "ready"
    assert body["index_status"] == "indexed" and body["indexed_count"] == body["child_count"]
    assert body["ingestion_route"] == "index" and body["needs_ocr"] is False
    serialized = json.dumps(body)
    assert "stored_name" not in serialized and str(tmp_path) not in serialized
    detail = client.get(f"/api/knowledge/documents/{body['document_id']}").json()
    assert "source_stored_name" not in detail and "parsed_stored_name" not in detail
