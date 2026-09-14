"""Small, strict HS256 JWT implementation with no optional runtime dependency."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .models import Principal


class JWTError(ValueError):
    def __init__(self, code: str = "access_token_invalid") -> None:
        self.code = code
        super().__init__(code)


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        if _encode(decoded) != value:
            raise JWTError()
        return decoded
    except Exception as exc:
        if isinstance(exc, JWTError):
            raise
        raise JWTError() from exc


def _json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"),
                      sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class JWTCodec:
    secret: bytes
    issuer: str = "nanoclaw"
    audience: str = "nanoclaw-api"
    lifetime_seconds: int = 900
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        if len(self.secret) < 32:
            raise ValueError("jwt_secret_must_be_at_least_32_bytes")
        if self.lifetime_seconds < 60:
            raise ValueError("jwt_lifetime_too_short")

    def issue(self, principal: Principal, *, now: int | None = None) -> str:
        issued_at = int(time.time() if now is None else now)
        token_id = principal.token_id or str(uuid.uuid4())
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": principal.user_id,
            "tenant_id": principal.tenant_id,
            "preferred_username": principal.username,
            "roles": sorted(principal.roles),
            "jti": token_id,
            "iat": issued_at,
            "nbf": issued_at,
            "exp": issued_at + self.lifetime_seconds,
            "token_use": "access",
        }
        signing_input = f"{_encode(_json(header))}.{_encode(_json(payload))}"
        signature = hmac.new(self.secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        return f"{signing_input}.{_encode(signature)}"

    def decode(self, token: str, *, now: int | None = None) -> Principal:
        if not isinstance(token, str) or len(token) > 8192:
            raise JWTError()
        parts = token.split(".")
        if len(parts) != 3 or not all(parts):
            raise JWTError()
        signing_input = f"{parts[0]}.{parts[1]}"
        expected = hmac.new(self.secret, signing_input.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode(parts[2])):
            raise JWTError()
        try:
            header = json.loads(_decode(parts[0]))
            payload = json.loads(_decode(parts[1]))
        except Exception as exc:
            raise JWTError() from exc
        if not isinstance(header, dict) or header != {"alg": "HS256", "typ": "JWT"}:
            raise JWTError()
        if not isinstance(payload, dict):
            raise JWTError()
        if (payload.get("iss") != self.issuer or payload.get("aud") != self.audience
                or payload.get("token_use") != "access"):
            raise JWTError()
        current = int(time.time() if now is None else now)
        for claim in ("iat", "nbf", "exp"):
            value = payload.get(claim)
            if isinstance(value, bool) or not isinstance(value, int):
                raise JWTError()
        if payload["iat"] > current + self.clock_skew_seconds:
            raise JWTError()
        if payload["nbf"] > current + self.clock_skew_seconds:
            raise JWTError("access_token_not_yet_valid")
        if payload["exp"] <= current - self.clock_skew_seconds:
            raise JWTError("access_token_expired")
        roles = payload.get("roles")
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise JWTError()
        try:
            return Principal(
                user_id=str(payload.get("sub") or ""),
                tenant_id=str(payload.get("tenant_id") or ""),
                username=str(payload.get("preferred_username") or ""),
                roles=frozenset(roles),
                token_id=str(payload.get("jti") or ""),
                expires_at=payload["exp"],
            )
        except ValueError as exc:
            raise JWTError() from exc
