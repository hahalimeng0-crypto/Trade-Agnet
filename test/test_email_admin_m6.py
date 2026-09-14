import inspect
import os
import sqlite3
from pathlib import Path

import pytest

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_delivery_repository import EmailDeliveryRepository
from agent.business.email_m5_acceptance import run_email_m5_acceptance
from agent.business.mysql_email_account_repository import MySQLEmailAccountRepository
from agent.business.mysql_email_delivery_repository import MySQLEmailDeliveryRepository
from agent.business.email_mysql_migration import _statements


def public_methods(cls):
    return {
        name for name, value in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_") and name not in {"init_schema", "verify_schema", "tx"}
    }


def test_mysql_repositories_cover_sqlite_runtime_contracts():
    assert public_methods(EmailAccountRepository) <= public_methods(MySQLEmailAccountRepository)
    assert public_methods(EmailDeliveryRepository) <= public_methods(MySQLEmailDeliveryRepository)


def test_mysql_delivery_migration_and_rollback_are_complete_and_ordered():
    root = Path(__file__).resolve().parents[1]
    migration = (root / "agent/business/migrations/004_email_delivery.mysql.sql").read_text(encoding="utf-8")
    rollback = (root / "agent/business/migrations/004_email_delivery.rollback.mysql.sql").read_text(encoding="utf-8")
    for marker in (
        "CREATE TABLE IF NOT EXISTS ops_email_delivery",
        "UNIQUE KEY uk_email_delivery_idempotency",
        "KEY ix_email_delivery_due",
        "content_redacted_at",
        "outcome_unknown",
        "FOREIGN KEY(account_id)",
        "FOREIGN KEY(approval_key)",
    ):
        assert marker in migration
    assert rollback.index("DROP TABLE IF EXISTS ops_email_delivery_audit") < rollback.index(
        "DROP TABLE IF EXISTS ops_email_delivery;"
    )
    assert len(_statements(root / "agent/business/migrations/004_email_delivery.mysql.sql")) == 2
    assert len(_statements(root / "agent/business/migrations/004_email_delivery.rollback.mysql.sql")) == 2


def test_mysql_account_decoder_matches_sqlite_safe_shape():
    decoded = MySQLEmailAccountRepository._decode({
        "account_id": "00000000-0000-0000-0000-000000000001",
        "inbound_enabled": 1, "outbound_enabled": 0,
        "allowed_senders_json": '["sender@example.test"]',
        "allowed_recipients_json": ["buyer@example.test"],
        "last_checked_at": None, "created_at": None, "updated_at": None, "deleted_at": None,
    })
    assert decoded["inbound_enabled"] is True and decoded["outbound_enabled"] is False
    assert decoded["allowed_senders"] == ["sender@example.test"]
    assert decoded["allowed_recipients"] == ["buyer@example.test"]


def test_sqlite_metrics_and_retention_redact_content_but_keep_receipt_and_audit(tmp_path: Path):
    result = run_email_m5_acceptance("qq", workspace=tmp_path)
    connection = sqlite3.connect(tmp_path / "m5-email-acceptance.sqlite3", check_same_thread=False)
    connection.row_factory = sqlite3.Row
    repository = EmailDeliveryRepository(connection)
    before = repository.metrics()
    assert before["status_counts"] == {"accepted": 1}
    assert before["terminal_unredacted"] == 1
    assert repository.redact_terminal_content(
        "2100-01-01T00:00:00Z", actor="m6-test-governance", apply=False
    ) == 1
    row = repository.get(result["delivery_id"])
    assert row["body_snapshot"] != "[redacted]"
    assert repository.redact_terminal_content(
        "2100-01-01T00:00:00Z", actor="m6-test-governance", apply=True
    ) == 1
    row = repository.get(result["delivery_id"])
    assert row["status"] == "accepted"
    assert row["recipient"] == row["subject_snapshot"] == row["body_snapshot"] == "[redacted]"
    assert row["smtp_message_id"] and row["content_hash"] and row["snapshot_hash"]
    actions = [item[0] for item in connection.execute(
        "SELECT action FROM ops_email_delivery_audit WHERE delivery_id=? ORDER BY audit_id",
        (result["delivery_id"],),
    ).fetchall()]
    assert actions[-1] == "content_redacted"
    assert repository.metrics()["terminal_unredacted"] == 0
    connection.close()


@pytest.mark.skipif(
    os.environ.get("NANOCLAW_TEST_MYSQL_EMAIL") != "1",
    reason="set NANOCLAW_TEST_MYSQL_EMAIL=1 with isolated MySQL credentials for live M6 smoke",
)
def test_live_mysql_email_schema_and_metrics_smoke():
    # This intentionally does not apply migrations or send mail. Deployment
    # must apply 001/003/004 explicitly to an isolated test database first.
    accounts = MySQLEmailAccountRepository()
    deliveries = MySQLEmailDeliveryRepository()
    assert isinstance(accounts.list_active(), list)
    metrics = deliveries.metrics()
    assert set(metrics) == {
        "status_counts", "terminal_unredacted", "accepted_latency_seconds_avg"
    }
