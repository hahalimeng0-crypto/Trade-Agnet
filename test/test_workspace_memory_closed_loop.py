import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.context import ContextBuilder
from agent.loop import AgentLoop
from agent.memory_runtime.errors import MemoryVersionConflict
from agent.memory_runtime.models import ActorContext, MemoryScope, TurnRequest
from agent.memory_runtime.outbox import MemoryIndexWorker
from agent.memory_runtime.retrieval import HybridMemoryRetriever
from agent.memory_runtime.services.workspace_memory import (
    DecayAwareRetriever,
    WorkspaceMemoryLifecycle,
    WorkspaceMemoryService,
    stable_project_id,
)
from agent.memory_runtime.stores.keyword import KeywordMemoryIndex
from agent.memory_runtime.stores.sqlite import WorkspaceSQLiteMemoryStore
from agent.memory_runtime.stores.vector import LocalHashEmbeddingAdapter, VectorMemoryIndex
from agent.memory_runtime.working_memory import WorkspaceWorkingMemoryStore
from agent.memory_runtime.workspace_commands import WorkspaceMemoryCommandRouter
from agent.tools.base import Tool
from agent.tools.registry import ToolRegistry
from channels.workspace_memory_api import create_workspace_memory_router
from providers.base import LLMResponse, ToolCallRequest
from session.bounded_manager import BoundedSessionManager


def runtime():
    actor = ActorContext(
        "workspace_operator", "operator-a", "tenant-a",
        frozenset({"workspace_memory_reader", "workspace_memory_writer"}), True,
    )
    scope = MemoryScope(
        "workspace_private", "tenant-a", subject_id="operator-a",
        project_id="project-a", purpose="project_assistance",
    )
    main = WorkspaceSQLiteMemoryStore(
        sqlite3.connect(":memory:", check_same_thread=False), indexing_enabled=True,
    )
    keyword = KeywordMemoryIndex(sqlite3.connect(":memory:", check_same_thread=False))
    vector = VectorMemoryIndex(
        sqlite3.connect(":memory:", check_same_thread=False), LocalHashEmbeddingAdapter(32),
    )
    hybrid = HybridMemoryRetriever(main, keyword, vector)
    return actor, scope, main, WorkspaceMemoryService(main), MemoryIndexWorker(main, keyword, vector), hybrid


def candidate(service, actor, scope, text="User prefers concise Python examples", **kwargs):
    return service.create_candidate(
        actor, scope, content=text, summary=text, memory_type=kwargs.get("memory_type", "semantic"),
        source_refs=("request-a:user",), confidence=.9, importance=.8,
        sensitivity=kwargs.get("sensitivity", "internal"), expires_at=kwargs.get("expires_at"),
    )


def test_candidate_requires_exact_confirmation_before_hybrid_recall():
    actor, scope, main, service, worker, hybrid = runtime()
    pending = candidate(service, actor, scope)
    assert pending.status == "pending_confirmation"
    assert hybrid.search(actor, scope, "Python", 3) == []
    with pytest.raises(MemoryVersionConflict):
        service.confirm(actor, pending.memory_id, version=1, expected_hash="0" * 64)
    active = service.confirm(
        actor, pending.memory_id, version=pending.version, expected_hash=pending.content_hash,
    )
    assert active.status == "active" and active.version == 2
    assert worker.drain() == 1
    assert [hit.item.memory_id for hit in hybrid.search(actor, scope, "Python", 3)] == [active.memory_id]


def test_cross_project_authority_revalidation_and_soft_delete():
    actor, scope, main, service, worker, hybrid = runtime()
    item = candidate(service, actor, scope)
    active = service.confirm(actor, item.memory_id, version=1, expected_hash=item.content_hash)
    worker.drain()
    other = MemoryScope(
        "workspace_private", "tenant-a", subject_id="operator-a",
        project_id="project-b", purpose="project_assistance",
    )
    assert hybrid.search(actor, other, "Python", 3) == []
    main.delete_owned(actor, active.memory_id, active.version)
    assert hybrid.search(actor, scope, "Python", 3) == []
    worker.drain()


def test_decay_changes_ranking_without_expiring_stable_memory():
    actor, scope, main, service, worker, hybrid = runtime()
    older = candidate(service, actor, scope, "Python preference old")
    newer = candidate(service, actor, scope, "Python preference new")
    older = service.confirm(actor, older.memory_id, version=1, expected_hash=older.content_hash)
    newer = service.confirm(actor, newer.memory_id, version=1, expected_hash=newer.content_hash)
    old_time = (datetime.now(timezone.utc) - timedelta(days=360)).isoformat().replace("+00:00", "Z")
    main.connection.execute(
        "UPDATE workspace_memory_item SET valid_from=? WHERE memory_id=?", (old_time, older.memory_id)
    )
    main.connection.commit(); worker.drain()
    decay = DecayAwareRetriever(hybrid, semantic_days=180)
    hits = decay.search(actor, scope, "Python preference", 10)
    assert [hit.item.memory_id for hit in hits][:2] == [newer.memory_id, older.memory_id]
    assert main.get_owned(actor, older.memory_id).status == "active"


def test_explicit_ttl_invalidates_and_enqueues_delete():
    actor, scope, main, service, worker, _ = runtime()
    expired = candidate(
        service, actor, scope, "Temporary preference",
        expires_at="2020-01-01T00:00:00Z",
    )
    active = service.confirm(actor, expired.memory_id, version=1, expected_hash=expired.content_hash)
    assert main.expire_due(now="2021-01-01T00:00:00Z") == 1
    assert main.get_owned(actor, active.memory_id).status == "invalid"
    assert worker.drain() >= 1


class Extractor:
    async def working_patch(self, event_kind, text):
        if event_kind == "user":
            return [{
                "op": "replace", "path": "/goal",
                "value": {"value": "build memory", "evidence": "build memory"},
            }]
        if event_kind == "tool":
            return [{
                "op": "add", "path": "/pending_hypotheses/-",
                "value": {"value": "tool evidence", "evidence": "tool evidence"},
            }]
        return []

    async def long_term_candidates(self, user_message, response):
        return [{
            "content": "Remember build memory", "summary": "Build memory preference",
            "memory_type": "procedural", "evidence": "build memory",
            "confidence": .8, "importance": .7, "sensitivity": "internal",
        }]


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, **kwargs):
        return "tool evidence"


def test_agent_success_tool_hook_updates_workbench_and_notice_once(tmp_path):
    class Provider:
        def __init__(self): self.calls = 0
        async def chat(self, messages, tools=None, model=None):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(tool_calls=[ToolCallRequest("call-a", "echo", {})])
            return LLMResponse(content="done")

    async def summarize(_): return "summary"
    actor, scope, main, service, _, _ = runtime()
    sessions = BoundedSessionManager(str(tmp_path / "sessions"), max_turns=10, summarizer=summarize)
    working = WorkspaceWorkingMemoryStore(sqlite3.connect(":memory:", check_same_thread=False))
    lifecycle = WorkspaceMemoryLifecycle(
        sessions, working, service, main, extractor=Extractor(), auto_extract=True,
    )
    tools = ToolRegistry(); tools.register(EchoTool())
    agent = AgentLoop(
        Provider(), tools, ContextBuilder(str(tmp_path), include_memory=False), sessions,
        session_key="cli:test", max_iterations=3, memory_lifecycle=lifecycle,
        memory_request_factory=lambda key, rid, msg, hist, trusted: TurnRequest(
            rid, actor, MemoryScope(**{**scope.__dict__, "conversation_id": key}), msg, hist, key,
        ),
    )
    answer = asyncio.run(agent.run("please build memory"))
    assert answer.count("[记忆候选") == 1
    state = working.get_state("tenant-a", "operator-a", "project-a", "cli:test")
    assert state.goal.value == "build memory" and state.goal.state == "confirmed"
    assert any(value.value == "tool evidence" for value in state.pending_hypotheses)
    assert sessions.get_history("cli:test")[-1]["content"] == answer


def test_deterministic_command_and_api_confirmation():
    actor, scope, _, service, _, _ = runtime()
    item = candidate(service, actor, scope)
    router = WorkspaceMemoryCommandRouter(service, actor, scope)
    vague = asyncio.run(router.execute("/memory confirm"))
    assert json.loads(vague)["status"] == "invalid"
    exact = asyncio.run(router.execute(
        f"/memory confirm {item.memory_id} {item.version} {item.content_hash}"
    ))
    assert json.loads(exact)["status"] == "active"

    app = FastAPI()
    app.include_router(create_workspace_memory_router(
        service, actor, scope, token="memory-token",
    ))
    client = TestClient(app)
    assert client.get("/api/workspace/memories").status_code == 401
    response = client.get(
        "/api/workspace/memories", headers={
            "Authorization": "Bearer memory-token", "Origin": "http://testserver",
        },
    )
    assert response.status_code == 200 and response.json()["items"]


def test_stable_project_id_is_checkout_scoped(tmp_path):
    assert stable_project_id(str(tmp_path / "a")) == stable_project_id(str(tmp_path / "a"))
    assert stable_project_id(str(tmp_path / "a")) != stable_project_id(str(tmp_path / "b"))
