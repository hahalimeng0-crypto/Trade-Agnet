import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from pdf_fixture_factory import build_fixture
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pdf_ingestion import PdfIngestionCoordinator
from trade_rag.pipeline import RagPipeline
from trade_rag.stores import InMemoryVectorStore


FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def _runtime(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    pipeline = RagPipeline(store=InMemoryVectorStore())
    coordinator = PdfIngestionCoordinator(repository, pipeline)
    channel = WebChannel(
        MessageBus(), knowledge_repository=repository, knowledge_pipeline=pipeline,
        pdf_ingestion=coordinator,
    )
    channel._app = FastAPI()
    channel._register_routes()
    return repository, pipeline, coordinator, TestClient(channel._app)


def _wait(client: TestClient, document_id: str, *, terminal=("indexed", "failed"), timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.get(f"/api/knowledge/documents/{document_id}").json()
        if item["index_status"] in terminal or item["status"] in {"review_required", "revoked"}:
            return item
        time.sleep(0.02)
    raise AssertionError("PDF ingestion did not reach the expected state")


def test_pdf_upload_returns_202_and_is_visible_while_worker_is_busy(tmp_path, monkeypatch):
    repository, _, coordinator, client = _runtime(tmp_path)
    original = repository.process_staged_pdf
    started = threading.Event()
    release = threading.Event()

    def slow_process(document_id):
        started.set()
        assert release.wait(5)
        return original(document_id)

    monkeypatch.setattr(repository, "process_staged_pdf", slow_process)
    before = time.monotonic()
    response = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["text_english"]),
        headers={"X-File-Name": "queued.pdf", "Content-Type": "application/pdf"},
    )
    elapsed = time.monotonic() - before
    assert response.status_code == 202 and elapsed < 1.0
    accepted = response.json()
    assert started.wait(1)
    visible = client.get("/api/knowledge/documents").json()["items"]
    assert visible[0]["document_id"] == accepted["document_id"]
    assert visible[0]["status"] == "draft"
    assert visible[0]["parse_status"] in {"pending", "running"}

    release.set()
    assert coordinator.wait_for_idle(15)
    completed = _wait(client, accepted["document_id"])
    assert completed["status"] == "published"
    assert completed["index_status"] == "indexed"
    assert completed["processing_completed_at"]
    coordinator.stop()


def test_shared_coordinator_serializes_jobs_and_deduplicates_two_web_ports(tmp_path, monkeypatch):
    repository, pipeline, coordinator, client_a = _runtime(tmp_path)
    channel_b = WebChannel(
        MessageBus(), knowledge_repository=repository, knowledge_pipeline=pipeline,
        pdf_ingestion=coordinator, channel_name="workspace_web",
    )
    channel_b._app = FastAPI()
    channel_b._register_routes()
    client_b = TestClient(channel_b._app)
    original = repository.process_staged_pdf
    lock = threading.Lock()
    active = 0
    maximum = 0
    calls = 0

    def counted_process(document_id):
        nonlocal active, maximum, calls
        with lock:
            active += 1
            calls += 1
            maximum = max(maximum, active)
        time.sleep(0.08)
        try:
            return original(document_id)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(repository, "process_staged_pdf", counted_process)
    first_payload = build_fixture(_cases()["text_english"])
    first = client_a.post(
        "/api/knowledge/import", content=first_payload,
        headers={"X-File-Name": "one.pdf", "Content-Type": "application/pdf"},
    ).json()
    duplicate = client_b.post(
        "/api/knowledge/import", content=first_payload,
        headers={"X-File-Name": "copy.pdf", "Content-Type": "application/pdf"},
    ).json()
    second = client_b.post(
        "/api/knowledge/import", content=build_fixture(_cases()["text_bilingual"]),
        headers={"X-File-Name": "two.pdf", "Content-Type": "application/pdf"},
    ).json()
    assert duplicate["duplicate"] is True
    assert duplicate["document_id"] == first["document_id"]
    assert coordinator.wait_for_idle(15)
    assert _wait(client_a, first["document_id"])["index_status"] == "indexed"
    assert _wait(client_b, second["document_id"])["index_status"] == "indexed"
    assert maximum == 1 and calls == 2
    coordinator.stop()


def test_pending_job_recovers_after_restart_and_terminal_failure_requires_retry(tmp_path, monkeypatch):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    pipeline = RagPipeline(store=InMemoryVectorStore())
    staged = repository.stage_pdf(
        "recover.pdf", build_fixture(_cases()["text_english"]),
        content_type="application/pdf",
    )
    with repository._lock:
        manifest = repository._read_upgraded_manifest()
        manifest["documents"][0]["parse_status"] = "running"
        repository._write_manifest(manifest)

    recovered = PdfIngestionCoordinator(repository, pipeline)
    recovered.start()
    assert recovered.wait_for_idle(15)
    assert repository.get_document(staged["document_id"])["index_status"] == "indexed"
    recovered.stop()

    failed = repository.stage_pdf("broken.pdf", b"not-a-pdf", content_type="application/pdf")
    worker = PdfIngestionCoordinator(repository, pipeline)
    worker.enqueue(failed["document_id"])
    assert worker.wait_for_idle(5)
    detail = repository.get_document(failed["document_id"])
    assert detail["parse_status"] == "failed"
    assert detail["last_error_code"] == "pdf_signature_mismatch"
    worker.stop()

    called = threading.Event()
    original = repository.process_staged_pdf

    def observe(document_id):
        called.set()
        return original(document_id)

    monkeypatch.setattr(repository, "process_staged_pdf", observe)
    restarted = PdfIngestionCoordinator(repository, pipeline)
    restarted.start()
    time.sleep(0.1)
    assert not called.is_set()
    restarted.stop()


def test_failed_duplicate_is_requeued_and_revoke_wins_running_worker(tmp_path, monkeypatch):
    repository, pipeline, coordinator, client = _runtime(tmp_path)
    payload = build_fixture(_cases()["text_english"])
    original = repository.process_staged_pdf
    first_call = True

    def fail_once(document_id):
        nonlocal first_call
        if first_call:
            first_call = False
            return repository._mark_pdf_processing_failure(
                document_id, stage="parse", error_code="ocr_recognition_failed",
            )
        return original(document_id)

    monkeypatch.setattr(repository, "process_staged_pdf", fail_once)
    first = client.post(
        "/api/knowledge/import", content=payload,
        headers={"X-File-Name": "retry.pdf", "Content-Type": "application/pdf"},
    ).json()
    assert _wait(client, first["document_id"])["last_error_code"] == "ocr_recognition_failed"
    retried = client.post(
        "/api/knowledge/import", content=payload,
        headers={"X-File-Name": "retry-again.pdf", "Content-Type": "application/pdf"},
    ).json()
    assert retried["duplicate"] is True and retried["document_id"] == first["document_id"]
    assert coordinator.wait_for_idle(15)
    assert _wait(client, first["document_id"])["index_status"] == "indexed"

    started = threading.Event()
    release = threading.Event()

    def blocked(document_id):
        started.set()
        assert release.wait(5)
        return original(document_id)

    monkeypatch.setattr(repository, "process_staged_pdf", blocked)
    running = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["text_bilingual"]),
        headers={"X-File-Name": "revoke.pdf", "Content-Type": "application/pdf"},
    ).json()
    assert started.wait(1)
    deleted = client.delete(f"/api/knowledge/documents/{running['document_id']}")
    assert deleted.status_code == 200 and deleted.json()["status"] == "revoked"
    release.set()
    assert coordinator.wait_for_idle(5)
    history = client.get("/api/knowledge/documents?include_deleted=true&limit=100").json()["items"]
    revoked = next(item for item in history if item["document_id"] == running["document_id"])
    assert revoked["status"] == "revoked" and revoked["index_status"] == "withdrawn"
    assert pipeline.delete_by_document(running["document_id"], 1)["semantic_deleted"] == 0
    coordinator.stop()

