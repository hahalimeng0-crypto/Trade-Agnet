import asyncio
import json
from pathlib import Path

from bus.queue import InboundMessage, MessageBus, OutboundMessage
from channels.customer_portal import CustomerPortalChannel
from channels.web import WebChannel
from gateway import Gateway
from gateway_coordination import InMemoryRuntimeCoordinator, RequestScope, payload_digest


def _message(conversation: str, request: str, content: str, *, socket: str = "socket"):
    return InboundMessage(
        "web", f"local:{conversation}", socket, content,
        {"conversation_id": conversation, "request_id": request},
    )


def test_gateway_serializes_sessions_but_overlaps_different_sessions():
    async def scenario():
        bus = MessageBus(); active = {}; maximum = {}; global_active = 0; global_max = 0
        guard = asyncio.Lock()

        class Agent:
            def __init__(self, key): self.key = key
            async def run(self, content):
                nonlocal global_active, global_max
                async with guard:
                    active[self.key] = active.get(self.key, 0) + 1
                    maximum[self.key] = max(maximum.get(self.key, 0), active[self.key])
                    global_active += 1; global_max = max(global_max, global_active)
                await asyncio.sleep(.02)
                async with guard:
                    active[self.key] -= 1; global_active -= 1
                return content

        gateway = Gateway(bus, [], Agent, max_concurrency=2)
        consumer = asyncio.create_task(gateway._process_inbound())
        messages = [
            _message("c1", "r1", "1"), _message("c1", "r2", "2"),
            _message("c2", "r3", "3"), _message("c2", "r4", "4"),
        ]
        for message in messages: await bus.publish_inbound(message)
        rows = [await asyncio.wait_for(bus.consume_outbound(), 1) for _ in messages]
        consumer.cancel(); await asyncio.gather(consumer, return_exceptions=True)
        await gateway.shutdown()
        return rows, maximum, global_max

    rows, maximum, global_max = asyncio.run(scenario())
    assert {row.request_id for row in rows} == {"r1", "r2", "r3", "r4"}
    assert max(maximum.values()) == 1
    assert global_max == 2


def test_shared_claim_executes_duplicate_once_and_rejects_hash_conflict():
    async def scenario():
        coordinator = InMemoryRuntimeCoordinator(); buses = [MessageBus(), MessageBus()]
        calls = 0

        class Agent:
            async def run(self, content):
                nonlocal calls
                calls += 1; await asyncio.sleep(.02); return "ok"

        gateways = [Gateway(buses[i], [], lambda _key: Agent(), coordinator=coordinator,
                            worker_id=f"worker-{i}") for i in range(2)]
        consumers = [asyncio.create_task(gateway._process_inbound()) for gateway in gateways]
        await buses[0].publish_inbound(_message("c1", "r1", "same", socket="s0"))
        await buses[1].publish_inbound(_message("c1", "r1", "same", socket="s1"))
        first = await asyncio.wait_for(buses[0].consume_outbound(), 1)
        second = await asyncio.wait_for(buses[1].consume_outbound(), 1)
        await buses[1].publish_inbound(_message("c1", "r1", "changed", socket="s1"))
        conflict = await asyncio.wait_for(buses[1].consume_outbound(), 1)
        for task in consumers: task.cancel()
        await asyncio.gather(*consumers, return_exceptions=True)
        for gateway in gateways: await gateway.shutdown()
        return calls, {first.event_type, second.event_type}, conflict

    calls, event_types, conflict = asyncio.run(scenario())
    assert calls == 1
    assert event_types == {"assistant.message", "chat.duplicate"}
    assert conflict.event_type == "error"
    assert conflict.error_code == "request_id_conflict"


def test_failed_claim_becomes_retryable():
    async def scenario():
        coordinator = InMemoryRuntimeCoordinator()
        scope = RequestScope("", "", "web", "conversation", "request")
        first = await coordinator.claim(scope, payload_digest("x"), "worker-a", 30)
        await coordinator.fail(scope, "worker-a")
        second = await coordinator.claim(scope, payload_digest("x"), "worker-b", 30)
        return first, second
    first, second = asyncio.run(scenario())
    assert first.decision == second.decision == "accepted"


class _Socket:
    def __init__(self): self.rows = []
    async def send_text(self, value): self.rows.append(json.loads(value))
    async def send_json(self, value): self.rows.append(value)


def test_channels_drop_late_request_and_return_correlation():
    async def scenario():
        web = WebChannel(MessageBus(), conversation_service=object())
        socket = _Socket(); web._connections["s"] = socket
        web._bindings["s"] = "c"; web._active_requests["s"] = {"new"}
        await web.send(OutboundMessage("web", "s", "late", conversation_id="c", request_id="old"))
        await web.send(OutboundMessage("web", "s", "ok", conversation_id="c", request_id="new"))
        return socket.rows
    rows = asyncio.run(scenario())
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "c"
    assert rows[0]["request_id"] == "new"


def test_channel_allows_multiple_inflight_requests_on_same_connection():
    async def scenario():
        web = WebChannel(MessageBus(), conversation_service=object())
        socket = _Socket(); web._connections["s"] = socket
        web._bindings["s"] = "c"; web._active_requests["s"] = {"first", "second"}
        await web.send(OutboundMessage("web", "s", "one", conversation_id="c", request_id="first"))
        await web.send(OutboundMessage("web", "s", "two", conversation_id="c", request_id="second"))
        return socket.rows
    rows = asyncio.run(scenario())
    assert [row["request_id"] for row in rows] == ["first", "second"]


def test_m6_migration_is_body_free_request_ledger():
    sql = (Path(__file__).parents[1] / "agent/business/migrations/005_m6_runtime.mysql.sql").read_text("utf-8")
    ledger = sql.split("CREATE TABLE IF NOT EXISTS runtime_request_ledger", 1)[1].split("CREATE TABLE", 1)[0]
    assert "payload_hash" in ledger and "lease_expires_at" in ledger
    assert "content_json" not in ledger and "response_body" not in ledger
