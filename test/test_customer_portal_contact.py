import sqlite3
import time
import uuid
from asyncio import QueueEmpty
from pathlib import Path

from fastapi.testclient import TestClient

from agent.business.email_account_repository import EmailAccountRepository
from agent.business.email_account_service import EmailAccountService
from agent.business.email_secret_store import MemoryEmailSecretStore
from bus import MessageBus
from channels.customer_portal import CustomerPortalChannel


ROOT = Path(__file__).resolve().parents[1]


class NoopConnectionTester:
    def test(self, account: dict, auth_code: str) -> None:
        return None


def account_payload(address: str) -> dict:
    return {
        "display_name": "Sales mailbox",
        "provider": "qq",
        "address": address,
        "auth_code": "test-only-auth-code",
        "inbound_enabled": True,
        "outbound_enabled": False,
        "poll_seconds": 60,
        "sender_name": "NanoClaw Sales",
        "allowed_senders": [],
        "allowed_recipients": [],
    }


def test_customer_portal_uses_latest_workspace_email_without_admin_credentials():
    repository = EmailAccountRepository(sqlite3.connect(":memory:", check_same_thread=False))
    service = EmailAccountService(repository, MemoryEmailSecretStore(), NoopConnectionTester())
    service.create_account(account_payload("first-sales@qq.com"))
    channel = CustomerPortalChannel(
        MessageBus(), host="127.0.0.1", port=8766, email_account_service=service,
    )

    with TestClient(channel.create_app()) as client:
        first = client.get("/api/public/config")
        assert first.status_code == 200
        assert first.json() == {"sales_email": "first-sales@qq.com"}

        service.create_account(account_payload("current-sales@qq.com"))
        current = client.get("/api/public/config")
        assert current.json() == {"sales_email": "current-sales@qq.com"}
        assert "authorization" not in current.request.headers


def test_contact_page_has_contact_navigation_and_dynamic_config_loader():
    repository = EmailAccountRepository(sqlite3.connect(":memory:", check_same_thread=False))
    service = EmailAccountService(repository, MemoryEmailSecretStore(), NoopConnectionTester())
    channel = CustomerPortalChannel(
        MessageBus(), host="127.0.0.1", port=8766, email_account_service=service,
    )

    with TestClient(channel.create_app()) as client:
        page = client.get("/").text
        script = client.get("/static/customer-contact.js").text

    assert 'data-section="contact"' in page
    assert 'data-section="rates"' in page
    assert 'id="contactPage"' in page
    assert 'id="ratesPage"' in page
    assert "open.er-api.com/v6/latest/USD" in script
    assert "/api/public/config" in script
    assert "预览模式" not in page


def test_customer_portal_websocket_publishes_real_agent_message():
    bus = MessageBus()
    channel = CustomerPortalChannel(bus, host="127.0.0.1", port=8766)
    conversation_id = str(uuid.uuid4())
    request_id = str(uuid.uuid4())
    with TestClient(channel.create_app()) as client:
        client.get("/")
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "type": "chat.message", "protocol_version": 2,
                "conversation_id": conversation_id, "request_id": request_id,
                "language": "de", "content": "Need 100 USB-C cables",
            })
            deadline = time.monotonic() + 2
            while True:
                try:
                    message = bus.inbound_queue.get_nowait()
                    break
                except QueueEmpty:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.01)
    assert message.channel == "customer_portal"
    assert message.content == "Need 100 USB-C cables"
    assert message.raw["conversation_id"] == conversation_id
    assert message.raw["language"] == "de"


def test_customer_portal_has_no_mail_admin_or_internal_static_routes():
    channel = CustomerPortalChannel(MessageBus(), host="127.0.0.1", port=8766)
    with TestClient(channel.create_app()) as client:
        assert client.get("/api/email/providers").status_code == 404
        assert client.get("/api/email/accounts").status_code == 404
        assert client.get("/api/knowledge/documents").status_code == 404
        assert client.get("/static/app.js").status_code == 404
        assert client.get("/static/customer-preview.js").status_code == 200


def test_customer_mobile_navigation_and_foreign_language_prompts_are_available():
    page = (ROOT / "channels" / "web_ui" / "customer.html").read_text(encoding="utf-8")
    script = (ROOT / "channels" / "web_ui" / "static" / "customer-preview.js").read_text(encoding="utf-8")
    styles = (ROOT / "channels" / "web_ui" / "static" / "css" / "customer.css").read_text(encoding="utf-8")

    assert 'data-prompt-key="prompt.usbcText"' in page
    assert 'data-i18n="assistant.identity"' in page
    assert "NanoClaw Product Advisor" in script
    assert "USB-C-Datenkabel" in script
    assert "Which industrial tablets do you offer?" in script
    assert "language: lang" in script
    assert 'id="quoteRequest"' in page
    assert "safeAssistantMessage" in script
    assert "chat.serviceUnavailable" in script
    assert "RFQ · Pending" not in page
    assert "@media(max-width:680px){.customer-rail nav{display:flex" in styles


def test_customer_account_login_and_server_history_loader_are_present():
    page = (ROOT / "channels" / "web_ui" / "customer.html").read_text(encoding="utf-8")
    script = (ROOT / "channels" / "web_ui" / "static" / "customer-preview.js").read_text(encoding="utf-8")

    assert 'id="customerAuthDialog"' in page
    assert 'autocomplete="current-password"' in page
    assert "/api/customer/auth/session" in script
    assert "/api/customer/auth/login" in script
    assert "updateAccountButton();" in script
    assert 'id="customerAccountLabel"' in page
    assert "/api/customer/conversations?limit=100" in script
    assert "loadServerMessages" in script
    assert "localStorage" in script
    assert "localStorage.setItem('nanoclaw_customer_session'" not in script


def test_customer_agent_replies_use_shared_safe_markdown_renderer():
    page = (ROOT / "channels" / "web_ui" / "customer.html").read_text(encoding="utf-8")
    script = (ROOT / "channels" / "web_ui" / "static" / "customer-preview.js").read_text(encoding="utf-8")
    markdown = (ROOT / "channels" / "web_ui" / "static" / "js" / "markdown.js").read_text(encoding="utf-8")

    assert page.index('/static/js/markdown.js') < page.index('/static/customer-preview.js')
    assert "window.NanoClawMarkdown?.render(safeAssistantMessage(value))" in script
    assert "message.innerHTML" in script
    assert "const safeHref" in markdown


def test_customer_conversation_renders_customer_and_agent_avatars():
    script = (ROOT / "channels" / "web_ui" / "static" / "customer-preview.js").read_text(encoding="utf-8")
    styles = (ROOT / "channels" / "web_ui" / "static" / "css" / "customer.css").read_text(encoding="utf-8")

    assert "portal-message-avatar" in script
    assert "brand-avatar" in script
    assert "customer-avatar" in script
    assert "avatar.innerHTML = isAssistant" in script
    assert "else row.append(message, avatar)" in script
    assert ".portal-message-row.user{grid-template-columns:minmax(0,1fr) 36px}" in styles
    assert "max-width:min(680px,100%)" in styles
    assert ".portal-message-row.user .preview-message{justify-self:end}" in styles
    assert ".portal-message-avatar.brand-avatar" in styles
    assert ".portal-message-avatar.customer-avatar" in styles


def test_workspace_profile_is_in_rail_and_conversation_panel_is_chat_only():
    page = (ROOT / "channels" / "web_ui" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "channels" / "web_ui" / "static" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "channels" / "web_ui" / "static" / "app.css").read_text(encoding="utf-8")

    assert page.index('class="language-wrap"') < page.index('class="rail-profile"')
    assert '<footer class="profile-card">' not in page
    assert "classList.toggle('non-chat-view',view!=='chat')" in script
    assert "body.non-chat-view .conversation-panel{display:none}" in styles
