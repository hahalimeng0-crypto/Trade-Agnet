from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.workflow import WorkflowService
from bus import MessageBus
from channels.web import WebChannel
from session.conversation import ConversationService


def build_client(tmp_path: Path) -> TestClient:
    channel = WebChannel(
        MessageBus(),
        conversation_service=ConversationService(tmp_path / "sessions"),
        workflow_service=WorkflowService(tmp_path / "workflows"),
        email_admin_token="m2-test-admin-token",
    )
    channel._app = FastAPI()
    channel._register_routes()
    return TestClient(channel._app)


def test_workspace_exposes_email_navigation_tabs_and_account_form(tmp_path: Path):
    with build_client(tmp_path) as client:
        page = client.get("/")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    for marker in (
        'data-view="email"', 'id="emailView"', 'data-email-tab="accounts"',
        'data-email-tab="inbound"', 'data-email-tab="sendable"',
        'data-email-tab="deliveries"', 'id="emailAccountForm"',
        'id="emailProvider"', 'id="emailAddress"', 'id="emailAuthCode"',
        'id="emailToggleAccount"',
        'id="emailReviewStatus"', 'id="emailReviewRefresh"',
        'id="emailInboundList"', 'id="emailInboundDetail"',
        'id="emailSendableContent"', 'id="emailDeliveriesContent"',
        'id="emailQueueDialog"', 'id="emailQueueConsent"',
        'id="emailMetricPending"', 'id="emailRuntimeStatus"',
    ):
        assert marker in page.text
    assert 'id="emailAuthCode" type="password"' in page.text
    assert 'id="emailAuthCode" type="password" autocomplete="off"' in page.text
    assert 'id="emailAdminToken"' not in page.text
    assert "Agent 自动审核 RFQ 字段" in page.text
    assert 'data-view="ops"' not in page.text
    assert 'id="opsView"' not in page.text
    assert "/static/app.css?v=20260827-approval-actions-1" in page.text
    assert "/static/app.js?v=20260827-approval-actions-2" in page.text


def test_email_ui_uses_m0_routes_and_never_persists_email_secrets(tmp_path: Path):
    with build_client(tmp_path) as client:
        script = client.get("/static/app.js")
    assert script.status_code == 200
    for endpoint in (
        "/api/email/providers", "/api/email/accounts", "/api/email/inbound",
        "/api/email/sendable-quotes", "/api/email/deliveries", "'disable':'enable'",
        "/api/email/runtime",
    ):
        assert endpoint in script.text
    assert "state.emailAdminToken=token" not in script.text
    assert "$('#emailAuthCode').value=''" in script.text
    assert "localStorage.setItem('nanoclaw-email" not in script.text
    assert "sessionStorage" not in script.text
    assert "email_feature_not_implemented" in script.text
    assert "/review-preview" in script.text
    assert "'Idempotency-Key':crypto.randomUUID()" in script.text
    assert "'If-Match':state.emailInboundEtag" in script.text
    assert "body.textContent=detail.text_body||''" in script.text
    assert "localStorage.setItem('nanoclaw-email-review" not in script.text
    assert "queue_requires_explicit_operator" not in script.text
    assert "window.confirm(t('email.queueFinalConfirm'" in script.text
    assert "presentAgentRfqCheck" in script.text
    assert "ready_for_business_confirmation" in script.text
    assert "controls.slice(1).forEach(control=>control.hidden=true)" in script.text
    assert "validateReviewCorrections" in script.text
    assert "email.reviewNoteRequired" in script.text
    assert "outboundReadinessError" in script.text
    assert "email.recipientAllowlistRequired" in script.text


def test_email_ui_has_complete_three_language_contract(tmp_path: Path):
    with build_client(tmp_path) as client:
        script = client.get("/static/app.js").text
    assert script.count("'nav.email':") == 3
    assert script.count("'email.tabAccounts':") == 3
    assert script.count("'email.authCodeHelp':") == 3
    assert script.count("'email.m2Boundary':") == 3
    assert script.count("'email.confirmReview':") >= 3
    assert script.count("'email.pendingRemain':") == 3
    assert script.count("'email.queueConsent':") == 3
    assert script.count("'email.agentCheckTitle':") == 3


def test_email_ui_styles_cover_desktop_mobile_and_secret_dialog(tmp_path: Path):
    with build_client(tmp_path) as client:
        styles = client.get("/static/app.css")
    assert styles.status_code == 200
    for marker in (
        ".email-content", ".email-tab-panel[data-email-panel=accounts]",
        ".email-account-form", ".email-admin-dialog::backdrop",
        ".email-review-layout", ".email-review-detail", ".email-review-fields",
        ".email-delivery-item", ".email-delivery-actions", ".email-queue-dialog",
        ".email-agent-check", ".requires-business-input",
        "@media(max-width:900px)", "@media(max-width:680px)",
    ):
        assert marker in styles.text
    assert '[data-email-panel="inbound"] .email-review-actions{display:none' not in styles.text
    assert '[data-email-panel="inbound"] .email-review-fields' not in styles.text


def test_quote_approval_buttons_use_separate_action_container(tmp_path: Path):
    with build_client(tmp_path) as client:
        script = client.get("/static/app.js").text
    assert "actions.className='email-delivery-actions'" in script
    assert "actions.append(approve,reject);card.append(actions)" in script
    assert "/approval-regenerate" in script
    assert "email.confirmFieldsToQuote" in script


def test_m2_provider_bootstrap_remains_public_and_secret_free(tmp_path: Path):
    with build_client(tmp_path) as client:
        response = client.get("/api/email/providers")
    assert response.status_code == 200
    assert [item["provider"] for item in response.json()["providers"]] == [
        "qq", "netease_163", "netease_126"
    ]
    assert "auth_code" not in response.text.lower()
