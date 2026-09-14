import asyncio

from agent.memory_runtime.context_provider import NoOpMemoryContextProvider
from agent.memory_runtime.lifecycle import NoOpAgentMemoryLifecycle
from agent.memory_runtime.models import (
    ActorContext,
    ToolResultEvent,
    TurnAbortedEvent,
    TurnCompletedEvent,
    TurnRequest,
    MemoryScope,
)


def test_noop_lifecycle_preserves_history_and_performs_no_context_injection():
    history = ({"role": "user", "content": "hello"},)
    request = TurnRequest(
        request_id="request-a",
        actor=ActorContext(
            actor_kind="customer",
            actor_id="customer-a",
            tenant_id="tenant-a",
            roles=frozenset(),
            authenticated=True,
        ),
        scope=MemoryScope(
            realm="customer_conversation",
            tenant_id="tenant-a",
            account_id="customer-a",
            conversation_id="conversation-a",
        ),
        current_message="next",
        history=history,
    )
    lifecycle = NoOpAgentMemoryLifecycle()
    prepared = asyncio.run(lifecycle.prepare_turn(request))

    assert prepared.history == history
    assert prepared.working_memory is None
    assert prepared.recalled == ()
    assert NoOpMemoryContextProvider().build_context_messages(prepared) == []

    asyncio.run(lifecycle.observe_tool_result(
        ToolResultEvent("request-a", "public-tool", {"ok": True})
    ))
    asyncio.run(lifecycle.complete_turn(TurnCompletedEvent("request-a", "done")))
    asyncio.run(lifecycle.abort_turn(TurnAbortedEvent("request-a", "test_abort")))

