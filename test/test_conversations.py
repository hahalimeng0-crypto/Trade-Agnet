import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus, OutboundMessage
from channels.web import WebChannel
from session.conversation import ConversationService
from session.manager import SessionManager
from session.conversation_migrate import main as migrate_main


def build_client(tmp_path: Path):
    service = ConversationService(tmp_path / "sessions")
    channel = WebChannel(MessageBus(), conversation_service=service)
    channel._app = FastAPI()
    channel._register_routes()
    return service, channel, TestClient(channel._app)


def test_conversation_crud_soft_delete_restore_and_message_whitelist(tmp_path: Path):
    service, _, client = build_client(tmp_path)
    created = client.post("/api/conversations", json={"title": "A\x00 conversation"})
    assert created.status_code == 201
    item = created.json()
    assert item["title"] == "A conversation"
    conversation_id = item["conversation_id"]

    session = SessionManager(str(service.sessions_dir))
    session.save_message(f"web:local:{conversation_id}", {"role": "user", "content": "hello"})
    session.save_message(f"web:local:{conversation_id}", {"role": "tool", "content": "private tool result"})
    with (service.sessions_dir / item["conversation_id"]).with_suffix(".missing").open("w"):
        pass
    message_path = service.sessions_dir / service.get(conversation_id).message_file
    with message_path.open("a", encoding="utf-8") as handle:
        handle.write("broken tail")

    messages = client.get(f"/api/conversations/{conversation_id}/messages").json()
    assert messages["total"] == 1
    assert messages["items"][0]["content"] == "hello"
    assert "private tool result" not in json.dumps(messages)

    renamed = client.patch(f"/api/conversations/{conversation_id}", json={"title": "Customer A"})
    assert renamed.json()["title"] == "Customer A"
    assert client.delete(f"/api/conversations/{conversation_id}").status_code == 200
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 404
    deleted = client.get("/api/conversations?include_deleted=true").json()["items"][0]
    assert deleted["deleted_at"]
    assert client.post(f"/api/conversations/{conversation_id}/restore").status_code == 200
    assert client.get(f"/api/conversations/{conversation_id}").status_code == 200


def test_list_search_pagination_and_invalid_id_are_stable(tmp_path: Path):
    _, _, client = build_client(tmp_path)
    for title in ("Alpha", "Beta", "Gamma"):
        assert client.post("/api/conversations", json={"title": title}).status_code == 201
    result = client.get("/api/conversations?search=a&offset=1&limit=1").json()
    assert result["total"] == 3
    assert len(result["items"]) == 1
    response = client.get("/api/conversations/../../config.json")
    assert response.status_code in {404, 405}
    response = client.get("/api/conversations/not-a-uuid")
    assert response.status_code == 404
    assert response.json()["detail"] == "conversation_not_found"


def test_legacy_web_sessions_are_indexed_without_rewrite(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    legacy_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    legacy = sessions / f"web_{legacy_id}.jsonl"
    original = b'{"role":"user","content":"legacy"}\n'
    legacy.write_bytes(original)
    (sessions / "qq_private.jsonl").write_text("{}\n", encoding="utf-8")

    service = ConversationService(sessions)

    assert legacy.read_bytes() == original
    items, total = service.list()
    assert total == 1
    assert items[0].conversation_id == legacy_id
    assert items[0].message_file == legacy.name


def test_migration_dry_run_and_apply_are_idempotent(tmp_path: Path, capsys):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    legacy = sessions / f"web_{conversation_id}.jsonl"
    legacy.write_text('{"role":"user","content":"safe"}\n', encoding="utf-8")
    original = legacy.read_bytes()

    assert migrate_main(["--dry-run", "--sessions-dir", str(sessions)]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run == {"existing": 0, "indexed": 1, "mode": "dry-run"}
    assert migrate_main(["--apply", "--sessions-dir", str(sessions)]) == 0
    assert json.loads(capsys.readouterr().out)["indexed"] == 1
    assert migrate_main(["--apply", "--sessions-dir", str(sessions)]) == 0
    assert json.loads(capsys.readouterr().out)["indexed"] == 0
    assert legacy.read_bytes() == original


def test_websocket_requires_bind_routes_stable_session_and_deduplicates(tmp_path: Path):
    service, channel, client = build_client(tmp_path)
    first = service.create("First")
    second = service.create("Second")
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "chat.message", "protocol_version": 2,
                             "conversation_id": first.conversation_id, "request_id": "r0", "content": "no bind"})
        assert websocket.receive_json()["code"] == "conversation_not_bound"
        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": first.conversation_id})
        assert websocket.receive_json()["type"] == "conversation.bound"
        assert websocket.receive_json()["type"] == "workflow.snapshot"
        websocket.send_json({"type": "chat.message", "protocol_version": 2,
                             "conversation_id": first.conversation_id, "request_id": "r1", "content": "hello"})
        websocket.send_json({"type": "chat.message", "protocol_version": 2,
                             "conversation_id": first.conversation_id, "request_id": "r1", "content": "hello"})
        assert websocket.receive_json()["type"] == "chat.duplicate"
        inbound = channel.bus.inbound_queue.get_nowait()
        assert inbound.sender_id == f"local:{first.conversation_id}"
        assert inbound.raw["conversation_id"] == first.conversation_id

        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": second.conversation_id})
        assert websocket.receive_json()["conversation_id"] == second.conversation_id
        assert websocket.receive_json()["type"] == "workflow.snapshot"
        assert channel._bindings


def test_late_reply_is_not_sent_after_conversation_switch(tmp_path: Path):
    service, channel, client = build_client(tmp_path)
    first, second = service.create("First"), service.create("Second")
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": first.conversation_id})
        websocket.receive_json()
        websocket.receive_json()
        client_id = next(iter(channel._connections))
        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": second.conversation_id})
        websocket.receive_json()
        websocket.receive_json()
        import asyncio
        asyncio.run(channel.send(OutboundMessage(channel="web", chat_id=client_id,
                                                  content="late", conversation_id=first.conversation_id)))
        assert channel._bindings[client_id] == second.conversation_id
