import asyncio
import os
from types import SimpleNamespace
import uuid

import pytest
import yaml

import employee_agent.runtime as runtime_module
from employee_agent.runtime import EmployeeLangGraphRuntime, ModelStepResult, ToolStepResult


class _FakeGraph:
    async def aget_state(self, config):
        return SimpleNamespace(values={}, next=())

    async def ainvoke(self, state, config):
        return {"final": "redis-done"}


class _FakeAsyncSaver:
    calls = []
    setup_called = False

    @classmethod
    def from_conn_string(cls, url, **kwargs):
        cls.calls.append((url, kwargs))
        return cls()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def asetup(self):
        type(self).setup_called = True


class _FakeSyncSaver:
    calls = []
    setup_called = False
    deleted = []

    @classmethod
    def from_conn_string(cls, url, **kwargs):
        cls.calls.append((url, kwargs))
        return cls()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def setup(self):
        type(self).setup_called = True

    def delete_thread(self, thread_id):
        type(self).deleted.append(thread_id)


async def _unused_model(messages, iteration):
    return ModelStepResult(messages, [], "unused")


async def _unused_tool(tool_call, request_id):
    return ToolStepResult(None)


def test_runtime_selects_namespaced_redis_checkpointer(monkeypatch):
    monkeypatch.setattr(runtime_module, "AsyncRedisSaver", _FakeAsyncSaver)
    monkeypatch.setattr(runtime_module, "RedisSaver", _FakeSyncSaver)
    runtime = EmployeeLangGraphRuntime(
        model_step=_unused_model,
        tool_step=_unused_tool,
        max_iterations=2,
        checkpoint_backend="redis",
        redis_url="redis://redis:6379/1",
        checkpoint_ttl_minutes=60,
        redis_connect_timeout_seconds=3,
    )
    monkeypatch.setattr(runtime, "_build_graph", lambda checkpointer=None: _FakeGraph())

    invocation = asyncio.run(runtime.invoke(
        lambda: {
            "messages": [], "request_id": "r", "iteration": 0,
            "pending_tool_calls": [], "final": None,
        },
        checkpoint_thread_id="employee-thread",
    ))
    runtime.delete_checkpoint("employee-thread")

    assert invocation.final == "redis-done"
    assert _FakeAsyncSaver.setup_called is True
    assert _FakeSyncSaver.setup_called is True
    assert _FakeSyncSaver.deleted == ["employee-thread"]
    url, options = _FakeAsyncSaver.calls[-1]
    assert url == "redis://redis:6379/1"
    assert options["ttl"] == {"default_ttl": 60, "refresh_on_read": True}
    assert options["checkpoint_prefix"] == "employee_checkpoint"
    assert options["checkpoint_write_prefix"] == "employee_checkpoint_write"
    assert options["connection_args"]["socket_connect_timeout"] == 3


def test_compose_uses_redis_8_and_separates_cache_from_checkpoints():
    with open("compose.yaml", encoding="utf-8") as handle:
        compose = yaml.safe_load(handle)

    assert compose["services"]["redis"]["image"].startswith("redis:8")
    environment = compose["services"]["app"]["environment"]
    assert environment["NANOCLAW_CUSTOMER_PRODUCT_REDIS_URL"].endswith("/0")
    assert environment["EMPLOYEE_AGENT_REDIS_URL"].endswith("/1")


def test_live_redis_checkpoint_round_trip_when_test_service_is_supplied():
    redis_url = os.environ.get("EMPLOYEE_AGENT_TEST_REDIS_URL", "").strip()
    if not redis_url:
        pytest.skip("set EMPLOYEE_AGENT_TEST_REDIS_URL to run Redis integration")
    thread_id = f"employee-integration-{uuid.uuid4()}"
    model_calls = []

    async def model(messages, iteration):
        model_calls.append(iteration)
        return ModelStepResult(messages, [], "redis-live-done")

    runtime = EmployeeLangGraphRuntime(
        model_step=model,
        tool_step=_unused_tool,
        max_iterations=2,
        checkpoint_backend="redis",
        redis_url=redis_url,
        checkpoint_ttl_minutes=5,
        redis_connect_timeout_seconds=3,
    )
    initial = lambda: {
        "messages": [], "request_id": "live", "iteration": 0,
        "pending_tool_calls": [], "final": None,
    }
    try:
        first = asyncio.run(runtime.invoke(initial, checkpoint_thread_id=thread_id))
        replay = asyncio.run(runtime.invoke(initial, checkpoint_thread_id=thread_id))
        assert first.final == replay.final == "redis-live-done"
        assert replay.completed_replay is True
        assert model_calls == [0]
    finally:
        runtime.delete_checkpoint(thread_id)
