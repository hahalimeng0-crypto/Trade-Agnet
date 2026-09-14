from __future__ import annotations

import json
from pathlib import Path

import pytest

from rag_evaluation.business_rules import validate_incoterm_payload, validate_quote_payload
from rag_evaluation.calibration import calibrate_binary_judge
from rag_evaluation.contracts import EvaluationCase
from rag_evaluation.dataset import load_dataset
from rag_evaluation.fixture_corpus import load_fixture_pipeline
from rag_evaluation.judges import CompositeCaseJudge
from rag_evaluation.regression import compare_reports
from rag_evaluation.runner import EvaluationRunner, load_thresholds
from trade_rag.contracts import Actor, CanonicalDocument, ChildChunk, DocumentStatus, QueryRequest, SearchResult
from trade_rag.retrieval import QualityGate


FIXTURES = Path(__file__).parents[1] / "fixtures" / "rag_eval"


@pytest.mark.parametrize("split", ("dev", "challenge"))
def test_external_trade_fixture_release_gates_pass_and_remain_non_production(split):
    pipeline = load_fixture_pipeline(FIXTURES / "corpus_v1.jsonl")
    filename = ("external_trade_v1.jsonl" if split == "dev"
                else "external_trade_challenge_v1.jsonl")
    cases = load_dataset(FIXTURES / split / filename)
    report = EvaluationRunner(pipeline.query).run(cases, dataset_version=f"fixture-{split}-v1")
    payload = report.as_dict()
    assert report.passed
    assert payload["production_ready"] is False
    assert payload["failed_case_ids"] == []
    serialized = json.dumps(payload, ensure_ascii=False)
    assert all(case.question not in serialized for case in cases)


def test_evaluation_mode_is_opt_in_and_claims_are_bound_to_selected_evidence():
    pipeline = load_fixture_pipeline(FIXTURES / "corpus_v1.jsonl")
    actor = Actor("tester", frozenset({"sales"}))
    normal = pipeline.query(QueryRequest("BL-1001 MOQ", actor))
    evaluated = pipeline.query(QueryRequest("BL-1001 MOQ", actor, evaluation_mode=True))
    assert "claims" not in normal and "_evaluation_trace" not in normal
    assert evaluated["claims"] and evaluated["_evaluation_trace"]["selected_contexts"]
    citation_ids = {row["citation_id"] for row in evaluated["_evaluation_trace"]["selected_contexts"]}
    assert all(set(claim["citation_ids"]).issubset(citation_ids)
               for claim in evaluated["claims"])


def test_case_judge_detects_unsupported_claim_route_leak_and_action():
    case = EvaluationCase.from_dict({
        "case_id": "SAFETY-1", "category": "safety", "question": "q",
        "risk_level": "critical", "expected_route": "rag",
        "forbidden_document_ids": ["secret"], "forbidden_actions": ["send_quote"],
    })
    response = {
        "status": "ANSWERED", "answer": "invented", "citations": [
            {"document_id": "secret", "location": "page:1", "child_id": "c", "version": 1}
        ],
        "claims": [{"text": "invented", "citation_ids": ["public:1:page:1:c"]}],
        "actions": [{"name": "send_quote"}],
        "_evaluation_trace": {"route": "mysql", "selected_contexts": [
            {"citation_id": "public:1:page:1:c", "text": "different evidence"}
        ]},
    }
    assessment = CompositeCaseJudge().evaluate(case, response)
    assert {"route_mismatch", "unsupported_claim", "forbidden_document_disclosed",
            "forbidden_action_triggered"}.issubset(assessment.failures)


def test_quote_and_incoterm_rules_are_deterministic():
    quote = {
        "kind": "quote", "items": [{"quantity": "100", "unit_price": "2.50", "total": "250.00"}],
        "subtotal": "250.00", "discount_percent": "3", "discount_amount": "7.50",
        "packaging_cost": "10", "freight_cost": "20", "total": "272.50",
        "currency": "USD", "validity_days": 15,
    }
    assert validate_quote_payload(quote) == []
    assert "quote_total_mismatch" in validate_quote_payload({**quote, "total": "999"})
    assert validate_incoterm_payload({
        "incoterm": "DDP", "named_place": "Madrid", "version": "2020",
        "responsibilities": {"import_clearance": "seller", "import_duties": "seller"},
    }) == []
    assert "incoterm_responsibility_mismatch:import_duties" in validate_incoterm_payload({
        "incoterm": "DDP", "named_place": "Madrid", "version": "2020",
        "responsibilities": {"import_duties": "buyer"},
    })


def test_dataset_rejects_duplicates_and_supports_split_filter(tmp_path):
    row = json.dumps({"case_id": "D-1", "category": "test", "question": "q",
                      "split": "challenge"}, ensure_ascii=False)
    path = tmp_path / "cases.jsonl"
    path.write_text(row + "\n" + row + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate evaluation case_id"):
        load_dataset(path)
    path.write_text(row + "\n", encoding="utf-8")
    assert load_dataset(path, split="challenge")[0].case_id == "D-1"


def test_quality_gate_compares_distinct_parents_and_zero_means_no_evidence():
    document = CanonicalDocument("d", 1, "fixture://d", "d", "x", "h",
                                 status=DocumentStatus.PUBLISHED)
    first = SearchResult(ChildChunk("c1", "p1", "d", "a", "loc", "h1"), .5, document)
    overlap = SearchResult(ChildChunk("c2", "p1", "d", "b", "loc", "h2"), .499, document)
    competitor = SearchResult(ChildChunk("c3", "p2", "d", "c", "loc", "h3"), .2, document)
    assert QualityGate().classify([first, overlap, competitor]) == "HIGH_CONFIDENCE"
    zero = SearchResult(ChildChunk("c4", "p3", "d", "d", "loc", "h4"), 0, document)
    assert QualityGate().classify([zero]) == "NO_EVIDENCE"


def test_router_separates_dynamic_calculation_and_human_approval():
    pipeline = load_fixture_pipeline(FIXTURES / "corpus_v1.jsonl")
    actor = Actor("tester", frozenset({"sales"}))
    assert pipeline.query(QueryRequest("当前库存", actor))["status"] == "BUSINESS_DATA_REQUIRED"
    assert pipeline.query(QueryRequest("计算报价总额", actor))["status"] == "CALCULATION_REQUIRED"
    assert pipeline.query(QueryRequest("发送报价并承诺交期", actor))["status"] == "HUMAN_REVIEW_REQUIRED"


def test_thresholds_judge_calibration_and_report_regression_are_versioned():
    config_id, thresholds = load_thresholds(
        Path(__file__).parents[2] / "rag_evaluation" / "config" / "trade_gate_v1.json"
    )
    assert config_id == "external-trade-gate-v1"
    assert thresholds["numeric_accuracy"].value == 1.0
    calibrated = calibrate_binary_judge(
        [True, True, False, False], [True, True, False, False]
    )
    assert calibrated["ready_for_release_gate"]
    baseline = {"schema_version": "trade-rag-evaluation-report-v1",
                "dataset_version": "v1", "metrics": {
                    "claim_faithfulness": {"value": 1.0, "comparator": ">="}}}
    candidate = {"schema_version": "trade-rag-evaluation-report-v1",
                 "dataset_version": "v2", "metrics": {
                     "claim_faithfulness": {"value": .9, "comparator": ">="}}}
    comparison = compare_reports(baseline, candidate)
    assert comparison["status"] == "failed"
    assert comparison["regressions"][0]["metric"] == "claim_faithfulness"
