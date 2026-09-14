from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from .contracts import EvaluationCase


def load_dataset(paths: str | Path | Iterable[str | Path], *, split: str | None = None,
                 risk_levels: set[str] | None = None) -> list[EvaluationCase]:
    """Load JSONL cases with duplicate IDs and schema errors rejected eagerly."""
    sources = [paths] if isinstance(paths, (str, Path)) else list(paths)
    cases: list[EvaluationCase] = []
    seen: set[str] = set()
    for source in sources:
        path = Path(source)
        default_split = path.parent.name if path.parent.name in {"dev", "test", "challenge"} else "dev"
        for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            try:
                value = json.loads(raw)
                case = EvaluationCase.from_dict(value, default_split=default_split)
            except Exception as exc:
                raise ValueError(f"{path}:{line_number}: {exc}") from exc
            if case.case_id in seen:
                raise ValueError(f"duplicate evaluation case_id: {case.case_id}")
            seen.add(case.case_id)
            if split is not None and case.split != split:
                continue
            if risk_levels is not None and case.risk_level not in risk_levels:
                continue
            cases.append(case)
    if not cases:
        raise ValueError("evaluation dataset is empty after filtering")
    return cases
