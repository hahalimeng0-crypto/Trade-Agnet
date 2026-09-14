import asyncio
import sqlite3
from types import SimpleNamespace

from agent.context import ContextBuilder
from agent.internal_langgraph_agent import NanoClawEmployeeAgentAdapter
from agent.tools.base import Tool
from agent.tools.registry import ToolRegistry
from agent.workflow import WorkflowService
from providers.base import LLMResponse, ToolCallRequest
from session.manager import SessionManager


class SequenceProvider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def chat(self, messages, tools=None, model=None):
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        return self.responses.pop(0)


class EchoTool(Tool):
    @property
    def name(self):
        return "echo_business_result"

    @property
    def description(self):
        return "Return a deterministic business result"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs):
        return f"business:{kwargs['value']}"


class ExtractRfqTool(Tool):
    @property
    def name(self):
        return "extract_rfq"

    @property
    def description(self):
        return "Extract an RFQ with deterministic evidence"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {"raw_text": {"type": "string"}},
            "required": ["raw_text"],
            "additionalProperties": False,
        }

    async def execute(self, **kwargs):
        return '{"rfq_id":"rfq-7","extraction":{"missing_fields":[]}}'


class WorkflowSpy:
    def __init__(self):
        self.tool_results = []
        self.analytics_results = []

    async def observe_tool(self, session_key, tool_name, result):
        self.tool_results.append((session_key, tool_name, result))

    async def observe_analytics(self, session_key, result):
        self.analytics_results.append((session_key, result))


class MemoryLifecycleSpy:
    def __init__(self):
        self.prepared = []
        self.tool_results = []
        self.completed = []
        self.aborted = []

    async def prepare_turn(self, request):
        self.prepared.append(request)
        return SimpleNamespace(history=[])

    async def observe_tool_result(self, event):
        self.tool_results.append(event)

    async def complete_turn(self, event):
        self.completed.append(event)
        return None

    async def abort_turn(self, event):
        self.aborted.append(event)


def test_internal_agent_uses_langgraph_and_preserves_existing_side_effects(tmp_path):
    (tmp_path / "identity.md").write_text("INTERNAL TRADE AGENT", encoding="utf-8")
    provider = SequenceProvider(
        LLMResponse(
            tool_calls=[ToolCallRequest(
                "call-1", "echo_business_result", {"value": "RFQ-7"},
            )],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="询盘处理完成。"),
    )
    tools = ToolRegistry()
    tools.register(EchoTool())
    workflow = WorkflowSpy()
    memory = MemoryLifecycleSpy()
    checkpoint_path = tmp_path / "employee-checkpoints.sqlite3"
    agent = NanoClawEmployeeAgentAdapter(
        provider=provider,
        tools=tools,
        context=ContextBuilder(workspace=str(tmp_path), identity_file="identity.md"),
        session_manager=SessionManager(tmp_path / "sessions"),
        model="test-model",
        max_iterations=4,
        session_key="web:local:00000000-0000-4000-8000-000000000007",
        workflow_service=workflow,
        memory_lifecycle=memory,
        memory_request_factory=lambda *args: args,
        checkpoint_path=str(checkpoint_path),
    )
    agent.set_request_context({"request_id": "request-7"})

    result = asyncio.run(agent.run("处理这条询盘"))

    assert result == "询盘处理完成。"
    assert agent.runtime.graph_name == "internal_foreign_trade_agent"
    assert len(provider.calls) == 2
    assert provider.calls[0]["model"] == "test-model"
    assert provider.calls[0]["tools"][0]["function"]["name"] == "echo_business_result"
    assert provider.calls[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "call-1", "content": "business:RFQ-7",
    }
    assert workflow.tool_results == [(
        agent.session_key, "echo_business_result", "business:RFQ-7",
    )]
    assert workflow.analytics_results == []
    assert [event.result for event in memory.tool_results] == ["business:RFQ-7"]
    assert len(memory.prepared) == len(memory.completed) == 1
    assert memory.aborted == []
    history = agent.session_manager.get_history(agent.session_key)
    assert [message["role"] for message in history] == [
        "user", "assistant", "tool", "assistant",
    ]
    assert history[-1]["content"] == "询盘处理完成。"
    with sqlite3.connect(checkpoint_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 0


def test_internal_langgraph_agent_keeps_generic_provider_error_response(tmp_path):
    (tmp_path / "identity.md").write_text("INTERNAL TRADE AGENT", encoding="utf-8")
    agent = NanoClawEmployeeAgentAdapter(
        provider=SequenceProvider(LLMResponse(content="provider detail", finish_reason="error")),
        tools=ToolRegistry(),
        context=ContextBuilder(workspace=str(tmp_path), identity_file="identity.md"),
        session_manager=SessionManager(tmp_path / "sessions"),
        max_iterations=2,
        session_key="cli:test",
    )

    assert asyncio.run(agent.run("hello")) == "抱歉，发生了错误，请稍后重试。"


def test_internal_langgraph_agent_keeps_trade_workflow_state_updates(tmp_path):
    conversation_id = "00000000-0000-4000-8000-000000000008"
    (tmp_path / "identity.md").write_text("INTERNAL TRADE AGENT", encoding="utf-8")
    provider = SequenceProvider(
        LLMResponse(
            tool_calls=[ToolCallRequest(
                "call-rfq", "extract_rfq", {"raw_text": "Need 100 units"},
            )],
            finish_reason="tool_calls",
        ),
        LLMResponse(content="RFQ extracted."),
    )
    tools = ToolRegistry()
    tools.register(ExtractRfqTool())
    workflow = WorkflowService(tmp_path / "workflows")
    agent = NanoClawEmployeeAgentAdapter(
        provider=provider,
        tools=tools,
        context=ContextBuilder(workspace=str(tmp_path), identity_file="identity.md"),
        session_manager=SessionManager(tmp_path / "sessions"),
        max_iterations=4,
        session_key=f"web:local:{conversation_id}",
        workflow_service=workflow,
    )

    assert asyncio.run(agent.run("Extract this inquiry")) == "RFQ extracted."
    runs = workflow.list_runs(conversation_id)
    assert len(runs) == 1
    assert runs[0].current_node == "extract_rfq"
    assert runs[0].completed_nodes == ["extract_rfq"]
    assert runs[0].status == "running"
