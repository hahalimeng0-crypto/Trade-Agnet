"""Thin NanoClaw adapter for the standalone employee LangGraph runtime."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from agent.loop import AgentLoop
from agent.memory_runtime.models import ToolResultEvent
from employee_agent.runtime import (
    EmployeeGraphState,
    EmployeeLangGraphRuntime,
    ModelStepResult,
    ToolStepResult,
)
from privacy import safe_print as print
from providers.base import ToolCallRequest


class NanoClawEmployeeAgentAdapter(AgentLoop):
    """Expose an independent LangGraph employee Agent through NanoClaw's Gateway API."""

    def __init__(
        self, *args: Any,
        checkpoint_backend: str | None = None,
        checkpoint_path: str | None = None,
        checkpoint_redis_url: str | None = None,
        checkpoint_ttl_minutes: int = 10080,
        redis_connect_timeout_seconds: float = 5.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.runtime = EmployeeLangGraphRuntime(
            model_step=self._model_step,
            tool_step=self._tool_step,
            max_iterations=self.max_iterations,
            checkpoint_path=checkpoint_path,
            checkpoint_backend=checkpoint_backend,
            redis_url=checkpoint_redis_url,
            checkpoint_ttl_minutes=checkpoint_ttl_minutes,
            redis_connect_timeout_seconds=redis_connect_timeout_seconds,
        )
        self._active_checkpoint_thread_id: str | None = None

    def _checkpoint_thread_id(self, request_id: str) -> str:
        principal = self._request_context.get("_principal") or {}
        raw = "\x1f".join((
            str(principal.get("tenant_id") or "local"),
            str(principal.get("user_id") or "local"),
            self.session_key,
            request_id,
        ))
        return "employee-agent-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def _model_step(
        self, messages: list[dict[str, Any]], iteration: int,
    ) -> ModelStepResult:
        if self.consolidator is not None:
            messages = await self.consolidator.maybe_consolidate(messages)
        print(f"  💭 思考中... (第 {iteration + 1} 轮)", end="", flush=True)
        response = await self.provider.chat(
            messages=messages,
            tools=self.tools.get_definitions(),
            model=self.model,
        )
        print(" ✓")
        if response.finish_reason == "error":
            return ModelStepResult(
                messages, [], self._finalize_response("抱歉，发生了错误，请稍后重试。"),
            )
        if response.has_tool_calls and not self._tool_calls_allowed(response):
            return ModelStepResult(messages, [], self._disallowed_tool_response())
        if response.tool_calls and response.tool_calls[0].reasoning_content:
            reasoning = response.tool_calls[0].reasoning_content
            preview = reasoning[:300] + "..." if len(reasoning) > 300 else reasoning
            print(f"  🧠 思考过程:\n{preview}")
        if not response.has_tool_calls:
            return ModelStepResult(
                messages, [], self._finalize_response(response.content or ""),
            )
        assistant_message = self._build_assistant_message(response)
        messages.append(assistant_message)
        self.session_manager.save_message(self.session_key, assistant_message)
        tool_calls = [{
            "id": item.id,
            "name": item.name,
            "arguments": item.arguments,
        } for item in response.tool_calls]
        return ModelStepResult(messages, tool_calls, None)

    async def _observe_tool_result(
        self, request_id: str, tool_call: ToolCallRequest, result: str, *,
        observe_workflow: bool = True,
    ) -> None:
        if observe_workflow and self.workflow_service is not None:
            bare_name = tool_call.name.rsplit("__", 1)[-1]
            if bare_name == "query_trade_data":
                await self.workflow_service.observe_analytics(self.session_key, result)
            else:
                await self.workflow_service.observe_tool(
                    self.session_key, tool_call.name, result,
                )
        if self.memory_lifecycle is not None:
            await self.memory_lifecycle.observe_tool_result(
                ToolResultEvent(
                    request_id, tool_call.name, result, tool_call.id,
                    f"{request_id}:tool:{tool_call.id}",
                )
            )

    async def _tool_step(
        self, value: dict[str, Any], request_id: str,
    ) -> ToolStepResult:
        tool_call = ToolCallRequest(
            str(value["id"]), str(value["name"]), dict(value.get("arguments") or {}),
        )
        arguments_json = json.dumps(tool_call.arguments, ensure_ascii=False)
        print(f"\n  🛠️  调用工具: {tool_call.name}({arguments_json})")
        check_result = self._check_tool_loop(tool_call.name, arguments_json)
        if check_result and "熔断" in check_result:
            print(f"  🚨 {check_result}")
            return ToolStepResult(None, check_result)
        if check_result and "警告" in check_result:
            print(f"  ⚠️  {check_result}")
            result = f"系统警告：{check_result}"
            observe_workflow = False
        else:
            result = await self.tools.execute(tool_call.name, tool_call.arguments)
            observe_workflow = True
            preview = result[:200] + "..." if len(result) > 200 else result
            print(f"  ✅ 结果: {preview}")
        tool_message = {
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": result,
        }
        self.session_manager.save_message(self.session_key, tool_message)
        await self._observe_tool_result(
            request_id, tool_call, result, observe_workflow=observe_workflow,
        )
        return ToolStepResult(tool_message)

    async def _run_turn(
        self, user_message: str, prepared_memory=None, request_id: str = "",
    ) -> str:
        checkpoint_thread_id = self._checkpoint_thread_id(request_id)
        self._active_checkpoint_thread_id = checkpoint_thread_id

        def initial_state() -> EmployeeGraphState:
            messages = self.context.build_messages(
                history=self._session_history,
                current_message=user_message,
                request_context=self._request_context,
                prepared_memory=prepared_memory,
            )
            self.session_manager.save_message(
                self.session_key, {"role": "user", "content": user_message},
            )
            return EmployeeGraphState(
                messages=messages,
                request_id=request_id,
                iteration=0,
                pending_tool_calls=[],
                final=None,
            )

        try:
            invocation = await self.runtime.invoke(
                initial_state,
                checkpoint_thread_id=checkpoint_thread_id,
            )
        except Exception:
            # Keep the durable checkpoint for a retry, but do not let an
            # unrelated later command clean it as if that command owned it.
            self._active_checkpoint_thread_id = None
            raise
        self._session_history = self.session_manager.get_history(self.session_key)
        return invocation.final

    def _persist_final_response(self, content: str) -> None:
        checkpoint_thread_id = self._active_checkpoint_thread_id
        try:
            super()._persist_final_response(content)
        finally:
            if checkpoint_thread_id is not None:
                try:
                    self.runtime.delete_checkpoint(checkpoint_thread_id)
                except Exception as exc:
                    print(f"警告: 清理内部 Agent 编排断点失败 - {type(exc).__name__}")
                self._active_checkpoint_thread_id = None

    def clear_history(self) -> None:
        super().clear_history()
        if self._active_checkpoint_thread_id is not None:
            self.runtime.delete_checkpoint(self._active_checkpoint_thread_id)
            self._active_checkpoint_thread_id = None


# Compatibility import for callers that used the first migration name.
InternalLangGraphAgent = NanoClawEmployeeAgentAdapter
