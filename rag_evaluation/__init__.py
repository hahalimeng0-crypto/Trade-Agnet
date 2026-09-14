"""Versioned, privacy-aware evaluation framework for the trade RAG system."""

from .contracts import EvaluationCase, EvaluationReport
from .dataset import load_dataset
from .runner import EvaluationRunner

__all__ = ["EvaluationCase", "EvaluationReport", "EvaluationRunner", "load_dataset"]
