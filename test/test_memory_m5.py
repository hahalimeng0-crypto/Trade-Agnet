import sqlite3

import pytest

from agent.memory_runtime.models import ActorContext, MemoryScope
from agent.memory_runtime.outbox import MemoryIndexWorker
from agent.memory_runtime.retrieval import HybridMemoryRetriever
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from agent.memory_runtime.services.customer_reader import (
    CustomerMemoryAccessAudit, CustomerMemoryReader, ReadonlyCustomerMemoryStore,
)
from agent.memory_runtime.stores.keyword import KeywordMemoryIndex
from agent.memory_runtime.stores.sqlite import CustomerSQLiteMemoryStore
from agent.memory_runtime.stores.vector import LocalHashEmbeddingAdapter, VectorMemoryIndex


def make_runtime(tmp_path):
    main = CustomerSQLiteMemoryStore(tmp_path / "customer.db", indexing_enabled=True)
    keyword = KeywordMemoryIndex(tmp_path / "keyword.db")
    vector = VectorMemoryIndex(
        tmp_path / "vector.db", LocalHashEmbeddingAdapter(dimensions=32),
    )
    worker = MemoryIndexWorker(main, keyword, vector)
    retriever = HybridMemoryRetriever(main, keyword, vector)
    return main, CustomerMemoryService(main), keyword, vector, worker, retriever


def activate(service, account, content, *, tenant="tenant-a", conversation_id=None):
    actor = service.actor(tenant, account)
    consent = service.grant_consent(
        actor, purpose="customer_support", categories=("semantic",), expires_at=None,
    )
    candidate = service.create_candidate(
        actor, content=content, summary=content, memory_type="semantic",
        purpose="customer_support", source_refs=("message-a",),
        conversation_id=conversation_id, confidence=.9, importance=.8,
    )
    return actor, consent, service.activate_candidate(
        actor, candidate.memory_id, consent.consent_record_id, candidate.version,
    )


def scope(account, *, tenant="tenant-a", conversation_id=None):
    return MemoryScope(
        "customer_conversation" if conversation_id else "customer_private",
        tenant, account_id=account, conversation_id=conversation_id,
        purpose="customer_support",
    )


def test_outbox_indexes_active_memory_and_hybrid_score_is_explainable(tmp_path):
    main, service, keyword, vector, worker, retriever = make_runtime(tmp_path)
    actor, _, active = activate(service, "account-a", "Preferred destination Hamburg")
    pending = main.connection.execute(
        "SELECT status,payload_json FROM memory_index_outbox"
    ).fetchone()
    assert pending["status"] == "pending"
    assert "Hamburg" not in pending["payload_json"]
    assert retriever.search(actor, scope("account-a"), "Hamburg", 3) == []

    assert worker.drain() == 1
    hits = retriever.search(actor, scope("account-a"), "Hamburg", 3)
    assert [hit.item.memory_id for hit in hits] == [active.memory_id]
    assert hits[0].explanation["fusion"] == "rrf"
    assert hits[0].explanation["index_version"].startswith("k1:v1")
    assert keyword.index_version == 1
    assert vector.index_version == 1


def test_scope_filtering_precedes_vector_ranking_and_authority_revalidates(tmp_path):
    main, service, keyword, vector, worker, retriever = make_runtime(tmp_path)
    actor_a, _, memory_a = activate(service, "account-a", "Destination Hamburg blue")
    _, _, memory_b = activate(service, "account-b", "Destination Hamburg blue")
    worker.drain()
    hits = retriever.search(actor_a, scope("account-a"), "Hamburg blue", 10)
    assert [hit.item.memory_id for hit in hits] == [memory_a.memory_id]
    assert memory_b.memory_id not in {hit.item.memory_id for hit in hits}

    # Even a corrupted derived row cannot bypass authoritative account filtering.
    keyword.connection.execute(
        "UPDATE memory_keyword_index SET account_id='account-a' WHERE memory_id=?",
        (memory_b.memory_id,),
    )
    keyword.connection.commit()
    hits = retriever.search(actor_a, scope("account-a"), "Hamburg blue", 10)
    assert memory_b.memory_id not in {hit.item.memory_id for hit in hits}


def test_consent_withdrawal_and_correction_remove_stale_index_entries(tmp_path):
    main, service, keyword, vector, worker, retriever = make_runtime(tmp_path)
    actor, consent, active = activate(service, "account-a", "Destination Hamburg")
    worker.drain()
    corrected = service.correct(
        actor, active.memory_id, content="Destination Rotterdam",
        summary="Destination Rotterdam", source_refs=("message-b",),
        expected_version=active.version,
    )
    worker.drain()
    assert retriever.search(actor, scope("account-a"), "Hamburg", 3) == []
    assert [hit.item.memory_id for hit in retriever.search(
        actor, scope("account-a"), "Rotterdam", 3,
    )] == [corrected.memory_id]
    service.withdraw_consent(actor, consent.consent_record_id)
    # Stale derived rows cannot bypass authoritative consent state.
    assert retriever.search(actor, scope("account-a"), "Rotterdam", 3) == []
    worker.drain()
    assert retriever.search(actor, scope("account-a"), "Rotterdam", 3) == []


def test_vector_failure_keeps_authoritative_memory_and_retries_idempotently(tmp_path):
    main, service, keyword, vector, _, _ = make_runtime(tmp_path)
    actor, _, active = activate(service, "account-a", "Destination Hamburg")

    class FlakyVector:
        def __init__(self, delegate):
            self.delegate = delegate
            self.fail = True

        def upsert(self, item):
            if self.fail:
                raise TimeoutError("embedding timeout")
            self.delegate.upsert(item)

        def delete(self, memory_id):
            self.delegate.delete(memory_id)

    flaky = FlakyVector(vector)
    worker = MemoryIndexWorker(main, keyword, flaky)
    assert worker.run_once() is True
    event = main.connection.execute("SELECT * FROM memory_index_outbox").fetchone()
    assert event["status"] == "retry_wait"
    assert main.get_owned(actor, active.memory_id).status == "active"
    assert keyword.index_version == 1

    main.connection.execute(
        "UPDATE memory_index_outbox SET available_at='1970-01-01T00:00:00Z'"
    )
    main.connection.commit()
    flaky.fail = False
    assert worker.run_once() is True
    assert main.connection.execute(
        "SELECT status FROM memory_index_outbox"
    ).fetchone()[0] == "completed"
    assert vector.index_version == 1


def test_embedding_model_version_mismatch_requires_separate_rebuild(tmp_path):
    path = tmp_path / "vector.db"
    VectorMemoryIndex(path, LocalHashEmbeddingAdapter(dimensions=32))
    with pytest.raises(RuntimeError, match="memory_embedding_model_version_mismatch"):
        VectorMemoryIndex(path, LocalHashEmbeddingAdapter(dimensions=64))


def test_index_bootstrap_is_idempotent_for_existing_active_rows(tmp_path):
    main, service, _, _, worker, retriever = make_runtime(tmp_path)
    actor, _, active = activate(service, "account-a", "Destination Hamburg")
    worker.drain()
    assert main.enqueue_active_for_indexing() == 0
    assert main.enqueue_active_for_indexing() == 0
    assert [hit.item.memory_id for hit in retriever.search(
        actor, scope("account-a"), "Hamburg", 3,
    )] == [active.memory_id]


def test_authoritative_activation_rolls_back_when_outbox_enqueue_fails(tmp_path, monkeypatch):
    main, service, _, _, _, _ = make_runtime(tmp_path)
    actor = service.actor("tenant-a", "account-a")
    consent = service.grant_consent(
        actor, purpose="customer_support", categories=("semantic",), expires_at=None,
    )
    candidate = service.create_candidate(
        actor, content="Destination Hamburg", summary="Destination Hamburg",
        memory_type="semantic", purpose="customer_support",
        source_refs=("message-a",), conversation_id=None,
        confidence=.9, importance=.8,
    )
    monkeypatch.setattr(main, "_enqueue_index", lambda *_args: (_ for _ in ()).throw(
        sqlite3.OperationalError("outbox unavailable")
    ))
    with pytest.raises(sqlite3.OperationalError, match="outbox unavailable"):
        service.activate_candidate(
            actor, candidate.memory_id, consent.consent_record_id, candidate.version,
        )
    unchanged = main.get_owned(actor, candidate.memory_id)
    assert unchanged.status == "pending_consent"
    assert unchanged.version == candidate.version


def test_m4_reader_uses_readonly_hybrid_indexes(tmp_path):
    main, service, _, _, worker, _ = make_runtime(tmp_path)
    _, _, active = activate(service, "account-a", "Destination Hamburg")
    worker.drain()
    readonly_main = ReadonlyCustomerMemoryStore(tmp_path / "customer.db")
    readonly_keyword = KeywordMemoryIndex(tmp_path / "keyword.db", readonly=True)
    readonly_vector = VectorMemoryIndex(
        tmp_path / "vector.db", LocalHashEmbeddingAdapter(dimensions=32), readonly=True,
    )
    hybrid = HybridMemoryRetriever(readonly_main, readonly_keyword, readonly_vector)
    audit = CustomerMemoryAccessAudit(sqlite3.connect(":memory:", check_same_thread=False))
    reader = CustomerMemoryReader(
        readonly_main, audit, search_backend=hybrid, max_top_k=3,
    )
    operator = ActorContext(
        "workspace_operator", "operator-a", "tenant-a",
        frozenset({"customer_memory_reader"}), True,
    )
    results = reader.search_for_workspace(
        operator, customer_account_id="account-a", purpose="customer_support",
        query="Hamburg", top_k=3,
    )
    assert [item.memory_id for item in results] == [active.memory_id]
    with pytest.raises(sqlite3.OperationalError):
        readonly_keyword.connection.execute("DELETE FROM memory_keyword_index")
    with pytest.raises(sqlite3.OperationalError):
        readonly_vector.connection.execute("DELETE FROM memory_vector_index")
