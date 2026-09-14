import asyncio
import json
import sqlite3

from agent.memory_runtime.compaction import plan_complete_turns
from agent.context import ContextBuilder
from agent.loop import AgentLoop
from agent.memory_runtime.context_provider import StructuredWorkingMemoryContextProvider
from agent.memory_runtime.lifecycle import BoundedWorkingMemoryLifecycle
from agent.memory_runtime.models import ActorContext, MemoryScope, TurnRequest
from agent.memory_runtime.models import CustomerInquiryWorkingMemory, SourcedValue
from agent.memory_runtime.services.working_memory import CustomerWorkingMemoryService
from agent.memory_runtime.working_memory import (
    CustomerWorkingMemoryStore,
    WorkspaceWorkingMemoryStore,
    WorkingMemoryConflict,
)
from bus import MessageBus
from channels.customer_portal import CustomerPortalChannel
from gateway import Gateway
from agent.tools.registry import ToolRegistry
from providers.base import LLMResponse
from session.bounded_manager import BoundedSessionManager
from session.customer_conversation import CustomerConversationRepository, CustomerOwner


def complete_history():
    return [
        {"role": "user", "content": "turn 1"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "tc-1"}]},
        {"role": "tool", "tool_call_id": "tc-1", "content": "result 1"},
        {"role": "assistant", "content": "done 1"},
        {"role": "user", "content": "turn 2"},
        {"role": "assistant", "content": "done 2"},
        {"role": "user", "content": "turn 3"},
        {"role": "assistant", "content": "done 3"},
    ]


def test_complete_turn_plan_never_splits_tool_group():
    history = complete_history()
    plan = plan_complete_turns(history, max_turns=2)
    assert list(plan.evicted) == history[:4]
    assert list(plan.retained) == history[4:]


def test_bounded_session_archives_raw_messages_then_atomically_replaces_active(tmp_path):
    summaries = []

    async def summarize(messages):
        summaries.append(messages)
        return "Turn 1 completed with its tool result."

    manager = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=2, summarizer=summarize)
    for message in complete_history():
        manager.save_message("cli:test", message)

    prepared = asyncio.run(manager.prepare_active_history("cli:test"))

    assert prepared[0]["role"] == "system"
    assert prepared[1:] == complete_history()[4:]
    assert summaries == [complete_history()[:4]]
    assert manager.get_history("cli:test") == prepared
    archive = tmp_path / "sessions" / "archive" / "cli_test.jsonl"
    records = [json.loads(line) for line in archive.read_text(encoding="utf-8").splitlines()]
    assert [record["message"] for record in records] == complete_history()[:4]
    assert len({record["compaction_id"] for record in records}) == 1


def test_summary_failure_preserves_original_history_and_creates_no_archive(tmp_path):
    async def fail(_messages):
        raise RuntimeError("summary unavailable")

    manager = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=1, summarizer=fail)
    for message in complete_history():
        manager.save_message("cli:test", message)
    original = manager.get_history("cli:test")

    assert asyncio.run(manager.prepare_active_history("cli:test")) == original
    assert manager.get_history("cli:test") == original
    assert not (tmp_path / "sessions" / "archive").exists()


def test_atomic_replace_failure_keeps_active_history(tmp_path, monkeypatch):
    async def summarize(_messages):
        return "summary"

    manager = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=1, summarizer=summarize)
    for message in complete_history():
        manager.save_message("cli:test", message)
    original = manager.get_history("cli:test")
    monkeypatch.setattr(manager, "replace_history", lambda *_args: (_ for _ in ()).throw(OSError("disk")))

    assert asyncio.run(manager.prepare_active_history("cli:test")) == original
    assert manager.get_history("cli:test") == original


def test_audit_failure_rolls_active_history_back(tmp_path, monkeypatch):
    async def summarize(_messages):
        return "summary"

    manager = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=1, summarizer=summarize)
    for message in complete_history():
        manager.save_message("cli:test", message)
    original = manager.get_history("cli:test")
    monkeypatch.setattr(manager, "_append_audit", lambda *_args: (_ for _ in ()).throw(OSError("audit")))

    assert asyncio.run(manager.prepare_active_history("cli:test")) == original
    assert manager.get_history("cli:test") == original


def test_customer_working_memory_is_account_scoped_and_unverified_values_stay_pending():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = CustomerWorkingMemoryStore(connection)
    base = CustomerInquiryWorkingMemory(
        account_id="account-a", conversation_id="conversation-shared", intent="rfq",
        fields={}, missing_fields=["quantity"], pending_confirmations=["quantity"],
        inquiry_record_id=None, version=0,
    )
    state_a = store.put("tenant-a", base, expected_version=None)
    state_b = store.put(
        "tenant-a", CustomerInquiryWorkingMemory(
            **{**base.__dict__, "account_id": "account-b"}
        ), expected_version=None,
    )
    assert store.get("tenant-a", "account-a", "conversation-shared").account_id == "account-a"
    assert store.get("tenant-a", "account-b", "conversation-shared").account_id == "account-b"
    assert state_b.version == 1

    service = CustomerWorkingMemoryService(store)
    pending = service.set_sourced_value(
        tenant_id="tenant-a", state=state_a, field_name="quantity", value=100,
        source_message_id="message-a", updated_at="2026-07-24T00:00:00Z",
    )
    assert pending.fields["quantity"].state == "pending"
    confirmed = service.set_sourced_value(
        tenant_id="tenant-a", state=pending, field_name="quantity", value=100,
        source_message_id="tool-a", updated_at="2026-07-24T00:01:00Z",
        authoritative=True,
    )
    assert confirmed.fields["quantity"].state == "confirmed"
    with __import__("pytest").raises(WorkingMemoryConflict):
        store.put("tenant-a", pending, expected_version=1)


def test_workspace_working_memory_has_separate_schema_without_customer_account():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = WorkspaceWorkingMemoryStore(connection)
    result = store.put(
        "tenant-a", "operator-a", "project-a", "conversation-a",
        {"goal": "prepare RFQ", "confirmed": False}, expected_version=None,
    )
    assert result["version"] == 1
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(workspace_working_memory)")
    }
    assert "account_id" not in columns


def test_conversation_delete_cascades_working_memory_request_cache_and_peer_agent():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    repository = CustomerConversationRepository(
        connection, cursor_secret=b"m2-cursor-secret-that-is-long-enough",
    )
    working = CustomerWorkingMemoryStore(connection)
    owner = CustomerOwner("tenant-a", "account-a")
    conversation = repository.create(owner, "Delete me")
    working.put("tenant-a", CustomerInquiryWorkingMemory(
        account_id=owner.account_id, conversation_id=conversation.conversation_id,
        intent="rfq", fields={}, missing_fields=[], pending_confirmations=[],
        inquiry_record_id=None, version=0,
    ), expected_version=None)
    channel = CustomerPortalChannel(MessageBus(), "127.0.0.1", 8766)
    cache_key = f"{owner.account_id}:{conversation.conversation_id}"
    channel._seen_requests[cache_key] = {"request-a"}

    class Agent:
        cleared = False

        def clear_peer_history(self):
            self.cleared = True

    agent = Agent()

    async def scenario():
        repository.soft_delete(owner, conversation.conversation_id, 1, "delete-request")
        await channel._on_conversation_deleted(owner, conversation.conversation_id)
        event = await channel.bus.consume_inbound()
        gateway = Gateway(channel.bus, [], lambda _key: agent)
        key = f"customer_portal:{event.sender_id}"
        gateway._agents[key] = agent
        await channel.bus.publish_inbound(event)
        task = asyncio.create_task(gateway._process_inbound())
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return key, gateway

    key, gateway = asyncio.run(scenario())
    assert working.get("tenant-a", owner.account_id, conversation.conversation_id) is None
    assert cache_key not in channel._seen_requests
    assert key not in gateway._agents
    assert agent.cleared is True


def test_customer_lifecycle_creates_empty_scoped_working_memory(tmp_path):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = CustomerWorkingMemoryStore(connection)

    async def summarize(_messages):
        return "summary"

    sessions = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=2, summarizer=summarize)
    lifecycle = BoundedWorkingMemoryLifecycle(sessions, customer_store=store)
    request = TurnRequest(
        "request-a",
        ActorContext("customer", "account-a", "tenant-a", frozenset(), True),
        MemoryScope(
            "customer_conversation", "tenant-a", account_id="account-a",
            conversation_id="conversation-a", purpose="customer_support",
        ),
        "new request", (), "customer_portal:account:account-a:conversation-a",
    )
    prepared = asyncio.run(lifecycle.prepare_turn(request))
    assert prepared.working_memory["account_id"] == "account-a"
    assert prepared.working_memory["conversation_id"] == "conversation-a"
    assert prepared.working_memory["fields"] == {}
    assert prepared.working_memory["version"] == 1


def test_agent_next_turn_contains_prior_final_assistant_and_working_context(tmp_path):
    class Provider:
        def __init__(self):
            self.calls = []

        async def chat(self, messages, tools=None, model=None):
            self.calls.append(messages)
            return LLMResponse(content=f"answer-{len(self.calls)}")

    async def summarize(_messages):
        return "summary"

    provider = Provider()
    sessions = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=10, summarizer=summarize)
    workspace_store = WorkspaceWorkingMemoryStore(sqlite3.connect(":memory:", check_same_thread=False))
    lifecycle = BoundedWorkingMemoryLifecycle(sessions, workspace_store=workspace_store)

    def request_factory(key, request_id, message, history, trusted):
        return TurnRequest(
            request_id,
            ActorContext(
                "workspace_operator", "local", "tenant-a",
                frozenset({"workspace_memory_reader"}), True,
            ),
            MemoryScope(
                "workspace_private", "tenant-a", subject_id="local",
                project_id="project-a", conversation_id=key,
            ),
            message, history, key,
        )

    agent = AgentLoop(
        provider=provider, tools=ToolRegistry(),
        context=ContextBuilder(
            str(tmp_path), include_memory=False,
            memory_context_provider=StructuredWorkingMemoryContextProvider(),
        ),
        session_manager=sessions, session_key="cli:m2", max_iterations=1,
        memory_lifecycle=lifecycle, memory_request_factory=request_factory,
    )
    assert asyncio.run(agent.run("first")) == "answer-1"
    assert asyncio.run(agent.run("second")) == "answer-2"
    second = provider.calls[1]
    assert any(message.get("content") == "answer-1" for message in second)
    structured = [
        message["content"] for message in second
        if isinstance(message.get("content"), str)
        and message["content"].startswith("Trusted scoped working memory")
    ]
    assert structured and '"pending_confirmations": []' in structured[0]
    assert sessions.get_history("cli:m2")[-1] == {
        "role": "assistant", "content": "answer-2"
    }


def test_agent_lifecycle_aborts_on_provider_failure_without_complete():
    class Provider:
        async def chat(self, **_kwargs):
            raise RuntimeError("provider down")

    class Lifecycle:
        completed = False
        aborted = False

        async def prepare_turn(self, request):
            from agent.memory_runtime.models import PreparedMemory
            return PreparedMemory(history=request.history)

        async def observe_tool_result(self, event):
            return None

        async def complete_turn(self, event):
            self.completed = True

        async def abort_turn(self, event):
            self.aborted = True

    lifecycle = Lifecycle()

    def request_factory(key, request_id, message, history, trusted):
        return TurnRequest(
            request_id,
            ActorContext("service", "service-a", "tenant-a", frozenset({"workspace_memory_service"}), True),
            MemoryScope("workspace_private", "tenant-a", project_id="project-a"),
            message, history, key,
        )

    agent = AgentLoop(
        Provider(), ToolRegistry(), ContextBuilder(".", include_memory=False),
        SessionManagerForTest(), session_key="cli:test", max_iterations=1,
        memory_lifecycle=lifecycle, memory_request_factory=request_factory,
    )
    with __import__("pytest").raises(RuntimeError, match="provider down"):
        asyncio.run(agent.run("fail"))
    assert lifecycle.aborted is True
    assert lifecycle.completed is False


class SessionManagerForTest:
    def __init__(self):
        self.messages = []

    def get_history(self, _key):
        return list(self.messages)

    def save_message(self, _key, message):
        self.messages.append(message)

    def clear(self, _key):
        self.messages.clear()
