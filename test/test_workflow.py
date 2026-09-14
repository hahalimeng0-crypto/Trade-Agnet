import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.workflow import TRADE_NODES, WorkflowError, WorkflowService
from bus import MessageBus
from channels.web import WebChannel
from session.conversation import ConversationService


@pytest.mark.parametrize("tool_name,node", [
    ("foreign_trade__extract_rfq", "extract_rfq"),
    ("foreign_trade__calculate_quote", "calculate_quote"),
    ("foreign_trade__approve_message", "approve_message"),
])
def test_trade_tool_aliases_are_observed(tmp_path: Path, tool_name: str, node: str):
    service = WorkflowService(tmp_path)
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    asyncio.run(service.observe_tool(f"web:local:{conversation_id}", tool_name, "{}"))
    run = service.list_runs(conversation_id)[0]
    assert run.current_node == node


def test_full_trade_sequence_is_persistent_ordered_and_safe(tmp_path: Path):
    service = WorkflowService(tmp_path)
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    session_key = f"web:local:{conversation_id}"
    secret = "customer complete private body"
    results = {
        "extract_rfq": {"rfq_id": "rfq-demo", "extraction": {"missing_fields": []}, "raw": secret},
        "search_product": {"items": [{"sku": "SKU-1"}]},
        "check_inventory": {"available": True},
        "calculate_quote": {"total_usd": 100.0},
        "create_quote": {"quote_id": "quote-demo", "version": 1},
        "approve_message": {"status": "approved"},
        "create_followup": {"followup_id": "follow-demo"},
    }
    for node in TRADE_NODES:
        asyncio.run(service.observe_tool(session_key, node, json.dumps(results[node])))

    run = service.list_runs(conversation_id)[0]
    assert run.status == "completed"
    assert run.completed_nodes == TRADE_NODES
    events = service.events(run.run_id)
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert events[0].type == "workflow.run.created"
    assert events[-1].type == "workflow.run.completed"
    serialized = json.dumps([event.safe_data for event in events])
    assert secret not in serialized
    assert "rfq-demo" in serialized and "quote-demo" in serialized

    restarted = WorkflowService(tmp_path)
    assert restarted.list_runs(conversation_id)[0].status == "completed"
    assert [event.sequence for event in restarted.events(run.run_id, after_sequence=3)][0] == 4


def test_missing_fields_wait_failure_error_code_and_cancel(tmp_path: Path):
    service = WorkflowService(tmp_path)
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    key = f"web:local:{conversation_id}"
    asyncio.run(service.observe_tool(key, "extract_rfq", json.dumps({
        "rfq_id": "rfq-demo", "extraction": {"missing_fields": ["items[0].quantity", "unit"]}
    })))
    run = service.list_runs(conversation_id)[0]
    assert run.status == "waiting_confirmation"
    waiting = service.events(run.run_id)[-1]
    assert waiting.safe_data == {"missing_field_count": 2}
    assert "quantity" not in json.dumps(waiting.safe_data)

    cancelled = asyncio.run(service.cancel(run.run_id))
    assert cancelled.status == "cancelled"
    with pytest.raises(WorkflowError) as exc:
        asyncio.run(service.cancel(run.run_id))
    assert exc.value.code == "workflow_not_cancellable"

    asyncio.run(service.observe_tool(key, "extract_rfq", json.dumps({"error": "private stack", "error_code": "extract_failed"})))
    failed = service.list_runs(conversation_id)[0]
    assert failed.status == "failed"
    assert service.events(failed.run_id)[-1].safe_data == {"error_code": "extract_failed"}

    asyncio.run(service.observe_tool(key, "calculate_quote", "错误: upstream unavailable"))
    latest = service.list_runs(conversation_id)[0]
    assert latest.status == "failed"
    assert latest.last_error_code == "tool_result_invalid"


def build_web(tmp_path: Path):
    conversation_service = ConversationService(tmp_path / "sessions")
    workflow_service = WorkflowService(tmp_path / "workflows")
    channel = WebChannel(MessageBus(), conversation_service=conversation_service,
                         workflow_service=workflow_service)
    channel._app = FastAPI()
    channel._register_routes()
    return conversation_service, workflow_service, channel, TestClient(channel._app)


def test_workflow_api_snapshot_and_websocket_broadcast_are_conversation_scoped(tmp_path: Path):
    conversations, workflows, _, client = build_web(tmp_path)
    first, second = conversations.create("First"), conversations.create("Second")
    asyncio.run(workflows.observe_tool(f"web:local:{first.conversation_id}", "extract_rfq",
                                       json.dumps({"rfq_id": "r1", "extraction": {"missing_fields": []}})))
    run = workflows.list_runs(first.conversation_id)[0]
    response = client.get(f"/api/conversations/{first.conversation_id}/workflow-runs")
    assert response.status_code == 200 and response.json()["items"][0]["run_id"] == run.run_id
    assert client.get(f"/api/workflow-runs/{run.run_id}/events?after_sequence=1").status_code == 200
    assert client.get("/api/workflow-runs/not-a-run/events").status_code == 404

    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": first.conversation_id})
        assert websocket.receive_json()["type"] == "conversation.bound"
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "workflow.snapshot" and len(snapshot["runs"]) == 1
        asyncio.run(workflows.observe_tool(f"web:local:{first.conversation_id}", "check_inventory", "{}"))
        assert websocket.receive_json()["type"] == "workflow.event"
        assert websocket.receive_json()["type"] == "workflow.event"

        websocket.send_json({"type": "conversation.bind", "protocol_version": 2,
                             "conversation_id": second.conversation_id})
        websocket.receive_json()
        assert websocket.receive_json()["runs"] == []
