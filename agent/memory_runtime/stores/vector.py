"""Versioned vector adapter contract and a local, no-network test implementation."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import threading
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import MemoryItem, MemoryScope
from .keyword import IndexHit, tokenize


@runtime_checkable
class EmbeddingAdapter(Protocol):
    @property
    def model_id(self) -> str: ...
    @property
    def dimensions(self) -> int: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LocalHashEmbeddingAdapter:
    """Deterministic local adapter for plumbing/tests; not a semantic production model."""

    def __init__(self, dimensions: int = 64):
        if dimensions < 8:
            raise ValueError("embedding_dimensions_invalid")
        self._dimensions = dimensions

    @property
    def model_id(self) -> str:
        return f"local-hash-v1-{self.dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for token in tokenize(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:4], "big") % self.dimensions
                vector[bucket] += 1.0 if digest[4] & 1 else -1.0
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    @property
    def external(self) -> bool:
        return False


class OpenAICompatibleEmbeddingAdapter:
    """Explicitly approved OpenAI-compatible embedding adapter."""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 dimensions: int, transfer_approved: bool, timeout_seconds: int = 20):
        if not transfer_approved:
            raise RuntimeError("workspace_memory_external_transfer_not_approved")
        parsed_url = urlparse(base_url.strip())
        if (parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
                or not api_key.strip() or not model.strip() or dimensions < 8):
            raise ValueError("workspace_memory_external_embedding_invalid")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def external(self) -> bool:
        return True

    def embed(self, texts: list[str]) -> list[list[float]]:
        payload = json.dumps({"model": self.model_id, "input": texts}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/embeddings", data=payload, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
        rows = sorted(body.get("data", []), key=lambda row: int(row.get("index", 0)))
        vectors = [row.get("embedding") for row in rows]
        if len(vectors) != len(texts) or any(
            not isinstance(vector, list) or len(vector) != self.dimensions
            for vector in vectors
        ):
            raise RuntimeError("workspace_memory_embedding_response_invalid")
        try:
            numeric = [[float(value) for value in vector] for vector in vectors]
        except (TypeError, ValueError, OverflowError) as exc:
            raise RuntimeError("workspace_memory_embedding_response_invalid") from exc
        if any(not math.isfinite(value) for vector in numeric for value in vector):
            raise RuntimeError("workspace_memory_embedding_response_invalid")
        return numeric


class VectorMemoryIndex:
    def __init__(
        self, database: str | Path | sqlite3.Connection,
        embedding: EmbeddingAdapter, *, readonly=False,
    ):
        self.embedding = embedding
        if isinstance(database, sqlite3.Connection):
            self.connection = database
        else:
            path = Path(database)
            if readonly:
                if not path.is_file():
                    raise RuntimeError("memory_vector_index_not_configured")
                self.connection = sqlite3.connect(
                    f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False,
                )
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        if readonly:
            self.connection.execute("PRAGMA query_only=ON")
            tables = {row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            if not {"memory_vector_index", "memory_vector_index_meta"} <= tables:
                raise RuntimeError("memory_vector_index_schema_invalid")
        else:
            with self.connection:
                self.connection.executescript("""
              CREATE TABLE IF NOT EXISTS memory_vector_index (
                memory_id TEXT PRIMARY KEY, realm TEXT NOT NULL, tenant_id TEXT NOT NULL,
                account_id TEXT, subject_id TEXT, project_id TEXT, conversation_id TEXT,
                purpose TEXT NOT NULL, vector_json TEXT NOT NULL,
                embedding_model TEXT NOT NULL, dimensions INTEGER NOT NULL,
                source_version INTEGER NOT NULL, updated_at TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS ix_memory_vector_scope ON memory_vector_index(
                realm,tenant_id,account_id,subject_id,project_id,purpose,conversation_id);
              CREATE TABLE IF NOT EXISTS memory_vector_index_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                index_version INTEGER NOT NULL, embedding_model TEXT NOT NULL,
                dimensions INTEGER NOT NULL);
                """)
        current = self.connection.execute(
            "SELECT embedding_model,dimensions FROM memory_vector_index_meta WHERE singleton=1"
        ).fetchone()
        if current is None and not readonly:
            with self.connection:
                self.connection.execute(
                    "INSERT INTO memory_vector_index_meta VALUES (1,0,?,?)",
                    (embedding.model_id, embedding.dimensions),
                )
        elif current is None or (current["embedding_model"] != embedding.model_id or
              current["dimensions"] != embedding.dimensions):
            raise RuntimeError("memory_embedding_model_version_mismatch")

    def upsert(self, item: MemoryItem) -> None:
        vector = self.embedding.embed([f"{item.summary} {item.content}"])[0]
        with self._lock, self.connection:
            self.connection.execute(
                """INSERT INTO memory_vector_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(memory_id) DO UPDATE SET
                     realm=excluded.realm,tenant_id=excluded.tenant_id,
                     account_id=excluded.account_id,subject_id=excluded.subject_id,
                     project_id=excluded.project_id,conversation_id=excluded.conversation_id,
                     purpose=excluded.purpose,vector_json=excluded.vector_json,
                     embedding_model=excluded.embedding_model,dimensions=excluded.dimensions,
                     source_version=excluded.source_version,updated_at=excluded.updated_at""",
                (item.memory_id, item.scope.realm, item.scope.tenant_id,
                 item.scope.account_id, item.scope.subject_id, item.scope.project_id,
                 item.scope.conversation_id, item.scope.purpose, json.dumps(vector),
                 self.embedding.model_id, self.embedding.dimensions, item.version,
                 item.updated_at),
            )
            self.connection.execute(
                "UPDATE memory_vector_index_meta SET index_version=index_version+1 WHERE singleton=1"
            )

    def delete(self, memory_id: str) -> None:
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "DELETE FROM memory_vector_index WHERE memory_id=?", (memory_id,)
            )
            if cursor.rowcount:
                self.connection.execute(
                    "UPDATE memory_vector_index_meta SET index_version=index_version+1 WHERE singleton=1"
                )

    def search(self, scope: MemoryScope, query: str, limit: int) -> list[IndexHit]:
        query_vector = self.embedding.embed([query])[0]
        with self._lock:
            rows = self.connection.execute(
                """SELECT memory_id,vector_json FROM memory_vector_index
                   WHERE realm=? AND tenant_id=? AND purpose=?
                     AND embedding_model=? AND dimensions=?
                     AND (? IS NULL OR account_id=?)
                     AND (? IS NULL OR subject_id=?)
                     AND (? IS NULL OR project_id=?)
                     AND (? IS NULL OR conversation_id IS NULL OR conversation_id=?)""",
                (scope.realm, scope.tenant_id, scope.purpose,
                 self.embedding.model_id, self.embedding.dimensions,
                 scope.account_id, scope.account_id,
                 scope.subject_id, scope.subject_id,
                 scope.project_id, scope.project_id,
                 scope.conversation_id, scope.conversation_id),
            ).fetchall()
        hits = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            score = sum(a * b for a, b in zip(query_vector, vector))
            if score > 0:
                hits.append(IndexHit(row["memory_id"], score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.memory_id))[:limit]

    @property
    def index_version(self) -> int:
        return int(self.connection.execute(
            "SELECT index_version FROM memory_vector_index_meta WHERE singleton=1"
        ).fetchone()[0])


def _milvus_literal(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("milvus_filter_value_must_be_text")
    return json.dumps(value, ensure_ascii=True)


class MilvusMemoryIndex:
    """Milvus semantic index for long-term memory.

    MySQL remains authoritative.  This collection contains only the embedding,
    scope fields needed for candidate selection, and the MySQL ``memory_id``.
    """

    def __init__(
        self, *, uri: str, token: str, database: str, collection: str,
        embedding: EmbeddingAdapter, client=None, create_collection: bool = True,
    ) -> None:
        if not uri.strip() or not database.strip() or not collection.strip():
            raise RuntimeError("memory_milvus_configuration_incomplete")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,254}", collection):
            raise ValueError("memory_milvus_collection_invalid")
        self.embedding = embedding
        self.uri = uri
        self.token = token
        self.database = database
        self.collection = collection
        self._client = client
        self._version = 0
        self._lock = threading.RLock()
        self._ensure_collection(create=create_collection)

    def _get_client(self):
        if self._client is None:
            try:
                from pymilvus import MilvusClient
            except ImportError as exc:
                raise RuntimeError("memory_milvus_driver_missing") from exc
            kwargs = {"uri": self.uri, "db_name": self.database, "timeout": 10}
            if self.token:
                kwargs["token"] = self.token
            self._client = MilvusClient(**kwargs)
        return self._client

    @staticmethod
    def _field_dimension(description: dict) -> int:
        for field in description.get("fields", ()):
            if field.get("name") == "embedding":
                params = field.get("params") or {}
                return int(params.get("dim") or field.get("dim") or 0)
        return 0

    def _ensure_collection(self, *, create: bool) -> None:
        client = self._get_client()
        exists = bool(client.has_collection(collection_name=self.collection))
        if not exists:
            if not create:
                raise RuntimeError("memory_milvus_collection_missing")
            try:
                from pymilvus import DataType, MilvusClient
            except ImportError as exc:
                raise RuntimeError("memory_milvus_driver_missing") from exc
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("memory_id", DataType.VARCHAR, is_primary=True, max_length=64)
            for name, length in (
                ("realm", 32), ("tenant_id", 128), ("account_id", 128),
                ("subject_id", 128), ("project_id", 128),
                ("conversation_id", 256), ("purpose", 128),
                ("embedding_model", 192),
            ):
                schema.add_field(name, DataType.VARCHAR, max_length=length)
            schema.add_field("source_version", DataType.INT64)
            schema.add_field(
                "embedding", DataType.FLOAT_VECTOR, dim=self.embedding.dimensions,
            )
            indexes = MilvusClient.prepare_index_params()
            indexes.add_index(
                field_name="embedding", index_type="HNSW", metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            client.create_collection(
                collection_name=self.collection, schema=schema, index_params=indexes,
                consistency_level="Strong",
            )
        description = client.describe_collection(collection_name=self.collection)
        if self._field_dimension(description) != self.embedding.dimensions:
            raise RuntimeError("memory_embedding_model_version_mismatch")
        try:
            client.load_collection(collection_name=self.collection)
        except Exception as exc:
            # Loading an already-loaded collection is client-version dependent.
            state = client.get_load_state(collection_name=self.collection)
            if "loaded" not in str(state.get("state", "")).lower():
                raise RuntimeError("memory_milvus_collection_not_loaded") from exc

    @staticmethod
    def _scope_filter(scope: MemoryScope) -> str:
        clauses = [
            f"realm == {_milvus_literal(scope.realm)}",
            f"tenant_id == {_milvus_literal(scope.tenant_id)}",
            f"purpose == {_milvus_literal(scope.purpose)}",
        ]
        for name in ("account_id", "subject_id", "project_id"):
            value = getattr(scope, name)
            if value is not None:
                clauses.append(f"{name} == {_milvus_literal(value)}")
        if scope.conversation_id is not None:
            value = _milvus_literal(scope.conversation_id)
            clauses.append(f'(conversation_id == "" or conversation_id == {value})')
        return " and ".join(clauses)

    def upsert(self, item: MemoryItem) -> None:
        vector = self.embedding.embed([f"{item.summary} {item.content}"])[0]
        if len(vector) != self.embedding.dimensions:
            raise RuntimeError("memory_embedding_dimension_invalid")
        entity = {
            "memory_id": item.memory_id,
            "realm": item.scope.realm,
            "tenant_id": item.scope.tenant_id,
            "account_id": item.scope.account_id or "",
            "subject_id": item.scope.subject_id or "",
            "project_id": item.scope.project_id or "",
            "conversation_id": item.scope.conversation_id or "",
            "purpose": item.scope.purpose,
            "embedding_model": self.embedding.model_id,
            "source_version": int(item.version),
            "embedding": [float(value) for value in vector],
        }
        with self._lock:
            self._get_client().upsert(
                collection_name=self.collection, data=[entity],
            )
            self._version += 1

    def delete(self, memory_id: str) -> None:
        with self._lock:
            self._get_client().delete(
                collection_name=self.collection,
                filter=f"memory_id == {_milvus_literal(memory_id)}",
            )
            self._version += 1

    def search(self, scope: MemoryScope, query: str, limit: int) -> list[IndexHit]:
        if not 1 <= limit <= 1000:
            raise ValueError("memory_top_k_invalid")
        vector = self.embedding.embed([query])[0]
        response = self._get_client().search(
            collection_name=self.collection, data=[vector], anns_field="embedding",
            filter=self._scope_filter(scope), limit=limit,
            output_fields=["memory_id", "embedding_model", "source_version"],
            search_params={"metric_type": "COSINE", "params": {"ef": max(64, limit)}},
            consistency_level="Strong",
        )
        hits: list[IndexHit] = []
        for hit in (response[0] if response else ()):
            entity = hit.get("entity") or {}
            memory_id = str(entity.get("memory_id") or hit.get("id") or "")
            if not memory_id or entity.get("embedding_model") != self.embedding.model_id:
                continue
            score = float(hit.get("distance", hit.get("score", 0.0)))
            if score > 0:
                hits.append(IndexHit(memory_id, score))
        return sorted(hits, key=lambda hit: (-hit.score, hit.memory_id))[:limit]

    @property
    def index_version(self) -> int:
        return self._version
