"""MySQL customer identity and authentication-session repository."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from .models import AuthRecord, AuthenticatedCustomer, CustomerAccount, CustomerAuthSession
from .repository import utcnow


class MySQLCustomerIdentityRepository:
    def __init__(self, connection_factory=None) -> None:
        if connection_factory is None:
            from agent.business.mysql_database import create_connection
            connection_factory = create_connection
        self._connection_factory = connection_factory

    @contextmanager
    def _tx(self) -> Iterator[Any]:
        connection = self._connection_factory()
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _account(row: dict[str, Any]) -> CustomerAccount:
        return CustomerAccount(
            row["account_id"], row["tenant_id"], row["account_status"],
            row["account_preferred_locale"], row["account_created_at"],
            row["account_updated_at"], row.get("account_last_login_at"),
            row.get("account_deleted_at"), int(row["account_version"]),
        )

    def create_account(
        self, *, tenant_id: str, identifier_type: str, identifier_normalized: str,
        credential_hash: str, preferred_locale: str,
    ) -> CustomerAccount:
        now, account_id = utcnow(), str(uuid.uuid4())
        account = CustomerAccount(account_id, tenant_id, "active", preferred_locale, now, now)
        with self._tx() as cursor:
            cursor.execute(
                """INSERT INTO customer_account
                   (account_id,tenant_id,status,preferred_locale,created_at,updated_at,
                    last_login_at,deleted_at,version) VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,1)""",
                (account_id, tenant_id, "active", preferred_locale, now, now),
            )
            cursor.execute(
                """INSERT INTO customer_auth_identity
                   (identity_id,account_id,tenant_id,identifier_type,identifier_normalized,
                    credential_hash,failed_attempts,locked_until,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,0,NULL,%s,%s)""",
                (str(uuid.uuid4()), account_id, tenant_id, identifier_type,
                 identifier_normalized, credential_hash, now, now),
            )
        return account

    def get_auth_record(self, tenant_id: str, identifier_type: str,
                        identifier_normalized: str) -> AuthRecord | None:
        with self._tx() as cursor:
            cursor.execute(
                """SELECT i.*,a.status AS account_status,
                          a.preferred_locale AS account_preferred_locale,
                          a.created_at AS account_created_at,a.updated_at AS account_updated_at,
                          a.last_login_at AS account_last_login_at,
                          a.deleted_at AS account_deleted_at,a.version AS account_version
                   FROM customer_auth_identity i JOIN customer_account a
                     ON a.account_id=i.account_id AND a.tenant_id=i.tenant_id
                   WHERE i.tenant_id=%s AND i.identifier_type=%s AND i.identifier_normalized=%s""",
                (tenant_id, identifier_type, identifier_normalized),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return AuthRecord(
            row["identity_id"], self._account(row), row["identifier_type"],
            row["identifier_normalized"], row["credential_hash"],
            int(row["failed_attempts"]), row.get("locked_until"),
        )

    def record_login_failure(self, identity_id: str, *, lock_after: int,
                             locked_until: str) -> None:
        with self._tx() as cursor:
            cursor.execute(
                """UPDATE customer_auth_identity SET failed_attempts=failed_attempts+1,
                   locked_until=CASE WHEN failed_attempts+1>=%s THEN %s ELSE locked_until END,
                   updated_at=%s WHERE identity_id=%s""",
                (lock_after, locked_until, utcnow(), identity_id),
            )

    def record_login_success(self, account_id: str, identity_id: str) -> None:
        now = utcnow()
        with self._tx() as cursor:
            cursor.execute(
                "UPDATE customer_auth_identity SET failed_attempts=0,locked_until=NULL,updated_at=%s WHERE identity_id=%s",
                (now, identity_id),
            )
            cursor.execute(
                "UPDATE customer_account SET last_login_at=%s,updated_at=%s WHERE account_id=%s",
                (now, now, account_id),
            )

    def create_session(self, session: CustomerAuthSession) -> None:
        with self._tx() as cursor:
            cursor.execute(
                """INSERT INTO customer_auth_session
                   (session_id,account_id,tenant_id,token_hash,csrf_hash,created_at,last_seen_at,
                    idle_expires_at,absolute_expires_at,revoked_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                tuple(session.__dict__.values()),
            )

    def resolve_active(self, hashed_token: str, now: str) -> AuthenticatedCustomer | None:
        with self._tx() as cursor:
            cursor.execute(
                """SELECT s.*,a.preferred_locale,a.status FROM customer_auth_session s
                   JOIN customer_account a ON a.account_id=s.account_id AND a.tenant_id=s.tenant_id
                   WHERE s.token_hash=%s AND s.revoked_at IS NULL AND s.idle_expires_at>%s
                     AND s.absolute_expires_at>%s AND a.status='active' FOR UPDATE""",
                (hashed_token, now, now),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            cursor.execute(
                "UPDATE customer_auth_session SET last_seen_at=%s WHERE session_id=%s",
                (now, row["session_id"]),
            )
        return AuthenticatedCustomer(
            row["session_id"], row["account_id"], row["tenant_id"],
            row["preferred_locale"], row["csrf_hash"],
        )

    def resolve_account(self, tenant_id: str, account_id: str) -> AuthenticatedCustomer | None:
        with self._tx() as cursor:
            cursor.execute(
                """SELECT account_id,tenant_id,preferred_locale FROM customer_account
                   WHERE tenant_id=%s AND account_id=%s AND status='active'""",
                (tenant_id, account_id),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return AuthenticatedCustomer(
            "jwt", row["account_id"], row["tenant_id"], row["preferred_locale"], "",
        )

    def revoke(self, session_id: str, now: str) -> None:
        with self._tx() as cursor:
            cursor.execute(
                "UPDATE customer_auth_session SET revoked_at=COALESCE(revoked_at,%s) WHERE session_id=%s",
                (now, session_id),
            )

    def revoke_account(self, tenant_id: str, account_id: str, now: str) -> int:
        with self._tx() as cursor:
            cursor.execute(
                """UPDATE customer_auth_session SET revoked_at=COALESCE(revoked_at,%s)
                   WHERE tenant_id=%s AND account_id=%s AND revoked_at IS NULL""",
                (now, tenant_id, account_id),
            )
            return int(cursor.rowcount or 0)
