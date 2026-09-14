"""Durable MySQL parent-chunk store used with Milvus/Elasticsearch RAG."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from .contracts import Actor, CanonicalDocument, ParentChunk
from .mysql_metadata import RagMetadataConfig


class MySQLParentStore:
    def __init__(self, config: RagMetadataConfig, *, connection_factory=None) -> None:
        config.validate()
        self.config = config
        self._connection_factory = connection_factory or self._connect

    def _connect(self):
        try:
            import pymysql
            from pymysql.cursors import DictCursor
        except ImportError as exc:
            raise RuntimeError("RAG MySQL driver is missing") from exc
        return pymysql.connect(
            host=self.config.host, port=self.config.port, database=self.config.database,
            user=self.config.user, password=self.config.password, charset="utf8mb4",
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
    def _json(value: Any) -> Any:
        return json.loads(value) if isinstance(value, str) else value

    def upsert(self, parents: Iterable[ParentChunk], source: CanonicalDocument) -> int:
        rows = list(parents)
        if any(parent.document_id != source.document_id for parent in rows):
            raise ValueError("parent_document_mismatch")
        with self._tx() as cursor:
            for parent in rows:
                cursor.execute(
                    """INSERT INTO rag_parent_chunk
                       (parent_id,document_id,document_version,content_hash,parent_text,
                        parent_location,metadata_json,business_unit_id,allowed_roles_json,
                        source_status,expires_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE document_id=VALUES(document_id),
                         document_version=VALUES(document_version),content_hash=VALUES(content_hash),
                         parent_text=VALUES(parent_text),parent_location=VALUES(parent_location),
                         metadata_json=VALUES(metadata_json),business_unit_id=VALUES(business_unit_id),
                         allowed_roles_json=VALUES(allowed_roles_json),source_status=VALUES(source_status),
                         expires_at=VALUES(expires_at),updated_at=CURRENT_TIMESTAMP(6)""",
                    (
                        parent.parent_id, source.document_id, source.version, parent.content_hash,
                        parent.text, parent.location,
                        json.dumps(parent.metadata, ensure_ascii=False, separators=(",", ":")),
                        source.business_unit_id,
                        json.dumps(sorted(source.allowed_roles), ensure_ascii=False),
                        source.status.value,
                        source.expires_at.astimezone(timezone.utc).isoformat() if source.expires_at else None,
                    ),
                )
        return len(rows)

    def get(self, parent_id: str, actor: Actor | None = None) -> ParentChunk | None:
        with self._tx() as cursor:
            cursor.execute("SELECT * FROM rag_parent_chunk WHERE parent_id=%s", (parent_id,))
            row = cursor.fetchone()
        if row is None:
            return None
        metadata = dict(self._json(row["metadata_json"]) or {})
        if actor is not None:
            if row["business_unit_id"] != actor.business_unit_id:
                return None
            if row["source_status"] not in {"approved", "published"}:
                return None
            expires_at = row.get("expires_at")
            if expires_at:
                expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry <= datetime.now(timezone.utc):
                    return None
            roles = frozenset(self._json(row["allowed_roles_json"]) or [])
            if roles and not roles.intersection(actor.roles):
                return None
            if ("customer" in actor.roles
                    and metadata.get("classification") != "public"):
                return None
        return ParentChunk(
            str(row["parent_id"]), str(row["document_id"]), str(row["parent_text"]),
            str(row["parent_location"]), str(row["content_hash"]),
            metadata,
        )

    def get_many(self, parent_ids: Iterable[str], actor: Actor | None = None) -> list[ParentChunk]:
        return [item for parent_id in parent_ids if (item := self.get(parent_id, actor)) is not None]

    def delete_by_document(self, document_id: str, version: int | None = None) -> int:
        where = "document_id=%s"
        params: list[Any] = [document_id]
        if version is not None:
            where += " AND document_version=%s"
            params.append(version)
        with self._tx() as cursor:
            cursor.execute(f"DELETE FROM rag_parent_chunk WHERE {where}", params)
            return int(cursor.rowcount or 0)
