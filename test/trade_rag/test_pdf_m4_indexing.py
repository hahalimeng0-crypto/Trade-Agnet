import json
from pathlib import Path

import pytest

from trade_rag.contracts import Actor, QueryRequest
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline
from trade_rag.stores import InMemoryKeywordStore

from pdf_fixture_factory import build_fixture


FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def _import_table(repository: KnowledgeRepository):
    payload = build_fixture(_cases()["table_units"])
    return repository.import_bytes("freight.pdf", payload, content_type="application/pdf")


def test_pdf_atomic_index_counts_parent_semantic_and_keyword_and_uses_parent_context(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    imported = _import_table(repository)
    pipeline = RagPipeline()

    indexed = repository.index_pdf(imported["document_id"], index_prepared=pipeline.index_prepared)
    assert indexed["index_status"] == "indexed"
    assert indexed["indexed_count"] == indexed["child_count"] > 0
    assert indexed["index_generation"] == 1
    assert len(pipeline.store._entries) == indexed["child_count"]
    assert len(pipeline.keyword_store._entries) == indexed["child_count"]
    assert len(pipeline.parent_store._entries) == indexed["parent_count"]

    pipeline.gate = type("HighConfidenceGate", (), {"classify": lambda self, results: "HIGH_CONFIDENCE"})()
    result = pipeline.query(QueryRequest(
        "Madrid 12 days", Actor("workspace", business_unit_id="default"), rerank=False
    ))
    assert result["status"] == "ANSWERED" and result["retrieval_mode"] == "hybrid"
    assert "Destination | Lead time | Unit" in result["answer"]
    assert result["citations"]
    assert result["citations"][0]["location"] == "page:1"
    assert result["citations"][0]["child_id"] in pipeline.store._entries


def test_three_store_index_failure_rolls_back_and_repository_retry_recovers(tmp_path):
    class FailingKeywordStore(InMemoryKeywordStore):
        def upsert(self, children, source):
            super().upsert(children, source)
            raise RuntimeError("simulated keyword failure")

    repository = KnowledgeRepository(tmp_path / "knowledge")
    imported = _import_table(repository)
    failing = RagPipeline(keyword_store=FailingKeywordStore())

    with pytest.raises(RuntimeError, match="simulated keyword failure"):
        repository.index_pdf(imported["document_id"], index_prepared=failing.index_prepared)
    failed = repository.get_document(imported["document_id"])
    assert failed["index_status"] == "failed" and failed["indexed_count"] == 0
    assert failed["last_error_code"] == "knowledge_index_failed"
    assert failing.store._entries == {}
    assert failing.keyword_store._entries == {}
    assert failing.parent_store._entries == {}

    healthy = RagPipeline()
    recovered = repository.retry_index(
        imported["document_id"], index_document=healthy.index_prepared
    )
    assert recovered["index_status"] == "indexed"
    assert recovered["indexed_count"] == recovered["child_count"]
    assert recovered["index_generation"] == 1


def test_pdf_revoke_deletes_parent_and_both_child_indexes_and_hits_zero(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    imported = _import_table(repository)
    pipeline = RagPipeline()
    repository.index_pdf(imported["document_id"], index_prepared=pipeline.index_prepared)
    pipeline.gate = type("HighConfidenceGate", (), {"classify": lambda self, results: "HIGH_CONFIDENCE"})()
    actor = Actor("workspace", business_unit_id="default")
    assert pipeline.query(QueryRequest("Madrid days", actor, rerank=False))["citations"]

    revoked = repository.revoke(
        imported["document_id"], delete_index=pipeline.delete_by_document
    )
    assert revoked["status"] == "revoked" and revoked["index_status"] == "withdrawn"
    assert pipeline.store._entries == {}
    assert pipeline.keyword_store._entries == {}
    assert pipeline.parent_store._entries == {}
    assert pipeline.query(QueryRequest("Madrid days", actor, rerank=False))["citations"] == []


def test_indexed_pdf_acl_is_enforced_for_child_recall_and_parent_expansion(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    imported = _import_table(repository)
    with repository._lock:
        manifest = repository._read_upgraded_manifest()
        item = manifest["documents"][0]
        item["business_unit_id"] = "trade"
        item["allowed_roles"] = ["sales"]
        repository._write_manifest(manifest)
    pipeline = RagPipeline()
    repository.index_pdf(imported["document_id"], index_prepared=pipeline.index_prepared)
    pipeline.gate = type("HighConfidenceGate", (), {"classify": lambda self, results: "HIGH_CONFIDENCE"})()

    allowed = pipeline.query(QueryRequest(
        "Madrid days", Actor("sales", frozenset({"sales"}), "trade"), rerank=False
    ))
    denied_role = pipeline.query(QueryRequest(
        "Madrid days", Actor("finance", frozenset({"finance"}), "trade"), rerank=False
    ))
    denied_unit = pipeline.query(QueryRequest(
        "Madrid days", Actor("sales", frozenset({"sales"}), "other"), rerank=False
    ))
    assert allowed["citations"]
    assert denied_role["citations"] == [] and denied_unit["citations"] == []
