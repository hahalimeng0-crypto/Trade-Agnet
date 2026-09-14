"""Small LangChain adapter for NanoClaw's existing OpenAI-compatible provider."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ConfigDict

from providers.base import LLMProvider


class ProviderChatModel(BaseChatModel):
    """Expose the existing provider through LangChain without changing its SDK."""

    provider: Any
    model_name: str
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "nanoclaw-openai-compatible"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    def bind_tools(
        self, tools: Sequence[dict[str, Any] | type | Any | BaseTool], *,
        tool_choice: str | None = None, **kwargs: Any,
    ):
        definitions = [convert_to_openai_tool(tool) for tool in tools]
        params: dict[str, Any] = {"tools": definitions, **kwargs}
        if tool_choice is not None:
            params["tool_choice"] = tool_choice
        return self.bind(**params)

    async def _agenerate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager=None, **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager
        raw_messages = convert_to_openai_messages(messages, include_id=False)
        response = await self.provider.chat(
            messages=list(raw_messages),
            tools=list(kwargs.get("tools") or ()),
            model=self.model_name,
        )
        tool_calls = [{
            "name": item.name,
            "args": item.arguments,
            "id": item.id,
            "type": "tool_call",
        } for item in response.tool_calls]
        message = AIMessage(
            content=response.content or "",
            tool_calls=tool_calls,
            response_metadata={
                "finish_reason": response.finish_reason,
                "usage": response.usage,
            },
        )
        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={"usage": response.usage},
        )

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None,
        run_manager=None, **kwargs: Any,
    ) -> ChatResult:
        return asyncio.run(self._agenerate(messages, stop, run_manager, **kwargs))


def langchain_tools(tools: list[Any]) -> list[StructuredTool]:
    output = []
    for item in tools:
        async def invoke(_item=item, **kwargs: Any) -> str:
            return await _item.execute(**kwargs)

        output.append(StructuredTool(
            name=item.name,
            description=item.description,
            args_schema=item.parameters,
            coroutine=invoke,
            handle_validation_error=True,
        ))
    return output
