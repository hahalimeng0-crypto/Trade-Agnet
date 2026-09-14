from __future__ import annotations

from typing import Iterable


def calibrate_binary_judge(human_labels: Iterable[bool], judge_labels: Iterable[bool],
                           *, minimum_kappa: float = 0.70,
                           maximum_false_support_rate: float = 0.02) -> dict:
    """Compare evidence-support judgments with reviewed human labels."""
    human = [bool(value) for value in human_labels]
    judge = [bool(value) for value in judge_labels]
    if not human or len(human) != len(judge):
        raise ValueError("human and judge labels must have the same non-zero length")
    tp = sum(h and j for h, j in zip(human, judge))
    tn = sum(not h and not j for h, j in zip(human, judge))
    fp = sum(not h and j for h, j in zip(human, judge))
    fn = sum(h and not j for h, j in zip(human, judge))
    total = len(human)
    observed = (tp + tn) / total
    human_positive = (tp + fn) / total
    judge_positive = (tp + fp) / total
    expected = (human_positive * judge_positive
                + (1 - human_positive) * (1 - judge_positive))
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    negative_count = tn + fp
    false_support_rate = fp / negative_count if negative_count else 0.0
    return {
        "sample_count": total,
        "accuracy": round(observed, 6),
        "precision": round(tp / (tp + fp), 6) if tp + fp else 0.0,
        "recall": round(tp / (tp + fn), 6) if tp + fn else 0.0,
        "cohen_kappa": round(kappa, 6),
        "false_support_rate": round(false_support_rate, 6),
        "ready_for_release_gate": (kappa >= minimum_kappa
                                   and false_support_rate <= maximum_false_support_rate),
        "thresholds": {"minimum_kappa": minimum_kappa,
                       "maximum_false_support_rate": maximum_false_support_rate},
    }
