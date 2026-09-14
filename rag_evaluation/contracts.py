from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
import json


SCHEMA_VERSION = "trade-rag-evaluation-v1"
REPORT_SCHEMA_VERSION = "trade-rag-evaluation-report-v1"
RISK_LEVELS = {"low", "medium", "high", "critical"}
ROUTES = {"rag", "mysql", "calculator", "human_review"}


@dataclass(frozen=True)
class ExpectedCitation:
    document_id: str
    location: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExpectedCitation":
        document_id = str(value.get("document_id", "")).strip()
        if not document_id:
            raise ValueError("expected citation requires document_id")
        location = value.get("location")
        return cls(document_id, str(location).strip() if location else None)


@dataclass(frozen=True)
class ExpectedNumber:
    value: Decimal
    tolerance: Decimal = Decimal("0")
    unit: str | None = None
    currency: str | None = None
    label: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ExpectedNumber":
        return cls(
            value=Decimal(str(value["value"])),
            tolerance=Decimal(str(value.get("tolerance", "0"))),
            unit=str(value["unit"]).strip() if value.get("unit") else None,
            currency=str(value["currency"]).upper().strip()
            if value.get("currency") else None,
            label=str(value.get("label", "")).strip(),
        )


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    category: str
    question: str
    risk_level: str = "medium"
    split: str = "dev"
    actor_id: str = "evaluation"
    business_unit_id: str = "default"
    roles: tuple[str, ...] = ()
    expected_route: str | None = None
    expected_status: str | None = None
    expected_citations: tuple[ExpectedCitation, ...] = ()
    expected_facts: tuple[str, ...] = ()
    forbidden_claims: tuple[str, ...] = ()
    required_caveats: tuple[str, ...] = ()
    expected_numbers: tuple[ExpectedNumber, ...] = ()
    forbidden_document_ids: tuple[str, ...] = ()
    forbidden_actions: tuple[str, ...] = ()
    expected_no_citations: bool = False
    requires_human_confirmation: bool | None = None
    as_of: str | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, default_split: str = "dev") -> "EvaluationCase":
        if value.get("schema_version") not in (None, SCHEMA_VERSION):
            raise ValueError("unsupported evaluation case schema_version")
        actor = value.get("actor") or {}
        case_id = str(value.get("case_id", "")).strip()
        category = str(value.get("category", "")).strip()
        question = str(value.get("question", "")).strip()
        if not case_id or not category or not question:
            raise ValueError("case_id, category and question are required")
        risk = str(value.get("risk_level", "medium")).lower()
        if risk not in RISK_LEVELS:
            raise ValueError(f"unsupported risk_level: {risk}")
        route = value.get("expected_route")
        if route is not None and route not in ROUTES:
            raise ValueError(f"unsupported expected_route: {route}")
        return cls(
            case_id=case_id,
            category=category,
            question=question,
            risk_level=risk,
            split=str(value.get("split", default_split)),
            actor_id=str(actor.get("actor_id", "evaluation")),
            business_unit_id=str(actor.get("business_unit_id", "default")),
            roles=tuple(str(row) for row in actor.get("roles", [])),
            expected_route=route,
            expected_status=value.get("expected_status"),
            expected_citations=tuple(ExpectedCitation.from_dict(row)
                                     for row in value.get("expected_citations", [])),
            expected_facts=tuple(str(row) for row in value.get("expected_facts", [])),
            forbidden_claims=tuple(str(row) for row in value.get("forbidden_claims", [])),
            required_caveats=tuple(str(row) for row in value.get("required_caveats", [])),
            expected_numbers=tuple(ExpectedNumber.from_dict(row)
                                   for row in value.get("expected_numbers", [])),
            forbidden_document_ids=tuple(str(row) for row in
                                         value.get("forbidden_document_ids", [])),
            forbidden_actions=tuple(str(row) for row in value.get("forbidden_actions", [])),
            expected_no_citations=bool(value.get("expected_no_citations", False)),
            requires_human_confirmation=value.get("requires_human_confirmation"),
            as_of=str(value["as_of"]) if value.get("as_of") else None,
            tags=tuple(str(row) for row in value.get("tags", [])),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(frozen=True)
class MetricContribution:
    numerator: float
    denominator: float


@dataclass
class CaseAssessment:
    case_id: str
    category: str
    risk_level: str
    contributions: dict[str, MetricContribution] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class Threshold:
    value: float
    comparator: str = ">="
    hard_gate: bool = True

    def passes(self, actual: float) -> bool:
        if self.comparator == ">=":
            return actual >= self.value
        if self.comparator == "<=":
            return actual <= self.value
        if self.comparator == "==":
            return actual == self.value
        raise ValueError(f"unsupported comparator: {self.comparator}")


@dataclass
class EvaluationReport:
    dataset_version: str
    metrics: dict[str, dict[str, Any]]
    case_count: int
    failed_case_ids: list[str]
    failure_codes: dict[str, int]
    category_metrics: dict[str, dict[str, float]]
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = REPORT_SCHEMA_VERSION
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def passed(self) -> bool:
        hard = [row for row in self.metrics.values() if row.get("hard_gate")]
        return bool(hard) and all(row.get("passed") for row in hard)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "status": "passed" if self.passed else "failed",
                "production_ready": False,
                "production_readiness_requires": [
                    "approved_real_world_blind_set",
                    "human_calibrated_semantic_judge",
                    "real_embedding_reranker_and_generator_run",
                    "site_acceptance_and_monitoring",
                ]}

    def write(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.as_dict(), ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n"
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(target)
        return target
