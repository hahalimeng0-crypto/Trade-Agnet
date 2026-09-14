import json
import sqlite3

import pytest

from agent.memory_runtime.backup import MemoryBackupManager
from agent.memory_runtime.deletion import CustomerDeletionCoordinator
from agent.memory_runtime.governance import CustomerMemoryGovernance
from agent.memory_runtime.index_rebuild import MemoryIndexRebuilder
from agent.memory_runtime.models import CustomerInquiryWorkingMemory
from agent.memory_runtime.outbox import MemoryIndexWorker
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from agent.memory_runtime.stores.keyword import KeywordMemoryIndex
from agent.memory_runtime.stores.sqlite import CustomerSQLiteMemoryStore
from agent.memory_runtime.stores.vector import LocalHashEmbeddingAdapter, VectorMemoryIndex
from agent.memory_runtime.working_memory import CustomerWorkingMemoryStore
from session.customer_conversation import CustomerConversationRepository, CustomerOwner
from config import load_config


def runtime(tmp_path):
    main = CustomerSQLiteMemoryStore(tmp_path / "main.db", indexing_enabled=True)
    service = CustomerMemoryService(main)
    keyword = KeywordMemoryIndex(tmp_path / "keyword.db")
    embedding = LocalHashEmbeddingAdapter(32)
    vector = VectorMemoryIndex(tmp_path / "vector.db", embedding)
    worker = MemoryIndexWorker(main, keyword, vector)
    return main, service, keyword, vector, embedding, worker


def active(service, account, text, expires_at=None, tenant="tenant-a"):
    actor = service.actor(tenant, account)
    consent = service.grant_consent(
        actor, purpose="support", categories=("semantic",), expires_at=expires_at,
    )
    candidate = service.create_candidate(
        actor, content=text, summary=text, memory_type="semantic", purpose="support",
        source_refs=("message-1",), confidence=.9, importance=.8,
        conversation_id=None,
    )
    return service.activate_candidate(
        actor, candidate.memory_id, consent.consent_record_id, candidate.version,
    )


def test_ttl_invalidates_recall_and_enqueues_delete_but_age_alone_does_not(tmp_path):
    main, service, keyword, vector, _, worker = runtime(tmp_path)
    expiring = active(service, "account-a", "expires", "2099-01-01T00:00:00Z")
    stable = active(service, "account-a", "stable")
    worker.drain()

    assert CustomerMemoryGovernance(main).review_ttl(now="2100-01-01T00:00:00Z") == 1
    assert main.get_index_item(expiring.memory_id) is None
    assert main.get_index_item(stable.memory_id).memory_id == stable.memory_id
    event = main.connection.execute(
        "SELECT event_type,status FROM memory_index_outbox WHERE aggregate_id=? ORDER BY created_at DESC",
        (expiring.memory_id,),
    ).fetchone()
    assert tuple(event) == ("delete", "pending")


def test_account_deletion_is_resumable_scoped_and_never_completes_early(tmp_path):
    main, service, keyword, vector, _, worker = runtime(tmp_path)
    memory_a = active(service, "account-a", "secret a")
    memory_b = active(service, "account-b", "secret b")
    worker.drain()
    conversations = CustomerConversationRepository(tmp_path / "conversation.db", cursor_secret=b"x")
    owner = CustomerOwner("tenant-a", "account-a")
    conversation = conversations.create(owner, "A")
    conversations.append_message(owner, conversation.conversation_id, role="user", content="secret")
    working = CustomerWorkingMemoryStore(tmp_path / "working.db")
    working.put("tenant-a", CustomerInquiryWorkingMemory(
        "account-a", conversation.conversation_id, "rfq", {}, [], [], None, 0,
    ), None)
    attempts = {"count": 0}

    def flaky_cleanup(tenant_id, account_id):
        attempts["count"] += 1
        return attempts["count"] > 1

    coordinator = CustomerDeletionCoordinator(
        sqlite3.connect(tmp_path / "jobs.db"), conversation_repository=conversations,
        working_memory_store=working, long_term_store=main, index_worker=worker,
        external_cleanups=(flaky_cleanup,),
    )
    first = coordinator.request_account_deletion(
        tenant_id="tenant-a", account_id="account-a", request_id="cancel-a",
    )
    assert coordinator.request_account_deletion(
        tenant_id="tenant-a", account_id="account-a", request_id="cancel-a",
    ).job_id == first.job_id
    partial = coordinator.run("cancel-a")
    assert partial.status == "retry_wait"
    assert partial.steps["indexes"] == "completed"
    assert partial.steps["external"] == "pending"
    assert main.get_index_item(memory_a.memory_id) is None
    assert main.get_index_item(memory_b.memory_id).memory_id == memory_b.memory_id
    assert working.get("tenant-a", "account-a", conversation.conversation_id) is None
    assert coordinator.run("cancel-a").status == "completed"
    assert coordinator.run("cancel-a").status == "completed"


def test_deletion_stays_pending_when_index_cleanup_is_not_acknowledged(tmp_path):
    main, service, _, _, _, _ = runtime(tmp_path)
    active(service, "account-a", "secret")
    conversations = CustomerConversationRepository(tmp_path / "conversation.db", cursor_secret=b"x")
    working = CustomerWorkingMemoryStore(tmp_path / "working.db")
    coordinator = CustomerDeletionCoordinator(
        sqlite3.connect(tmp_path / "jobs.db"), conversation_repository=conversations,
        working_memory_store=working, long_term_store=main,
    )
    coordinator.request_account_deletion(
        tenant_id="tenant-a", account_id="account-a", request_id="pending-index",
    )
    result = coordinator.run("pending-index")
    assert result.status == "retry_wait"
    assert result.last_error_code == "memory_index_cleanup_pending"


def test_merge_is_service_only_same_tenant_and_conflict_safe(tmp_path):
    main, service, *_ = runtime(tmp_path)
    active(service, "source", "source memory")
    conversations = CustomerConversationRepository(main.connection, cursor_secret=b"x")
    working = CustomerWorkingMemoryStore(main.connection)
    owner = CustomerOwner("tenant-a", "source")
    conversation = conversations.create(owner, "source conversation")
    conversations.append_message(owner, conversation.conversation_id, role="user", content="hello")
    working.put("tenant-a", CustomerInquiryWorkingMemory(
        "source", conversation.conversation_id, "support", {}, [], [], None, 0,
    ), None)
    governance = CustomerMemoryGovernance(main)
    with pytest.raises(PermissionError, match="actor_denied"):
        governance.merge_accounts(
            actor_kind="customer", actor_id="source", tenant_id="tenant-a",
            source_account_id="source", target_account_id="target",
        )
    with pytest.raises(PermissionError, match="cross_tenant"):
        governance.merge_accounts(
            actor_kind="identity_service", actor_id="idp", tenant_id="tenant-a",
            target_tenant_id="tenant-b", source_account_id="source", target_account_id="target",
        )
    assert governance.merge_accounts(
        actor_kind="identity_service", actor_id="idp", tenant_id="tenant-a",
        source_account_id="source", target_account_id="target",
    ) == 5
    audit = main.connection.execute("SELECT * FROM memory_account_merge_audit").fetchone()
    assert audit["actor_id"] == "idp"
    assert conversations.get_owned(
        CustomerOwner("tenant-a", "target"), conversation.conversation_id,
    ).account_id == "target"
    assert working.get("tenant-a", "target", conversation.conversation_id) is not None


def test_backup_restore_verifies_checksum_before_creating_staging(tmp_path):
    source = sqlite3.connect(tmp_path / "source.db")
    source.execute("CREATE TABLE sample(value TEXT)")
    source.execute("INSERT INTO sample VALUES ('ok')")
    source.commit()
    manager = MemoryBackupManager()
    manifest = manager.create({"customer": source}, tmp_path / "backup")
    restored = manager.restore_to_staging(tmp_path / "backup", tmp_path / "restore")
    assert sqlite3.connect(restored["customer"]).execute("SELECT value FROM sample").fetchone()[0] == "ok"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    (tmp_path / "backup" / payload["files"][0]["file"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="checksum"):
        manager.restore_to_staging(tmp_path / "backup", tmp_path / "never-created")
    assert not (tmp_path / "never-created").exists()


def test_rebuild_contains_only_current_authoritative_rows_and_preserves_old_on_build_failure(tmp_path):
    main, service, _, _, embedding, _ = runtime(tmp_path)
    keep = active(service, "account-a", "keep")
    remove = active(service, "account-a", "remove", "2099-01-01T00:00:00Z")
    main.expire_due(now="2100-01-01T00:00:00Z")
    keyword_path, vector_path = tmp_path / "rebuilt-keyword.db", tmp_path / "rebuilt-vector.db"
    assert MemoryIndexRebuilder(main, embedding).rebuild(keyword_path, vector_path) == 1
    assert KeywordMemoryIndex(keyword_path).connection.execute(
        "SELECT memory_id FROM memory_keyword_index"
    ).fetchone()[0] == keep.memory_id
    assert sqlite3.connect(vector_path).execute(
        "SELECT COUNT(*) FROM memory_vector_index WHERE memory_id=?", (remove.memory_id,),
    ).fetchone()[0] == 0

    before = keyword_path.read_bytes()

    class BrokenEmbedding(LocalHashEmbeddingAdapter):
        def embed(self, texts):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        MemoryIndexRebuilder(main, BrokenEmbedding(32)).rebuild(keyword_path, vector_path)
    assert keyword_path.read_bytes() == before


def test_m6_release_switches_are_off_and_dependencies_fail_closed(tmp_path, monkeypatch):
    for name in (
        "NANOCLAW_MEMORY_GOVERNANCE_ENABLED", "NANOCLAW_MEMORY_BACKUP_ENABLED",
        "NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED",
        "NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED", "NANOCLAW_CUSTOMER_AUTH_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)
    config = load_config(str(tmp_path / "missing.json"))
    assert config.memory_governance_enabled is False
    assert config.memory_backup_enabled is False
    assert not list(tmp_path.glob("**/*.db"))

    monkeypatch.setenv("NANOCLAW_MEMORY_GOVERNANCE_ENABLED", "true")
    with pytest.raises(ValueError, match="governance requires"):
        load_config(str(tmp_path / "missing.json"))
