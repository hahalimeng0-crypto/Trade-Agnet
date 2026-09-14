"""Permission-scoped cache and rate limiting for customer product queries."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Protocol


class ProductCache(Protocol):
    async def get(self, key: str) -> dict[str, Any] | None: ...
    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None: ...
    async def allow(self, subject: str, limit: int, window_seconds: int) -> bool: ...


@dataclass
class _Entry:
    expires_at: float
    value: dict[str, Any]


class InMemoryProductCache:
    """Safe local fallback. Production can use the same contract with Redis."""

    def __init__(self) -> None:
        self._values: dict[str, _Entry] = {}
        self._rates: dict[str, list[float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> dict[str, Any] | None:
        async with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            if item.expires_at <= time.monotonic():
                self._values.pop(key, None)
                return None
            return json.loads(json.dumps(item.value, ensure_ascii=False))

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        async with self._lock:
            self._values[key] = _Entry(
                time.monotonic() + max(1, int(ttl_seconds)),
                json.loads(json.dumps(value, ensure_ascii=False)),
            )

    async def allow(self, subject: str, limit: int, window_seconds: int) -> bool:
        now = time.monotonic()
        cutoff = now - max(1, int(window_seconds))
        async with self._lock:
            values = [value for value in self._rates.get(subject, []) if value > cutoff]
            if len(values) >= max(1, int(limit)):
                self._rates[subject] = values
                return False
            values.append(now)
            self._rates[subject] = values
            return True


class RedisProductCache:
    def __init__(self, url: str, *, prefix: str = "nanoclaw:customer-product") -> None:
        from redis.asyncio import Redis

        self.client = Redis.from_url(url, encoding="utf-8", decode_responses=True)
        self.prefix = prefix.strip(":") or "nanoclaw:customer-product"

    def _key(self, kind: str, value: str) -> str:
        return f"{self.prefix}:{kind}:{value}"

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self.client.get(self._key("cache", key))
        if raw is None:
            return None
        value = json.loads(raw)
        return value if isinstance(value, dict) else None

    async def set(self, key: str, value: dict[str, Any], ttl_seconds: int) -> None:
        await self.client.set(
            self._key("cache", key),
            json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            ex=max(1, int(ttl_seconds)),
        )

    async def allow(self, subject: str, limit: int, window_seconds: int) -> bool:
        key = self._key("rate", subject)
        count = await self.client.incr(key)
        if count == 1:
            await self.client.expire(key, max(1, int(window_seconds)))
        return int(count) <= max(1, int(limit))


def create_product_cache(url: str, *, prefix: str) -> ProductCache:
    return RedisProductCache(url, prefix=prefix) if url.strip() else InMemoryProductCache()
