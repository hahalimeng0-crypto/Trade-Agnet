"""Trusted request identity used by customer product tools."""

from __future__ import annotations

from dataclasses import dataclass

from agent.access_control.models import Principal


@dataclass(frozen=True)
class CustomerAccessContext:
    principal: Principal
    customer_level: str
    default_region: str
    default_currency: str
    locale: str
    authenticated: bool = True

    @property
    def account_id(self) -> str:
        return self.principal.user_id


class CustomerContextBinding:
    """Per-Agent request binding. Model arguments can never replace this value."""

    def __init__(
        self, *, allow_anonymous: bool = False, default_tenant: str = "default",
        customer_level: str = "standard", default_region: str = "GLOBAL",
        default_currency: str = "USD",
    ) -> None:
        self.allow_anonymous = bool(allow_anonymous)
        self.default_tenant = default_tenant.strip() or "default"
        self.customer_level = customer_level.strip().lower() or "standard"
        self.default_region = default_region.strip().upper() or "GLOBAL"
        self.default_currency = default_currency.strip().upper() or "USD"
        self._current: CustomerAccessContext | None = None

    def bind(self, request_context: dict | None) -> None:
        trusted = dict(request_context or {})
        raw_principal = trusted.get("_principal")
        authenticated = raw_principal is not None
        if authenticated:
            principal = Principal.from_trusted_dict(raw_principal)
            if principal.roles != frozenset({"customer"}):
                raise ValueError("customer_principal_role_invalid")
            supplied_tenant = str(trusted.get("tenant_id") or principal.tenant_id)
            supplied_account = str(trusted.get("account_id") or principal.user_id)
            if supplied_tenant != principal.tenant_id or supplied_account != principal.user_id:
                raise ValueError("customer_principal_scope_mismatch")
        elif self.allow_anonymous:
            principal = Principal(
                "anonymous", self.default_tenant, "anonymous", frozenset({"customer"}),
            )
        else:
            self._current = None
            raise ValueError("authenticated_principal_missing")
        locale = str(trusted.get("language") or "en")
        if locale not in {"zh", "en", "de"}:
            locale = "en"
        self._current = CustomerAccessContext(
            principal=principal,
            customer_level=self.customer_level,
            default_region=self.default_region,
            default_currency=self.default_currency,
            locale=locale,
            authenticated=authenticated,
        )

    def require(self) -> CustomerAccessContext:
        if self._current is None:
            raise PermissionError("customer_authentication_required")
        return self._current
