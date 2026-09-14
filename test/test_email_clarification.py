import asyncio
import sqlite3
import uuid

import pytest

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_clarification import (
    EmailClarificationError,
    EmailClarificationRepository,
)
from agent.business.email_config import EmailIngestionConfig
from agent.business.email_repository import EmailRepository
from agent.business.email_secret_store import MemoryEmailSecretStore
from agent.business.managed_email_ingestion import ManagedEmailIngestionRuntime
from channels.email.contracts import EmailEnvelope
from channels.email.delivery_worker import EmailDeliveryWorker


def extraction(missing=None):
    return {
        "customer": {"name": {"value": "Michael", "status": "confirmed"}},
        "missing_fields": missing if missing is not None else [
            "customer.company", "items[0].quantity", "trade_term",
        ],
    }


def setup_database(*, outbound=True, status="healthy"):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    emails = EmailRepository(connection)
    accounts = EmailAccountRepository(connection)
    account_id = str(uuid.uuid4())
    accounts.create({
        "account_id": account_id,
        "display_name": "Sales",
        "provider": "qq",
        "address": "sales@qq.com",
        "secret_ref": f"email-account/{account_id}",
        "folder": "INBOX",
        "inbound_enabled": True,
        "outbound_enabled": outbound,
        "poll_seconds": 30,
        "sender_name": "NanoClaw Sales",
        "allowed_senders": [],
        "allowed_recipients": [],
        "status": status,
    }, actor="test")
    clarifications = EmailClarificationRepository(connection)
    return connection, emails, accounts, clarifications, account_id


def persist_inbound(emails, account_id, *, reply_to=("purchasing@example.com",)):
    envelope = EmailEnvelope(
        account_id=account_id,
        provider="qq",
        provider_message_id="provider-one",
        folder="INBOX",
        uidvalidity=1,
        uid=1,
        internet_message_id="<buyer-one@example.com>",
        from_name="Michael",
        from_address="buyer@example.com",
        reply_to=reply_to,
        to=("sales@qq.com",),
        subject="RFQ for USB-C cables",
        text_body="Please quote 500 pcs USB-C data cables for our purchase order.",
        raw_sha256="a" * 64,
    )
    email_id, _ = emails.persist(
        envelope, classification_code="email_trade_rfq_accepted",
    )
    emails.complete_extraction(email_id, extraction())
    return email_id


def test_clarification_is_sender_bound_rendered_and_idempotent():
    connection, emails, _, repository, account_id = setup_database()
    email_id = persist_inbound(emails, account_id)

    first = repository.queue_for_inbound(email_id, extraction())
    second = repository.queue_for_inbound(email_id, extraction())

    assert first["delivery_id"] == second["delivery_id"]
    assert first["recipient"] == "purchasing@example.com"
    assert first["subject_snapshot"] == "Re: RFQ for USB-C cables"
    assert "Company name" in first["body_snapshot"]
    assert "Item 1: quantity and unit" in first["body_snapshot"]
    assert "FOB Shanghai" in first["body_snapshot"]
    assert connection.execute(
        "SELECT COUNT(1) FROM ops_email_clarification_delivery"
    ).fetchone()[0] == 1


def test_clarification_requires_missing_fields_and_healthy_inbound_account():
    _, emails, _, repository, account_id = setup_database(outbound=False, status="disabled")
    email_id = persist_inbound(emails, account_id)
    with pytest.raises(EmailClarificationError, match="email_clarification_account_unavailable"):
        repository.queue_for_inbound(email_id, extraction())
    with pytest.raises(EmailClarificationError, match="email_clarification_no_missing_fields"):
        repository.queue_for_inbound(email_id, extraction([]))


def test_clarification_worker_revalidates_original_recipient_and_marks_accepted():
    _, emails, _, repository, account_id = setup_database()
    queued = repository.queue_for_inbound(
        persist_inbound(emails, account_id), extraction(),
    )

    class RecordingSender:
        def __init__(self):
            self.calls = []

        def send(self, delivery, account):
            self.calls.append((delivery, account))
            return delivery["smtp_message_id"]

    sender = RecordingSender()
    result = EmailDeliveryWorker(
        repository, sender, worker_id="clarification-test",
    ).run_once()

    assert result["delivery_id"] == queued["delivery_id"]
    assert result["status"] == "accepted"
    assert sender.calls[0][0]["auto_submitted"] is True
    assert sender.calls[0][0]["delivery_kind"] == "rfq_clarification"


def test_managed_ingestion_queues_but_does_not_send_clarification():
    connection, emails, accounts, repository, account_id = setup_database()
    secrets = MemoryEmailSecretStore()
    secrets.set(f"email-account/{account_id}", "test-auth-code")
    envelope = EmailEnvelope(
        account_id=account_id,
        provider="qq",
        provider_message_id="provider-two",
        folder="INBOX",
        uidvalidity=1,
        uid=2,
        internet_message_id="<buyer-two@example.com>",
        from_name="Buyer",
        from_address="buyer@example.com",
        to=("sales@qq.com",),
        subject="Need a quote",
        text_body="Please quote 500 pcs USB-C data cables for our purchase order.",
        raw_sha256="b" * 64,
    )

    class Source:
        def __init__(self, settings, limits):
            pass

        def fetch_after(self, last_uid, limit=50):
            return [envelope] if last_uid < 2 else []

    runtime = ManagedEmailIngestionRuntime(
        EmailIngestionConfig(
            managed_accounts_enabled=True,
            clarification_auto_reply_enabled=True,
        ),
        account_repository=accounts,
        email_repository=emails,
        secret_store=secrets,
        clarification_repository=repository,
        source_factory=Source,
    )

    result = asyncio.run(runtime.poll_due())
    message = result[0]["messages"][0]
    assert message["status"] == "needs_review"
    assert message["clarification_status"] == "pending"
    assert connection.execute(
        "SELECT COUNT(1) FROM ops_email_clarification_delivery WHERE status='pending'"
    ).fetchone()[0] == 1


def test_automatic_replies_are_rejected_before_rfq_extraction():
    from agent.business.email_trade_classifier import classify_trade_rfq_email

    envelope = EmailEnvelope(
        account_id="one", provider="qq", provider_message_id="auto", folder="INBOX",
        uidvalidity=1, uid=1, from_address="buyer@example.com",
        subject="Re: RFQ for 500 pcs", text_body="Please quote 500 pcs cables.",
        auto_submitted="auto-replied", raw_sha256="c" * 64,
    )
    result = classify_trade_rfq_email(envelope)
    assert result.accepted is False
    assert result.code == "email_trade_automated_message"
