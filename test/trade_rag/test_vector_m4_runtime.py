from __future__ import annotations

import json
import asyncio
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from agent.tools.customer_public import CustomerPublicKnowledgeTool
from agent.tools.workspace_peer import WorkspaceKnowledgeAnalysisTool
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.config import RagVectorConfig
from trade_rag.contracts import Actor
from trade_rag.pipeline import RagPipeline
from trade_rag.vector_runtime import (
    ManagedVectorStore,
    VectorBackendUnavailable,
    vector_runtime_state,
)


class FakeStore:
    def check_ready(self):
        return None

    def upsert(self, children, source, vectors):
        return len(list(children))

    def search(self, vector, actor, limit=30):
        return []

    def delete_by_document(self, document_id, version=None):
        return 0


def test_runtime_does_not_fallback_and_recovers_without_leaking_errors():
    vector_runtime_state.reset()
    config = RagVectorConfig(
        "milvus", 64, milvus_uri="http://127.0.0.1:19530",
        milvus_token="user:super-secret", milvus_database="db",
        milvus_alias="trade_knowledge_active",
    )
    with patch("trade_rag.vector_runtime.create_vector_store", side_effect=RuntimeError("token=super-secret")):
        store = ManagedVectorStore(config, retry_seconds=0)
        with pytest.raises(VectorBackendUnavailable):
            store.search([0.0] * 64, Actor("actor"))
    snapshot = vector_runtime_state.snapshot(include_audit=True)
    serialized = json.dumps(snapshot)
    assert snapshot["backend"] == "milvus" and snapshot["ready"] is False
    assert "super-secret" not in serialized and "token=" not in serialized

    with patch("trade_rag.vector_runtime.create_vector_store", return_value=FakeStore()):
        assert store.refresh(force=True) is True
        assert store.search([0.0] * 64, Actor("actor")) == []
    assert vector_runtime_state.snapshot()["ready"] is True


def test_memory_runtime_records_content_free_metrics():
    vector_runtime_state.reset()
    store = ManagedVectorStore(RagVectorConfig("memory", 64))
    assert store.search([0.0] * 64, Actor("private-actor", frozenset({"secret-role"}))) == []
    payload = vector_runtime_state.snapshot(include_audit=True)
    serialized = json.dumps(payload)
    assert payload["operations_total"]["search"] == 1
    assert "private-actor" not in serialized and "secret-role" not in serialized
    prometheus = vector_runtime_state.prometheus()
    assert "nanoclaw_vector_backend_ready" in prometheus
    assert "private-actor" not in prometheus


def test_web_health_readiness_and_observability_are_separate(monkeypatch):
    monkeypatch.setenv("RAG_OBSERVABILITY_TOKEN", "observer-secret")
    vector_runtime_state.reset()
    pipeline = RagPipeline(store=ManagedVectorStore(RagVectorConfig("memory", 64)))
    channel = WebChannel(MessageBus(), knowledge_pipeline=pipeline)
    channel._app = __import__("fastapi").FastAPI()
    channel._register_routes()
    client = TestClient(channel._app)

    assert client.get("/healthz").json() == {"status": "ok", "service": "nanoclaw-web"}
    assert client.get("/readyz").status_code == 200
    assert client.get("/api/rag/metrics").status_code == 401
    metrics = client.get(
        "/api/rag/metrics", headers={"Authorization": "Bearer observer-secret"}
    )
    assert metrics.status_code == 200 and metrics.json()["backend"] == "memory"
    assert "observer-secret" not in metrics.text
    prometheus = client.get(
        "/metrics/rag", headers={"Authorization": "Bearer observer-secret"}
    )
    assert prometheus.status_code == 200


def test_degraded_backend_keeps_liveness_but_fails_readiness(monkeypatch):
    monkeypatch.setenv("RAG_OBSERVABILITY_TOKEN", "observer-secret")
    config = RagVectorConfig(
        "milvus", 64, milvus_uri="http://127.0.0.1:19530",
        milvus_token="app:not-used", milvus_database="db",
        milvus_alias="trade_knowledge_active",
    )
    with patch("trade_rag.vector_runtime.create_vector_store", side_effect=RuntimeError("offline")):
        managed = ManagedVectorStore(config, retry_seconds=0)
        pipeline = RagPipeline(store=managed)
        channel = WebChannel(MessageBus(), knowledge_pipeline=pipeline)
        channel._app = __import__("fastapi").FastAPI()
        channel._register_routes()
        client = TestClient(channel._app)
        assert client.get("/healthz").status_code == 200
        response = client.get("/readyz")
    assert response.status_code == 503 and response.json() == {"status": "not_ready"}


def test_customer_and_workspace_fail_closed_without_content(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    with patch("agent.tools.customer_public.RagPipeline", side_effect=RuntimeError("offline")):
        payload = json.loads(asyncio.run(CustomerPublicKnowledgeTool(repository).execute(query="secret")))
    assert payload == {"status": "TEMPORARILY_UNAVAILABLE", "answer": "", "citations": []}

    with patch("agent.tools.workspace_peer.RagPipeline", side_effect=RuntimeError("offline")):
        payload = json.loads(asyncio.run(WorkspaceKnowledgeAnalysisTool(repository).execute(query="secret")))
    assert payload == {
        "status": "TEMPORARILY_UNAVAILABLE", "analysis_material": "", "citations": []
    }


def test_mcp_failure_returns_no_answer_or_citations():
    import trade_rag.server as server
    with patch.object(server, "_refresh_imported_knowledge", side_effect=RuntimeError("offline")):
        payload = server.search_enterprise_knowledge("private question", "actor")
    assert payload == {"status": "VECTOR_BACKEND_UNAVAILABLE", "answer": "", "citations": []}
