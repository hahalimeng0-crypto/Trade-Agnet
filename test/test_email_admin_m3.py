import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_repository import EmailRepository
from agent.business.email_review_service import (
    EmailReviewGate,
    EmailReviewService,
    EmailReviewServiceError,
)
from agent.business.rfq_extractor import pending_result
from agent.workflow import WorkflowService
from bus import MessageBus
from channels.email.contracts import AttachmentMeta, EmailEnvelope
from channels.web import WebChannel
from session.conversation import ConversationService


ADMIN_TOKEN = "m3-admin-token"
REVIEWER = "reviewer-001"


def build_review():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = EmailRepository(connection)
    accounts = EmailAccountRepository(connection)
    account_id = str(uuid.uuid4())
    accounts.create({
        "account_id": account_id, "display_name": "Review mailbox", "provider": "qq",
        "address": "sales@qq.com", "secret_ref": f"email-account/{account_id}", "folder": "INBOX",
        "inbound_enabled": True, "outbound_enabled": False, "poll_seconds": 60,
        "sender_name": "Sales", "allowed_senders": [], "allowed_recipients": [], "status": "healthy",
    }, actor="test")
    body = "Please quote 500 pcs demo sensors for delivery to Hamburg."
    envelope = EmailEnvelope(
        account_id=account_id, provider="qq", provider_message_id="m3-1", folder="INBOX",
        uidvalidity=1, uid=1, internet_message_id="<m3@example.test>",
        from_name="Alice", from_address="alice@example.test", subject="RFQ demo sensors",
        received_at="2026-07-23T08:00:00Z", text_body=body, raw_sha256="a" * 64,
        attachments=(AttachmentMeta("spec.pdf", "application/pdf", 123, "b" * 64),),
    )
    email_id, _ = repository.persist(envelope)
    repository.complete_extraction(
        email_id, pending_result(), extraction_mode="deterministic_fallback",
        extractor_version="email-rfq-rules-v1",
    )
    return EmailReviewService(repository, REVIEWER), repository, connection, email_id, account_id


def operator_change(path, value):
    return {
        "path": path, "value": value, "source_type": "operator_input",
        "reason_code": "phone_verified", "note": "Verified with the customer by phone",
    }


def complete_payload():
    return {"base_review_version": 0, "changes": [
        operator_change("customer.name", "Alice Buyer"),
        operator_change("customer.company", "Example Trading Ltd"),
        {"path": "customer.email", "value": "alice@example.test", "source_type": "header_evidence"},
        operator_change("country", "Germany"),
        operator_change("items[0].product", "demo sensors"),
        operator_change("items[0].specification", "standard demo specification"),
        operator_change("items[0].quantity.value", 500),
        operator_change("items[0].quantity.unit", "pcs"),
        operator_change("delivery_deadline.raw", "before 15 September 2026"),
        operator_change("delivery_deadline.normalized", "2026-09-15"),
        operator_change("trade_term.incoterm", "FOB"),
        operator_change("trade_term.named_place", "Shanghai"),
    ]}


def build_client(tmp_path: Path, service: EmailReviewService):
    channel = WebChannel(
        MessageBus(), conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"), email_admin_token=ADMIN_TOKEN,
        email_review_service=service,
    )
    channel._app = FastAPI(); channel._register_routes()
    return TestClient(channel._app)


def headers(**values):
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", **values}


def test_list_is_cursor_paginated_and_privacy_minimized():
    service, repository, _, email_id, _ = build_review()
    result = service.list_reviews(limit=1)
    assert result["items"][0]["email_id"] == email_id
    assert result["items"][0]["sender_masked"] == "a***@example.test"
    assert result["items"][0]["missing_count"] > 0
    assert result["items"][0]["agent_check"]["checker"] == "nanoclaw"
    assert result["items"][0]["agent_check"]["status"] == "business_input_required"
    serialized = json.dumps(result)
    assert "Please quote" not in serialized
    assert "alice@example.test" not in serialized
    assert "spec.pdf" not in serialized


def test_detail_is_protected_and_returns_etag_and_safe_attachment_metadata(tmp_path: Path):
    service, _, _, email_id, _ = build_review()
    with build_client(tmp_path, service) as client:
        assert client.get(f"/api/email/inbound/{email_id}").status_code == 401
        response = client.get(f"/api/email/inbound/{email_id}", headers=headers())
    assert response.status_code == 200
    assert response.headers["etag"] == f'"email-{email_id}-review-0"'
    assert response.json()["text_body"].startswith("Please quote")
    assert response.json()["attachments"][0]["filename"] == "spec.pdf"
    assert "content" not in response.json()["attachments"][0]
    assert response.json()["agent_check"]["pending_fields"]
    assert response.json()["agent_check"]["checked_field_count"] == 0


def test_preview_and_confirm_http_routes_complete_review_without_outbound_side_effect(tmp_path: Path):
    service, _, connection, email_id, _ = build_review()
    with build_client(tmp_path, service) as client:
        detail = client.get(f"/api/email/inbound/{email_id}", headers=headers())
        preview = client.post(
            f"/api/email/inbound/{email_id}/review-preview",
            headers=headers(), json=complete_payload(),
        )
        confirmed = client.post(
            f"/api/email/inbound/{email_id}/confirm",
            headers=headers(**{
                "Idempotency-Key": str(uuid.uuid4()),
                "If-Match": detail.headers["etag"],
            }),
            json=complete_payload(),
        )
    assert preview.status_code == 200 and preview.json()["confirmable"] is True
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert connection.execute(
        "SELECT reviewer_id FROM ops_email_review_revision"
    ).fetchone()[0] == REVIEWER
    assert connection.execute(
        "SELECT count(*) FROM sqlite_master WHERE name='ops_email_delivery'"
    ).fetchone()[0] == 0


def test_preview_recomputes_pending_and_does_not_write_revision():
    service, _, connection, email_id, _ = build_review()
    partial = {"base_review_version": 0, "changes": [operator_change("country", "Germany")]}
    result = service.preview(email_id, partial)
    assert result["confirmable"] is False
    assert "country" not in result["missing_fields"]
    assert "items[0].quantity" in result["missing_fields"]
    assert connection.execute("SELECT count(*) FROM ops_email_review_revision").fetchone()[0] == 0
    assert connection.execute("SELECT count(*) FROM ops_email_review_audit").fetchone()[0] == 0


def test_confirm_is_immutable_idempotent_minimal_and_quote_gated():
    service, repository, connection, email_id, _ = build_review()
    payload = complete_payload()
    key = str(uuid.uuid4())
    result = service.confirm(email_id, payload, idempotency_key=key,
                             if_match=f'"email-{email_id}-review-0"')
    replay = service.confirm(email_id, payload, idempotency_key=key,
                             if_match=f'"email-{email_id}-review-0"')
    assert result == replay
    assert result["status"] == "confirmed" and result["quote_eligible"] is True
    assert connection.execute("SELECT count(*) FROM ops_email_review_revision").fetchone()[0] == 1
    audit = dict(connection.execute("SELECT * FROM ops_email_review_audit ORDER BY audit_id DESC").fetchone())
    assert audit["changes_json"] == "[]"
    audit_dump = json.dumps(audit)
    assert "Alice Buyer" not in audit_dump
    assert "Verified with the customer" not in audit_dump
    snapshot = EmailReviewGate(repository).require_confirmed(
        email_id=email_id, review_id=result["review_id"], review_hash=result["review_hash"]
    )
    assert snapshot["missing_fields"] == []


def test_idempotency_version_pending_and_evidence_fail_closed():
    service, _, _, email_id, _ = build_review()
    with pytest.raises(EmailReviewServiceError, match="email_review_pending_fields"):
        service.confirm(
            email_id, {"base_review_version": 0, "changes": []},
            idempotency_key=str(uuid.uuid4()), if_match=f'"email-{email_id}-review-0"',
        )
    invalid = {"base_review_version": 0, "changes": [{
        "path": "country", "value": "Germany", "source_type": "email_evidence",
        "source_part": "body", "start": 0, "end": 6, "quote": "forged",
    }]}
    with pytest.raises(EmailReviewServiceError, match="email_review_invalid_evidence"):
        service.preview(email_id, invalid)
    key = str(uuid.uuid4())
    payload = complete_payload()
    service.confirm(email_id, payload, idempotency_key=key,
                    if_match=f'"email-{email_id}-review-0"')
    changed = complete_payload(); changed["changes"][0]["value"] = "Mallory"
    with pytest.raises(EmailReviewServiceError, match="email_review_idempotency_conflict"):
        service.confirm(email_id, changed, idempotency_key=key,
                        if_match=f'"email-{email_id}-review-0"')
    with pytest.raises(EmailReviewServiceError, match="email_review_version_conflict"):
        service.confirm(email_id, payload, idempotency_key=str(uuid.uuid4()),
                        if_match=f'"email-{email_id}-review-0"')


def test_reviewer_is_server_trusted_and_supersede_invalidates_gate(tmp_path: Path):
    service, repository, _, email_id, _ = build_review()
    no_reviewer = EmailReviewService(repository, "")
    with pytest.raises(EmailReviewServiceError, match="email_reviewer_not_configured"):
        no_reviewer.confirm(email_id, complete_payload(), idempotency_key=str(uuid.uuid4()),
                            if_match=f'"email-{email_id}-review-0"')
    with build_client(tmp_path, service) as client:
        injected = complete_payload(); injected["reviewer"] = "browser-admin"
        response = client.post(
            f"/api/email/inbound/{email_id}/confirm", headers=headers(
                **{"Idempotency-Key": str(uuid.uuid4()), "If-Match": f'"email-{email_id}-review-0"'}
            ), json=injected,
        )
    assert response.status_code == 400
    result = service.confirm(email_id, complete_payload(), idempotency_key=str(uuid.uuid4()),
                             if_match=f'"email-{email_id}-review-0"')
    gate = EmailReviewGate(repository)
    repository.supersede_review(email_id, "new extraction")
    with pytest.raises(EmailReviewServiceError, match="email_review_superseded"):
        gate.require_confirmed(email_id=email_id, review_id=result["review_id"], review_hash=result["review_hash"])
