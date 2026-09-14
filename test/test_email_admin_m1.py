import json
import os
import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.business.email_account_repository import EmailAccountRepository, EmailAccountRepositoryError
from agent.business.email_account_service import EmailAccountService, EmailAccountServiceError
from agent.business.email_config import EmailIngestionConfig
from agent.business.email_secret_store import DpapiFileEmailSecretStore, MemoryEmailSecretStore
from agent.business.email_repository import EmailRepository
from agent.business.email_review_service import EmailReviewService
from agent.workflow import WorkflowService
from bus import MessageBus
from channels.web import WebChannel
from session.conversation import ConversationService


ADMIN_TOKEN = "m1-test-admin-token"


class RecordingConnectionTester:
    def __init__(self, failure: Exception | None = None):
        self.failure = failure
        self.calls = []

    def test(self, account: dict, auth_code: str) -> None:
        self.calls.append((account["account_id"], auth_code, account["outbound_enabled"]))
        if self.failure:
            raise self.failure


def account_payload(provider="qq", address="sales@qq.com", auth_code="mailbox-code-one"):
    return {
        "display_name": "Sales mailbox", "provider": provider, "address": address,
        "auth_code": auth_code, "inbound_enabled": True, "outbound_enabled": False,
        "poll_seconds": 60, "sender_name": "NanoClaw Sales",
        "allowed_senders": [], "allowed_recipients": [],
    }


def build_service(tester=None):
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    repository = EmailAccountRepository(connection)
    secrets = MemoryEmailSecretStore()
    service = EmailAccountService(repository, secrets, tester or RecordingConnectionTester())
    return service, repository, secrets


def build_client(tmp_path: Path, tester=None):
    service, repository, secrets = build_service(tester)
    channel = WebChannel(
        MessageBus(), conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"), email_admin_token=ADMIN_TOKEN,
        email_account_service=service,
        email_review_service=EmailReviewService(EmailRepository(repository.connection), "m1-reviewer"),
    )
    channel._app = FastAPI()
    channel._register_routes()
    return TestClient(channel._app), repository, secrets


def auth_headers():
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


def test_dpapi_file_store_persists_only_protected_blob(tmp_path: Path):
    def protect(value: bytes) -> bytes:
        return b"protected:" + value[::-1]

    def unprotect(value: bytes) -> bytes:
        assert value.startswith(b"protected:")
        return value[len(b"protected:"):][::-1]

    path = tmp_path / "email-secrets.dpapi.json"
    store = DpapiFileEmailSecretStore(path, protect=protect, unprotect=unprotect)
    store.set("email-account/one", "mailbox-secret-value")
    assert store.get("email-account/one") == "mailbox-secret-value"
    assert store.contains("email-account/one") is True
    assert "mailbox-secret-value" not in path.read_text(encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    store.delete("email-account/one")
    assert store.contains("email-account/one") is False


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI acceptance")
def test_windows_dpapi_round_trip_never_writes_plaintext(tmp_path: Path):
    path = tmp_path / "real-dpapi.json"
    store = DpapiFileEmailSecretStore(path)
    secret = "dpapi-local-acceptance-secret"
    store.set("email-account/windows", secret)
    assert store.get("email-account/windows") == secret
    assert secret not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize(("provider", "address"), [
    ("qq", "sales@qq.com"), ("netease_163", "sales@163.com"), ("netease_126", "sales@126.com"),
])
def test_create_supported_accounts_without_persisting_plaintext_secret(provider: str, address: str):
    service, repository, secrets = build_service()
    created = service.create_account(account_payload(provider, address))
    assert created["provider"] == provider
    assert created["address"] == address
    assert created["credential_configured"] is True
    assert "auth_code" not in created and "secret_ref" not in created
    database_dump = "\n".join(repository.connection.iterdump())
    assert "mailbox-code-one" not in database_dump
    stored = repository.get(created["account_id"])
    assert secrets.get(stored["secret_ref"]) == "mailbox-code-one"
    audit_dump = json.dumps(repository.audit_rows(created["account_id"]))
    assert "mailbox-code-one" not in audit_dump


def test_account_validation_rejects_wrong_domain_and_unbounded_outbound():
    service, _, _ = build_service()
    with pytest.raises(EmailAccountServiceError, match="email_invalid_address"):
        service.create_account(account_payload("qq", "sales@163.com"))
    payload = account_payload()
    payload["outbound_enabled"] = True
    with pytest.raises(EmailAccountServiceError, match="email_recipients_required"):
        service.create_account(payload)


def test_rotate_credential_uses_optimistic_lock_and_restores_on_conflict():
    service, repository, secrets = build_service()
    created = service.create_account(account_payload())
    account_id = created["account_id"]
    updated = service.update_account(account_id, {
        "config_version": created["config_version"], "display_name": "Updated", "auth_code": "rotated-code",
    })
    stored = repository.get(account_id)
    assert updated["config_version"] == 2
    assert secrets.get(stored["secret_ref"]) == "rotated-code"
    with pytest.raises(EmailAccountRepositoryError, match="email_config_version_conflict"):
        service.update_account(account_id, {
            "config_version": 1, "display_name": "Stale", "auth_code": "must-not-survive",
        })
    assert secrets.get(stored["secret_ref"]) == "rotated-code"


def test_rotate_credential_can_replace_missing_local_secret():
    service, repository, secrets = build_service()
    created = service.create_account(account_payload())
    stored = repository.get(created["account_id"])
    secrets.delete(stored["secret_ref"])

    updated = service.update_account(created["account_id"], {
        "config_version": created["config_version"],
        "display_name": created["display_name"],
        "auth_code": "replacement-code",
    })

    assert updated["config_version"] == 2
    assert updated["credential_configured"] is True
    assert secrets.get(stored["secret_ref"]) == "replacement-code"


def test_enable_disable_and_connection_health_are_audited_without_secret():
    tester = RecordingConnectionTester()
    service, repository, _ = build_service(tester)
    created = service.create_account(account_payload())
    enabled = service.set_enabled(created["account_id"], True)
    assert enabled["status"] == "validating"
    healthy = service.test_connection(created["account_id"])
    assert healthy["status"] == "healthy" and healthy["last_checked_at"]
    assert tester.calls == [(created["account_id"], "mailbox-code-one", False)]
    disabled = service.set_enabled(created["account_id"], False)
    assert disabled["status"] == "disabled"
    audit = repository.audit_rows(created["account_id"])
    assert [row["action"] for row in audit] == ["created", "enabled", "connection_test", "disabled"]
    assert "mailbox-code-one" not in json.dumps(audit)


def test_legacy_environment_migration_is_explicit_and_idempotent():
    service, repository, secrets = build_service()
    legacy = EmailIngestionConfig(
        enabled=True, provider="netease_163", account_id="legacy-mailbox",
        address="legacy@163.com", auth_code="legacy-auth-code", poll_seconds=90,
    )
    first = service.migrate_legacy_config(legacy)
    second = service.migrate_legacy_config(legacy)
    assert first["account_id"] == second["account_id"]
    assert len(repository.list_active()) == 1
    stored = repository.get(first["account_id"])
    assert secrets.get(stored["secret_ref"]) == "legacy-auth-code"
    assert repository.audit_rows(first["account_id"])[0]["action"] == "legacy_migrated"


def test_m1_api_create_list_patch_test_enable_disable_and_m3_list(tmp_path: Path):
    tester = RecordingConnectionTester()
    client, repository, _ = build_client(tmp_path, tester)
    with client:
        created_response = client.post("/api/email/accounts", headers=auth_headers(), json=account_payload())
        assert created_response.status_code == 201
        created = created_response.json()
        assert "auth_code" not in created and "secret_ref" not in created
        listed = client.get("/api/email/accounts", headers=auth_headers()).json()["items"]
        assert [item["account_id"] for item in listed] == [created["account_id"]]
        patched = client.patch(f"/api/email/accounts/{created['account_id']}", headers=auth_headers(), json={
            "config_version": created["config_version"], "display_name": "API Updated",
        })
        assert patched.status_code == 200 and patched.json()["display_name"] == "API Updated"
        enabled = client.post(f"/api/email/accounts/{created['account_id']}/enable", headers=auth_headers())
        assert enabled.status_code == 200 and enabled.json()["status"] == "validating"
        tested = client.post(f"/api/email/accounts/{created['account_id']}/test", headers=auth_headers())
        assert tested.status_code == 200 and tested.json()["status"] == "healthy"
        disabled = client.post(f"/api/email/accounts/{created['account_id']}/disable", headers=auth_headers())
        assert disabled.status_code == 200 and disabled.json()["status"] == "disabled"
        m3 = client.get("/api/email/inbound", headers=auth_headers())
        assert m3.status_code == 200 and m3.json() == {"items": [], "next_cursor": None}
    assert "mailbox-code-one" not in "\n".join(repository.connection.iterdump())


def test_m1_api_conflict_and_secret_zero_echo(tmp_path: Path):
    client, _, _ = build_client(tmp_path)
    with client:
        created = client.post("/api/email/accounts", headers=auth_headers(), json=account_payload()).json()
        secret = "new-secret-never-echoed"
        response = client.patch(f"/api/email/accounts/{created['account_id']}", headers=auth_headers(), json={
            "config_version": 0, "auth_code": secret,
        })
    assert response.status_code == 409
    assert response.json() == {"detail": "email_config_version_conflict"}
    assert secret not in response.text
