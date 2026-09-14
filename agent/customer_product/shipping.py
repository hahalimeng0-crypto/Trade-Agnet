"""Reserved shipping-provider boundary. No carrier call is implemented yet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ShippingProvider(Protocol):
    @property
    def available(self) -> bool: ...
    async def estimate(self, request: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SFInternationalProvider:
    """Configuration placeholder for a future official SF International API adapter."""

    api_base_url: str = ""
    api_key: str = ""
    monthly_account: str = ""

    @property
    def available(self) -> bool:
        # The production request/response signing protocol is intentionally not invented.
        return False

    async def estimate(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise RuntimeError("sf_international_provider_not_implemented")
