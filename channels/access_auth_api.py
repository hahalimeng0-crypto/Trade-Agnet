"""HTTP login/refresh/logout API for JWT access control."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from agent.access_control.identity import IdentityError, IdentityService, IssuedTokens
from agent.access_control.jwt import JWTError


ACCESS_COOKIE = "nanoclaw_access_token"
REFRESH_COOKIE = "nanoclaw_refresh_token"


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class RefreshPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str | None = Field(default=None, max_length=512)


def _public(tokens: IssuedTokens) -> dict:
    return {
        "access_token": tokens.access_token,
        "token_type": "Bearer",
        "expires_in": tokens.access_expires_in,
        "user": {
            "user_id": tokens.principal.user_id,
            "tenant_id": tokens.principal.tenant_id,
            "username": tokens.principal.username,
            "roles": sorted(tokens.principal.roles),
        },
    }


def _set_cookies(response: Response, request: Request, tokens: IssuedTokens) -> None:
    secure = request.url.scheme == "https"
    response.set_cookie(
        ACCESS_COOKIE, tokens.access_token, httponly=True, secure=secure,
        samesite="strict", max_age=tokens.access_expires_in,
    )
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token, httponly=True, secure=secure,
        samesite="strict", max_age=tokens.refresh_expires_in,
    )


def bearer_token(headers, cookies) -> str | None:
    scheme, separator, token = headers.get("authorization", "").partition(" ")
    if separator and scheme.casefold() == "bearer" and token:
        return token
    return cookies.get(ACCESS_COOKIE)


def create_access_auth_router(service: IdentityService) -> APIRouter:
    router = APIRouter(prefix="/api/auth", tags=["access-auth"])

    @router.post("/login")
    async def login(payload: LoginPayload, request: Request, response: Response):
        try:
            tokens = service.login(payload.username, payload.password)
        except IdentityError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        _set_cookies(response, request, tokens)
        return _public(tokens)

    @router.post("/refresh")
    async def refresh(payload: RefreshPayload, request: Request, response: Response):
        token = payload.refresh_token or request.cookies.get(REFRESH_COOKIE)
        try:
            tokens = service.refresh(token or "")
        except IdentityError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
        _set_cookies(response, request, tokens)
        return _public(tokens)

    @router.post("/logout", status_code=204)
    async def logout(payload: RefreshPayload, request: Request, response: Response):
        service.logout(payload.refresh_token or request.cookies.get(REFRESH_COOKIE))
        response.delete_cookie(ACCESS_COOKIE)
        response.delete_cookie(REFRESH_COOKIE)
        return Response(status_code=204, headers=response.headers)

    @router.get("/me")
    async def me(request: Request):
        token = bearer_token(request.headers, request.cookies)
        if not token:
            raise HTTPException(status_code=401, detail="authentication_required")
        try:
            principal = service.authenticate_access(token)
        except (IdentityError, JWTError) as exc:
            raise HTTPException(status_code=401, detail=getattr(exc, "code", "access_token_invalid")) from exc
        return principal.to_trusted_dict()

    return router
