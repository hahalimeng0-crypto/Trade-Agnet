import asyncio
import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.memory_runtime.migrate_workspace_markdown import run as migrate_markdown
from agent.memory_runtime.models import ActorContext, MemoryScope
from agent.memory_runtime.outbox import MemoryIndexWorker
from agent.memory_runtime.retrieval import HybridMemoryRetriever
from agent.memory_runtime.services.workspace_memory import (
    WorkspaceMemoryReviewService,
    WorkspaceMemoryService,
)
from agent.memory_runtime.stores.keyword import KeywordMemoryIndex
from agent.memory_runtime.stores.sqlite import WorkspaceSQLiteMemoryStore
from agent.memory_runtime.stores.vector import (
    LocalHashEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
    VectorMemoryIndex,
)
from channels.workspace_memory_api import create_workspace_memory_router
from providers.base import LLMResponse


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
        actor, scope, content=text, summary=text,
        memory_type=kwargs.get("memory_type", "semantic"),
        source_refs=("request-a:user",), confidence=.9, importance=.8,
        sensitivity=kwargs.get("sensitivity", "internal"),
        expires_at=kwargs.get("expires_at"),
    )


def test_external_embedding_configuration_and_response_fail_closed(monkeypatch):
    with pytest.raises(RuntimeError, match="external_transfer_not_approved"):
        OpenAICompatibleEmbeddingAdapter(
            base_url="https://embedding.example/v1", api_key="key", model="model",
            dimensions=8, transfer_approved=False,
        )
    with pytest.raises(ValueError, match="external_embedding_invalid"):
        OpenAICompatibleEmbeddingAdapter(
            base_url="not-a-url", api_key="key", model="model",
            dimensions=8, transfer_approved=True,
        )

    adapter = OpenAICompatibleEmbeddingAdapter(
        base_url="https://embedding.example/v1", api_key="key", model="model",
        dimensions=8, transfer_approved=True,
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"data": [{"index": 0, "embedding": [0.0] * 7}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="embedding_response_invalid"):
        adapter.embed(["text"])


def test_restricted_item_never_reaches_external_vector_and_keyword_degrades():
    actor, scope, main, service, _, _ = runtime()
    item = candidate(service, actor, scope, "restricted local detail", sensitivity="restricted")
    service.confirm(actor, item.memory_id, version=item.version, expected_hash=item.content_hash)
    keyword = KeywordMemoryIndex(sqlite3.connect(":memory:", check_same_thread=False))

    class ExternalVector:
        class Embedding:
            external = True

        embedding = Embedding()
        index_version = 0
        called = False

        def upsert(self, item):
            self.called = True

        def delete(self, memory_id):
            pass

        def search(self, scope, query, limit):
            raise RuntimeError("vector_unavailable")

    vector = ExternalVector()
    worker = MemoryIndexWorker(main, keyword, vector)
    assert worker.run_once() is True
    assert vector.called is False

    retriever = HybridMemoryRetriever(main, keyword, vector)
    hits = retriever.search(actor, scope, "restricted", 3)
    assert [hit.item.memory_id for hit in hits] == [item.memory_id]
    assert retriever.last_mode == "keyword_degraded"


def test_review_persists_pending_suggestion_without_mutating_active_memory():
    actor, scope, main, service, _, _ = runtime()
    item = candidate(service, actor, scope)
    active = service.confirm(
        actor, item.memory_id, version=item.version, expected_hash=item.content_hash,
    )

    class Provider:
        async def chat(self, messages, tools=None, model=None):
            return LLMResponse(content=json.dumps([{
                "action": "invalidate", "memory_ids": [active.memory_id],
                "rationale": "possible conflict",
            }]))

    review = WorkspaceMemoryReviewService(main, Provider())
    assert asyncio.run(review.run_once(actor, scope)) == 1
    assert main.get_owned(actor, active.memory_id).status == "active"
    row = main.connection.execute(
        "SELECT status FROM workspace_memory_review_suggestion"
    ).fetchone()
    assert row["status"] == "pending_confirmation"


def test_api_scope_origin_conflict_and_confirmation_retry_are_safe():
    actor, scope, _, service, _, _ = runtime()
    item = candidate(service, actor, scope)
    app = FastAPI()
    app.include_router(create_workspace_memory_router(
        service, actor, scope, token="memory-token",
        allowed_origins=("https://approved.example",),
    ))
    client = TestClient(app)
    headers = {"Authorization": "Bearer memory-token"}
    assert client.get("/api/workspace/memories", headers=headers).status_code == 403
    assert client.get(
        "/api/workspace/memories", headers={**headers, "Origin": "https://evil.example"},
    ).status_code == 403
    headers["Origin"] = "https://approved.example"
    payload = {"version": item.version, "content_hash": item.content_hash}
    first = client.post(
        f"/api/workspace/memories/{item.memory_id}/confirm", json=payload, headers=headers,
    )
    retry = client.post(
        f"/api/workspace/memories/{item.memory_id}/confirm", json=payload, headers=headers,
    )
    assert first.status_code == retry.status_code == 200
    bad = client.post(
        f"/api/workspace/memories/{item.memory_id}/confirm",
        json={"version": 99, "content_hash": item.content_hash}, headers=headers,
    )
    assert bad.status_code == 409

    other_scope = MemoryScope(
        "workspace_private", scope.tenant_id, subject_id=scope.subject_id,
        project_id="project-b", purpose=scope.purpose,
    )
    other_app = FastAPI()
    other_app.include_router(create_workspace_memory_router(
        service, actor, other_scope, token="memory-token",
    ))
    other_client = TestClient(other_app)
    assert other_client.get(
        f"/api/workspace/memories/{item.memory_id}", headers={
            "Authorization": "Bearer memory-token", "Origin": "http://testserver",
        },
    ).status_code == 404


def test_markdown_migration_is_dry_run_idempotent_and_preserves_source(tmp_path, monkeypatch):
    workspace = tmp_path / "checkout"
    memory_dir = workspace / "workspace" / "memory"
    memory_dir.mkdir(parents=True)
    legacy = memory_dir / "MEMORY.md"
    original = b"# Memory\n\n- Prefer concise answers\n- Use Python 3.11\n"
    legacy.write_bytes(original)
    (memory_dir / "HISTORY.md").write_text("# History\n", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"workspace": str(workspace)}), encoding="utf-8")
    monkeypatch.delenv("NANOCLAW_WORKSPACE_MEMORY_ENABLED", raising=False)

    dry = migrate_markdown(apply=False, config_path=str(config_path))
    assert dry["candidate_count"] == 2
    assert not (memory_dir / "workspace_memory.db").exists()

    first = migrate_markdown(apply=True, config_path=str(config_path))
    second = migrate_markdown(apply=True, config_path=str(config_path))
    assert first["created"] == 2
    assert second["created"] == 0
    assert legacy.read_bytes() == original
    connection = sqlite3.connect(memory_dir / "workspace_memory.db")
    statuses = connection.execute(
        "SELECT DISTINCT status FROM workspace_memory_item"
    ).fetchall()
    sources = connection.execute(
        "SELECT source_refs_json FROM workspace_memory_item ORDER BY memory_id"
    ).fetchall()
    connection.close()
    assert statuses == [("pending_confirmation",)]
    assert all("legacy:workspace/memory/MEMORY.md#L" in row[0] for row in sources)
    assert len(list((memory_dir / "migration_backups").iterdir())) == 2
