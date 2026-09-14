import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import agent.business.config as business_config
from storage_topology import validate_storage_topology


PRODUCTION_ENV = {
    "NANOCLAW_STORAGE_PROFILE": "production",
    "NANOCLAW_MYSQL_HOST": "mysql",
    "NANOCLAW_MYSQL_PORT": "3306",
    "NANOCLAW_MYSQL_DATABASE": "nanoclaw",
    "NANOCLAW_MYSQL_USER": "app",
    "NANOCLAW_MYSQL_PASSWORD": "secret",
    "BUSINESS_DATABASE_BACKEND": "mysql",
    "NANOCLAW_CONVERSATION_BACKEND": "mysql",
    "RAG_METADATA_BACKEND": "mysql",
    "RAG_VECTOR_BACKEND": "milvus",
    "NANOCLAW_MILVUS_URI": "http://milvus:19530",
    "NANOCLAW_MILVUS_TOKEN": "app:secret",
    "NANOCLAW_MILVUS_DATABASE": "default",
    "RAG_KEYWORD_BACKEND": "elasticsearch",
    "NANOCLAW_ELASTICSEARCH_URL": "http://elasticsearch:9200",
    "NANOCLAW_ELASTICSEARCH_USERNAME": "elastic",
    "NANOCLAW_ELASTICSEARCH_PASSWORD": "secret",
}


def runtime_config(**overrides):
    values = {
        "memory_long_term_backend": "mysql",
        "memory_vector_backend": "milvus",
        "workspace_memory_legacy_fallback_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_production_profile_accepts_only_the_agreed_topology():
    with patch.dict(os.environ, PRODUCTION_ENV, clear=True):
        business_config._loaded = None
        validate_storage_topology(runtime_config())
    business_config._loaded = None


def test_production_profile_rejects_sqlite_keyword_fallback():
    values = dict(PRODUCTION_ENV, RAG_KEYWORD_BACKEND="sqlite")
    with patch.dict(os.environ, values, clear=True):
        business_config._loaded = None
        with pytest.raises(RuntimeError, match="rag_keyword=sqlite"):
            validate_storage_topology(runtime_config())
    business_config._loaded = None
