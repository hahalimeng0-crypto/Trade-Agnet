"""Unified employee/customer-capable local identity service and refresh sessions."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .jwt import JWTCodec
from .models import Principal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class IdentityError(ValueError):
    STATUS = {
        "authentication_failed": 401,
        "authentication_required": 401,
        "refresh_token_invalid": 401,
        "account_disabled": 403,
        "identity_conflict": 409,
        "identity_input_invalid": 422,
    }

    def __init__(self, code: str) -> None:
        self.code = code
        self.status_code = self.STATUS.get(code, 400)
        super().__init__(code)


class ScryptPasswordHasher:
    """Versioned stdlib password hashes; parameters are stored with each digest."""

    n = 2 ** 14
    r = 8
    p = 1

    def hash(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=self.n, r=self.r, p=self.p, dklen=32)
        return f"scrypt${self.n}${self.r}${self.p}${salt.hex()}${digest.hex()}"

    def verify(self, encoded: str, password: str) -> bool:
        try:
            algorithm, raw_n, raw_r, raw_p, raw_salt, raw_digest = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            n, r, p = int(raw_n), int(raw_r), int(raw_p)
            if n > 2 ** 16 or r > 16 or p > 4:
                return False
            digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(raw_salt),
                                    n=n, r=r, p=p, dklen=32)
            return hmac.compare_digest(digest, bytes.fromhex(raw_digest))
        except (ValueError, TypeError):
            return False


@dataclass(frozen=True)
class AccessUser:
    user_id: str
    tenant_id: str
    username: str
    password_hash: str
    roles: frozenset[str]
    status: str = "active"

    def principal(self) -> Principal:
        return Principal(self.user_id, self.tenant_id, self.username, self.roles)


@dataclass(frozen=True)
class IssuedTokens:
    principal: Principal
    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_at: str
    refresh_expires_in: int


class IdentityRepository:
    def __init__(self, database: str | Path | sqlite3.Connection) -> None:
        if isinstance(database, sqlite3.Connection):
            self.connection = database
        else:
            path = Path(database)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self.connection:
            self.connection.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS access_user (
                  user_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  username_normalized TEXT NOT NULL,
                  username_display TEXT NOT NULL,
                  password_hash TEXT NOT NULL,
                  roles_json TEXT NOT NULL,
                  status TEXT NOT NULL CHECK(status IN ('active','disabled')),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(tenant_id, username_normalized)
                );
                CREATE TABLE IF NOT EXISTS access_refresh_session (
                  session_id TEXT PRIMARY KEY,
                  user_id TEXT NOT NULL,
                  token_hash TEXT NOT NULL UNIQUE,
                  created_at TEXT NOT NULL,
                  expires_at TEXT NOT NULL,
                  revoked_at TEXT,
                  replaced_by TEXT,
                  FOREIGN KEY(user_id) REFERENCES access_user(user_id)
                );
                CREATE INDEX IF NOT EXISTS idx_access_refresh_user
                  ON access_refresh_session(user_id, revoked_at, expires_at);
            """)

    @staticmethod
    def _user(row: sqlite3.Row | None) -> AccessUser | None:
        if row is None:
            return None
        roles = json.loads(row["roles_json"])
        return AccessUser(row["user_id"], row["tenant_id"], row["username_display"],
                          row["password_hash"], frozenset(roles), row["status"])

    def create_user(self, *, tenant_id: str, username: str, password_hash: str,
                    roles: frozenset[str]) -> AccessUser:
        normalized = username.strip().casefold()
        now = _iso(_now())
        user = AccessUser(str(uuid.uuid4()), tenant_id, username.strip(), password_hash, roles)
        try:
            with self._lock, self.connection:
                self.connection.execute(
                    """INSERT INTO access_user
                       (user_id,tenant_id,username_normalized,username_display,password_hash,
                        roles_json,status,created_at,updated_at)
                       VALUES (?,?,?,?,?,?,'active',?,?)""",
                    (user.user_id, tenant_id, normalized, user.username, password_hash,
                     json.dumps(sorted(roles)), now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise IdentityError("identity_conflict") from exc
        return user

    def get_by_username(self, tenant_id: str, username: str) -> AccessUser | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM access_user WHERE tenant_id=? AND username_normalized=?",
                (tenant_id, username.strip().casefold()),
            ).fetchone()
        return self._user(row)

    def get_by_id(self, user_id: str) -> AccessUser | None:
        with self._lock:
            row = self.connection.execute(
                "SELECT * FROM access_user WHERE user_id=?", (user_id,),
            ).fetchone()
        return self._user(row)

    def create_refresh(self, *, user_id: str, token: str, expires_at: str) -> str:
        session_id = str(uuid.uuid4())
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO access_refresh_session VALUES (?,?,?,?,?,NULL,NULL)",
                (session_id, user_id, _token_hash(token), _iso(_now()), expires_at),
            )
        return session_id

    def consume_refresh(self, token: str, *, replacement_id: str | None = None) -> AccessUser | None:
        now = _iso(_now())
        with self._lock, self.connection:
            row = self.connection.execute(
                """SELECT s.session_id,s.user_id FROM access_refresh_session s
                   WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?""",
                (_token_hash(token), now),
            ).fetchone()
            if row is None:
                return None
            changed = self.connection.execute(
                """UPDATE access_refresh_session SET revoked_at=?,replaced_by=?
                   WHERE session_id=? AND revoked_at IS NULL""",
                (now, replacement_id, row["session_id"]),
            ).rowcount
            if changed != 1:
                return None
        return self.get_by_id(row["user_id"])

    def revoke_refresh(self, token: str) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                """UPDATE access_refresh_session SET revoked_at=COALESCE(revoked_at,?)
                   WHERE token_hash=?""",
                (_iso(_now()), _token_hash(token)),
            )


class IdentityService:
    def __init__(self, repository: IdentityRepository, password_hasher: ScryptPasswordHasher,
                 jwt_codec: JWTCodec, *, tenant_id: str = "default",
                 refresh_days: int = 7) -> None:
        self.repository = repository
        self.password_hasher = password_hasher
        self.jwt_codec = jwt_codec
        self.tenant_id = tenant_id
        self.refresh_days = refresh_days

    @staticmethod
    def _validate(username: str, password: str, roles: frozenset[str] | None = None) -> None:
        if (not username.strip() or len(username) > 254 or len(password) < 12
                or len(password) > 256 or (roles is not None and not roles)):
            raise IdentityError("identity_input_invalid")

    def provision_user(self, username: str, password: str, roles: frozenset[str]) -> AccessUser:
        self._validate(username, password, roles)
        return self.repository.create_user(
            tenant_id=self.tenant_id, username=username,
            password_hash=self.password_hasher.hash(password), roles=roles,
        )

    def login(self, username: str, password: str) -> IssuedTokens:
        if not username.strip() or not password:
            raise IdentityError("authentication_failed")
        user = self.repository.get_by_username(self.tenant_id, username)
        if user is None or not self.password_hasher.verify(user.password_hash, password):
            raise IdentityError("authentication_failed")
        if user.status != "active":
            raise IdentityError("account_disabled")
        return self._issue(user)

    def _issue(self, user: AccessUser) -> IssuedTokens:
        principal = user.principal()
        access = self.jwt_codec.issue(principal)
        refresh = secrets.token_urlsafe(48)
        expires = _now() + timedelta(days=self.refresh_days)
        self.repository.create_refresh(
            user_id=user.user_id, token=refresh, expires_at=_iso(expires),
        )
        return IssuedTokens(
            principal, access, refresh, self.jwt_codec.lifetime_seconds,
            _iso(expires), self.refresh_days * 24 * 3600,
        )

    def refresh(self, refresh_token: str) -> IssuedTokens:
        user = self.repository.consume_refresh(refresh_token)
        if user is None or user.status != "active":
            raise IdentityError("refresh_token_invalid")
        return self._issue(user)

    def logout(self, refresh_token: str | None) -> None:
        if refresh_token:
            self.repository.revoke_refresh(refresh_token)

    def authenticate_access(self, token: str) -> Principal:
        principal = self.jwt_codec.decode(token)
        user = self.repository.get_by_id(principal.user_id)
        if user is None or user.status != "active" or user.tenant_id != principal.tenant_id:
            raise IdentityError("authentication_required")
        if user.roles != principal.roles:
            raise IdentityError("authentication_required")
        return principal
