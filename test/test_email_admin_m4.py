import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_delivery_repository import (
    EmailDeliveryRepository,
    EmailDeliveryRepositoryError,
    canonical_quote_hash,
)
from agent.business.email_delivery_service import EmailDeliveryService, EmailDeliveryServiceError
from agent.business.email_repository import EmailRepository
from agent.business.email_review_service import EmailReviewService
from agent.workflow import WorkflowService
from bus import MessageBus
from channels.email.delivery_worker import EmailDeliveryWorker
from channels.email.delivery_runtime import run_delivery_batch
from channels.email.smtp_sender import SmtpDeliveryError
from channels.email.smtp_sender import SmtpSslSender
from channels.web import WebChannel
from session.conversation import ConversationService


ADMIN_TOKEN = "m4-test-admin-token"


def quote_payload(version=1, total=120.0):
    return {
        "version": version,
        "items": [{
            "product_sku": "PCB-1", "product_name_en": "Control board", "quantity": 10,
            "unit_price_usd": 12.0, "total_price_usd": total,
        }],
        "total_usd": total, "valid_until": "2026-08-31", "payment_terms": "T/T",
        "delivery_term": "FOB Shanghai", "remarks_en": "Thank you for your inquiry.",
    }


def build_service(*, approved=True, healthy=True, outbound=True, allowed=None):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    accounts = EmailAccountRepository(connection)
    account_id = str(uuid.uuid4())
    accounts.create({
        "account_id": account_id, "display_name": "Sales", "provider": "qq",
        "address": "sales@qq.com", "secret_ref": f"email-account/{account_id}", "folder": "INBOX",
        "inbound_enabled": True, "outbound_enabled": outbound, "poll_seconds": 60,
        "sender_name": "NanoClaw Sales", "allowed_senders": [],
        "allowed_recipients": allowed or ["buyer@example.com"],
        "status": "healthy" if healthy else "disabled",
    }, actor="test")
    connection.executescript("""
    CREATE TABLE quotes(
      id INTEGER PRIMARY KEY,rfq_id INTEGER,status TEXT,current_version INTEGER,
      version_data TEXT,created_at TEXT
    );
    CREATE TABLE approval_records(
      id INTEGER PRIMARY KEY,quote_id INTEGER,version INTEGER,status TEXT,reviewer TEXT,
      comment TEXT,content_hash TEXT,created_at TEXT,decided_at TEXT
    );
    """)
    version = quote_payload()
    digest = canonical_quote_hash(version)
    connection.execute(
        "INSERT INTO quotes VALUES(1,1,'approved',1,?,?)",
        (json.dumps([version]), "2026-07-23T00:00:00Z"),
    )
    connection.execute(
        "INSERT INTO approval_records VALUES(11,1,1,?,?,?,?,?,?)",
        ("approved" if approved else "pending", "reviewer", "", digest,
         "2026-07-23T00:00:00Z", "2026-07-23T00:01:00Z"),
    )
    connection.commit()
    repository = EmailDeliveryRepository(connection)
    return EmailDeliveryService(repository), repository, connection, account_id


def request_payload(account_id):
    return {
        "account_id": account_id, "quote_id": 1, "quote_version": 1,
        "approval_key": 11, "recipient": "buyer@example.com",
    }


def test_queue_is_server_rendered_immutable_idempotent_and_privacy_safe():
    service, repository, connection, account_id = build_service()
    first = service.queue(request_payload(account_id))
    second = service.queue(request_payload(account_id))
    assert first["delivery_id"] == second["delivery_id"]
    assert first["status"] == "pending" and first["recipient_masked"] == "b***@example.com"
    serialized = json.dumps(first)
    assert "body_snapshot" not in serialized and "buyer@example.com" not in serialized
    row = repository.get(first["delivery_id"])
    assert row["subject_snapshot"] == "Quotation #1 v1"
    assert "Control board" in row["body_snapshot"]
    assert connection.execute("SELECT count(*) FROM ops_email_delivery").fetchone()[0] == 1
    actions = [row[0] for row in connection.execute(
        "SELECT action FROM ops_email_delivery_audit ORDER BY audit_id"
    ).fetchall()]
    assert actions == ["queued"]


@pytest.mark.parametrize(("approved", "healthy", "outbound", "code"), [
    (False, True, True, "email_quote_not_approved"),
    (True, False, True, "email_outbound_account_disabled"),
    (True, True, False, "email_outbound_account_disabled"),
])
def test_queue_hard_gates_approval_and_account(approved, healthy, outbound, code):
    service, _, _, account_id = build_service(approved=approved, healthy=healthy, outbound=outbound)
    with pytest.raises(EmailDeliveryServiceError, match=code):
        service.queue(request_payload(account_id))


def test_manual_retry_revalidates_and_recovers_stale_delivery():
    service, repository, _, account_id = build_service()
    queued = service.queue(request_payload(account_id))
    repository.mark_stale(queued["delivery_id"], "worker-a", "email_outbound_account_disabled")

    retried = service.retry(queued["delivery_id"], actor="operator")

    assert retried["status"] == "pending"
    assert retried["attempt_count"] == 0
    assert retried["last_error_code"] is None


def test_queue_and_pre_send_both_enforce_allowlist_version_and_hash():
    service, repository, connection, account_id = build_service()
    blocked = request_payload(account_id)
    blocked["recipient"] = "attacker@example.com"
    with pytest.raises(EmailDeliveryServiceError, match="email_recipient_not_allowed"):
        service.queue(blocked)
    queued = service.queue(request_payload(account_id))
    claimed = repository.claim_delivery("worker-a")
    connection.execute("UPDATE quotes SET current_version=2 WHERE id=1")
    connection.commit()
    with pytest.raises(EmailDeliveryRepositoryError, match="email_quote_version_stale"):
        repository.revalidate_claim(claimed["delivery_id"], "worker-a")
    stale = repository.mark_stale(queued["delivery_id"], "worker-a", "email_quote_version_stale")
    assert stale["status"] == "stale"


class RecordingSender:
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []

    def send(self, delivery, account):
        self.calls.append((delivery["delivery_id"], account["account_id"]))
        if self.failure:
            raise self.failure
        return delivery["smtp_message_id"]


def test_worker_claim_is_exclusive_and_marks_smtp_accepted():
    service, repository, _, account_id = build_service()
    queued = service.queue(request_payload(account_id))
    claimed = repository.claim_delivery("other-worker")
    assert claimed["delivery_id"] == queued["delivery_id"]
    assert repository.claim_delivery("worker-b") is None
    repository.fail_delivery(claimed["delivery_id"], "other-worker", "temporary")
    repository.connection.execute(
        "UPDATE ops_email_delivery SET next_attempt_at='2000-01-01T00:00:00Z' WHERE delivery_id=?",
        (queued["delivery_id"],),
    )
    repository.connection.commit()
    sender = RecordingSender()
    result = EmailDeliveryWorker(repository, sender, worker_id="worker-b").run_once()
    assert result["status"] == "accepted" and result["attempt_count"] == 2
    assert sender.calls == [(queued["delivery_id"], account_id)]


def test_worker_timeout_is_outcome_unknown_and_permanent_error_dead_letters():
    service, repository, _, account_id = build_service()
    first = service.queue(request_payload(account_id))
    result = EmailDeliveryWorker(
        repository,
        RecordingSender(SmtpDeliveryError("email_smtp_outcome_unknown", outcome_unknown=True)),
        worker_id="worker-timeout",
    ).run_once()
    assert result["status"] == "outcome_unknown" and result["next_attempt_at"] is None

    # A distinct approval key creates a distinct human send decision/idempotency key.
    repository.connection.execute(
        "INSERT INTO approval_records SELECT 12,quote_id,version,status,reviewer,comment,content_hash,created_at,decided_at FROM approval_records WHERE id=11"
    )
    repository.connection.commit()
    payload = request_payload(account_id); payload["approval_key"] = 12
    second = service.queue(payload)
    result = EmailDeliveryWorker(
        repository,
        RecordingSender(SmtpDeliveryError("email_smtp_recipient_refused", permanent=True)),
        worker_id="worker-permanent",
    ).run_once()
    assert result["delivery_id"] == second["delivery_id"] and result["status"] == "dead_letter"
    retried = service.retry(second["delivery_id"])
    assert retried["status"] == "pending" and retried["attempt_count"] == 0
    assert repository.get(first["delivery_id"])["status"] == "outcome_unknown"


def test_smtp_adapter_uses_ssl_authorization_code_and_deterministic_message_id():
    class SecretStore:
        def get(self, ref):
            assert ref == "email-account/one"
            return "smtp-authorization-code"

    class FakeSmtp:
        instance = None
        def __init__(self, host, port, **kwargs):
            self.host, self.port, self.kwargs = host, port, kwargs
            self.login_args = None; self.message = None
            FakeSmtp.instance = self
        def login(self, address, code): self.login_args = (address, code)
        def send_message(self, message): self.message = message; return {}
        def quit(self): return None

    sender = SmtpSslSender(SecretStore(), smtp_factory=FakeSmtp)
    result = sender.send({
        "recipient": "buyer@example.com", "subject_snapshot": "Quotation #1 v1",
        "body_snapshot": "Approved body\n", "smtp_message_id": "<stable@outbox.local>",
        "in_reply_to": None,
    }, {
        "provider": "qq", "address": "sales@qq.com", "sender_name": "NanoClaw Sales",
        "secret_ref": "email-account/one",
    })
    assert result == "<stable@outbox.local>"
    assert (FakeSmtp.instance.host, FakeSmtp.instance.port) == ("smtp.qq.com", 465)
    assert FakeSmtp.instance.login_args == ("sales@qq.com", "smtp-authorization-code")
    assert FakeSmtp.instance.message["Message-ID"] == "<stable@outbox.local>"


def test_expired_sending_lease_is_recovered_without_blind_send():
    service, repository, connection, account_id = build_service()
    queued = service.queue(request_payload(account_id))
    repository.claim_delivery("crashed-worker", lease_seconds=60)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    connection.execute("UPDATE ops_email_delivery SET lease_until=? WHERE delivery_id=?", (expired, queued["delivery_id"]))
    connection.commit()
    assert repository.requeue_expired_leases() == 1
    recovered = repository.get(queued["delivery_id"])
    assert recovered["status"] == "retry_wait"
    assert recovered["last_error_code"] == "email_delivery_lease_expired"


def test_m4_api_is_protected_and_m3_list_is_available(tmp_path: Path):
    service, _, connection, account_id = build_service()
    channel = WebChannel(
        MessageBus(), conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"), email_admin_token=ADMIN_TOKEN,
        email_delivery_service=service,
        email_review_service=EmailReviewService(EmailRepository(connection), "m4-reviewer"),
    )
    channel._app = FastAPI(); channel._register_routes()
    headers = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
    with TestClient(channel._app) as client:
        assert client.get("/api/email/deliveries").status_code == 401
        sendable = client.get("/api/email/sendable-quotes", headers=headers)
        assert sendable.status_code == 200 and sendable.json()["items"][0]["approval_key"] == 11
        created = client.post("/api/email/deliveries", headers=headers, json=request_payload(account_id))
        assert created.status_code == 200 and created.json()["status"] == "pending"
        listed = client.get("/api/email/deliveries", headers=headers).json()["items"]
        assert listed[0]["delivery_id"] == created.json()["delivery_id"]
        assert "body_snapshot" not in json.dumps(listed)
        metrics = client.get("/api/email/metrics", headers=headers)
        assert metrics.status_code == 200 and metrics.json()["status_counts"] == {"pending": 1}
        inbound = client.get("/api/email/inbound", headers=headers)
        assert inbound.status_code == 200
        assert inbound.json() == {"items": [], "next_cursor": None}


def test_real_smtp_runtime_status_is_protected_and_environment_controlled(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_EMAIL_SMTP_WORKER_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_EMAIL_CLARIFICATION_AUTO_REPLY_ENABLED", "false")
    service, _, connection, _ = build_service()
    channel = WebChannel(
        MessageBus(), conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"), email_admin_token=ADMIN_TOKEN,
        email_delivery_service=service,
        email_review_service=EmailReviewService(EmailRepository(connection), "m4-reviewer"),
    )
    channel._app = FastAPI(); channel._register_routes()
    with TestClient(channel._app) as client:
        assert client.get("/api/email/runtime").status_code == 401
        response = client.get("/api/email/runtime", headers={"Authorization": f"Bearer {ADMIN_TOKEN}"})
    assert response.status_code == 200
    assert response.json() == {
        "smtp_worker_enabled": True,
        "smtp_transport": "smtp_ssl",
        "queue_requires_explicit_operator": True,
        "quote_queue_requires_explicit_operator": True,
        "clarification_auto_reply_enabled": False,
        "agent_smtp_tool_registered": False,
        "managed_ingestion_enabled": True,
        "inbound_scope": "foreign_trade_rfq_only",
        "extraction_mode": "deterministic_local",
    }


def test_delivery_runtime_batch_stops_when_queue_is_idle():
    class Worker:
        def __init__(self):
            self.results = [{"delivery_id": "one", "status": "accepted"}, None]
            self.calls = 0

        def run_once(self):
            self.calls += 1
            return self.results.pop(0)

    worker = Worker()
    assert run_delivery_batch(worker, 10) == [{"delivery_id": "one", "status": "accepted"}]
    assert worker.calls == 2
