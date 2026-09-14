"""Configuration owned by the standalone employee Agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class EmployeeAgentSettings:
    checkpoint_backend: str = "redis"
    checkpoint_path: str = "workspace/internal_agent/checkpoints.sqlite3"
    redis_url: str = "redis://127.0.0.1:6379/1"
    checkpoint_ttl_minutes: int = 10080
    redis_connect_timeout_seconds: float = 5.0

    @classmethod
    def from_environment(cls, workspace: str = ".") -> "EmployeeAgentSettings":
        backend = os.environ.get(
            "EMPLOYEE_AGENT_CHECKPOINT_BACKEND", "redis",
        ).strip().lower()
        if backend not in {"redis", "sqlite", "off"}:
            raise ValueError(
                "EMPLOYEE_AGENT_CHECKPOINT_BACKEND must be redis, sqlite or off"
            )
        configured = os.environ.get(
            "EMPLOYEE_AGENT_CHECKPOINT_PATH",
            "workspace/internal_agent/checkpoints.sqlite3",
        ).strip()
        if backend == "sqlite" and not configured:
            raise ValueError("employee Agent SQLite checkpoint path is required")
        path = Path(configured)
        if not path.is_absolute():
            path = Path(workspace) / path
        redis_url = os.environ.get(
            "EMPLOYEE_AGENT_REDIS_URL", "redis://127.0.0.1:6379/1",
        ).strip()
        parsed = urlparse(redis_url)
        if backend == "redis" and (
            parsed.scheme not in {"redis", "rediss"} or not parsed.hostname
        ):
            raise ValueError("employee Agent Redis URL must use redis:// or rediss://")
        ttl_minutes = 10080
        timeout_seconds = 5.0
        if backend == "redis":
            try:
                ttl_minutes = int(os.environ.get(
                    "EMPLOYEE_AGENT_CHECKPOINT_TTL_MINUTES", "10080",
                ))
            except ValueError as exc:
                raise ValueError(
                    "employee Agent checkpoint TTL must be an integer"
                ) from exc
            if ttl_minutes <= 0:
                raise ValueError("employee Agent checkpoint TTL must be positive")
            try:
                timeout_seconds = float(os.environ.get(
                    "EMPLOYEE_AGENT_REDIS_CONNECT_TIMEOUT_SECONDS", "5",
                ))
            except ValueError as exc:
                raise ValueError("employee Agent Redis timeout must be numeric") from exc
            if timeout_seconds <= 0:
                raise ValueError("employee Agent Redis timeout must be positive")
        return cls(
            backend,
            str(path.resolve()),
            redis_url,
            ttl_minutes,
            timeout_seconds,
        )

    @property
    def persistent_checkpoint_path(self) -> str | None:
        return self.checkpoint_path if self.checkpoint_backend == "sqlite" else None

    @property
    def checkpoint_redis_url(self) -> str | None:
        return self.redis_url if self.checkpoint_backend == "redis" else None
