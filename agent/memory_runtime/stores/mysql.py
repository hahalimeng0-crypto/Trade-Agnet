"""MySQL authoritative stores for structured long-term memory.

The domain behavior intentionally reuses the thoroughly tested SQLite store
implementations.  ``MySQLCompatConnection`` only adapts DB-API placeholders and
row shapes; all consent, confirmation, optimistic-locking, TTL and outbox rules
remain identical across backends.
"""

from __future__ import annotations

import threading
from typing import Any, Iterable

from ..policy import MemoryPolicy
from .sqlite import CustomerSQLiteMemoryStore, WorkspaceSQLiteMemoryStore


class _CompatRow(dict):
    """Dictionary row that also supports SQLite-style numeric access."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


class _Result:
    def __init__(self, cursor) -> None:
        self.rowcount = int(cursor.rowcount or 0)
        self.lastrowid = cursor.lastrowid
        if cursor.description:
            self._rows = [_CompatRow(row) for row in cursor.fetchall()]
        else:
            self._rows = []
        cursor.close()

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class MySQLCompatConnection:
    """Small transaction-aware adapter used by the existing store contract."""

    def __init__(self, connection) -> None:
        self.raw = connection
        self.total_changes = 0
        self._depth = 0
        self._guard = threading.RLock()

    @staticmethod
    def _sql(statement: str) -> str:
        return statement.replace("INSERT OR IGNORE", "INSERT IGNORE").replace("?", "%s")

    def execute(self, statement: str, parameters: Iterable[Any] = ()) -> _Result:
        cursor = self.raw.cursor()
        try:
            cursor.execute(self._sql(statement), tuple(parameters))
            result = _Result(cursor)
        except Exception:
            cursor.close()
            raise
        if result.rowcount > 0:
            self.total_changes += result.rowcount
        return result

    def __enter__(self):
        with self._guard:
            if self._depth == 0:
                self.raw.begin()
            self._depth += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        del exc, traceback
        with self._guard:
            self._depth -= 1
            if self._depth == 0:
                self.raw.rollback() if exc_type else self.raw.commit()
        return False

    def close(self) -> None:
        self.raw.close()


def create_memory_mysql_connection(
    *, host: str, port: int, database: str, user: str, password: str,
    connect_timeout_seconds: int = 5,
) -> MySQLCompatConnection:
    if not all((host.strip(), database.strip(), user.strip(), password)):
        raise RuntimeError("memory_mysql_configuration_incomplete")
    try:
        import pymysql
        from pymysql.cursors import DictCursor
    except ImportError as exc:
        raise RuntimeError("memory_mysql_driver_missing") from exc
    raw = pymysql.connect(
        host=host, port=int(port), database=database, user=user, password=password,
        charset="utf8mb4", cursorclass=DictCursor, autocommit=True,
        connect_timeout=int(connect_timeout_seconds), read_timeout=15, write_timeout=15,
    )
    return MySQLCompatConnection(raw)


_CUSTOMER_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS customer_memory_consent (
      consent_record_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
      account_id VARCHAR(128) NOT NULL, purpose VARCHAR(128) NOT NULL,
      categories_json JSON NOT NULL, status VARCHAR(32) NOT NULL,
      granted_at VARCHAR(40) NOT NULL, expires_at VARCHAR(40) NULL,
      withdrawn_at VARCHAR(40) NULL,
      KEY ix_customer_consent_scope (tenant_id,account_id,purpose,status,expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS customer_memory_item (
      memory_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
      account_id VARCHAR(128) NOT NULL, conversation_id VARCHAR(191) NULL,
      memory_type VARCHAR(32) NOT NULL, purpose VARCHAR(128) NOT NULL,
      content TEXT NOT NULL, summary TEXT NOT NULL, source_refs_json JSON NOT NULL,
      status VARCHAR(32) NOT NULL, confidence DOUBLE NOT NULL, importance DOUBLE NOT NULL,
      sensitivity VARCHAR(32) NOT NULL, consent_record_id VARCHAR(64) NULL,
      version INT NOT NULL, supersedes VARCHAR(64) NULL, content_hash CHAR(64) NOT NULL,
      embedding_model VARCHAR(191) NULL, created_at VARCHAR(40) NOT NULL,
      updated_at VARCHAR(40) NOT NULL, valid_from VARCHAR(40) NOT NULL,
      expires_at VARCHAR(40) NULL, invalid_reason VARCHAR(255) NULL,
      live_content_hash CHAR(64) GENERATED ALWAYS AS
        (CASE WHEN status IN ('pending_consent','active') THEN content_hash ELSE NULL END) STORED,
      UNIQUE KEY uq_customer_memory_live_hash
        (tenant_id,account_id,purpose,live_content_hash),
      KEY ix_customer_memory_scope
        (tenant_id,account_id,purpose,status,expires_at),
      CONSTRAINT fk_customer_memory_consent FOREIGN KEY (consent_record_id)
        REFERENCES customer_memory_consent(consent_record_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS memory_deletion_job (
      job_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
      account_id VARCHAR(128) NULL, conversation_id VARCHAR(191) NULL,
      request_id VARCHAR(191) NOT NULL UNIQUE, status VARCHAR(32) NOT NULL,
      steps_json JSON NOT NULL, attempt_count INT NOT NULL DEFAULT 0,
      created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
      completed_at VARCHAR(40) NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS memory_index_outbox (
      event_id VARCHAR(64) PRIMARY KEY, store_kind VARCHAR(32) NOT NULL,
      aggregate_id VARCHAR(64) NOT NULL, event_type VARCHAR(32) NOT NULL,
      payload_json JSON NOT NULL, status VARCHAR(32) NOT NULL,
      attempt_count INT NOT NULL DEFAULT 0, available_at VARCHAR(40) NOT NULL,
      created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
      KEY ix_memory_index_outbox_due (status,available_at,created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


_WORKSPACE_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS workspace_memory_item (
      memory_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
      subject_id VARCHAR(128) NULL, project_id VARCHAR(128) NULL,
      memory_type VARCHAR(32) NOT NULL, purpose VARCHAR(128) NOT NULL,
      content TEXT NOT NULL, summary TEXT NOT NULL, source_refs_json JSON NOT NULL,
      status VARCHAR(32) NOT NULL, confidence DOUBLE NOT NULL, importance DOUBLE NOT NULL,
      sensitivity VARCHAR(32) NOT NULL, version INT NOT NULL,
      supersedes VARCHAR(64) NULL, content_hash CHAR(64) NOT NULL,
      created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL,
      valid_from VARCHAR(40) NOT NULL, expires_at VARCHAR(40) NULL,
      live_content_hash CHAR(64) GENERATED ALWAYS AS
        (CASE WHEN status IN ('pending_confirmation','active') THEN content_hash ELSE NULL END) STORED,
      UNIQUE KEY uq_workspace_memory_live_hash
        (tenant_id,subject_id,project_id,purpose,live_content_hash),
      KEY ix_workspace_memory_scope
        (tenant_id,subject_id,project_id,purpose,status,expires_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS workspace_memory_index_outbox (
      event_id VARCHAR(64) PRIMARY KEY, aggregate_id VARCHAR(64) NOT NULL,
      event_type VARCHAR(32) NOT NULL, payload_json JSON NOT NULL,
      status VARCHAR(32) NOT NULL, attempt_count INT NOT NULL DEFAULT 0,
      available_at VARCHAR(40) NOT NULL, created_at VARCHAR(40) NOT NULL,
      updated_at VARCHAR(40) NOT NULL,
      KEY ix_workspace_memory_index_due (status,available_at,created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS workspace_memory_review_suggestion (
      suggestion_id VARCHAR(64) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL,
      subject_id VARCHAR(128) NOT NULL, project_id VARCHAR(128) NOT NULL,
      action VARCHAR(32) NOT NULL, memory_ids_json JSON NOT NULL,
      rationale TEXT NOT NULL, status VARCHAR(32) NOT NULL,
      content_hash CHAR(64) NOT NULL, version INT NOT NULL,
      created_at VARCHAR(40) NOT NULL, updated_at VARCHAR(40) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
)


def _ensure_schema(connection: MySQLCompatConnection, statements: tuple[str, ...]) -> None:
    with connection:
        for statement in statements:
            connection.execute(statement)


class CustomerMySQLMemoryStore(CustomerSQLiteMemoryStore):
    """Customer long-term authority persisted in MySQL."""

    def __init__(self, connection: MySQLCompatConnection, policy: MemoryPolicy | None = None,
                 *, indexing_enabled: bool = True, ensure_schema: bool = True):
        self.connection = connection
        self.policy = policy or MemoryPolicy()
        self.indexing_enabled = bool(indexing_enabled)
        self._lock = threading.RLock()
        if ensure_schema:
            _ensure_schema(connection, _CUSTOMER_SCHEMA)

    def search_owned(self, *, tenant_id: str, account_id: str,
                     conversation_id: str | None, purpose: str, query: str,
                     top_k: int):
        from ..models import ActorContext, MemoryScope
        actor = ActorContext("customer", account_id, tenant_id, frozenset(), True)
        scope = MemoryScope(
            "customer_conversation" if conversation_id else "customer_private",
            tenant_id, account_id=account_id, conversation_id=conversation_id,
            purpose=purpose,
        )
        return self.search(actor, scope, query, top_k)


class WorkspaceMySQLMemoryStore(WorkspaceSQLiteMemoryStore):
    """Workspace long-term authority persisted in MySQL."""

    def __init__(self, connection: MySQLCompatConnection, policy: MemoryPolicy | None = None,
                 *, indexing_enabled: bool = True, ensure_schema: bool = True):
        self.connection = connection
        self.policy = policy or MemoryPolicy()
        self.indexing_enabled = bool(indexing_enabled)
        self._lock = threading.RLock()
        if ensure_schema:
            _ensure_schema(connection, _WORKSPACE_SCHEMA)
