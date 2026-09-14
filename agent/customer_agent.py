"""A public customer agent isolated from NanoClaw's internal agent runtime."""

from __future__ import annotations

import json

from agent.customer_security import CustomerDataGuard
from agent.customer_product.context import CustomerContextBinding
from agent.loop import AgentLoop
from providers.base import LLMResponse
from providers.openai_compat import OpenAICompatProvider


class CustomerAgent(AgentLoop):
    """Public agent limited to explicitly filtered read-only data tools."""

    # This is an exact boundary, not merely a list of preferred tools. Keep the
    # compatibility name because existing tests and integrations inspect it.
    CONTROLLED_TOOLS = frozenset({
        "search_products", "get_product_details", "compare_products",
    })
    SAFE_TOOLS = CONTROLLED_TOOLS

    def __init__(
        self, *args, peer_coordinator=None,
        request_binding: CustomerContextBinding | None = None,
        langchain_enabled: bool = True, **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._validate_tool_boundary()
        self.peer_coordinator = peer_coordinator
        self.request_binding = request_binding
        self.langchain_enabled = bool(langchain_enabled)
        self._langchain_graph = None
        self._langchain_provider = None

    def _validate_tool_boundary(self) -> None:
        """Fail closed unless the customer Agent owns exactly three public tools."""
        configured = frozenset(self.tools.list_tools())
        if configured != self.CONTROLLED_TOOLS:
            raise RuntimeError("customer_agent_tool_boundary_invalid")

    def set_request_context(self, context: dict | None) -> None:
        if self.request_binding is not None:
            self.request_binding.bind(context)
        super().set_request_context(context)

    def _language(self) -> str:
        language = str(self._request_context.get("language", "en"))
        return language if language in {"zh", "en", "de"} else "en"

    async def run(self, user_message: str) -> str:
        # Detect accidental tool registration after construction as well as at
        # startup. A public request must never reach the model with extra tools.
        self._validate_tool_boundary()
        refusal = CustomerDataGuard.inspect_request(user_message, self._language())
        if refusal is None:
            if self.peer_coordinator is not None:
                peer_result = await self.peer_coordinator.analyze(
                    self.session_key, user_message, self._language())
                self._request_context["workspace_peer_result"] = peer_result
            return await super().run(user_message)

        user_msg = {"role": "user", "content": user_message}
        assistant_msg = {"role": "assistant", "content": refusal}
        self.session_manager.save_message(self.session_key, user_msg)
        self.session_manager.save_message(self.session_key, assistant_msg)
        self._session_history.extend((user_msg, assistant_msg))
        return refusal

    def _finalize_response(self, content: str) -> str:
        return CustomerDataGuard.sanitize_response(content, self._language())

    def _tool_calls_allowed(self, response: LLMResponse) -> bool:
        for tool_call in response.tool_calls:
            if tool_call.name not in self.CONTROLLED_TOOLS:
                return False
            arguments = json.dumps(tool_call.arguments, ensure_ascii=False)
            if CustomerDataGuard.inspect_request(arguments, self._language()):
                return False
            if CustomerDataGuard.sanitize_response(arguments, self._language()) != arguments:
                return False
        return True

    def _disallowed_tool_response(self) -> str:
        return CustomerDataGuard.refusal(self._language())

    async def _run_turn(self, user_message: str, prepared_memory=None,
                        request_id: str = "") -> str:
        if self.langchain_enabled and isinstance(self.provider, OpenAICompatProvider):
            return await self._run_langchain_turn(user_message, prepared_memory)
        # Unit-test and non-OpenAI-compatible providers retain the established
        # loop while production uses LangChain's high-level create_agent API.
        return await super()._run_turn(user_message, prepared_memory, request_id)

    def _build_langchain_graph(self, system_prompt: str):
        from langchain.agents import create_agent

        from agent.langchain_runtime import ProviderChatModel, langchain_tools

        self._validate_tool_boundary()
        model = ProviderChatModel(provider=self.provider, model_name=self.model or self.provider.model)
        # Customer product tools belong to this Agent but must not be copied to
        # spawned/untrusted subagents, so use the Agent-owned registry here.
        tools = langchain_tools(self.tools.registered_tools())
        self._langchain_graph = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            name="customer_product_consultation",
        )
        self._langchain_provider = self.provider

    async def _run_langchain_turn(self, user_message: str, prepared_memory=None) -> str:
        messages = self.context.build_messages(
            history=self._session_history,
            current_message=user_message,
            request_context=self._request_context,
            prepared_memory=prepared_memory,
        )
        user_msg = {"role": "user", "content": user_message}
        self.session_manager.save_message(self.session_key, user_msg)
        self._session_history.append(user_msg)
        system_prompt = str(messages[0].get("content") or "")
        if self._langchain_graph is None or self._langchain_provider is not self.provider:
            self._build_langchain_graph(system_prompt)
        result = await self._langchain_graph.ainvoke(
            {"messages": messages[1:]},
            config={"recursion_limit": max(5, self.max_iterations * 2 + 1)},
        )
        final = result["messages"][-1]
        content = getattr(final, "content", "")
        if isinstance(content, str):
            return self._finalize_response(content)
        text_parts = [
            str(block.get("text") or "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return self._finalize_response("\n".join(part for part in text_parts if part))

    def clear_peer_history(self) -> None:
        if self.peer_coordinator is not None:
            self.peer_coordinator.clear(self.session_key)

    def clear_history(self) -> None:
        super().clear_history()
        self.clear_peer_history()
