"""Dedicated HTTP/WebSocket server for the public customer portal."""

import hashlib
import hmac
import json
import os
import secrets
import uuid

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from bus import InboundMessage, MessageBus, OutboundMessage
from channels.base import Channel
from agent.business.email_account_service import EmailAccountService, create_default_email_account_service
from agent.customer_identity.service import CustomerIdentityService
from agent.customer_identity.session_cookie import AUTH_COOKIE
from channels.customer_auth_api import create_customer_auth_router
from channels.customer_conversation_api import create_customer_conversation_router
from channels.customer_memory_api import create_customer_memory_router
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from privacy import safe_print as print
from session.customer_conversation import (
    CustomerConversationError,
    CustomerConversationRepository,
    CustomerOwner,
)
from channels.access_auth_api import ACCESS_COOKIE, bearer_token
from agent.access_control.models import Principal


def create_app() -> FastAPI:
    """Application factory for standalone serving and HTTP acceptance tests."""
    return CustomerPortalChannel(MessageBus(), host="127.0.0.1", port=8766).create_app()


class CustomerPortalChannel(Channel):
    """Serve the customer-facing UI on a port isolated from the workspace UI."""

    def __init__(self, bus: MessageBus, host: str, port: int,
                 email_account_service: EmailAccountService | None = None,
                 identity_service: CustomerIdentityService | None = None,
                 conversation_repository: CustomerConversationRepository | None = None,
                 memory_service: CustomerMemoryService | None = None) -> None:
        super().__init__(name="customer_portal", bus=bus)
        self.host = host
        self.port = port
        self._server: uvicorn.Server | None = None
        self._app: FastAPI | None = None
        self._email_account_service = email_account_service
        self._identity_service = identity_service
        self._conversation_repository = conversation_repository
        self._memory_service = memory_service
        if (identity_service is None) != (conversation_repository is None):
            raise ValueError("customer_auth_dependencies_incomplete")
        self._auth_enabled = identity_service is not None
        self._connections: dict[str, WebSocket] = {}
        self._bindings: dict[str, str] = {}
        self._connection_owners: dict[str, CustomerOwner] = {}
        self._active_requests: dict[str, set[str]] = {}
        self._seen_requests: dict[str, set[str]] = {}
        self._request_hashes: dict[str, dict[str, str]] = {}
        configured_secret = os.environ.get("NANOCLAW_CUSTOMER_SESSION_SECRET", "").encode()
        self._session_secret = configured_secret or secrets.token_bytes(32)

    def _sign_customer_id(self, customer_id: str) -> str:
        signature = hmac.new(self._session_secret, customer_id.encode(), hashlib.sha256).hexdigest()
        return f"{customer_id}.{signature}"

    def _customer_id(self, token: str | None) -> str | None:
        try:
            customer_id, signature = (token or "").rsplit(".", 1)
        except ValueError:
            return None
        expected = hmac.new(self._session_secret, customer_id.encode(), hashlib.sha256).hexdigest()
        try:
            uuid.UUID(customer_id)
        except ValueError:
            return None
        return customer_id if hmac.compare_digest(signature, expected) else None

    def _account_service(self) -> EmailAccountService:
        if self._email_account_service is None:
            self._email_account_service = create_default_email_account_service()
        return self._email_account_service

    def create_app(self) -> FastAPI:
        ui_dir = Path(__file__).parent / "web_ui"
        app = FastAPI(title="NanoClaw Customer Portal")
        # The marketing homepage is served by the workspace port while account
        # registration remains isolated on the customer portal port.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
        )
        if self._auth_enabled:
            app.include_router(create_customer_auth_router(self._identity_service))
            app.include_router(create_customer_conversation_router(
                self._identity_service, self._conversation_repository,
                on_deleted=self._on_conversation_deleted,
            ))
            if self._memory_service is not None:
                app.include_router(create_customer_memory_router(
                    self._identity_service, self._memory_service,
                ))
        public_assets = {
            "css/tokens.css", "css/common.css", "css/customer.css", "css/markdown.css",
            "js/theme.js", "js/markdown.js", "customer-preview.js",
            "customer-layout-fix.js", "customer-contact.js", "product.css", "product.js",
        }

        @app.get("/static/{asset_path:path}")
        async def customer_static(asset_path: str):
            """Serve a fixed customer-only asset allowlist; internal workspace JS is private."""
            if asset_path not in public_assets:
                raise HTTPException(status_code=404, detail="customer_asset_not_found")
            return FileResponse(
                ui_dir / "static" / asset_path,
                headers={"Cache-Control": "no-cache, must-revalidate"},
            )

        async def portal_page(request: Request):
            page = ui_dir / "customer.html"
            if page.exists():
                response = FileResponse(
                    page, media_type="text/html",
                    headers={"Cache-Control": "no-cache, must-revalidate"},
                )
                if (not self._auth_enabled
                        and self._customer_id(request.cookies.get(AUTH_COOKIE)) is None):
                    response.set_cookie(
                        AUTH_COOKIE,
                        self._sign_customer_id(str(uuid.uuid4())),
                        httponly=True,
                        samesite="lax",
                        secure=request.url.scheme == "https",
                    )
                return response
            return HTMLResponse("<h1>customer.html not found</h1>", status_code=404)

        app.add_api_route("/", portal_page, methods=["GET"])
        app.add_api_route("/customer", portal_page, methods=["GET"])

        async def product_page():
            page = ui_dir / "product.html"
            return FileResponse(page, media_type="text/html") if page.exists() else HTMLResponse("<h1>product.html not found</h1>", status_code=404)

        app.add_api_route("/product", product_page, methods=["GET"])

        @app.get("/health")
        async def health():
            return {"status": "ok", "service": "customer_portal"}

        @app.get("/api/public/config")
        async def public_config():
            """Expose only the contact address selected from the shared workspace account store."""
            fallback = os.environ.get("NANOCLAW_PUBLIC_SALES_EMAIL", "").strip() or "sales@qq.com"
            try:
                sales_email = self._account_service().public_contact_email() or fallback
            except Exception:
                sales_email = fallback
            return {"sales_email": sales_email}

        @app.websocket("/ws")
        async def customer_websocket(websocket: WebSocket):
            owner = None
            if self._auth_enabled:
                customer = self._identity_service.resolve(websocket.cookies.get(AUTH_COOKIE))
                if customer is None:
                    customer = self._identity_service.resolve_access(
                        bearer_token(websocket.headers, websocket.cookies)
                        or websocket.cookies.get(ACCESS_COOKIE)
                    )
                if customer is None:
                    await websocket.close(code=4401)
                    return
                customer_id = customer.account_id
                owner = CustomerOwner(customer.tenant_id, customer.account_id)
            else:
                customer_id = self._customer_id(websocket.cookies.get(AUTH_COOKIE))
                if customer_id is None:
                    await websocket.close(code=4401)
                    return
            await websocket.accept()
            client_id = str(uuid.uuid4())
            self._connections[client_id] = websocket
            if owner is not None:
                self._connection_owners[client_id] = owner
            try:
                while True:
                    payload = json.loads(await websocket.receive_text())
                    if not isinstance(payload, dict) or payload.get("type") != "chat.message":
                        await websocket.send_json({"type": "error", "protocol_version": 2,
                                                   "code": "invalid_message"})
                        continue
                    conversation_id = str(payload.get("conversation_id", ""))
                    request_id = str(payload.get("request_id", ""))
                    content = payload.get("content")
                    language = str(payload.get("language", "en"))
                    try:
                        uuid.UUID(conversation_id)
                        uuid.UUID(request_id)
                    except ValueError:
                        await websocket.send_json({"type": "error", "protocol_version": 2,
                                                   "code": "invalid_message"})
                        continue
                    if (payload.get("protocol_version") != 2 or language not in {"zh", "en", "de"}
                            or not isinstance(content, str)
                            or not content.strip() or len(content) > 120_000):
                        await websocket.send_json({"type": "error", "protocol_version": 2,
                                                   "code": "invalid_message"})
                        continue
                    if owner is not None:
                        try:
                            self._conversation_repository.get_owned(owner, conversation_id)
                        except CustomerConversationError:
                            await websocket.send_json({
                                "type": "error", "protocol_version": 2,
                                "code": "customer_resource_not_found",
                                "conversation_id": conversation_id,
                                "request_id": request_id,
                            })
                            continue
                    request_scope = f"{customer_id}:{conversation_id}"
                    seen = self._seen_requests.setdefault(request_scope, set())
                    digest = hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
                    if request_id in seen:
                        expected = self._request_hashes.get(request_scope, {}).get(request_id)
                        event = ({"type": "error", "protocol_version": 2,
                                  "code": "request_id_conflict"}
                                 if expected is not None and expected != digest else
                                 {"type": "chat.duplicate", "protocol_version": 2})
                        await websocket.send_json({**event, "conversation_id": conversation_id,
                                                   "request_id": request_id})
                        continue
                    seen.add(request_id)
                    self._request_hashes.setdefault(request_scope, {})[request_id] = digest
                    self._bindings[client_id] = conversation_id
                    self._active_requests.setdefault(client_id, set()).add(request_id)
                    if owner is not None:
                        self._conversation_repository.append_message(
                            owner, conversation_id, role="user", content=content.strip(),
                            request_id=request_id,
                        )
                    await self.bus.publish_inbound(InboundMessage(
                        channel=self.name,
                        sender_id=(f"account:{customer_id}:{conversation_id}" if owner
                                   else f"anonymous:{customer_id}:{conversation_id}"),
                        chat_id=client_id,
                        content=content.strip(),
                        raw={"event": "chat.message", "conversation_id": conversation_id,
                             "request_id": request_id, "language": language,
                             **({"tenant_id": owner.tenant_id, "account_id": owner.account_id}
                                if owner else {}),
                             **({"_principal": Principal(
                                 owner.account_id, owner.tenant_id, owner.account_id,
                                 frozenset({"customer"}),
                             ).to_trusted_dict()} if owner else {})},
                    ))
            except Exception as exc:
                print(f"[CustomerPortal] 客户连接断开: client_id={client_id} reason={exc}")
            finally:
                self._connections.pop(client_id, None)
                self._bindings.pop(client_id, None)
                self._connection_owners.pop(client_id, None)
                self._active_requests.pop(client_id, None)

        return app

    async def _on_conversation_deleted(
        self, owner: CustomerOwner, conversation_id: str
    ) -> None:
        self._seen_requests.pop(f"{owner.account_id}:{conversation_id}", None)
        self._request_hashes.pop(f"{owner.account_id}:{conversation_id}", None)
        for client_id, bound in list(self._bindings.items()):
            if bound == conversation_id and self._connection_owners.get(client_id) == owner:
                self._bindings.pop(client_id, None)
                self._active_requests.pop(client_id, None)
        await self.bus.publish_inbound(InboundMessage(
            channel=self.name,
            sender_id=f"account:{owner.account_id}:{conversation_id}",
            chat_id="",
            content="",
            raw={
                "event": "conversation_deleted", "conversation_id": conversation_id,
                "tenant_id": owner.tenant_id, "account_id": owner.account_id,
            },
        ))

    async def start(self) -> None:
        self._app = self.create_app()
        config = uvicorn.Config(self._app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        print(f"[CustomerPortal] 正在启动客户门户: http://{self.host}:{self.port}")
        await self._server.serve()

    async def send(self, message: OutboundMessage) -> None:
        """Return an Agent response only to the socket still showing that conversation."""
        websocket = self._connections.get(message.chat_id)
        if websocket is None:
            return
        if message.conversation_id and self._bindings.get(message.chat_id) != message.conversation_id:
            return
        if message.request_id and message.request_id not in self._active_requests.get(message.chat_id, set()):
            return
        try:
            if message.event_type != "assistant.message":
                payload = {
                    "type": message.event_type, "protocol_version": 2,
                    "conversation_id": message.conversation_id,
                    "request_id": message.request_id,
                }
                if message.error_code:
                    payload["code"] = message.error_code
                await websocket.send_json(payload)
                if message.request_id:
                    active = self._active_requests.get(message.chat_id)
                    if active is not None:
                        active.discard(message.request_id)
                        if not active: self._active_requests.pop(message.chat_id, None)
                return
            owner = self._connection_owners.get(message.chat_id)
            if owner is not None and message.conversation_id:
                self._conversation_repository.append_message(
                    owner, message.conversation_id, role="assistant", content=message.content,
                    request_id=message.request_id,
                )
            await websocket.send_json({
                "type": "assistant.message",
                "protocol_version": 2,
                "conversation_id": message.conversation_id,
                "request_id": message.request_id,
                "content": message.content,
            })
            if message.request_id:
                active = self._active_requests.get(message.chat_id)
                if active is not None:
                    active.discard(message.request_id)
                    if not active: self._active_requests.pop(message.chat_id, None)
        except Exception as exc:
            print(f"[CustomerPortal] 回复发送失败: chat_id={message.chat_id} reason={exc}")
            self._connections.pop(message.chat_id, None)
            self._bindings.pop(message.chat_id, None)
            self._connection_owners.pop(message.chat_id, None)
            self._active_requests.pop(message.chat_id, None)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
            self._server = None
        for websocket in list(self._connections.values()):
            try:
                await websocket.close()
            except Exception:
                pass
        self._connections.clear()
        self._bindings.clear()
        self._connection_owners.clear()
        self._active_requests.clear()
        print("[CustomerPortal] 服务已停止")
