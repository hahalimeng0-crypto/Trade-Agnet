"""Fail-closed validation for the agreed local/production storage boundaries."""

from __future__ import annotations

import os


def storage_profile() -> str:
    value = os.environ.get("NANOCLAW_STORAGE_PROFILE", "local").strip().lower()
    if value not in {"local", "production"}:
        raise ValueError("NANOCLAW_STORAGE_PROFILE must be local or production")
    return value


def validate_storage_topology(config=None) -> None:
    """Reject a production process that silently falls back to local persistence."""
    if storage_profile() != "production":
        return

    from agent.business.config import load_business_config
    from session.mysql_conversation import conversation_backend
    from trade_rag.config import load_rag_keyword_config, load_rag_vector_config
    from trade_rag.mysql_metadata import load_rag_metadata_config

    actual = {
        "business": load_business_config().database_backend,
        "conversations": conversation_backend(),
        "rag_metadata": load_rag_metadata_config().backend,
        "rag_vector": load_rag_vector_config().backend,
        "rag_keyword": load_rag_keyword_config().backend,
    }
    expected = {
        "business": "mysql", "conversations": "mysql", "rag_metadata": "mysql",
        "rag_vector": "milvus", "rag_keyword": "elasticsearch",
    }
    mismatches = [f"{key}={actual[key]} (expected {value})" for key, value in expected.items()
                  if actual[key] != value]
    if config is not None:
        if config.memory_long_term_backend != "mysql":
            mismatches.append("long_term_memory must use mysql")
        if config.memory_vector_backend != "milvus":
            mismatches.append("semantic_memory must use milvus")
        if config.workspace_memory_legacy_fallback_enabled:
            mismatches.append("workspace Markdown memory fallback must be disabled")
    if mismatches:
        raise RuntimeError("production storage topology is invalid: " + "; ".join(mismatches))
