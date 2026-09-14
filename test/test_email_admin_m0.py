from dataclasses import asdict
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.workflow import WorkflowService
from agent.business.email_repository import EmailRepository
from agent.business.email_review_service import EmailReviewService
from bus import MessageBus
from channels.email.admin_contracts import (
    EMAIL_ADMIN_CONTRACT_VERSION,
    EMAIL_ADMIN_ROUTE_CONTRACT,
    EmailAccountResponse,
    EmailAccountStatus,
    EmailProviderId,
)
from channels.web import WebChannel
from session.conversation import ConversationService


ADMIN_TOKEN = "m0-test-admin-token"


def build_client(tmp_path: Path, token: str = ADMIN_TOKEN,
                 allowed_origins: tuple[str, ...] = ()) -> tuple[WebChannel, TestClient]:
    review_connection = sqlite3.connect(":memory:", check_same_thread=False)
    review_connection.row_factory = sqlite3.Row
    channel = WebChannel(
        MessageBus(),
        conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"),
        email_admin_token=token,
        email_admin_allowed_origins=allowed_origins,
        email_review_service=EmailReviewService(EmailRepository(review_connection), "m0-reviewer"),
    )
    channel._app = FastAPI()
    channel._register_routes()
    return channel, TestClient(channel._app)


def protected_routes():
    return [
        (method, path.replace("{account_id}", "00000000-0000-0000-0000-000000000001")
         .replace("{email_id}", "1").replace("{delivery_id}", "delivery-1")
         .replace("{approval_key}", "1").replace("{quote_id}", "1"))
        for method, path, access in EMAIL_ADMIN_ROUTE_CONTRACT
        if access.startswith("protected")
    ]


def test_provider_contract_is_public_fixed_and_secret_free(tmp_path: Path):
    _, client = build_client(tmp_path)
    response = client.get("/api/email/providers")
    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == EMAIL_ADMIN_CONTRACT_VERSION
    assert [item["provider"] for item in payload["providers"]] == [
        "qq", "netease_163", "netease_126"
    ]
    assert payload["providers"][0]["imap"] == {
        "host": "imap.qq.com", "port": 993, "security": "ssl_tls"
    }
    assert payload["providers"][1]["imap_client_id_required"] is True
    serialized = response.text.lower()
    assert "auth_code" not in serialized
    assert "secret_ref" not in serialized
    assert ADMIN_TOKEN not in response.text


def test_safe_account_response_contract_cannot_serialize_credentials():
    payload = asdict(EmailAccountResponse(
        account_id="00000000-0000-0000-0000-000000000001",
        display_name="Sales",
        provider=EmailProviderId.QQ,
        address="sales@qq.com",
        credential_configured=True,
        folder="INBOX",
        inbound_enabled=True,
        outbound_enabled=False,
        poll_seconds=60,
        sender_name="NanoClaw Sales",
        allowed_senders=(),
        allowed_recipients=(),
        status=EmailAccountStatus.DISABLED,
        last_checked_at=None,
        last_error_code=None,
        config_version=1,
        created_at="2026-07-23T00:00:00Z",
        updated_at="2026-07-23T00:00:00Z",
    ))
    assert "auth_code" not in payload
    assert "secret_ref" not in payload
    assert payload["credential_configured"] is True


def test_registered_email_routes_match_m0_contract(tmp_path: Path):
    channel, _ = build_client(tmp_path)
    registered = {
        (method, route.path)
        for route in channel._app.routes
        if route.path.startswith("/api/email/")
        for method in getattr(route, "methods", set())
        if method in {"GET", "POST", "PATCH"}
    }
    expected = {(method, path) for method, path, _ in EMAIL_ADMIN_ROUTE_CONTRACT}
    assert registered == expected


@pytest.mark.parametrize(("method", "path"), protected_routes())
def test_all_protected_email_routes_reject_missing_token(tmp_path: Path, method: str, path: str):
    _, client = build_client(tmp_path)
    response = client.request(method, path)
    assert response.status_code == 401
    assert response.json() == {"detail": "email_admin_unauthorized"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_email_admin_fails_closed_when_token_is_not_configured(tmp_path: Path):
    _, client = build_client(tmp_path, token="")
    response = client.get("/api/email/accounts", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 503
    assert response.json() == {"detail": "email_admin_auth_not_configured"}


def test_email_admin_rejects_cross_origin_even_with_valid_token(tmp_path: Path):
    _, client = build_client(tmp_path)
    response = client.post("/api/email/accounts", headers={
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Origin": "https://attacker.example",
    })
    assert response.status_code == 403
    assert response.json() == {"detail": "email_admin_origin_forbidden"}


@pytest.mark.parametrize("origin", ["http://testserver", "https://workspace.example"])
def test_authorized_same_or_allowlisted_origin_reaches_protected_inbound_api(tmp_path: Path, origin: str):
    _, client = build_client(tmp_path, allowed_origins=("https://workspace.example",))
    response = client.get("/api/email/inbound", headers={
        "Authorization": f"Bearer {ADMIN_TOKEN}",
        "Origin": origin,
    })
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_non_browser_bearer_client_reaches_protected_inbound_api(tmp_path: Path):
    _, client = build_client(tmp_path)
    response = client.get("/api/email/inbound", headers={
        "Authorization": f"Bearer {ADMIN_TOKEN}",
    })
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_loopback_workspace_reaches_email_api_without_token_prompt(tmp_path: Path):
    channel, existing = build_client(tmp_path, token="")
    existing.close()
    with TestClient(channel._app, client=("127.0.0.1", 50000)) as client:
        response = client.get("/api/email/inbound", headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.json() == {"items": [], "next_cursor": None}


def test_m4_delivery_validation_never_echoes_mailbox_authorization_code(tmp_path: Path):
    _, client = build_client(tmp_path)
    mailbox_secret = "simulated-mailbox-auth-code"
    response = client.post(
        "/api/email/deliveries",
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"},
        json={"address": "sales@qq.com", "auth_code": mailbox_secret},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "email_invalid_delivery_request"}
    assert mailbox_secret not in response.text
