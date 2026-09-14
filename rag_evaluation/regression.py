from __future__ import annotations

from typing import Any


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any], *,
                    maximum_drop: float = 0.03) -> dict[str, Any]:
    """Detect metric and category regressions without reading raw questions or answers."""
    if baseline.get("schema_version") != candidate.get("schema_version"):
        raise ValueError("report schema versions differ")
    regressions = []
    baseline_metrics = baseline.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    for name, old in baseline_metrics.items():
        if name not in candidate_metrics:
            regressions.append({"metric": name, "reason": "missing_metric"})
            continue
        old_value = float(old.get("value", 0))
        new_value = float(candidate_metrics[name].get("value", 0))
        comparator = old.get("comparator", ">=")
        drop = ((old_value - new_value) if comparator != "<="
                else (new_value - old_value))
        if drop > maximum_drop:
            regressions.append({"metric": name, "baseline": old_value,
                                "candidate": new_value, "adverse_change": round(drop, 6)})
    return {
        "status": "failed" if regressions else "passed",
        "maximum_drop": maximum_drop,
        "regressions": regressions,
        "baseline_dataset_version": baseline.get("dataset_version"),
        "candidate_dataset_version": candidate.get("dataset_version"),
    }
