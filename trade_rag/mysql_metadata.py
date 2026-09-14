"""MySQL authority for enterprise knowledge metadata and index-job state."""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class RagMetadataConfig:
    backend: str
    host: str = "127.0.0.1"
    port: int = 3306
    database: str = "nanoclaw"
    user: str = ""
    password: str = ""
    connect_timeout_seconds: int = 5

    def validate(self) -> None:
        if self.backend not in {"manifest", "mysql"}:
            raise ValueError("RAG_METADATA_BACKEND must be manifest or mysql")
        if self.backend == "mysql" and not all(
            (self.host.strip(), self.database.strip(), self.user.strip(), self.password)
        ):
            raise ValueError("MySQL RAG metadata configuration is incomplete")


def _env(module_name: str, global_name: str, default: str) -> str:
    return os.environ.get(module_name, os.environ.get(global_name, default))


def load_rag_metadata_config() -> RagMetadataConfig:
    profile = os.environ.get("NANOCLAW_STORAGE_PROFILE", "local").strip().lower()
    if profile not in {"local", "production"}:
        raise ValueError("NANOCLAW_STORAGE_PROFILE must be local or production")
    default_backend = "mysql" if profile == "production" else "manifest"
    config = RagMetadataConfig(
        backend=os.environ.get("RAG_METADATA_BACKEND", default_backend).strip().lower(),
        host=_env("RAG_MYSQL_HOST", "NANOCLAW_MYSQL_HOST", "127.0.0.1"),
        port=int(_env("RAG_MYSQL_PORT", "NANOCLAW_MYSQL_PORT", "3306")),
        database=_env("RAG_MYSQL_DATABASE", "NANOCLAW_MYSQL_DATABASE", "nanoclaw"),
        user=_env("RAG_MYSQL_USER", "NANOCLAW_MYSQL_USER", ""),
        password=_env("RAG_MYSQL_PASSWORD", "NANOCLAW_MYSQL_PASSWORD", ""),
        connect_timeout_seconds=int(os.environ.get("RAG_MYSQL_CONNECT_TIMEOUT_SECONDS", "5")),
    )
    config.validate()
    return config


def _stable_metadata_id(item: dict[str, Any]) -> str:
    identity = "\0".join(
        str(item.get(key, ""))
        for key in ("document_id", "version", "source_hash", "created_at")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


class MySQLKnowledgeMetadataStore:
    """Stores the complete document record in JSON while indexing key fields."""

    def __init__(self, config: RagMetadataConfig, *, connection_factory=None) -> None:
        config.validate()
        if config.backend != "mysql":
            raise ValueError("MySQL metadata store requires backend=mysql")
        self.config = config
        self._connection_factory = connection_factory or self._connect

    def _connect(self):
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError("RAG MySQL driver is missing") from exc
        return pymysql.connect(
            host=self.config.host, port=self.config.port,
            database=self.config.database, user=self.config.user,
            password=self.config.password, charset="utf8mb4",
            cursorclass=DictCursor, autocommit=False,
            connect_timeout=self.config.connect_timeout_seconds,
            read_timeout=15, write_timeout=15,
        )

    @contextmanager
    def _tx(self) -> Iterator[Any]:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _json_value(value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value)
        return value

    def read(self) -> dict[str, Any]:
        try:
            with self._tx() as cursor:
                cursor.execute(
                    "SELECT schema_version,revision FROM rag_manifest_state WHERE singleton_id=1"
                )
                state = cursor.fetchone()
                if state is None:
                    return {"schema_version": "knowledge-import-v4", "documents": [], "_storage_revision": 0}
                cursor.execute(
                    "SELECT payload_json FROM rag_document_metadata ORDER BY sequence_no,metadata_id"
                )
                documents = [self._json_value(row["payload_json"]) for row in cursor.fetchall()]
        except Exception as exc:
            raise RuntimeError(
                "knowledge_metadata_mysql_unavailable; apply trade_rag/migrations/002_mysql_metadata.sql"
            ) from exc
        return {
            "schema_version": str(state["schema_version"]),
            "documents": documents,
            "_storage_revision": int(state["revision"]),
        }

    def write(self, manifest: dict[str, Any]) -> None:
        documents = list(manifest.get("documents") or [])
        expected_revision = int(manifest.get("_storage_revision", 0))
        with self._tx() as cursor:
            cursor.execute(
                "SELECT schema_version,revision FROM rag_manifest_state WHERE singleton_id=1 FOR UPDATE"
            )
            state = cursor.fetchone()
            actual_revision = int(state["revision"]) if state else 0
            if actual_revision != expected_revision:
                raise RuntimeError("knowledge_metadata_conflict")

            cursor.execute(
                "SELECT metadata_id,document_id,document_version FROM rag_document_metadata"
            )
            previous = {row["metadata_id"]: row for row in cursor.fetchall()}
            current_ids = {_stable_metadata_id(item) for item in documents}
            for metadata_id, row in previous.items():
                if metadata_id not in current_ids:
                    job_id = hashlib.sha256(f"delete:{metadata_id}".encode()).hexdigest()
                    cursor.execute(
                        """INSERT INTO rag_index_job
                           (job_id,metadata_id,document_id,document_version,operation,status)
                           VALUES (%s,%s,%s,%s,'delete','pending')
                           ON DUPLICATE KEY UPDATE status=IF(status='completed',status,'pending'),updated_at=CURRENT_TIMESTAMP(6)""",
                        (job_id, metadata_id, row["document_id"], row["document_version"]),
                    )

            cursor.execute("DELETE FROM rag_document_metadata")
            for sequence_no, item in enumerate(documents):
                metadata_id = _stable_metadata_id(item)
                cursor.execute(
                    """INSERT INTO rag_document_metadata
                       (metadata_id,document_id,document_version,source_hash,status,index_status,
                        classification,business_unit_id,sequence_no,payload_json)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        metadata_id, str(item.get("document_id", "")), int(item.get("version", 1)),
                        str(item.get("source_hash", "")), str(item.get("status", "pending")),
                        str(item.get("index_status", "pending")), str(item.get("classification", "internal")),
                        str(item.get("business_unit_id", "default")), sequence_no,
                        json.dumps(item, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                job_id = hashlib.sha256(f"index:{metadata_id}".encode()).hexdigest()
                index_status = str(item.get("index_status", "pending"))
                job_status = {
                    "indexed": "completed", "failed": "failed", "running": "running",
                }.get(index_status, "pending")
                cursor.execute(
                    """INSERT INTO rag_index_job
                       (job_id,metadata_id,document_id,document_version,operation,status,last_error)
                       VALUES (%s,%s,%s,%s,'index',%s,%s)
                       ON DUPLICATE KEY UPDATE status=VALUES(status),last_error=VALUES(last_error),
                           attempt_count=attempt_count+IF(VALUES(status)='running',1,0),updated_at=CURRENT_TIMESTAMP(6)""",
                    (job_id, metadata_id, str(item.get("document_id", "")), int(item.get("version", 1)),
                     job_status, item.get("index_error")),
                )

            new_revision = actual_revision + 1
            cursor.execute(
                """INSERT INTO rag_manifest_state(singleton_id,schema_version,revision)
                   VALUES (1,%s,%s)
                   ON DUPLICATE KEY UPDATE schema_version=VALUES(schema_version),revision=VALUES(revision),
                       updated_at=CURRENT_TIMESTAMP(6)""",
                (str(manifest.get("schema_version", "knowledge-import-v4")), new_revision),
            )
        manifest["_storage_revision"] = new_revision


def create_mysql_metadata_store_if_configured():
    config = load_rag_metadata_config()
    return MySQLKnowledgeMetadataStore(config) if config.backend == "mysql" else None


def bootstrap_mysql_metadata(store: MySQLKnowledgeMetadataStore, manifest_path: str | Path) -> bool:
    """Import a legacy manifest only when the MySQL authority is empty."""
    path = Path(manifest_path)
    current = store.read()
    if current["documents"] or not path.is_file():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_storage_revision"] = current["_storage_revision"]
    store.write(payload)
    return True
