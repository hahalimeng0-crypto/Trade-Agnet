import asyncio
import json
import sqlite3
import os
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agent.business.email_ingestion import EmailIngestionService
from agent.business.email_config import load_email_config
from agent.business.email_repository import EmailRepository
from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_secret_store import MemoryEmailSecretStore
from agent.business.email_trade_classifier import classify_trade_rfq_email
from agent.business.managed_email_ingestion import ManagedEmailIngestionRuntime
from agent.business.email_config import EmailIngestionConfig
from agent.business.email_notification import QQNotificationDispatcher, build_qq_rfq_summary
from agent.business.rfq_extractor import (
    DETERMINISTIC_RULE_VERSION,
    _parse_json_object,
    deterministic_extract_rfq_fields,
    pending_result,
    validate_rfq_v2,
)
from channels.email.mime_parser import EmailParseLimits, EmailSecurityError, parse_email
from channels.email.imap_source import ImapEmailSource, NETEASE_CLIENT_ID, _imap_error_code
from channels.email.mock_source import MockEmailSource


FIXTURES = Path(__file__).parent / "fixtures"


class MimeParserTests(unittest.TestCase):
    def test_plain_html_and_attachment_are_bounded(self):
        source = MockEmailSource(FIXTURES)
        rows = source.fetch_after(0)
        self.assertEqual(3, len(rows))
        html = next(row for row in rows if row.internet_message_id == "<rfq-002@example.invalid>")
        self.assertIn("Please quote 20 kg copper wire.", html.text_body)
        self.assertNotIn("alert", html.text_body)
        attachment = next(row for row in rows if row.attachments)
        self.assertEqual("payload.exe", attachment.attachments[0].filename)
        self.assertEqual("not_processed", attachment.attachments[0].processing_status)
        self.assertNotIn("TVq", attachment.text_body)

    def test_size_limit_quarantines_before_parse(self):
        with self.assertRaisesRegex(EmailSecurityError, "message_too_large"):
            parse_email(b"x" * 20, account_id="a", provider="mock", folder="f", uidvalidity=1, uid=1,
                        limits=EmailParseLimits(max_message_bytes=10))

    def test_unsafe_login_has_stable_safe_error_code(self):
        self.assertEqual("imap_select_unsafe_login",
                         _imap_error_code("select", [b"EXAMINE Unsafe Login. Please contact support"]))

    def test_netease_id_handshake_contains_no_credentials(self):
        class FakeClient:
            def __init__(self):
                self.call = None

            def _simple_command(self, command, value):
                self.call = (command, value)
                return "OK", [b"ID completed"]

        client = FakeClient()
        ImapEmailSource._send_netease_client_id(client)
        self.assertEqual(("ID", NETEASE_CLIENT_ID), client.call)
        self.assertNotIn("@", NETEASE_CLIENT_ID)
        self.assertNotIn("auth", NETEASE_CLIENT_ID.lower())


class EmailConfigTests(unittest.TestCase):
    def test_loads_email_values_from_project_env(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "NANOCLAW_EMAIL_ENABLED=true\n"
                "NANOCLAW_EMAIL_PROVIDER=netease_163\n"
                "NANOCLAW_EMAIL_ACCOUNT_ID=netease-test\n"
                "NANOCLAW_EMAIL_ADDRESS=test@example.invalid\n"
                "NANOCLAW_EMAIL_AUTH_CODE=simulated-auth-code\n",
                encoding="utf-8",
            )
            with patch("agent.business.email_config._PROJECT_ENV_PATH", env_path), patch.dict(os.environ, {}, clear=True):
                config = load_email_config()
        self.assertTrue(config.enabled)
        self.assertEqual("netease_163", config.provider)
        self.assertEqual("netease-test", config.account_id)

    def test_process_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("NANOCLAW_EMAIL_PROVIDER=netease_163\n", encoding="utf-8")
            with patch("agent.business.email_config._PROJECT_ENV_PATH", env_path), patch.dict(
                os.environ, {"NANOCLAW_EMAIL_PROVIDER": "netease_126"}, clear=True
            ):
                config = load_email_config()
        self.assertEqual("netease_126", config.provider)


class RfqValidationTests(unittest.TestCase):
    def test_fenced_json_is_parsed_without_relaxing_object_contract(self):
        self.assertEqual({"ok": True}, _parse_json_object('```json\n{"ok": true}\n```'))
        with self.assertRaises(ValueError):
            _parse_json_object("not json")

    def test_missing_and_bad_evidence_are_pending(self):
        data = pending_result()
        data["country"] = {"value": "Germany", "status": "extracted", "evidence": "not in body"}
        result = validate_rfq_v2(data, subject="RFQ", body="Please quote widgets", from_address="buyer@example.invalid")
        self.assertEqual("pending_confirmation", result["country"]["status"])
        self.assertIsNone(result["country"]["value"])
        self.assertEqual("header_confirmed", result["customer"]["email"]["status"])

    def test_unitless_quantity_is_pending(self):
        data = pending_result()
        data["items"][0]["quantity"] = {"value": 100, "unit": None, "status": "extracted", "evidence": "100"}
        result = validate_rfq_v2(data, subject="", body="Need 100 widgets")
        self.assertEqual("pending_confirmation", result["items"][0]["quantity"]["status"])

    def test_unknown_model_status_is_safely_downgraded(self):
        data = pending_result()
        data["customer"]["name"] = {"value": "Invented", "status": "not_found", "evidence": ""}
        result = validate_rfq_v2(data, subject="", body="")
        self.assertEqual("pending_confirmation", result["customer"]["name"]["status"])
        self.assertIsNone(result["customer"]["name"]["value"])

    def test_unknown_status_with_exact_evidence_is_safely_extracted(self):
        data = pending_result()
        data["country"] = {"value": "Germany", "status": "explicit", "evidence": "Germany"}
        result = validate_rfq_v2(data, subject="", body="Ship to Germany")
        self.assertEqual("extracted", result["country"]["status"])
        self.assertEqual("Germany", result["country"]["value"])
        self.assertNotIn("country", result["missing_fields"])

    def test_missing_fields_are_recomputed_after_validation(self):
        data = pending_result()
        data["missing_fields"] = []
        result = validate_rfq_v2(data, subject="", body="")
        self.assertIn("customer.name", result["missing_fields"])
        self.assertIn("items[0].quantity", result["missing_fields"])

    def test_deterministic_fallback_extracts_only_exact_evidence(self):
        body = ("Please quote 1,000 pcs Bluetooth speakers, black, IPX7. "
                "Delivery to Hamburg, Germany before 15 September. FOB Shenzhen.")
        result = deterministic_extract_rfq_fields(
            body, {"subject": "RFQ", "from_address": "buyer@example.invalid"})
        self.assertEqual("Bluetooth speakers", result["items"][0]["product"]["value"])
        self.assertEqual(1000, result["items"][0]["quantity"]["value"])
        self.assertEqual("Germany", result["country"]["value"])
        self.assertEqual("FOB", result["trade_term"]["incoterm"])
        self.assertIn(f"deterministic_fallback:{DETERMINISTIC_RULE_VERSION}", result["warnings"])
        source = "RFQ\n" + body
        for node in (result["country"], result["items"][0]["product"],
                     result["items"][0]["specification"], result["items"][0]["quantity"],
                     result["delivery_deadline"], result["trade_term"]):
            if node["status"] == "extracted":
                self.assertIn(node["evidence"], source)

    def test_product_measurement_is_not_mistaken_for_second_delivery_date(self):
        body = (
            "Hello,\n\n"
            "Please provide a quotation for 500 pcs USB-C data cables, "
            "1 meter, USB 3.0, black.\n"
            "Destination country: Germany.\n"
            "Required delivery: before 15 September 2026.\n"
            "Trade term: FOB Shenzhen, Incoterms 2020.\n\n"
            "Best regards,\nMichael Brown\nBerlin Tech GmbH"
        )
        result = deterministic_extract_rfq_fields(
            body, {"subject": "RFQ for USB-C Data Cables", "from_address": "buyer@example.invalid"}
        )
        self.assertEqual([], result["missing_fields"])
        self.assertEqual("before 15 September 2026", result["delivery_deadline"]["raw"])
        self.assertEqual("1 meter, USB 3.0, black", result["items"][0]["specification"]["value"])

    def test_deterministic_fallback_keeps_ambiguous_or_absent_facts_pending(self):
        result = deterministic_extract_rfq_fields(
            "Please quote 500-800 pcs smart sensors. MOQ 100 pcs. Contact us soon.",
            {"subject": "Question", "from_address": "buyer@example.invalid"})
        self.assertEqual("pending_confirmation", result["items"][0]["quantity"]["status"])
        self.assertEqual("pending_confirmation", result["country"]["status"])
        self.assertIn("items[0].quantity", result["missing_fields"])
        self.assertIn("country", result["missing_fields"])


class RepositoryAndServiceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.repo = EmailRepository(self.connection)
        self.envelope = MockEmailSource(FIXTURES).fetch_after(0)[0]

    def test_duplicate_delivery_extracts_once_and_advances_cursor(self):
        calls = 0

        async def extractor(body, context):
            nonlocal calls
            calls += 1
            return pending_result()

        service = EmailIngestionService(self.repo, extractor)
        first = asyncio.run(service.ingest(self.envelope))
        second = asyncio.run(service.ingest(self.envelope))
        self.assertEqual("needs_review", first["status"])
        self.assertFalse(second["created"])
        self.assertEqual(1, calls)
        self.assertEqual((1, self.envelope.uid), self.repo.get_cursor(self.envelope.account_id, self.envelope.folder))

    def test_trade_gate_accepts_rfq_keeps_regular_mail_and_protects_security_body(self):
        trade = replace(
            self.envelope, uid=101, internet_message_id="<trade-gate@example.invalid>",
            from_address="buyer@example.invalid", subject="RFQ for control boards",
            text_body="Please quote 500 pcs control boards, FOB Shenzhen.", raw_sha256="1" * 64,
        )
        security = replace(
            self.envelope, uid=102, internet_message_id="<security-gate@example.invalid>",
            from_address="service@example.invalid", subject="Security notice",
            text_body="Your verification code is 123456. Do not share it.", raw_sha256="2" * 64,
        )
        regular = replace(
            self.envelope, uid=103, internet_message_id="<regular-gate@example.invalid>",
            from_address="buyer@example.invalid", subject="Project update",
            text_body="The sample review meeting is scheduled for Friday.", raw_sha256="3" * 64,
        )
        self.assertTrue(classify_trade_rfq_email(trade).accepted)
        self.assertFalse(classify_trade_rfq_email(security).accepted)
        calls = 0

        async def extractor(body, context):
            nonlocal calls
            calls += 1
            return pending_result()

        service = EmailIngestionService(
            self.repo, extractor, message_filter=classify_trade_rfq_email,
            extractor_mode="deterministic_local", extractor_version=DETERMINISTIC_RULE_VERSION,
        )
        accepted = asyncio.run(service.ingest(trade))
        ignored = asyncio.run(service.ingest(security))
        received = asyncio.run(service.ingest(regular))
        self.assertEqual("needs_review", accepted["status"])
        self.assertEqual("ignored_non_trade", ignored["status"])
        self.assertEqual("received", received["status"])
        self.assertEqual(1, calls)
        self.assertEqual(1, len(self.repo.list_skip_receipts()))
        self.assertEqual("", self.repo.get(ignored["email_id"])["text_body"])
        self.assertIn("scheduled for Friday", self.repo.get(received["email_id"])["text_body"])
        statuses = [row["status"] for row in self.repo.list_inbound_reviews(status="all", limit=10)[0]]
        self.assertEqual(["received", "ignored_non_trade", "needs_review"], statuses)
        dump = "\n".join(self.connection.iterdump())
        self.assertNotIn("verification code", dump)
        self.assertNotIn("123456", dump)
        self.assertEqual((1, 103), self.repo.get_cursor(security.account_id, security.folder))

    def test_sender_allowlist_is_an_exact_pre_parse_gate(self):
        envelope = replace(
            self.envelope, uid=103, from_address="unknown@example.invalid",
            subject="RFQ", text_body="Please quote 10 pcs sensors.", raw_sha256="3" * 64,
        )
        result = classify_trade_rfq_email(
            envelope, allowed_senders=("approved@example.invalid",)
        )
        self.assertFalse(result.accepted)
        self.assertEqual("email_trade_sender_not_allowed", result.code)


    def test_lease_blocks_concurrent_owner(self):
        email_id, _ = self.repo.persist(self.envelope)
        self.assertTrue(self.repo.acquire(email_id, "one"))
        self.assertFalse(self.repo.acquire(email_id, "two"))

    def test_review_confirmation_is_audited(self):
        email_id, _ = self.repo.persist(self.envelope)
        result = pending_result()
        def resolve(value):
            if isinstance(value, dict):
                if value.get("status") == "pending_confirmation":
                    value["status"] = "human_confirmed"
                for child in value.values():
                    resolve(child)
            elif isinstance(value, list):
                for child in value:
                    resolve(child)
        resolve(result)
        self.repo.complete_extraction(email_id, result)
        self.repo.confirm(email_id, "operator-1")
        self.assertEqual("confirmed", self.repo.get(email_id)["status"])
        count = self.connection.execute("SELECT COUNT(*) FROM ops_email_review_audit").fetchone()[0]
        self.assertEqual(1, count)

    def test_pending_fields_cannot_be_confirmed(self):
        email_id, _ = self.repo.persist(self.envelope)
        self.repo.complete_extraction(email_id, pending_result())
        with self.assertRaisesRegex(ValueError, "pending fields"):
            self.repo.confirm(email_id, "operator-1")

    def test_uidvalidity_change_stops_cursor(self):
        self.repo.advance_cursor("a", "INBOX", 1, 5)
        with self.assertRaisesRegex(RuntimeError, "uidvalidity_changed"):
            self.repo.advance_cursor("a", "INBOX", 2, 1)

    def test_extraction_creates_one_privacy_minimized_qq_outbox(self):
        async def extractor(body, context):
            result = pending_result()
            result["customer"]["company"] = {"value": "Example Trading", "status": "extracted",
                                               "evidence": "Example Trading"}
            return result

        service = EmailIngestionService(self.repo, extractor, qq_target_id="qq-target", qq_target_type="group")
        asyncio.run(service.ingest(self.envelope))
        asyncio.run(service.ingest(self.envelope))
        rows = self.repo.pending_notifications()
        self.assertEqual(1, len(rows))
        self.assertEqual("group", rows[0]["target_type"])
        self.assertNotIn(self.envelope.from_address, rows[0]["content"])
        self.assertNotIn(self.envelope.text_body, rows[0]["content"])

    def test_qq_dispatch_marks_success_and_failure(self):
        email_id, _ = self.repo.persist(self.envelope)
        result = pending_result()
        self.repo.complete_extraction_with_notification(email_id, result, target_id="target", target_type="c2c",
                                                        content=build_qq_rfq_summary(email_id, result))
        sent_messages = []

        async def sender(message):
            sent_messages.append(message)

        report = asyncio.run(QQNotificationDispatcher(self.repo, sender).dispatch_pending())
        self.assertEqual({"sent": 1, "failed": 0}, report)
        self.assertEqual("c2c", sent_messages[0].target_type)
        status = self.connection.execute("SELECT status FROM ops_email_notification_outbox").fetchone()[0]
        self.assertEqual("sent", status)

        envelope2 = MockEmailSource(FIXTURES).fetch_after(1, 1)[0]
        email_id2, _ = self.repo.persist(envelope2)
        self.repo.complete_extraction_with_notification(email_id2, result, target_id="target", target_type="c2c",
                                                        content="safe")

        async def failing_sender(message):
            raise RuntimeError("simulated")

        report = asyncio.run(QQNotificationDispatcher(self.repo, failing_sender).dispatch_pending())
        self.assertEqual({"sent": 0, "failed": 1}, report)
        status = self.connection.execute("SELECT status FROM ops_email_notification_outbox WHERE email_id=?",
                                         (email_id2,)).fetchone()[0]
        self.assertEqual("retry_wait", status)

    def test_extraction_timeout_enters_retry_and_can_recover(self):
        async def slow_extractor(body, context):
            await asyncio.sleep(0.05)
            return pending_result()

        service = EmailIngestionService(self.repo, slow_extractor, extraction_timeout_seconds=0.001)
        result = asyncio.run(service.ingest(self.envelope))
        self.assertEqual("retry_wait", result["status"])
        self.assertEqual("TimeoutError", result["error_code"])

        self.connection.execute("UPDATE ops_inbound_email SET next_retry_at=NULL")
        self.connection.commit()

        async def fast_extractor(body, context):
            return pending_result()

        recovered = EmailIngestionService(self.repo, fast_extractor)
        results = asyncio.run(recovered.recover_pending())
        self.assertEqual("needs_review", results[0]["status"])
        self.assertEqual("needs_review", self.repo.get(1)["status"])

    def test_default_dual_model_failure_uses_deterministic_fallback(self):
        import agent.business.email_ingestion as ingestion_module

        full = AsyncMock(side_effect=TimeoutError())
        compact = AsyncMock(side_effect=TimeoutError())
        with patch.object(ingestion_module, "extract_rfq_fields", full), patch.object(
            ingestion_module, "extract_rfq_fields_compact", compact
        ):
            service = EmailIngestionService(self.repo)
            service.extractor = full
            result = asyncio.run(service.ingest(self.envelope))
        self.assertEqual("needs_review", result["status"])
        self.assertEqual("deterministic_fallback", result["extraction_mode"])
        row = self.repo.get(result["email_id"])
        self.assertEqual("deterministic_fallback", row["extraction_mode"])
        self.assertEqual(DETERMINISTIC_RULE_VERSION, row["extractor_version"])
        extraction = json.loads(row["extraction_json"])
        self.assertEqual(extraction["missing_fields"], [
            path for path in extraction["missing_fields"]
        ])

    def test_contract_error_then_compact_success_does_not_trigger_deterministic_fallback(self):
        import agent.business.email_ingestion as ingestion_module
        from agent.business.rfq_extractor import RfqValidationError

        full = AsyncMock(side_effect=RfqValidationError("invalid model contract"))
        compact = AsyncMock(return_value=pending_result())
        with patch.object(ingestion_module, "extract_rfq_fields", full), patch.object(
            ingestion_module, "extract_rfq_fields_compact", compact
        ), patch.object(ingestion_module, "deterministic_extract_rfq_fields") as deterministic:
            service = EmailIngestionService(self.repo)
            service.extractor = full
            result = asyncio.run(service.ingest(self.envelope))
        self.assertEqual("llm_compact", result["extraction_mode"])
        deterministic.assert_not_called()

    def test_legacy_outbox_schema_migrates_without_losing_sent_notice(self):
        connection = sqlite3.connect(":memory:")
        connection.executescript("""
          CREATE TABLE ops_email_notification_outbox(
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT, email_id INTEGER NOT NULL,
            channel TEXT NOT NULL, target_id TEXT NOT NULL, target_type TEXT NOT NULL,
            content TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TEXT, last_error_code TEXT, created_at TEXT NOT NULL, sent_at TEXT,
            UNIQUE(email_id,channel,target_id,target_type));
          INSERT INTO ops_email_notification_outbox(
            email_id,channel,target_id,target_type,content,status,created_at)
          VALUES(1,'qq','target','c2c','safe-old','sent','2026-07-22T00:00:00Z');
        """)
        EmailRepository(connection)
        row = connection.execute("""SELECT notification_version,content,status
          FROM ops_email_notification_outbox""").fetchone()
        self.assertEqual((1, "safe-old", "sent"), tuple(row))

    def test_custom_validator_error_does_not_use_default_compact_fallback(self):
        async def invalid(body, context):
            from agent.business.rfq_extractor import RfqValidationError
            raise RfqValidationError("simulated")

        service = EmailIngestionService(self.repo, invalid, extraction_timeout_seconds=1)
        result = asyncio.run(service.ingest(self.envelope))
        self.assertEqual("retry_wait", result["status"])
        self.assertEqual("RfqValidationError", result["error_code"])

    def test_interrupted_extraction_can_be_released_safely(self):
        email_id, _ = self.repo.persist(self.envelope)
        self.assertTrue(self.repo.acquire(email_id, "stopped-worker"))
        self.assertTrue(self.repo.release_extraction_for_retry(email_id))
        self.assertEqual("retry_wait", self.repo.get(email_id)["status"])
        self.assertFalse(self.repo.release_extraction_for_retry(email_id))

    def test_failed_extraction_requires_explicit_reopen(self):
        email_id, _ = self.repo.persist(self.envelope)
        self.connection.execute("UPDATE ops_inbound_email SET status='failed',attempt_count=3 WHERE email_id=?", (email_id,))
        self.connection.commit()
        self.assertTrue(self.repo.reopen_failed_extraction(email_id))
        row = self.repo.get(email_id)
        self.assertEqual("retry_wait", row["status"])
        self.assertEqual(0, row["attempt_count"])
        self.assertFalse(self.repo.reopen_failed_extraction(email_id))

    def test_final_extraction_failure_creates_privacy_safe_alert(self):
        async def failing(body, context):
            raise TimeoutError()

        service = EmailIngestionService(self.repo, failing, qq_target_id="target", extraction_timeout_seconds=1)
        result = asyncio.run(service.ingest(self.envelope))
        for _ in range(2):
            if result["status"] == "retry_wait":
                self.connection.execute("UPDATE ops_inbound_email SET next_retry_at=NULL")
                self.connection.commit()
            result = asyncio.run(service.process_stored(1))
        self.assertEqual("failed", result["status"])
        rows = self.repo.pending_notifications()
        self.assertEqual(1, len(rows))
        self.assertIn("解析失败", rows[0]["content"])
        self.assertNotIn(self.envelope.from_address, rows[0]["content"])
        self.assertNotIn(self.envelope.text_body, rows[0]["content"])

    def test_corrected_sent_summary_creates_new_notification_version(self):
        email_id, _ = self.repo.persist(self.envelope)
        result = pending_result()
        first = self.repo.complete_extraction_with_notification(
            email_id, result, target_id="target", target_type="c2c", content="safe-v1")
        self.repo.mark_notification_sent(first)
        self.assertTrue(self.repo.reopen_review_for_extraction(email_id))
        self.assertTrue(self.repo.acquire(email_id, "worker"))
        second = self.repo.complete_extraction_with_notification(
            email_id, result, target_id="target", target_type="c2c", content="safe-v2",
            extraction_mode="deterministic_fallback", extractor_version=DETERMINISTIC_RULE_VERSION)
        self.assertNotEqual(first, second)
        rows = self.connection.execute("""SELECT notification_version,status,content
          FROM ops_email_notification_outbox ORDER BY notification_version""").fetchall()
        self.assertEqual([(1, "sent", "safe-v1"), (2, "pending", "safe-v2")], [tuple(row) for row in rows])

class ManagedAccountRuntimeTests(unittest.TestCase):
    def test_polls_only_healthy_inbound_workspace_accounts_with_local_extractor(self):
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        accounts = EmailAccountRepository(connection)
        emails = EmailRepository(connection)
        secrets = MemoryEmailSecretStore()
        account_id = str(uuid.uuid4())
        secret_ref = f"email-account/{account_id}"
        accounts.create({
            "account_id": account_id, "display_name": "Managed", "provider": "qq",
            "address": "sales@qq.com", "secret_ref": secret_ref, "folder": "INBOX",
            "inbound_enabled": True, "outbound_enabled": False, "poll_seconds": 30,
            "sender_name": "Sales", "allowed_senders": [], "allowed_recipients": [],
            "status": "healthy",
        }, actor="test")
        secrets.set(secret_ref, "test-auth-code")
        envelope = replace(
            MockEmailSource(FIXTURES).fetch_after(0)[0], account_id=account_id,
            provider="qq", folder="INBOX", uid=1, from_address="buyer@example.invalid",
            subject="Request for quotation - sensors",
            text_body="Please quote 250 pcs demo sensors, DAP Hamburg.", raw_sha256="4" * 64,
        )

        class Source:
            def __init__(self, settings, limits):
                self.settings = settings

            def fetch_after(self, last_uid, limit=50):
                return [envelope] if last_uid < 1 else []

        now = [100.0]
        runtime = ManagedEmailIngestionRuntime(
            EmailIngestionConfig(managed_accounts_enabled=True),
            account_repository=accounts, email_repository=emails, secret_store=secrets,
            source_factory=Source, clock=lambda: now[0],
        )
        first = asyncio.run(runtime.poll_due())
        second = asyncio.run(runtime.poll_due())
        self.assertEqual("needs_review", first[0]["messages"][0]["status"])
        self.assertEqual("deterministic_local", emails.get(1)["extraction_mode"])
        self.assertEqual([], second)

    def test_validating_managed_account_recovers_to_healthy_after_poll(self):
        connection = sqlite3.connect(":memory:", check_same_thread=False)
        connection.row_factory = sqlite3.Row
        accounts = EmailAccountRepository(connection)
        emails = EmailRepository(connection)
        secrets = MemoryEmailSecretStore()
        account_id = str(uuid.uuid4())
        secret_ref = f"email-account/{account_id}"
        accounts.create({
            "account_id": account_id, "display_name": "Recovering", "provider": "qq",
            "address": "sales@qq.com", "secret_ref": secret_ref, "folder": "INBOX",
            "inbound_enabled": True, "outbound_enabled": False, "poll_seconds": 30,
            "sender_name": "Sales", "allowed_senders": [], "allowed_recipients": [],
            "status": "validating",
        }, actor="test")
        secrets.set(secret_ref, "test-auth-code")

        class EmptySource:
            def __init__(self, settings, limits):
                pass

            def fetch_after(self, last_uid, limit=50):
                return []

        runtime = ManagedEmailIngestionRuntime(
            EmailIngestionConfig(managed_accounts_enabled=True),
            account_repository=accounts, email_repository=emails, secret_store=secrets,
            source_factory=EmptySource,
        )
        result = asyncio.run(runtime.poll_due())
        self.assertEqual("polled", result[0]["status"])
        self.assertEqual("healthy", accounts.get(account_id)["status"])


if __name__ == "__main__":
    unittest.main()
