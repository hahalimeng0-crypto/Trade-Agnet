"""Deterministic role-to-Agent allow-list evaluated before the LLM classifier."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.access_control.models import Principal

from .contracts import AgentRoute, RouteError


DEFAULT_ROLE_ROUTES: dict[str, frozenset[AgentRoute]] = {
    "customer": frozenset({AgentRoute.CUSTOMER_PRODUCT_CONSULTATION}),
    "sales": frozenset({
        AgentRoute.INTERNAL_QUOTE_REPLY,
    }),
    "employee": frozenset({
        AgentRoute.INTERNAL_QUOTE_REPLY,
    }),
    "quote_reviewer": frozenset({AgentRoute.INTERNAL_QUOTE_REPLY}),
    "admin": frozenset({AgentRoute.INTERNAL_QUOTE_REPLY}),
}


@dataclass(frozen=True)
class AgentRouteAuthorizer:
    role_routes: dict[str, frozenset[AgentRoute]] = field(
        default_factory=lambda: dict(DEFAULT_ROLE_ROUTES)
    )

    def allowed_routes(self, principal: Principal) -> frozenset[AgentRoute]:
        customer_identity = "customer" in principal.roles
        internal_identity = bool(
            {"employee", "sales", "quote_reviewer", "admin"} & principal.roles
        )
        if customer_identity and internal_identity:
            raise RouteError("mixed_account_realm_forbidden")
        allowed: set[AgentRoute] = set()
        for role in principal.roles:
            allowed.update(self.role_routes.get(role, ()))
        if not allowed:
            raise RouteError("no_agent_permission")
        return frozenset(allowed)

    def require_allowed(
        self, principal: Principal, selected: AgentRoute | str,
    ) -> AgentRoute:
        try:
            route = selected if isinstance(selected, AgentRoute) else AgentRoute(selected)
        except ValueError as exc:
            raise RouteError("agent_route_invalid") from exc
        if route not in self.allowed_routes(principal):
            raise RouteError("agent_access_denied")
        return route
