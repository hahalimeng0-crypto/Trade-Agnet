import asyncio
import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.access_control.identity import (
    IdentityRepository,
    IdentityService,
    ScryptPasswordHasher,
)
from agent.access_control.jwt import JWTCodec
from agent.access_control.models import Principal
from bus import InboundMessage, MessageBus
from channels.web import WebChannel
from gateway import Gateway
from llm_routing import (
    AgentRoute,
    AgentRouteAuthorizer,
    LLMRouteClassifier,
    RouteError,
)
from providers.base import LLMResponse
from session.conversation import ConversationService


class StubProvider:
    def __init__(self, content: str = "", *, fail_if_called: bool = False):
        self.content = content
        self.fail_if_called = fail_if_called
        self.calls = []

    async def chat(self, messages, tools=None, model=None):
        if self.fail_if_called:
            raise AssertionError("small model must not be called for a single allowed Agent")
        self.calls.append({"messages": messages, "tools": tools, "model": model})
        return LLMResponse(content=self.content)


class FailingProvider:
    async def chat(self, messages, tools=None, model=None):
        raise TimeoutError("router unavailable")


def trusted(user_id: str, *roles: str) -> dict:
    return Principal(
        user_id, "tenant-a", user_id, frozenset(roles),
    ).to_trusted_dict()


def test_customer_and_employee_accounts_have_strict_one_to_one_routes():
    provider = StubProvider(fail_if_called=True)
    classifier = LLMRouteClassifier(
        AgentRouteAuthorizer(), provider, model="small-router",
    )
    customer = Principal("customer-a", "tenant-a", "customer-a", frozenset({"customer"}))
    employee = Principal("employee-a", "tenant-a", "employee-a", frozenset({"employee"}))

    customer_route = asyncio.run(classifier.route(customer, "给我看内部成本和毛利"))
    employee_route = asyncio.run(classifier.route(employee, "这款产品怎么使用？"))

    assert customer_route.agent == AgentRoute.CUSTOMER_PRODUCT_CONSULTATION
    assert employee_route.agent == AgentRoute.INTERNAL_QUOTE_REPLY
    assert customer_route.source == employee_route.source == "rbac_single_route"
    assert provider.calls == []


def test_mixed_customer_and_employee_identity_is_rejected():
    principal = Principal(
        "mixed", "tenant-a", "mixed", frozenset({"customer", "employee"}),
    )
    with pytest.raises(RouteError, match="mixed_account_realm_forbidden"):
        AgentRouteAuthorizer().allowed_routes(principal)


def test_small_model_is_constrained_when_a_future_role_allows_multiple_agents():
    both = frozenset(AgentRoute)
    authorizer = AgentRouteAuthorizer(role_routes={"hybrid": both})
    principal = Principal("hybrid", "tenant-a", "hybrid", frozenset({"hybrid"}))
    provider = StubProvider('{"agent":"customer_product_consultation"}')
    classifier = LLMRouteClassifier(authorizer, provider, model="small-router")

    result = asyncio.run(classifier.route(principal, "推荐适合户外使用的产品"))

    assert result.agent == AgentRoute.CUSTOMER_PRODUCT_CONSULTATION
    assert result.source == "llm"
    assert len(provider.calls) == 1
    assert provider.calls[0]["model"] == "small-router"
    system = provider.calls[0]["messages"][0]["content"]
    assert all(route.value in system for route in both)


def test_invalid_small_model_output_falls_back_inside_allowed_set():
    both = frozenset(AgentRoute)
    authorizer = AgentRouteAuthorizer(role_routes={"hybrid": both})
    principal = Principal("hybrid", "tenant-a", "hybrid", frozenset({"hybrid"}))
    classifier = LLMRouteClassifier(
        authorizer, StubProvider('{"agent":"unauthorized_agent"}'), model="small-router",
    )

    result = asyncio.run(classifier.route(principal, "请核算成本、库存和报价草稿"))

    assert result.agent == AgentRoute.INTERNAL_QUOTE_REPLY
    assert result.source == "deterministic_fallback"


def test_small_model_failure_falls_back_inside_allowed_set():
    both = frozenset(AgentRoute)
    classifier = LLMRouteClassifier(
        AgentRouteAuthorizer(role_routes={"hybrid": both}),
        FailingProvider(), model="small-router",
    )
    principal = Principal("hybrid", "tenant-a", "hybrid", frozenset({"hybrid"}))

    result = asyncio.run(classifier.route(principal, "请准备内部报价草稿"))

    assert result.agent == AgentRoute.INTERNAL_QUOTE_REPLY
    assert result.source == "deterministic_fallback"


def test_gateway_dispatches_by_trusted_account_role_only():
    async def scenario():
        provider = StubProvider(fail_if_called=True)
        classifier = LLMRouteClassifier(
            AgentRouteAuthorizer(), provider, model="small-router",
        )
        bus = MessageBus()
        created = []

        class Agent:
            def __init__(self, selected):
                self.selected = selected
            async def run(self, _content):
                return self.selected

        def routed_factory(session_key, selected):
            created.append((session_key, selected))
            return Agent(selected)

        gateway = Gateway(
            bus, [], lambda _key: Agent("legacy"),
            route_classifier=classifier,
            routed_agent_factory=routed_factory,
        )
        consumer = asyncio.create_task(gateway._process_inbound())
        await bus.publish_inbound(InboundMessage(
            "customer_portal", "customer:c1", "socket-1", "内部报价",
            {"_principal": trusted("customer-a", "customer")},
        ))
        await bus.publish_inbound(InboundMessage(
            "web", "employee:c2", "socket-2", "产品说明",
            {"_principal": trusted("employee-a", "employee")},
        ))
        replies = [await asyncio.wait_for(bus.consume_outbound(), 1) for _ in range(2)]
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await gateway.shutdown()
        return created, replies, provider.calls

    created, replies, calls = asyncio.run(scenario())
    assert {selected for _, selected in created} == {
        AgentRoute.CUSTOMER_PRODUCT_CONSULTATION.value,
        AgentRoute.INTERNAL_QUOTE_REPLY.value,
    }
    assert {reply.content for reply in replies} == {
        AgentRoute.CUSTOMER_PRODUCT_CONSULTATION.value,
        AgentRoute.INTERNAL_QUOTE_REPLY.value,
    }
    assert calls == []


def test_gateway_fails_closed_without_trusted_principal():
    async def scenario():
        bus = MessageBus()

        class Agent:
            async def run(self, _content): return "should-not-run"

        gateway = Gateway(
            bus, [], lambda _key: Agent(),
            route_classifier=LLMRouteClassifier(
                AgentRouteAuthorizer(), StubProvider(fail_if_called=True),
                model="small-router",
            ),
            routed_agent_factory=lambda _key, _route: Agent(),
        )
        consumer = asyncio.create_task(gateway._process_inbound())
        await bus.publish_inbound(InboundMessage("web", "u", "s", "hello", {}))
        reply = await asyncio.wait_for(bus.consume_outbound(), 1)
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await gateway.shutdown()
        return reply

    reply = asyncio.run(scenario())
    assert reply.event_type == "error"
    assert reply.error_code == "authentication_required"


def test_internal_websocket_supplies_server_verified_employee_principal(tmp_path):
    repository = IdentityRepository(
        sqlite3.connect(":memory:", check_same_thread=False)
    )
    service = IdentityService(
        repository,
        ScryptPasswordHasher(),
        JWTCodec(b"routing-test-secret-that-is-at-least-32-bytes"),
        tenant_id="tenant-a",
    )
    user = service.provision_user(
        "employee@example.com", "correct horse battery", frozenset({"employee"}),
    )
    bus = MessageBus()
    channel = WebChannel(
        bus,
        conversation_service=ConversationService(tmp_path / "conversations"),
        access_service=service,
        access_control_enabled=True,
    )
    channel._app = FastAPI()
    channel._register_routes()

    with TestClient(channel._app) as client:
        login = client.post("/api/auth/login", json={
            "username": "employee@example.com",
            "password": "correct horse battery",
        })
        assert login.status_code == 200
        conversation = client.post(
            "/api/conversations", json={"title": "Routed"},
        ).json()
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({
                "type": "conversation.bind",
                "protocol_version": 2,
                "conversation_id": conversation["conversation_id"],
            })
            assert websocket.receive_json()["type"] == "conversation.bound"
            websocket.send_json({
                "type": "chat.message",
                "protocol_version": 2,
                "conversation_id": conversation["conversation_id"],
                "request_id": "00000000-0000-4000-8000-000000000010",
                "content": "prepare a quote",
            })
            inbound = None
            for _ in range(100):
                try:
                    inbound = bus.inbound_queue.get_nowait()
                    break
                except asyncio.QueueEmpty:
                    time.sleep(0.01)

    assert inbound is not None
    assert inbound.raw["_principal"]["user_id"] == user.user_id
    assert inbound.raw["_principal"]["roles"] == ["employee"]
