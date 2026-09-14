import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent.access_control.identity import (
    IdentityError,
    IdentityRepository,
    IdentityService,
    ScryptPasswordHasher,
)
from agent.access_control.jwt import JWTCodec, JWTError
from agent.access_control.models import Principal
from channels.access_auth_api import create_access_auth_router


SECRET = b"test-secret-that-is-at-least-thirty-two-bytes"


def principal(*roles: str) -> Principal:
    return Principal("user-1", "tenant-1", "user@example.com", frozenset(roles))


def build_identity():
    repository = IdentityRepository(sqlite3.connect(":memory:", check_same_thread=False))
    codec = JWTCodec(SECRET, lifetime_seconds=300, clock_skew_seconds=0)
    return IdentityService(
        repository, ScryptPasswordHasher(), codec, tenant_id="tenant-1", refresh_days=1,
    ), codec


def test_jwt_rejects_tampering_expiry_and_wrong_audience():
    codec = JWTCodec(SECRET, lifetime_seconds=60, clock_skew_seconds=0)
    token = codec.issue(principal("customer"), now=1_000)
    decoded = codec.decode(token, now=1_001)
    assert decoded.roles == frozenset({"customer"})
    changed = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(JWTError):
        codec.decode(changed, now=1_001)
    with pytest.raises(JWTError, match="access_token_expired"):
        codec.decode(token, now=1_060)
    with pytest.raises(JWTError):
        JWTCodec(SECRET, audience="other", lifetime_seconds=60).decode(token, now=1_001)


def test_identity_login_refresh_rotation_and_http_bearer_flow():
    service, _ = build_identity()
    user = service.provision_user(
        "sales@example.com", "correct horse battery", frozenset({"sales"}),
    )
    issued = service.login("SALES@example.com", "correct horse battery")
    assert service.authenticate_access(issued.access_token).user_id == user.user_id
    rotated = service.refresh(issued.refresh_token)
    assert rotated.refresh_token != issued.refresh_token
    with pytest.raises(IdentityError, match="refresh_token_invalid"):
        service.refresh(issued.refresh_token)

    app = FastAPI()
    app.include_router(create_access_auth_router(service))
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={
            "username": "sales@example.com", "password": "correct horse battery",
        })
        assert login.status_code == 200
        body = login.json()
        assert body["token_type"] == "Bearer"
        assert body["user"]["roles"] == ["sales"]
        me = client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {body['access_token']}"
        })
        assert me.status_code == 200
        assert me.json()["user_id"] == user.user_id
