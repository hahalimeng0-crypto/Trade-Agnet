"""Trusted identity and Agent identifiers used by the authorization boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Principal:
    """A server-verified user. Never construct this from model or message text."""

    user_id: str
    tenant_id: str
    username: str
    roles: frozenset[str]
    token_id: str = ""
    expires_at: int | None = None

    def __post_init__(self) -> None:
        if not self.user_id or not self.tenant_id or not self.roles:
            raise ValueError("authenticated_principal_invalid")

    def to_trusted_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "roles": sorted(self.roles),
            "token_id": self.token_id,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_trusted_dict(cls, value: object) -> "Principal":
        if not isinstance(value, dict):
            raise ValueError("authenticated_principal_missing")
        roles = value.get("roles")
        if not isinstance(roles, (list, tuple, set, frozenset)):
            raise ValueError("authenticated_principal_roles_invalid")
        return cls(
            user_id=str(value.get("user_id") or ""),
            tenant_id=str(value.get("tenant_id") or ""),
            username=str(value.get("username") or ""),
            roles=frozenset(str(role) for role in roles if str(role)),
            token_id=str(value.get("token_id") or ""),
            expires_at=(int(value["expires_at"])
                        if value.get("expires_at") is not None else None),
        )
