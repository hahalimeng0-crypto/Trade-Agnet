import json
import time
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.workflow import WorkflowService
from bus import MessageBus
from channels.web import WebChannel
from session.conversation import ConversationService
from session.manager import SessionManager
from trade_rag.knowledge_repository import KnowledgeRepository


def build_channel(tmp_path: Path):
    conversations = ConversationService(tmp_path / "sessions")
    workflows = WorkflowService(tmp_path / "workflows")
    channel = WebChannel(MessageBus(), conversation_service=conversations,
                         workflow_service=workflows)
    channel._knowledge_repository = KnowledgeRepository(tmp_path / "knowledge")
    channel._app = FastAPI()
    channel._register_routes()
    return conversations, workflows, channel, TestClient(channel._app)


def test_controlled_release_switches_hide_new_entry_points_without_deleting_data(tmp_path: Path):
    conversations, _, channel, client = build_channel(tmp_path)
    item = conversations.create("keep me")
    source = channel._knowledge_repository.import_bytes("keep.md", b"keep this local knowledge")
    channel._multi_conversation_enabled = False
    channel._knowledge_admin_enabled = False
    channel._workflow_events_enabled = False

    capabilities = client.get("/api/capabilities").json()
    assert capabilities == {"web_multi_conversation": False, "knowledge_admin": False,
                            "workflow_events": False}
    assert client.get("/api/conversations").status_code == 404
    assert client.get("/api/knowledge/documents").status_code == 404
    assert client.get(f"/api/conversations/{item.conversation_id}/workflow-runs").status_code == 404
    assert conversations.get(item.conversation_id).title == "keep me"
    assert channel._knowledge_repository.get_document(source["document_id"])["status"] == "published"


def test_manifest_v1_upgrade_creates_read_only_backup_and_is_idempotent(tmp_path: Path):
    root = tmp_path / "knowledge"
    documents = root / "documents"
    documents.mkdir(parents=True)
    (documents / "legacy.md").write_text("# Legacy\n\nSafe knowledge", encoding="utf-8")
    original = {"schema_version": "knowledge-import-v1", "documents": [{
        "document_id": "legacy-doc", "version": 1, "original_name": "legacy.md",
        "stored_name": "legacy.md", "content_hash": "abc", "content_type": "text/markdown",
        "business_unit_id": "default", "allowed_roles": [], "status": "published",
    }]}
    (root / "manifest.json").write_text(json.dumps(original), encoding="utf-8")

    repository = KnowledgeRepository(root)
    repository.list_documents()
    backup = root / "manifest.v1.backup.json"
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    before = backup.read_bytes()
    repository.list_documents()
    assert backup.read_bytes() == before


def test_manifest_upgrade_failure_restores_v1_for_read_only_recovery(tmp_path: Path):
    root = tmp_path / "knowledge"
    root.mkdir()
    original = {"schema_version": "knowledge-import-v1", "documents": []}
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps(original), encoding="utf-8")
    repository = KnowledgeRepository(root)
    with patch.object(repository, "_write_manifest", side_effect=OSError("simulated")):
        try:
            repository.list_documents()
        except OSError:
            pass
        else:
            raise AssertionError("upgrade failure must be visible to the caller")
    assert json.loads(manifest.read_text(encoding="utf-8")) == original


def test_security_payloads_are_blocked_or_returned_as_inert_data(tmp_path: Path):
    _, _, _, client = build_channel(tmp_path)
    assert client.get("/api/conversations/not-a-uuid").json()["detail"] == "conversation_not_found"
    assert client.get("/api/conversations/..%2F..%2Fconfig.json").status_code in {404, 405}
    response = client.post("/api/knowledge/import", content=b"unsafe path", 
                           headers={"X-File-Name": "..%2F..%2Fevil.txt"})
    assert response.status_code == 200
    assert response.json()["name"] == "evil.txt"
    assert not (tmp_path / "evil.txt").exists()
    response = client.post("/api/knowledge/import", content=b"<p>safe text</p><script>alert(1)</script>",
                           headers={"X-File-Name": "evil.html"})
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "evil.html"
    assert "stored_name" not in body and str(tmp_path) not in json.dumps(body)
    detail = client.get(f"/api/knowledge/documents/{body['document_id']}").json()
    assert "stored_name" not in detail and str(tmp_path) not in json.dumps(detail)


def test_local_list_and_pagination_p95_budget_smoke(tmp_path: Path):
    conversations, workflows, channel, client = build_channel(tmp_path)
    populated_id = None
    for index in range(100):
        item = conversations.create(f"Conversation {index:03d}")
        if index == 0:
            populated_id = item.conversation_id
            session = SessionManager(str(conversations.sessions_dir))
            for message in range(1000):
                session.save_message(f"web:local:{item.conversation_id}", {
                    "role": "user" if message % 2 == 0 else "assistant", "content": f"message {message}"})
    for index in range(100):
        channel._knowledge_repository.import_bytes(f"doc-{index}.md", f"unique knowledge {index}".encode())

    durations = []
    for _ in range(20):
        started = time.perf_counter()
        assert client.get("/api/conversations?limit=100").status_code == 200
        assert client.get("/api/knowledge/documents?limit=100").status_code == 200
        durations.append((time.perf_counter() - started) * 1000)
    durations.sort()
    p95 = durations[int(len(durations) * 0.95) - 1]
    assert p95 < 500, f"local list P95 was {p95:.1f} ms"

    page = client.get(f"/api/conversations/{populated_id}/messages?offset=900&limit=100")
    assert page.status_code == 200
    assert page.json()["total"] == 1000 and len(page.json()["items"]) == 100
