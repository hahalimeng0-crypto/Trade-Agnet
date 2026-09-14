from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_rag.pipeline import RagPipeline

from .dataset import load_dataset
from .fixture_corpus import load_fixture_pipeline
from .runner import EvaluationRunner, load_thresholds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the external-trade RAG evaluation gate")
    parser.add_argument("dataset", nargs="+", type=Path)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--split", choices=("dev", "test", "challenge"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fixture-corpus", type=Path,
                        help="use an isolated de-identified JSONL corpus")
    parser.add_argument("--thresholds", type=Path,
                        help="versioned trade-rag-thresholds-v1 configuration")
    args = parser.parse_args(argv)
    cases = load_dataset(args.dataset, split=args.split)
    pipeline = (load_fixture_pipeline(args.fixture_corpus) if args.fixture_corpus
                else RagPipeline())
    threshold_id, thresholds = (load_thresholds(args.thresholds)
                                if args.thresholds else ("builtin-v1", None))
    report = EvaluationRunner(
        pipeline.query,
        thresholds=thresholds,
        runtime_metadata={
            "embedding_model": pipeline.embedder.model_id,
            "reranker_model": pipeline.reranker.model_id,
            "generator_mode": "extractive_claims_v1",
            "threshold_config": threshold_id,
        },
    ).run(cases, dataset_version=args.dataset_version)
    report.write(args.output)
    print(json.dumps({"status": "passed" if report.passed else "failed",
                      "case_count": report.case_count,
                      "report": str(args.output)}, ensure_ascii=False))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
