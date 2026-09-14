import asyncio

import pytest

from employee_agent.runtime import (
    EmployeeGraphState,
    EmployeeLangGraphRuntime,
    ModelStepResult,
    ToolStepResult,
)


def _initial_state() -> EmployeeGraphState:
    return EmployeeGraphState(
        messages=[{"role": "user", "content": "process RFQ-7"}],
        request_id="request-7",
        iteration=0,
        pending_tool_calls=[],
        final=None,
    )


def test_sqlite_checkpoint_resumes_at_failed_tool_node(tmp_path):
    checkpoint_path = str(tmp_path / "employee-checkpoints.sqlite3")
    first_model_calls = []

    async def first_model(messages, iteration):
        first_model_calls.append((messages, iteration))
        return ModelStepResult(
            messages + [{"role": "assistant", "content": None}],
            [{"id": "call-7", "name": "lookup", "arguments": {"rfq": "RFQ-7"}}],
            None,
        )

    async def failed_tool(tool_call, request_id):
        assert tool_call["id"] == "call-7"
        assert request_id == "request-7"
        raise RuntimeError("temporary tool outage")

    first_runtime = EmployeeLangGraphRuntime(
        model_step=first_model,
        tool_step=failed_tool,
        max_iterations=4,
        checkpoint_path=checkpoint_path,
    )

    with pytest.raises(RuntimeError, match="temporary tool outage"):
        asyncio.run(first_runtime.invoke(
            _initial_state,
            checkpoint_thread_id="tenant-user-session-request-7",
        ))
    assert len(first_model_calls) == 1

    resumed_model_calls = []
    resumed_tool_calls = []

    async def resumed_model(messages, iteration):
        resumed_model_calls.append((messages, iteration))
        assert messages[-1]["content"] == "business:RFQ-7"
        return ModelStepResult(messages, [], "RFQ processed")

    async def resumed_tool(tool_call, request_id):
        resumed_tool_calls.append((tool_call, request_id))
        return ToolStepResult({
            "role": "tool",
            "tool_call_id": tool_call["id"],
            "content": "business:RFQ-7",
        })

    second_runtime = EmployeeLangGraphRuntime(
        model_step=resumed_model,
        tool_step=resumed_tool,
        max_iterations=4,
        checkpoint_path=checkpoint_path,
    )

    def unexpected_initial_state():
        raise AssertionError("resume must use the persisted graph state")

    invocation = asyncio.run(second_runtime.invoke(
        unexpected_initial_state,
        checkpoint_thread_id="tenant-user-session-request-7",
    ))

    assert invocation.final == "RFQ processed"
    assert invocation.resumed is True
    assert invocation.completed_replay is False
    assert len(resumed_tool_calls) == 1
    assert len(resumed_model_calls) == 1


def test_completed_checkpoint_can_replay_then_be_deleted(tmp_path):
    checkpoint_path = str(tmp_path / "employee-checkpoints.sqlite3")
    model_calls = []

    async def model(messages, iteration):
        model_calls.append((messages, iteration))
        return ModelStepResult(messages, [], "done")

    async def unused_tool(tool_call, request_id):
        raise AssertionError("tool node should not run")

    runtime = EmployeeLangGraphRuntime(
        model_step=model,
        tool_step=unused_tool,
        max_iterations=2,
        checkpoint_path=checkpoint_path,
    )
    first = asyncio.run(runtime.invoke(
        _initial_state,
        checkpoint_thread_id="completed-thread",
    ))
    replay = asyncio.run(runtime.invoke(
        lambda: (_ for _ in ()).throw(AssertionError("must replay checkpoint")),
        checkpoint_thread_id="completed-thread",
    ))

    assert first.final == replay.final == "done"
    assert replay.resumed is True
    assert replay.completed_replay is True
    assert len(model_calls) == 1

    runtime.delete_checkpoint("completed-thread")
    fresh = asyncio.run(runtime.invoke(
        _initial_state,
        checkpoint_thread_id="completed-thread",
    ))
    assert fresh.resumed is False
    assert len(model_calls) == 2


def test_each_tool_call_is_checkpointed_before_the_next_tool(tmp_path):
    checkpoint_path = str(tmp_path / "employee-checkpoints.sqlite3")
    executed = []

    async def first_model(messages, iteration):
        return ModelStepResult(messages, [
            {"id": "call-1", "name": "first", "arguments": {}},
            {"id": "call-2", "name": "second", "arguments": {}},
        ], None)

    async def interrupted_tools(tool_call, request_id):
        executed.append(tool_call["id"])
        if tool_call["id"] == "call-2":
            raise RuntimeError("interrupted second tool")
        return ToolStepResult({
            "role": "tool", "tool_call_id": tool_call["id"], "content": "first-ok",
        })

    first_runtime = EmployeeLangGraphRuntime(
        model_step=first_model,
        tool_step=interrupted_tools,
        max_iterations=3,
        checkpoint_path=checkpoint_path,
    )
    with pytest.raises(RuntimeError, match="interrupted second tool"):
        asyncio.run(first_runtime.invoke(
            _initial_state,
            checkpoint_thread_id="two-tools",
        ))

    async def final_model(messages, iteration):
        assert [message.get("content") for message in messages[-2:]] == [
            "first-ok", "second-ok",
        ]
        return ModelStepResult(messages, [], "done")

    async def resumed_tools(tool_call, request_id):
        executed.append(tool_call["id"])
        return ToolStepResult({
            "role": "tool", "tool_call_id": tool_call["id"], "content": "second-ok",
        })

    second_runtime = EmployeeLangGraphRuntime(
        model_step=final_model,
        tool_step=resumed_tools,
        max_iterations=3,
        checkpoint_path=checkpoint_path,
    )
    result = asyncio.run(second_runtime.invoke(
        lambda: (_ for _ in ()).throw(AssertionError("must resume")),
        checkpoint_thread_id="two-tools",
    ))

    assert result.final == "done"
    assert executed == ["call-1", "call-2", "call-2"]
