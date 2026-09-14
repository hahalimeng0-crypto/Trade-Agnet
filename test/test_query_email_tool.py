import asyncio
import json
import sqlite3

from agent.business.email_repository import EmailRepository
from agent.business.rfq_extractor import pending_result
from agent.tools.query_email import QueryInboundEmailTool
from channels.email.contracts import EmailEnvelope


def test_agent_mail_tool_lists_and_returns_local_extraction_without_body():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    repository = EmailRepository(connection)
    envelope = EmailEnvelope(
        account_id="mailbox", provider="qq", provider_message_id="one", folder="INBOX",
        uidvalidity=1, uid=1, internet_message_id="<one@example.test>",
        from_name="Buyer", from_address="buyer@example.test", subject="RFQ sensors",
        received_at="2026-07-24T08:00:00Z", text_body="SECRET BODY: quote 20 sensors",
        raw_sha256="a" * 64,
    )
    email_id, _ = repository.persist(envelope, classification_code="email_trade_rfq_accepted")
    repository.complete_extraction(
        email_id, pending_result(), extraction_mode="deterministic_local",
        extractor_version="email-rfq-rules-v1",
    )
    tool = QueryInboundEmailTool(repository)

    listed = json.loads(asyncio.run(tool.execute(action="list", status="all", limit=10)))
    detail = json.loads(asyncio.run(tool.execute(action="get", email_id=email_id)))

    assert listed["items"][0]["email_id"] == email_id
    assert detail["extraction_mode"] == "deterministic_local"
    assert detail["body_in_agent_response"] is False
    assert "SECRET BODY" not in json.dumps(detail)
    assert detail["sender_masked"] == "b***@example.test"
