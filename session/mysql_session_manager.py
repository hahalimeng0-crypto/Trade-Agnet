"""Agent session history backed by the production MySQL conversation tables."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from agent.memory_runtime.compaction import SummaryFunction, plan_complete_turns
from privacy import sanitize_data


class MySQLSessionManager:
    """Persist internal sessions in MySQL; customer-portal writes stay channel-owned."""

    def __init__(self, sessions_dir: str = "", *, connection_factory=None) -> None:
        del sessions_dir
        if connection_factory is None:
            from agent.business.mysql_database import create_connection
            connection_factory = create_connection
        self._connection_factory = connection_factory

    @staticmethod
    def _customer_owned(session_key: str) -> bool:
        return session_key.startswith("customer_portal:")

    @staticmethod
    def _conversation_id(session_key: str) -> str:
        candidate = session_key.rsplit(":", 1)[-1]
        try:
            return str(uuid.UUID(candidate))
        except (ValueError, TypeError):
            return str(uuid.uuid5(uuid.NAMESPACE_URL, f"nanoclaw-session:{session_key}"))

    @staticmethod
    def _channel(session_key: str) -> str:
        return (session_key.split(":", 1)[0] or "internal")[:32]

    @staticmethod
    def _message_scope(session_key: str) -> tuple[str, list[str]]:
        conversation_id = MySQLSessionManager._conversation_id(session_key)
        parts = session_key.split(":")
        if len(parts) >= 5 and parts[:2] == ["customer_portal", "account"]:
            return "conversation_id=%s AND account_id=%s", [conversation_id, parts[2]]
        return "conversation_id=%s", [conversation_id]

    def _connection(self):
        return self._connection_factory()

    def _ensure_internal_conversation(self, cursor, session_key: str, conversation_id: str) -> None:
        owner_id = (session_key.split(":", 2)[1] if ":" in session_key else "local")[:128]
        channel = self._channel(session_key)
        cursor.execute(
            """INSERT IGNORE INTO runtime_conversation
               (conversation_id,tenant_id,account_id,owner_id,channel,title,status,created_at,updated_at)
               VALUES (%s,'','',%s,%s,%s,'active',CURRENT_TIMESTAMP(6),CURRENT_TIMESTAMP(6))""",
            (conversation_id, owner_id, channel, session_key[:120]),
        )

    def save_message(self, session_key: str, message: dict[str, Any]) -> None:
        # CustomerPortalChannel already performs request-id idempotent writes.
        if self._customer_owned(session_key):
            return
        conversation_id = self._conversation_id(session_key)
        record = sanitize_data(dict(message))
        role = str(record.get("role", "assistant"))
        if role not in {"user", "assistant", "tool"}:
            role = "assistant"
        payload = json.dumps({"_nanoclaw_message": record}, ensure_ascii=False)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                self._ensure_internal_conversation(cursor, session_key, conversation_id)
                cursor.execute(
                    """INSERT INTO runtime_message
                       (message_id,tenant_id,account_id,conversation_id,role,content_json,created_at)
                       VALUES (%s,'','',%s,%s,%s,CURRENT_TIMESTAMP(6))""",
                    (str(uuid.uuid4()), conversation_id, role, payload),
                )
                cursor.execute(
                    """UPDATE runtime_conversation SET last_message_at=CURRENT_TIMESTAMP(6),
                       updated_at=CURRENT_TIMESTAMP(6) WHERE conversation_id=%s""",
                    (conversation_id,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _decode_message(row: dict[str, Any]) -> dict[str, Any]:
        value = row["content_json"]
        payload = json.loads(value) if isinstance(value, str) else value
        if isinstance(payload, dict) and isinstance(payload.get("_nanoclaw_message"), dict):
            return dict(payload["_nanoclaw_message"])
        return {"role": str(row["role"]), "content": payload}

    def get_history(self, session_key: str) -> list[dict[str, Any]]:
        where, params = self._message_scope(session_key)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""SELECT role,content_json,created_at,message_id FROM runtime_message
                       WHERE {where} AND archived_at IS NULL ORDER BY created_at,message_id""",
                    params,
                )
                history = [self._decode_message(row) for row in cursor.fetchall()]
        finally:
            connection.close()
        # The portal writes the inbound user message before constructing/running the Agent.
        # It is supplied separately to AgentLoop, so exclude that one current message.
        if self._customer_owned(session_key) and history and history[-1].get("role") == "user":
            history.pop()
        return history

    def clear(self, session_key: str) -> None:
        conversation_id = self._conversation_id(session_key)
        where, params = self._message_scope(session_key)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM runtime_message WHERE {where}", params)
                cursor.execute(
                    "UPDATE runtime_conversation SET updated_at=CURRENT_TIMESTAMP(6) WHERE conversation_id=%s",
                    (conversation_id,),
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def list_sessions(self) -> list[str]:
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT conversation_id,channel,owner_id FROM runtime_conversation
                       WHERE status!='deleted' ORDER BY updated_at DESC"""
                )
                return [
                    (f"customer_portal:account:{row['owner_id']}:{row['conversation_id']}"
                     if row["channel"] == "customer_portal" else
                     f"{row['channel']}:{row['owner_id']}:{row['conversation_id']}")
                    for row in cursor.fetchall()
                ]
        finally:
            connection.close()


class MySQLBoundedSessionManager(MySQLSessionManager):
    """Build a bounded prompt without deleting the complete MySQL audit history."""

    def __init__(self, sessions_dir: str = "", *, max_turns: int,
                 summarizer: SummaryFunction, connection_factory=None) -> None:
        super().__init__(sessions_dir, connection_factory=connection_factory)
        self.max_turns = max_turns
        self.summarizer = summarizer

    async def prepare_active_history(self, session_key: str) -> list[dict[str, Any]]:
        original = self.get_history(session_key)
        try:
            plan = plan_complete_turns(original, self.max_turns)
            if not plan.needed:
                return original
            summary = await self.summarizer(list(plan.evicted))
            if not summary.strip():
                return original
            return [{
                "role": "system",
                "content": f"[Bounded history summary]\n{summary.strip()}",
            }, *plan.retained]
        except Exception:
            return original


def create_session_manager(
    sessions_dir: str, *, max_turns: int | None = None,
    summarizer: SummaryFunction | None = None,
):
    from session.mysql_conversation import conversation_backend
    if conversation_backend() == "mysql":
        if max_turns is not None:
            if summarizer is None:
                raise ValueError("bounded MySQL sessions require a summarizer")
            return MySQLBoundedSessionManager(
                sessions_dir, max_turns=max_turns, summarizer=summarizer,
            )
        return MySQLSessionManager(sessions_dir)
    if max_turns is not None:
        if summarizer is None:
            raise ValueError("bounded local sessions require a summarizer")
        from session.bounded_manager import BoundedSessionManager
        return BoundedSessionManager(sessions_dir, max_turns=max_turns, summarizer=summarizer)
    from session.manager import SessionManager
    return SessionManager(sessions_dir)
