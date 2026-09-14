from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


MONEY = Decimal("0.01")
INCOTERM_RULES = {
    "EXW": {"main_carriage": "buyer", "import_clearance": "buyer", "export_clearance": "buyer"},
    "FCA": {"main_carriage": "buyer", "import_clearance": "buyer", "export_clearance": "seller"},
    "FOB": {"main_carriage": "buyer", "import_clearance": "buyer", "export_clearance": "seller"},
    "CFR": {"main_carriage": "seller", "insurance": "buyer", "import_clearance": "buyer"},
    "CIF": {"main_carriage": "seller", "insurance": "seller", "import_clearance": "buyer"},
    "DAP": {"main_carriage": "seller", "import_clearance": "buyer", "unloading": "buyer"},
    "DPU": {"main_carriage": "seller", "import_clearance": "buyer", "unloading": "seller"},
    "DDP": {"main_carriage": "seller", "import_clearance": "seller", "import_duties": "seller"},
}


def _decimal(value: Any, field: str, failures: list[str]) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        failures.append(f"quote_invalid_decimal:{field}")
        return Decimal("0")


def validate_quote_payload(payload: dict[str, Any]) -> list[str]:
    """Recalculate quote invariants using Decimal; language-model judgment is forbidden."""
    failures: list[str] = []
    items = payload.get("items") or []
    calculated_subtotal = Decimal("0")
    for index, item in enumerate(items):
        quantity = _decimal(item.get("quantity"), f"items[{index}].quantity", failures)
        unit_price = _decimal(item.get("unit_price"), f"items[{index}].unit_price", failures)
        item_total = _decimal(item.get("total"), f"items[{index}].total", failures)
        expected = (quantity * unit_price).quantize(MONEY, rounding=ROUND_HALF_UP)
        if item_total != expected:
            failures.append(f"quote_item_total_mismatch:{index}")
        calculated_subtotal += expected
    subtotal = _decimal(payload.get("subtotal"), "subtotal", failures)
    calculated_subtotal = calculated_subtotal.quantize(MONEY, rounding=ROUND_HALF_UP)
    if subtotal != calculated_subtotal:
        failures.append("quote_subtotal_mismatch")
    discount_percent = _decimal(payload.get("discount_percent", 0),
                                "discount_percent", failures)
    discount = _decimal(payload.get("discount_amount", 0), "discount_amount", failures)
    expected_discount = (subtotal * discount_percent / Decimal("100")).quantize(
        MONEY, rounding=ROUND_HALF_UP)
    if discount != expected_discount:
        failures.append("quote_discount_mismatch")
    packaging = _decimal(payload.get("packaging_cost", 0), "packaging_cost", failures)
    freight = _decimal(payload.get("freight_cost", 0), "freight_cost", failures)
    total = _decimal(payload.get("total"), "total", failures)
    expected_total = (subtotal - discount + packaging + freight).quantize(
        MONEY, rounding=ROUND_HALF_UP)
    if total != expected_total:
        failures.append("quote_total_mismatch")
    if not str(payload.get("currency", "")).strip():
        failures.append("quote_currency_missing")
    if int(payload.get("validity_days", 0) or 0) <= 0:
        failures.append("quote_validity_invalid")
    return failures


def validate_incoterm_payload(payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    term = str(payload.get("incoterm", "")).upper()
    if term not in INCOTERM_RULES:
        return ["incoterm_unknown"]
    if not str(payload.get("named_place", "")).strip():
        failures.append("incoterm_named_place_missing")
    if not str(payload.get("version", "")).strip():
        failures.append("incoterm_version_missing")
    claimed = payload.get("responsibilities") or {}
    for field, expected in INCOTERM_RULES[term].items():
        if field in claimed and str(claimed[field]).casefold() != expected:
            failures.append(f"incoterm_responsibility_mismatch:{field}")
    return failures
