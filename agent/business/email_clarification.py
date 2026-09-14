"""Durable automatic replies that request missing RFQ fields.

This outbox is intentionally separate from approved quotation delivery.  A
clarification can only reply to the sender (or Reply-To) of the persisted
inbound RFQ and never accepts an arbitrary recipient from an Agent or API.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from agent.business.config import load_business_config


_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_ITEM_FIELD = re.compile(r"^items\[(\d+)]\.(product|specification|quantity)$")


class EmailClarificationError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_header(value: str, limit: int = 900) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]


def _missing_label(path: str) -> str | None:
    labels = {
        "customer.name": "Contact name",
        "customer.company": "Company name",
        "country": "Destination country or region",
        "delivery_deadline": "Required delivery date",
        "trade_term": "Trade term and named place/port (for example, FOB Shanghai or CIF Hamburg)",
    }
    if path in labels:
        return labels[path]
    match = _ITEM_FIELD.fullmatch(path)
    if not match:
        return None
    item_number = int(match.group(1)) + 1
    detail = {
        "product": "product name or SKU",
        "specification": "required model/specification",
        "quantity": "quantity and unit",
    }[match.group(2)]
    return f"Item {item_number}: {detail}"


def _contact_name(extraction: dict) -> str:
    node = (extraction.get("customer") or {}).get("name") or {}
    value = _clean_header(node.get("value") or "", 80)
    return value if value else "there"


def build_clarification_message(subject: str, extraction: dict) -> tuple[str, str, list[str]]:
    missing_paths: list[str] = []
    labels: list[str] = []
    for raw in extraction.get("missing_fields") or []:
        path = str(raw)
        label = _missing_label(path)
        if label and path not in missing_paths:
            missing_paths.append(path)
            labels.append(label)
    if not labels:
        raise EmailClarificationError("email_clarification_no_missing_fields")
    clean_subject = _clean_header(subject) or "Your quotation request"
    reply_subject = clean_subject if clean_subject.lower().startswith("re:") else f"Re: {clean_subject}"
    bullets = "\n".join(f"- {label}" for label in labels)
    body = (
        f"Hello {_contact_name(extraction)},\n\n"
        "Thank you for your inquiry. To prepare an accurate quotation, please reply "
        "with the following missing information:\n\n"
        f"{bullets}\n\n"
        "Once we receive these details, our sales team will continue the quotation process.\n\n"
        "Best regards,\nNanoClaw Sales Team\n"
    )
    return reply_subject, body, missing_paths


class EmailClarificationRepository:
    """SQLite clarification outbox with sender-bound recipients and leases."""

    def __init__(self, connection: sqlite3.Connection | None = None):
        if connection is None:
            connection = sqlite3.connect(
                load_business_config().database_path, check_same_thread=False,
            )
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.init_schema()

    @contextmanager
    def tx(self, *, immediate: bool = False):
        with self._lock:
            cursor = self.connection.cursor()
            try:
                if immediate:
                    cursor.execute("BEGIN IMMEDIATE")
                yield cursor
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise
            finally:
                cursor.close()

    def init_schema(self) -> None:
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS ops_email_clarification_delivery(
          delivery_id TEXT PRIMARY KEY,
          email_id INTEGER NOT NULL UNIQUE,
          account_id TEXT NOT NULL,
          recipient TEXT NOT NULL,
          subject_snapshot TEXT NOT NULL,
          body_snapshot TEXT NOT NULL,
          missing_fields_json TEXT NOT NULL,
          extraction_hash TEXT NOT NULL,
          snapshot_hash TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending',
          attempt_count INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 5,
          next_attempt_at TEXT,
          lease_owner TEXT,
          lease_until TEXT,
          smtp_message_id TEXT NOT NULL,
          smtp_accepted_at TEXT,
          last_error_code TEXT,
          in_reply_to TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          CHECK(status IN ('pending','sending','retry_wait','accepted','dead_letter','stale','outcome_unknown')),
          CHECK(attempt_count >= 0),
          CHECK(max_attempts > 0),
          FOREIGN KEY(email_id) REFERENCES ops_inbound_email(email_id)
        );
        CREATE INDEX IF NOT EXISTS ix_email_clarification_due
          ON ops_email_clarification_delivery(status,next_attempt_at,lease_until);
        CREATE TABLE IF NOT EXISTS ops_email_clarification_audit(
          audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
          delivery_id TEXT NOT NULL,
          actor TEXT NOT NULL,
          action TEXT NOT NULL,
          error_code TEXT,
          created_at TEXT NOT NULL
        );
        """)
        self.connection.commit()

    @staticmethod
    def _reply_recipient(envelope: dict, fallback: str) -> str:
        reply_to = envelope.get("reply_to") or []
        candidates = [*reply_to, fallback]
        for candidate in candidates:
            value = str(candidate or "").strip().lower()
            if _EMAIL_PATTERN.fullmatch(value) and len(value) <= 254:
                return value
        raise EmailClarificationError("email_clarification_recipient_invalid")

    @staticmethod
    def _account_gate(cursor: sqlite3.Cursor, account_id: str) -> dict:
        row = cursor.execute(
            "SELECT * FROM ops_email_account WHERE account_id=? AND deleted_at IS NULL",
            (account_id,),
        ).fetchone()
        if row is None:
            raise EmailClarificationError("email_account_not_found")
        # The dedicated auto-reply feature flag is the outbound authorization
        # for this narrow path.  Formal quote delivery keeps its independent
        # account outbound flag and recipient allowlist.
        if not bool(row["inbound_enabled"]) or row["status"] != "healthy":
            raise EmailClarificationError("email_clarification_account_unavailable")
        return dict(row)

    def queue_for_inbound(self, email_id: int, extraction: dict,
                          *, actor: str = "rfq_clarification") -> dict:
        if not isinstance(extraction, dict):
            raise EmailClarificationError("email_clarification_invalid_extraction")
        subject, body, missing = build_clarification_message("", extraction)
        del subject, body  # Render again from the transaction-protected inbound row.
        with self.tx(immediate=True) as cursor:
            existing = cursor.execute(
                "SELECT * FROM ops_email_clarification_delivery WHERE email_id=?",
                (email_id,),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            inbound = cursor.execute(
                "SELECT * FROM ops_inbound_email WHERE email_id=?", (email_id,),
            ).fetchone()
            if inbound is None:
                raise EmailClarificationError("email_inbound_not_found")
            if inbound["status"] != "needs_review" or inbound["ingestion_classification_code"] != "email_trade_rfq_accepted":
                raise EmailClarificationError("email_clarification_inbound_not_eligible")
            account = self._account_gate(cursor, inbound["account_id"])
            try:
                envelope = json.loads(inbound["envelope_json"] or "{}")
            except json.JSONDecodeError as exc:
                raise EmailClarificationError("email_clarification_envelope_invalid") from exc
            recipient = self._reply_recipient(envelope, inbound["from_address"])
            if recipient == str(account["address"]).strip().lower():
                raise EmailClarificationError("email_clarification_self_reply_blocked")
            subject, body, missing = build_clarification_message(inbound["subject"], extraction)
            extraction_hash = hashlib.sha256(
                json.dumps(missing, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            snapshot_hash = hashlib.sha256((subject + "\n" + body).encode("utf-8")).hexdigest()
            delivery_id = str(uuid.uuid4())
            message_id = f"<nanoclaw.clarification.{email_id}.{extraction_hash[:16]}@outbox.local>"
            now = _now()
            cursor.execute("""INSERT INTO ops_email_clarification_delivery(
              delivery_id,email_id,account_id,recipient,subject_snapshot,body_snapshot,
              missing_fields_json,extraction_hash,snapshot_hash,status,attempt_count,max_attempts,
              smtp_message_id,in_reply_to,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,'pending',0,5,?,?,?,?)""", (
                delivery_id, email_id, inbound["account_id"], recipient, subject, body,
                json.dumps(missing), extraction_hash, snapshot_hash, message_id,
                inbound["internet_message_id"] or None, now, now,
            ))
            self._audit(cursor, delivery_id, actor, "queued")
            return dict(cursor.execute(
                "SELECT * FROM ops_email_clarification_delivery WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone())

    def get(self, delivery_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM ops_email_clarification_delivery WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return dict(row) if row else None

    def claim_delivery(self, worker_id: str, *, lease_seconds: int = 60) -> dict | None:
        now = _now()
        lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat().replace("+00:00", "Z")
        with self.tx(immediate=True) as cursor:
            row = cursor.execute("""SELECT * FROM ops_email_clarification_delivery
              WHERE status='pending' OR (status='retry_wait' AND next_attempt_at<=?)
              ORDER BY created_at,delivery_id LIMIT 1""", (now,)).fetchone()
            if row is None:
                return None
            cursor.execute("""UPDATE ops_email_clarification_delivery SET status='sending',
              attempt_count=attempt_count+1,lease_owner=?,lease_until=?,updated_at=?
              WHERE delivery_id=? AND status=?""",
              (worker_id, lease_until, now, row["delivery_id"], row["status"]))
            if cursor.rowcount != 1:
                return None
            self._audit(cursor, row["delivery_id"], worker_id, "claimed")
            return dict(cursor.execute(
                "SELECT * FROM ops_email_clarification_delivery WHERE delivery_id=?",
                (row["delivery_id"],),
            ).fetchone())

    def revalidate_claim(self, delivery_id: str, worker_id: str) -> tuple[dict, dict]:
        with self.tx() as cursor:
            delivery = cursor.execute("""SELECT * FROM ops_email_clarification_delivery
              WHERE delivery_id=? AND status='sending' AND lease_owner=?""",
              (delivery_id, worker_id)).fetchone()
            if delivery is None:
                raise EmailClarificationError("email_delivery_lease_lost")
            account = self._account_gate(cursor, delivery["account_id"])
            inbound = cursor.execute(
                "SELECT * FROM ops_inbound_email WHERE email_id=?", (delivery["email_id"],),
            ).fetchone()
            if inbound is None or inbound["ingestion_classification_code"] != "email_trade_rfq_accepted":
                raise EmailClarificationError("email_clarification_inbound_not_eligible")
            envelope = json.loads(inbound["envelope_json"] or "{}")
            expected_recipient = self._reply_recipient(envelope, inbound["from_address"])
            if delivery["recipient"] != expected_recipient:
                raise EmailClarificationError("email_clarification_recipient_changed")
            expected_hash = hashlib.sha256(
                (delivery["subject_snapshot"] + "\n" + delivery["body_snapshot"]).encode("utf-8")
            ).hexdigest()
            if expected_hash != delivery["snapshot_hash"]:
                raise EmailClarificationError("email_delivery_snapshot_tampered")
            result = dict(delivery)
            result["auto_submitted"] = True
            result["delivery_kind"] = "rfq_clarification"
            return result, account

    def mark_smtp_accepted(self, delivery_id: str, worker_id: str,
                           internet_message_id: str | None = None) -> dict:
        now = _now()
        with self.tx() as cursor:
            cursor.execute("""UPDATE ops_email_clarification_delivery SET status='accepted',
              smtp_accepted_at=?,lease_owner=NULL,lease_until=NULL,last_error_code=NULL,updated_at=?
              WHERE delivery_id=? AND status='sending' AND lease_owner=?""",
              (now, now, delivery_id, worker_id))
            if cursor.rowcount != 1:
                raise EmailClarificationError("email_delivery_lease_lost")
            self._audit(cursor, delivery_id, worker_id, "smtp_accepted")
        return self.get(delivery_id)

    def fail_delivery(self, delivery_id: str, worker_id: str, error_code: str, *,
                      permanent: bool = False, outcome_unknown: bool = False) -> dict:
        with self.tx() as cursor:
            row = cursor.execute("""SELECT * FROM ops_email_clarification_delivery
              WHERE delivery_id=? AND status='sending' AND lease_owner=?""",
              (delivery_id, worker_id)).fetchone()
            if row is None:
                raise EmailClarificationError("email_delivery_lease_lost")
            if outcome_unknown:
                status, next_at = "outcome_unknown", None
            elif permanent or int(row["attempt_count"]) >= int(row["max_attempts"]):
                status, next_at = "dead_letter", None
            else:
                delay = min(3600, 30 * (2 ** max(0, int(row["attempt_count"]) - 1)))
                status = "retry_wait"
                next_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
            cursor.execute("""UPDATE ops_email_clarification_delivery SET status=?,next_attempt_at=?,
              lease_owner=NULL,lease_until=NULL,last_error_code=?,updated_at=? WHERE delivery_id=?""",
              (status, next_at, error_code[:100], _now(), delivery_id))
            self._audit(cursor, delivery_id, worker_id, status, error_code[:100])
        return self.get(delivery_id)

    def mark_stale(self, delivery_id: str, actor: str, error_code: str) -> dict:
        with self.tx() as cursor:
            cursor.execute("""UPDATE ops_email_clarification_delivery SET status='stale',
              lease_owner=NULL,lease_until=NULL,last_error_code=?,updated_at=?
              WHERE delivery_id=? AND status IN ('pending','sending','retry_wait','dead_letter')""",
              (error_code[:100], _now(), delivery_id))
            if cursor.rowcount:
                self._audit(cursor, delivery_id, actor, "stale", error_code[:100])
        return self.get(delivery_id)

    def requeue_expired_leases(self, actor: str = "clarification_recovery") -> int:
        now = _now()
        with self.tx(immediate=True) as cursor:
            rows = cursor.execute("""SELECT delivery_id FROM ops_email_clarification_delivery
              WHERE status='sending' AND lease_until<?""", (now,)).fetchall()
            for row in rows:
                cursor.execute("""UPDATE ops_email_clarification_delivery SET status='retry_wait',
                  next_attempt_at=?,lease_owner=NULL,lease_until=NULL,
                  last_error_code='email_delivery_lease_expired',updated_at=? WHERE delivery_id=?""",
                  (now, now, row["delivery_id"]))
                self._audit(cursor, row["delivery_id"], actor, "lease_recovered",
                            "email_delivery_lease_expired")
            return len(rows)

    @staticmethod
    def _audit(cursor: sqlite3.Cursor, delivery_id: str, actor: str,
               action: str, error_code: str | None = None) -> None:
        cursor.execute("""INSERT INTO ops_email_clarification_audit(
          delivery_id,actor,action,error_code,created_at) VALUES(?,?,?,?,?)""",
          (delivery_id, actor, action, error_code, _now()))
