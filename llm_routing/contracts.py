"""Contracts for routing without depending on either Agent implementation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AgentRoute(StrEnum):
    CUSTOMER_PRODUCT_CONSULTATION = "customer_product_consultation"
    INTERNAL_QUOTE_REPLY = "internal_quote_reply"


class RouteError(PermissionError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RouteDecision:
    agent: AgentRoute
    source: str
