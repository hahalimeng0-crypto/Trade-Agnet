import json
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline

from pdf_fixture_factory import build_fixture


ROOT = Path(__file__).parents[2]
FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def _client(tmp_path):
    channel = WebChannel(MessageBus())
    channel._knowledge_repository = KnowledgeRepository(tmp_path / "knowledge")
    channel._knowledge_pipeline = RagPipeline()
    channel._app = FastAPI()
    channel._register_routes()
    return channel, TestClient(channel._app)


def _wait_for_terminal(client: TestClient, document_id: str, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = client.get(f"/api/knowledge/documents/{document_id}").json()
        if item["status"] == "review_required" or item["index_status"] in {"indexed", "failed"}:
            return item
        time.sleep(0.02)
    raise AssertionError("PDF ingestion did not reach a terminal state")


def test_pdf_m5_ui_assets_expose_picker_status_detail_and_preview_controls():
    page = (ROOT / "channels" / "web_ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "channels" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "channels" / "web_ui" / "static" / "app.css").read_text(encoding="utf-8")

    assert ".pdf" in page and "application/pdf" in page
    assert 'id="knowledgeDetailStages"' in page
    assert 'id="knowledgeOcrNotice"' in page
    assert 'id="knowledgeApproveReview"' in page
    assert 'id="knowledgeClassification"' in page
    assert 'id="knowledgePreviewSection"' in page
    assert "/chunks-preview?limit=12" in script
    assert "/approve-review" in script
    assert "knowledge.approveReviewConfirm" in script
    assert "knowledgeFailed(item)" in script
    assert "scheduleKnowledgeRefresh" in script and "knowledgeRefreshTimer" in script
    assert "file.knowledgeQueued" in script and "knowledge-error" in styles
    assert "knowledge.indexed" in script and "knowledge.needsOcr" in script
    assert "file.type?file.type:'application/octet-stream'" in script
    assert ".knowledge-stage.needs_ocr" in styles
    assert ".knowledge-review-approve" in styles
    assert "@media(max-width:520px)" in styles
    assert "body.non-chat-view .workflow-panel{display:none}" in styles


def test_pdf_preview_api_is_bounded_private_and_returns_page_locations(tmp_path):
    channel, client = _client(tmp_path)
    payload = build_fixture(_cases()["table_units"])
    imported = client.post(
        "/api/knowledge/import", content=payload,
        headers={"X-File-Name": "freight.pdf", "Content-Type": "application/pdf"},
    )
    assert imported.status_code == 202
    accepted = imported.json()
    assert accepted["status"] == "draft"
    body = _wait_for_terminal(client, accepted["document_id"])
    assert body["index_status"] == "indexed"

    response = client.get(
        f"/api/knowledge/documents/{body['document_id']}/chunks-preview?limit=2"
    )
    assert response.status_code == 200
    preview = response.json()
    assert 1 <= len(preview["parents"]) <= 2
    assert 1 <= len(preview["children"]) <= 2
    assert all(row["page_start"] >= 1 and row["page_end"] >= row["page_start"]
               for row in preview["children"])
    serialized = json.dumps(preview)
    assert "stored_name" not in serialized and str(tmp_path) not in serialized
    listing = client.get("/api/knowledge/documents").json()
    assert listing["summary"]["indexed_count"] == body["indexed_count"]
    assert channel._knowledge_repository.get_document(body["document_id"])["classification"] == "internal"


def test_needs_ocr_and_review_pdf_states_are_visible_but_preview_is_blocked(tmp_path):
    _, client = _client(tmp_path)
    scanned_accepted = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["scanned_only"]),
        headers={"X-File-Name": "scan.pdf", "Content-Type": "application/pdf"},
    ).json()
    mixed_accepted = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["mixed_text_scan"]),
        headers={"X-File-Name": "mixed.pdf", "Content-Type": "application/pdf"},
    ).json()
    scanned = _wait_for_terminal(client, scanned_accepted["document_id"])
    mixed = _wait_for_terminal(client, mixed_accepted["document_id"])

    assert scanned["status"] == "review_required" and scanned["needs_ocr"] is True
    assert scanned["parse_status"] == "needs_ocr" and scanned["index_status"] == "pending"
    assert mixed["status"] == "review_required" and mixed["needs_ocr"] is False
    assert mixed["ingestion_route"] == "review_required"
    assert client.get(
        f"/api/knowledge/documents/{scanned['document_id']}"
    ).json()["review_approval_eligible"] is False
    assert client.get(
        f"/api/knowledge/documents/{mixed['document_id']}"
    ).json()["review_approval_eligible"] is False
    assert client.post(
        f"/api/knowledge/documents/{scanned['document_id']}/approve-review"
    ).status_code == 409
    assert client.post(
        f"/api/knowledge/documents/{mixed['document_id']}/approve-review"
    ).status_code == 409
    assert client.get(
        f"/api/knowledge/documents/{scanned['document_id']}/chunks-preview"
    ).status_code == 409
    listing = client.get("/api/knowledge/documents").json()
    assert listing["summary"]["needs_ocr_count"] == 1


def test_complex_layout_review_approval_chunks_indexes_and_previews_pdf(tmp_path):
    _, client = _client(tmp_path)
    imported = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["two_column"]),
        headers={"X-File-Name": "layout.pdf", "Content-Type": "application/pdf"},
    )
    assert imported.status_code == 202
    before = _wait_for_terminal(client, imported.json()["document_id"])
    document_id = before["document_id"]
    assert before["status"] == "review_required"
    assert before["chunk_status"] == "pending"
    assert before["index_status"] == "pending"

    detail = client.get(f"/api/knowledge/documents/{document_id}").json()
    assert detail["review_approval_eligible"] is True
    assert detail["classification"] == "internal"

    approved = client.post(
        f"/api/knowledge/documents/{document_id}/approve-review"
    )
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "published"
    assert body["chunk_status"] == "ready"
    assert body["index_status"] == "indexed"
    assert body["parent_count"] > 0
    assert body["child_count"] > 0
    assert body["indexed_count"] == body["child_count"]
    assert body["review_approval_eligible"] is False

    preview_response = client.get(
        f"/api/knowledge/documents/{document_id}/chunks-preview?limit=12"
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["parent_count"] == body["parent_count"]
    assert preview["child_count"] == body["child_count"]
    assert preview["parents"] and preview["children"]
    serialized = json.dumps({"approved": body, "preview": preview})
    assert "stored_name" not in serialized
    assert "parsed_hash" not in serialized
    assert str(tmp_path) not in serialized


def test_pdf_classification_control_rebuilds_index_and_remains_path_private(tmp_path):
    channel, client = _client(tmp_path)
    imported = client.post(
        "/api/knowledge/import", content=build_fixture(_cases()["text_english"]),
        headers={"X-File-Name": "guide.pdf", "Content-Type": "application/pdf"},
    ).json()
    document_id = imported["document_id"]
    _wait_for_terminal(client, document_id)
    before_generation = channel._knowledge_repository.get_document(document_id)["index_generation"]
    response = client.patch(
        f"/api/knowledge/documents/{document_id}/classification",
        json={"classification": "public"},
    )
    assert response.status_code == 200 and response.json()["classification"] == "public"
    detail = client.get(f"/api/knowledge/documents/{document_id}").json()
    assert detail["classification"] == "public"
    assert detail["index_status"] == "indexed"
    assert detail["index_generation"] == before_generation + 1
    assert "stored_name" not in json.dumps(detail)
