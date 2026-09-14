from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_default_rag_backends(monkeypatch):
    """Unit tests use fresh memory stores even when the developer's .env is persistent."""
    if not any(os.environ.get(name) == "1" for name in (
        "NANOCLAW_TEST_PGVECTOR", "NANOCLAW_TEST_MILVUS",
    )):
        monkeypatch.setenv("RAG_VECTOR_BACKEND", "memory")
    if os.environ.get("NANOCLAW_TEST_ELASTICSEARCH") != "1":
        monkeypatch.setenv("RAG_KEYWORD_BACKEND", "memory")
