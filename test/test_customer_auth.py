import sqlite3

from fastapi.testclient import TestClient

from agent.customer_identity.repository import CustomerIdentityRepository
from agent.customer_identity.service import CustomerIdentityService
from agent.customer_identity.session_cookie import AUTH_COOKIE, CSRF_COOKIE
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from agent.memory_runtime.stores.sqlite import CustomerSQLiteMemoryStore
from bus import MessageBus
from channels.customer_portal import CustomerPortalChannel
from session.customer_conversation import CustomerConversationRepository


class TestPasswordHasher:
    """Deterministic test double; never used by production assembly."""

    def hash(self, password: str) -> str:
        return "test$" + password[::-1]

    def verify(self, encoded: str, password: str) -> bool:
        return encoded == self.hash(password)


def build_channel(*, registration_enabled: bool = True, memory_enabled: bool = False):
    identity_connection = sqlite3.connect(":memory:", check_same_thread=False)
    data_connection = sqlite3.connect(":memory:", check_same_thread=False)
    identity = CustomerIdentityService(
        CustomerIdentityRepository(identity_connection), TestPasswordHasher(),
        registration_enabled=registration_enabled, tenant_id="tenant-test",
    )
    conversations = CustomerConversationRepository(
        data_connection, cursor_secret=b"test-cursor-secret-that-is-long-enough",
    )
    bus = MessageBus()
    channel = CustomerPortalChannel(
        bus, host="127.0.0.1", port=8766,
        identity_service=identity, conversation_repository=conversations,
        memory_service=(CustomerMemoryService(CustomerSQLiteMemoryStore(data_connection))
                        if memory_enabled else None),
    )
    return channel, bus, identity, conversations


def csrf(client: TestClient) -> str:
    client.get("/api/customer/auth/session")
    return client.cookies.get(CSRF_COOKIE)


def test_customer_account_menu_button_uses_localized_text_label():
    channel, _, _, _ = build_channel()
    with TestClient(channel.create_app()) as client:
        page = client.get("/customer")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-cache, must-revalidate"
        assert "/static/customer-preview.js?v=20260827-1" in page.text
        assert 'id="customerAccount" class="customer-account-button"' in page.text
        assert '>客户登录</span></button>' in page.text
        assert 'data-i18n="auth.loginButton"' in page.text
        assert 'class="customer-auth-dialog"' in page.text
        assert page.text.count('formmethod="dialog" formnovalidate value="cancel"') == 2
        assert '>♙</button>' not in page.text

        script = client.get("/static/customer-preview.js")
        assert script.status_code == 200
        assert script.headers["cache-control"] == "no-cache, must-revalidate"
        assert "'auth.loginButton': '客户登录'" in script.text
        assert "'auth.loginButton': 'Sign in'" in script.text
        assert "'auth.loginButton': 'Anmelden'" in script.text
        assert "'auth.passwordPlaceholder': 'Passwort eingeben'" in script.text
        assert "$('customerAccountLabel').textContent = label" in script.text
        assert "authDialog.close('cancel')" in script.text

        stylesheet = client.get("/static/css/customer.css")
        assert stylesheet.status_code == 200
        assert ".customer-account-button{" in stylesheet.text
        assert ".customer-shell.rail-expanded .customer-brand{display:none}" in stylesheet.text


def register_and_login(client: TestClient, email: str):
    token = csrf(client)
    payload = {"email": email, "password": "correct horse battery", "locale": "en"}
    registered = client.post(
        "/api/customer/auth/register", json=payload, headers={"X-CSRF-Token": token},
    )
    assert registered.status_code == 201
    logged_in = client.post(
        "/api/customer/auth/login", json=payload, headers={"X-CSRF-Token": token},
    )
    assert logged_in.status_code == 200
    assert client.cookies.get(AUTH_COOKIE)
    return logged_in.json(), client.cookies.get(CSRF_COOKIE)


def test_registration_login_session_rotation_and_logout():
    channel, _, _, _ = build_channel()
    with TestClient(channel.create_app()) as client:
        session, login_csrf = register_and_login(client, "Customer@Example.com")
        assert session["authenticated"] is True
        assert client.get("/api/customer/auth/session").json()["account_id"] == session["account_id"]

        no_csrf = client.post("/api/customer/auth/logout")
        assert no_csrf.status_code == 403
        logged_out = client.post(
            "/api/customer/auth/logout", headers={"X-CSRF-Token": login_csrf},
        )
        assert logged_out.status_code == 204
        assert client.get("/api/customer/auth/session").json() == {"authenticated": False}


def test_login_failure_is_generic_and_registration_switch_fails_closed():
    channel, _, _, _ = build_channel(registration_enabled=False)
    with TestClient(channel.create_app()) as client:
        token = csrf(client)
        payload = {"email": "missing@example.com", "password": "wrong-password", "locale": "en"}
        disabled = client.post(
            "/api/customer/auth/register", json=payload,
            headers={"X-CSRF-Token": token},
        )
        assert disabled.status_code == 403
        assert disabled.json()["detail"] == "customer_registration_disabled"
        failed = client.post(
            "/api/customer/auth/login", json=payload,
            headers={"X-CSRF-Token": token},
        )
        assert failed.status_code == 401
        assert failed.json()["detail"] == "customer_auth_failed"


def test_account_owned_conversation_history_and_cross_account_404():
    channel, _, _, repository = build_channel()
    app = channel.create_app()
    with TestClient(app) as customer_a:
        account_a, token_a = register_and_login(customer_a, "a@example.com")
        created = customer_a.post(
            "/api/customer/conversations", json={"title": "A private RFQ"},
            headers={"X-CSRF-Token": token_a},
        )
        assert created.status_code == 201
        conversation_id = created.json()["conversation_id"]
        listed = customer_a.get("/api/customer/conversations").json()
        assert [item["conversation_id"] for item in listed["items"]] == [conversation_id]

    with TestClient(app) as customer_b:
        account_b, _ = register_and_login(customer_b, "b@example.com")
        assert account_a["account_id"] != account_b["account_id"]
        denied = customer_b.get(
            f"/api/customer/conversations/{conversation_id}/messages"
        )
        assert denied.status_code == 404
        assert denied.json()["detail"] == "customer_resource_not_found"

    rows = repository.connection.execute(
        "SELECT tenant_id,account_id FROM customer_conversation"
    ).fetchall()
    assert [(row["tenant_id"], row["account_id"]) for row in rows] == [
        ("tenant-test", account_a["account_id"])
    ]


def test_authenticated_websocket_uses_server_account_and_rejects_other_owner():
    channel, bus, _, _ = build_channel()
    app = channel.create_app()
    with TestClient(app) as customer_a:
        account_a, token_a = register_and_login(customer_a, "ws-a@example.com")
        created = customer_a.post(
            "/api/customer/conversations", json={"title": "Owned"},
            headers={"X-CSRF-Token": token_a},
        ).json()
        with customer_a.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "type": "chat.message", "protocol_version": 2,
                "conversation_id": created["conversation_id"],
                "request_id": "00000000-0000-4000-8000-000000000001",
                "language": "en", "content": "Need 100 units",
                "account_id": "client-forged-account",
            })
            websocket.send_json({
                "type": "chat.message", "protocol_version": 2,
                "conversation_id": created["conversation_id"],
                "request_id": "00000000-0000-4000-8000-000000000001",
                "language": "en", "content": "Need 100 units",
            })
            assert websocket.receive_json()["type"] == "chat.duplicate"
            inbound = bus.inbound_queue.get_nowait()
        assert inbound.sender_id.startswith(f"account:{account_a['account_id']}:")
        assert inbound.raw["account_id"] == account_a["account_id"]
        assert inbound.raw["tenant_id"] == "tenant-test"
        assert inbound.raw["_principal"]["user_id"] == account_a["account_id"]
        assert inbound.raw["_principal"]["roles"] == ["customer"]

    with TestClient(app) as customer_b:
        register_and_login(customer_b, "ws-b@example.com")
        with customer_b.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "type": "chat.message", "protocol_version": 2,
                "conversation_id": created["conversation_id"],
                "request_id": "00000000-0000-4000-8000-000000000002",
                "language": "en", "content": "Try other account",
            })
            error = websocket.receive_json()
        assert error["code"] == "customer_resource_not_found"


def test_customer_memory_api_consent_candidate_activate_export_and_delete():
    channel, _, _, _ = build_channel(memory_enabled=True)
    with TestClient(channel.create_app()) as client:
        _, token = register_and_login(client, "memory@example.com")
        consent = client.post(
            "/api/customer/memories/consents",
            json={"purpose": "customer_support", "categories": ["semantic"]},
            headers={"X-CSRF-Token": token},
        )
        assert consent.status_code == 201
        candidate = client.post(
            "/api/customer/memories/candidates",
            json={
                "content": "Preferred destination Hamburg",
                "summary": "Destination preference",
                "memory_type": "semantic", "purpose": "customer_support",
                "source_refs": ["message-a"], "conversation_id": None,
                "confidence": .9, "importance": .7,
            },
            headers={"X-CSRF-Token": token},
        )
        assert candidate.status_code == 201
        activated = client.post(
            f"/api/customer/memories/{candidate.json()['memory_id']}/activate",
            json={"consent_record_id": consent.json()["consent_record_id"], "version": 1},
            headers={"X-CSRF-Token": token},
        )
        assert activated.status_code == 200
        assert activated.json()["status"] == "active"
        corrected = client.patch(
            f"/api/customer/memories/{candidate.json()['memory_id']}",
            json={
                "content": "Preferred port Rotterdam",
                "summary": "Port corrected to Rotterdam",
                "source_refs": ["message-b"],
                "version": activated.json()["version"],
            },
            headers={"X-CSRF-Token": token},
        )
        assert corrected.status_code == 200
        assert corrected.json()["supersedes"] == candidate.json()["memory_id"]
        exported = client.get("/api/customer/memories/export")
        assert exported.status_code == 200
        assert {item["status"] for item in exported.json()["items"]} == {
            "active", "superseded",
        }
        deleted = client.delete(
            "/api/customer/memories", headers={
                "X-CSRF-Token": token, "Idempotency-Key": "delete-all-memory-a",
            },
        )
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "completed"
