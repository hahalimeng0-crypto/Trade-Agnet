"""Framework-only LangGraph runtime, independent of NanoClaw business modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

import aiosqlite
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.redis import RedisSaver
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph


class EmployeeGraphState(TypedDict):
    messages: list[dict[str, Any]]
    request_id: str
    iteration: int
    pending_tool_calls: list[dict[str, Any]]
    final: str | None


@dataclass(frozen=True)
class ModelStepResult:
    messages: list[dict[str, Any]]
    pending_tool_calls: list[dict[str, Any]]
    final: str | None


@dataclass(frozen=True)
class ToolStepResult:
    message: dict[str, Any] | None
    final: str | None = None


@dataclass(frozen=True)
class RuntimeInvocation:
    final: str
    checkpoint_thread_id: str
    resumed: bool
    completed_replay: bool


ModelStep = Callable[[list[dict[str, Any]], int], Awaitable[ModelStepResult]]
ToolStep = Callable[[dict[str, Any], str], Awaitable[ToolStepResult]]
InitialStateFactory = Callable[[], EmployeeGraphState]


def _strict_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_json_modules=(),
        allowed_msgpack_modules=(),
    )


class EmployeeLangGraphRuntime:
    """Own only graph execution/checkpoints; business behavior is injected."""

    graph_name = "internal_foreign_trade_agent"

    def __init__(
        self, *, model_step: ModelStep, tool_step: ToolStep,
        max_iterations: int, checkpoint_path: str | None = None,
        checkpoint_backend: str | None = None,
        redis_url: str | None = None,
        checkpoint_ttl_minutes: int = 10080,
        redis_connect_timeout_seconds: float = 5.0,
    ) -> None:
        self.model_step = model_step
        self.tool_step = tool_step
        self.max_iterations = max_iterations
        if checkpoint_backend is None:
            checkpoint_backend = "sqlite" if checkpoint_path else "off"
        if checkpoint_backend not in {"redis", "sqlite", "off"}:
            raise ValueError("unsupported employee Agent checkpoint backend")
        if checkpoint_backend == "sqlite" and not checkpoint_path:
            raise ValueError("SQLite checkpoint path is required")
        if checkpoint_backend == "redis" and not redis_url:
            raise ValueError("Redis checkpoint URL is required")
        self.checkpoint_backend = checkpoint_backend
        self.checkpoint_path = checkpoint_path
        self.redis_url = redis_url
        self.checkpoint_ttl_minutes = checkpoint_ttl_minutes
        self.redis_connect_timeout_seconds = redis_connect_timeout_seconds

    def _build_graph(self, checkpointer=None):
        builder = StateGraph(EmployeeGraphState)
        builder.add_node("model", self._model_node)
        builder.add_node("tools", self._tools_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges(
            "model", self._route_after_model,
            {"tools": "tools", "end": END},
        )
        builder.add_conditional_edges(
            "tools", self._route_after_tools,
            {"tools": "tools", "model": "model", "end": END},
        )
        return builder.compile(checkpointer=checkpointer, name=self.graph_name)

    @staticmethod
    def _route_after_model(state: EmployeeGraphState) -> Literal["tools", "end"]:
        return "end" if state.get("final") is not None else "tools"

    @staticmethod
    def _route_after_tools(
        state: EmployeeGraphState,
    ) -> Literal["tools", "model", "end"]:
        if state.get("final") is not None:
            return "end"
        if state.get("pending_tool_calls"):
            return "tools"
        return "model"

    async def _model_node(self, state: EmployeeGraphState) -> dict[str, Any]:
        iteration = int(state["iteration"])
        if iteration >= self.max_iterations:
            return {
                "pending_tool_calls": [],
                "final": "已达到最大迭代次数，任务未完成。",
            }
        step = await self.model_step(list(state["messages"]), iteration)
        return {
            "messages": step.messages,
            "iteration": iteration + 1,
            "pending_tool_calls": step.pending_tool_calls,
            "final": step.final,
        }

    async def _tools_node(self, state: EmployeeGraphState) -> dict[str, Any]:
        messages = list(state["messages"])
        pending = list(state["pending_tool_calls"])
        tool_call = pending.pop(0)
        step = await self.tool_step(tool_call, state["request_id"])
        if step.message is not None:
            messages.append(step.message)
        if step.final is not None:
            pending = []
        return {
            "messages": messages,
            "pending_tool_calls": pending,
            "final": step.final,
        }

    def _recursion_limit(self) -> int:
        # One model iteration may emit many tools. The explicit model iteration
        # counter remains the business limit; this protects LangGraph from
        # stopping a valid multi-tool turn earlier than the legacy loop did.
        return max(100, self.max_iterations * 25 + 5)

    async def _invoke_graph(
        self, graph, initial_state_factory: InitialStateFactory,
        checkpoint_thread_id: str,
    ) -> RuntimeInvocation:
        config = {
            "configurable": {"thread_id": checkpoint_thread_id},
            "recursion_limit": self._recursion_limit(),
        }
        snapshot = await graph.aget_state(config)
        if snapshot.values and snapshot.next:
            result = await graph.ainvoke(None, config=config)
            return RuntimeInvocation(
                str(result.get("final") or ""), checkpoint_thread_id, True, False,
            )
        if snapshot.values and snapshot.values.get("final") is not None:
            return RuntimeInvocation(
                str(snapshot.values.get("final") or ""), checkpoint_thread_id, True, True,
            )
        result = await graph.ainvoke(initial_state_factory(), config=config)
        return RuntimeInvocation(
            str(result.get("final") or ""), checkpoint_thread_id, False, False,
        )

    async def invoke(
        self, initial_state_factory: InitialStateFactory, *,
        checkpoint_thread_id: str,
    ) -> RuntimeInvocation:
        if self.checkpoint_backend == "off":
            graph = self._build_graph()
            result = await graph.ainvoke(
                initial_state_factory(),
                config={"recursion_limit": self._recursion_limit()},
            )
            return RuntimeInvocation(
                str(result.get("final") or ""), checkpoint_thread_id, False, False,
            )

        if self.checkpoint_backend == "redis":
            return await self._invoke_redis(
                initial_state_factory, checkpoint_thread_id,
            )

        path = Path(str(self.checkpoint_path))
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = await aiosqlite.connect(str(path))
        try:
            await connection.execute("PRAGMA journal_mode=WAL")
            await connection.execute("PRAGMA busy_timeout=5000")
            checkpointer = AsyncSqliteSaver(connection, serde=_strict_serializer())
            await checkpointer.setup()
            graph = self._build_graph(checkpointer)
            return await self._invoke_graph(
                graph, initial_state_factory, checkpoint_thread_id,
            )
        finally:
            await connection.close()

    def _redis_connection_args(self) -> dict[str, Any]:
        return {
            "socket_connect_timeout": self.redis_connect_timeout_seconds,
            "socket_timeout": self.redis_connect_timeout_seconds,
            "health_check_interval": 30,
        }

    def _redis_ttl(self) -> dict[str, Any]:
        return {
            "default_ttl": self.checkpoint_ttl_minutes,
            "refresh_on_read": True,
        }

    async def _invoke_redis(
        self, initial_state_factory: InitialStateFactory,
        checkpoint_thread_id: str,
    ) -> RuntimeInvocation:
        async with AsyncRedisSaver.from_conn_string(
            self.redis_url,
            connection_args=self._redis_connection_args(),
            ttl=self._redis_ttl(),
            checkpoint_prefix="employee_checkpoint",
            checkpoint_write_prefix="employee_checkpoint_write",
        ) as checkpointer:
            await checkpointer.asetup()
            graph = self._build_graph(checkpointer)
            return await self._invoke_graph(
                graph, initial_state_factory, checkpoint_thread_id,
            )

    def delete_checkpoint(self, checkpoint_thread_id: str) -> None:
        if self.checkpoint_backend == "off":
            return
        if self.checkpoint_backend == "redis":
            with RedisSaver.from_conn_string(
                self.redis_url,
                connection_args=self._redis_connection_args(),
                ttl=self._redis_ttl(),
                checkpoint_prefix="employee_checkpoint",
                checkpoint_write_prefix="employee_checkpoint_write",
            ) as saver:
                saver.setup()
                saver.delete_thread(checkpoint_thread_id)
            return
        if self.checkpoint_path is None or not Path(self.checkpoint_path).is_file():
            return
        connection = sqlite3.connect(self.checkpoint_path, check_same_thread=False)
        try:
            saver = SqliteSaver(connection, serde=_strict_serializer())
            saver.setup()
            saver.delete_thread(checkpoint_thread_id)
        finally:
            connection.close()
