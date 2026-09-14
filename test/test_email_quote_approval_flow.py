import json
import sqlite3
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_delivery_repository import EmailDeliveryRepository
from agent.business.email_delivery_service import EmailDeliveryService
from agent.business.email_quote_workflow import EmailQuoteWorkflowService
from agent.business.email_repository import EmailRepository
from agent.business.email_review_service import EmailReviewService
from agent.workflow import WorkflowService
from bus import MessageBus
from channels.email.contracts import EmailEnvelope
from channels.email.delivery_worker import EmailDeliveryWorker
from channels.email.mock_smtp_sender import MockSmtpSender
from channels.web import WebChannel
from session.conversation import ConversationService


ADMIN_TOKEN = "quote-flow-admin"
REVIEWER = "business-reviewer"


def complete_extraction(product="USB-C Cable 1m"):
    specification = ("PD 100W USB 3.1 braided" if product == "USB-C Cable 1m"
                     else "uncatalogued quantum specification")
    return {
        "schema_version": "rfq-v2",
        "customer": {
            "name": {"value": "Test Buyer", "status": "extracted", "evidence": "Test Buyer"},
            "company": {"value": "Test Trading", "status": "extracted", "evidence": "Test Trading"},
            "email": {"value": "buyer@example.test", "status": "header_confirmed", "evidence": "From header"},
        },
        "country": {"value": "Germany", "status": "extracted", "evidence": "Germany"},
        "items": [{
            "product": {"value": product, "status": "extracted", "evidence": product},
            "specification": {"value": specification, "status": "extracted", "evidence": specification},
            "quantity": {"value": 500, "unit": "pcs", "status": "extracted", "evidence": "500 pcs"},
        }],
        "delivery_deadline": {
            "raw": "within 30 days", "normalized": "2026-08-31",
            "status": "extracted", "evidence": "within 30 days",
        },
        "trade_term": {
            "incoterm": "FOB", "named_place": "Shanghai", "version": "Incoterms 2020",
            "status": "extracted", "evidence": "FOB Shanghai",
        },
        "missing_fields": [], "warnings": [],
    }


def build_client(tmp_path: Path, product="USB-C Cable 1m"):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    emails = EmailRepository(connection)
    accounts = EmailAccountRepository(connection)
    account_id = str(uuid.uuid4())
    accounts.create({
        "account_id": account_id, "display_name": "Sales", "provider": "qq",
        "address": "sales@qq.com", "secret_ref": f"email-account/{account_id}", "folder": "INBOX",
        "inbound_enabled": True, "outbound_enabled": True, "poll_seconds": 60,
        "sender_name": "NanoClaw Sales", "allowed_senders": [],
        "allowed_recipients": ["buyer@example.test"], "status": "healthy",
    }, actor="test")
    workflow = EmailQuoteWorkflowService(connection)
    connection.execute("""INSERT INTO products(
      sku,name_cn,name_en,category,specification,unit,moq,price_usd,inventory,lead_time_days,active)
      VALUES('CB-3001','USB-C 数据线','USB-C Cable 1m','electronics',
      'PD 100W, USB 3.1, braided','pcs',500,1.8,20000,10,1)""")
    envelope = EmailEnvelope(
        account_id=account_id, provider="qq", provider_message_id="flow-one", folder="INBOX",
        uidvalidity=1, uid=1, internet_message_id="<flow@example.test>",
        from_name="Test Buyer", from_address="buyer@example.test", subject="RFQ USB-C Cable 1m",
        received_at="2026-07-24T08:00:00Z", text_body="De-identified RFQ fixture",
        raw_sha256="a" * 64,
    )
    email_id, _ = emails.persist(envelope, classification_code="email_trade_rfq_accepted")
    emails.complete_extraction(
        email_id, complete_extraction(product), extraction_mode="deterministic_local",
        extractor_version="email-rfq-rules-v1",
    )
    review = EmailReviewService(emails, REVIEWER)
    delivery_repository = EmailDeliveryRepository(connection)
    channel = WebChannel(
        MessageBus(), conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"), email_admin_token=ADMIN_TOKEN,
        email_review_service=review, email_delivery_service=EmailDeliveryService(delivery_repository),
        email_quote_workflow_service=workflow, email_reviewer_id=REVIEWER,
    )
    channel._app = FastAPI(); channel._register_routes()
    return TestClient(channel._app), connection, delivery_repository, account_id, email_id


def headers(**values):
    return {"Authorization": f"Bearer {ADMIN_TOKEN}", **values}


def test_confirm_quote_approve_queue_deliver_and_show_in_both_dashboards(tmp_path: Path):
    client, connection, deliveries, account_id, email_id = build_client(tmp_path)
    with client:
        detail = client.get(f"/api/email/inbound/{email_id}", headers=headers())
        assert detail.json()["agent_check"]["status"] == "ready_for_business_confirmation"
        assert detail.json()["agent_check"]["pending_fields"] == []
        confirmed = client.post(
            f"/api/email/inbound/{email_id}/confirm",
            headers=headers(**{"Idempotency-Key": str(uuid.uuid4()), "If-Match": detail.headers["etag"]}),
            json={"base_review_version": 0, "changes": []},
        )
        assert confirmed.status_code == 200
        work = confirmed.json()["quote_workflow"]
        assert work["work_status"] == "pending_approval"
        assert work["total_usd"] > 0 and work["approval_key"]

        mailbox = client.get("/api/email/sendable-quotes", headers=headers()).json()["items"]
        assert any(item.get("approval_key") == work["approval_key"] for item in mailbox)

        approved = client.post(
            f"/api/email/approvals/{work['approval_key']}/decision", headers=headers(),
            json={"action": "approve"},
        )
        assert approved.status_code == 200 and approved.json()["work_status"] == "approved"
        approved_item = next(
            item for item in client.get("/api/email/sendable-quotes", headers=headers()).json()["items"]
            if item.get("approval_key") == work["approval_key"]
        )
        assert approved_item["work_status"] == "approved"

        queued = client.post("/api/email/deliveries", headers=headers(), json={
            "account_id": account_id, "quote_id": work["quote_id"],
            "quote_version": work["quote_version"], "approval_key": work["approval_key"],
            "recipient": "buyer@example.test",
        })
        assert queued.status_code == 200 and queued.json()["status"] == "pending"
        accepted = EmailDeliveryWorker(
            deliveries, MockSmtpSender(), worker_id="quote-flow-worker"
        ).run_once()
        assert accepted["status"] == "accepted"

        delivery_items = client.get("/api/email/deliveries", headers=headers()).json()["items"]
        metrics = client.get("/api/email/metrics", headers=headers()).json()
        assert delivery_items[0]["status"] == "accepted"
        assert metrics["accepted_today"] == 1
        assert metrics["active_deliveries"] == 0
        assert connection.execute(
            "SELECT status FROM quotes WHERE id=?", (work["quote_id"],)
        ).fetchone()[0] == "approved"


def test_unknown_product_is_visible_but_quote_and_approval_are_blocked(tmp_path: Path):
    client, _, _, _, email_id = build_client(tmp_path, product="Uncatalogued Quantum Widget")
    with client:
        detail = client.get(f"/api/email/inbound/{email_id}", headers=headers())
        confirmed = client.post(
            f"/api/email/inbound/{email_id}/confirm",
            headers=headers(**{"Idempotency-Key": str(uuid.uuid4()), "If-Match": detail.headers["etag"]}),
            json={"base_review_version": 0, "changes": []},
        )
        work = confirmed.json()["quote_workflow"]
        assert work == {
            "email_id": email_id, "work_status": "quote_blocked",
            "error_code": "email_quote_product_match_required",
        }
        mailbox = client.get("/api/email/sendable-quotes", headers=headers()).json()["items"]
        assert any(item["email_id"] == email_id and item["work_status"] == "quote_blocked" for item in mailbox)
        assert client.post(
            "/api/email/approvals/1/decision", headers=headers(), json={"action": "approve"}
        ).status_code == 404


def test_unbound_legacy_approval_is_blocked_instead_of_rendered_as_approvable(tmp_path: Path):
    client, connection, _, _, email_id = build_client(tmp_path)
    with client:
        detail = client.get(f"/api/email/inbound/{email_id}", headers=headers())
        confirmed = client.post(
            f"/api/email/inbound/{email_id}/confirm",
            headers=headers(**{"Idempotency-Key": str(uuid.uuid4()), "If-Match": detail.headers["etag"]}),
            json={"base_review_version": 0, "changes": []},
        ).json()
        approval_key = confirmed["quote_workflow"]["approval_key"]
        connection.execute("UPDATE approval_records SET content_hash=NULL WHERE id=?", (approval_key,))
        connection.commit()

        item = next(
            item for item in client.get("/api/email/sendable-quotes", headers=headers()).json()["items"]
            if item.get("approval_key") == approval_key
        )
        assert item["work_status"] == "quote_blocked"
        assert item["error_code"] == "email_approval_regeneration_required"
        rejected = client.post(
            f"/api/email/approvals/{approval_key}/decision", headers=headers(), json={"action": "approve"}
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "email_approval_quote_stale"


def test_stale_approval_can_be_regenerated_and_then_approved(tmp_path: Path):
    client, connection, _, _, email_id = build_client(tmp_path)
    with client:
        detail = client.get(f"/api/email/inbound/{email_id}", headers=headers())
        confirmed = client.post(
            f"/api/email/inbound/{email_id}/confirm",
            headers=headers(**{"Idempotency-Key": str(uuid.uuid4()), "If-Match": detail.headers["etag"]}),
            json={"base_review_version": 0, "changes": []},
        ).json()["quote_workflow"]
        old_key = confirmed["approval_key"]
        connection.execute("UPDATE approval_records SET content_hash=NULL WHERE id=?", (old_key,))
        connection.commit()

        regenerated = client.post(
            f"/api/email/quotes/{confirmed['quote_id']}/approval-regenerate", headers=headers()
        )
        assert regenerated.status_code == 200
        work = regenerated.json()
        assert work["work_status"] == "pending_approval"
        assert work["approval_key"] != old_key
        assert connection.execute(
            "SELECT status FROM approval_records WHERE id=?", (old_key,)
        ).fetchone()[0] == "superseded"
        new_approval = connection.execute(
            "SELECT status,content_hash FROM approval_records WHERE id=?", (work["approval_key"],)
        ).fetchone()
        assert new_approval[0] == "pending" and new_approval[1]

        approved = client.post(
            f"/api/email/approvals/{work['approval_key']}/decision",
            headers=headers(), json={"action": "approve"},
        )
        assert approved.status_code == 200
        assert approved.json()["work_status"] == "approved"
