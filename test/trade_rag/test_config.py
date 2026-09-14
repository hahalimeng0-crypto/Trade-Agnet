import os
import unittest
from pathlib import Path
from unittest.mock import patch

from trade_rag.config import load_rag_api_config, load_rag_keyword_config, load_rag_vector_config


class RagApiConfigTests(unittest.TestCase):
    def test_load_and_validate_without_exposing_keys(self):
        values = {
            "RAG_EMBEDDING_API_KEY": "secret-embedding",
            "RAG_EMBEDDING_BASE_URL": "https://embedding.example/v1/",
            "RAG_EMBEDDING_MODEL": "embedding-model",
            "RAG_EMBEDDING_DIMENSIONS": "768",
            "RAG_RERANK_API_KEY": "secret-rerank",
            "RAG_RERANK_BASE_URL": "https://rerank.example/v1/",
            "RAG_RERANK_MODEL": "rerank-model",
            "RAG_REMOTE_DATA_TRANSFER_APPROVED": "true",
        }
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, values, clear=True):
            cfg = load_rag_api_config(); cfg.validate_remote_ready()
        self.assertEqual(cfg.embedding_dimensions, 768)
        self.assertEqual(cfg.embedding.base_url, "https://embedding.example/v1")
        self.assertTrue(cfg.embedding.configured and cfg.rerank.configured)

    def test_missing_or_unapproved_remote_config_is_blocked(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, {}, clear=True):
            cfg = load_rag_api_config()
            with self.assertRaises(ValueError): cfg.validate_remote_ready()

    def test_invalid_numeric_config_is_rejected(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, {"RAG_EMBEDDING_DIMENSIONS": "0"}, clear=True):
                with self.assertRaises(ValueError): load_rag_api_config()

    def test_vector_backend_defaults_to_memory_and_fixed_64_dimensions(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, {}, clear=True):
            cfg = load_rag_vector_config()
        self.assertEqual(cfg.backend, "memory")
        self.assertEqual(cfg.dimensions, 64)

    def test_keyword_backend_defaults_to_memory(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, {}, clear=True):
            cfg = load_rag_keyword_config()
        self.assertEqual(cfg.backend, "memory")

    def test_elasticsearch_keyword_config_is_explicit_and_fail_closed(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(
            os.environ, {"RAG_KEYWORD_BACKEND": "elasticsearch"}, clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "missing Elasticsearch configuration"):
                load_rag_keyword_config()

        values = {
            "RAG_KEYWORD_BACKEND": "elasticsearch",
            "RAG_ELASTICSEARCH_URL": "http://127.0.0.1:9201/",
            "RAG_ELASTICSEARCH_USERNAME": "elastic",
            "RAG_ELASTICSEARCH_PASSWORD": "secret",
            "RAG_ELASTICSEARCH_INDEX": "trade_knowledge_child_v1",
        }
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, values, clear=True):
            cfg = load_rag_keyword_config()
        self.assertEqual(cfg.url, "http://127.0.0.1:9201")

    def test_pgvector_config_is_fail_closed(self):
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(
            os.environ, {"RAG_VECTOR_BACKEND": "pgvector"}, clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "missing pgvector configuration"):
                load_rag_vector_config()

        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(
            os.environ, {"RAG_VECTOR_BACKEND": "memory", "RAG_VECTOR_DIMENSIONS": "1024"}, clear=True,
        ):
            with self.assertRaisesRegex(ValueError, "requires RAG_VECTOR_DIMENSIONS=64"):
                load_rag_vector_config()

    def test_sqlite_vector_and_keyword_config_share_a_persistent_path(self):
        values = {
            "RAG_VECTOR_BACKEND": "sqlite",
            "RAG_KEYWORD_BACKEND": "sqlite",
            "RAG_SQLITE_INDEX_PATH": "workspace/knowledge_base/test-index.db",
        }
        with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(
            os.environ, values, clear=True,
        ):
            vector = load_rag_vector_config()
            keyword = load_rag_keyword_config()
        self.assertEqual(vector.backend, "sqlite")
        self.assertEqual(keyword.backend, "sqlite")
        self.assertEqual(vector.sqlite_path, keyword.sqlite_path)


if __name__ == "__main__": unittest.main()
