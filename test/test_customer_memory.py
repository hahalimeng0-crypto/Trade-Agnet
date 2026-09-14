import asyncio
import json
import sqlite3

import pytest

from agent.memory_runtime.errors import MemoryAccessDenied, MemoryVersionConflict
from agent.memory_runtime.context_provider import StructuredWorkingMemoryContextProvider
from agent.memory_runtime.lifecycle import BoundedWorkingMemoryLifecycle
from agent.memory_runtime.models import ActorContext, MemoryScope, TurnRequest
from agent.memory_runtime.services.customer_memory import CustomerMemoryService
from agent.memory_runtime.stores.sqlite import (
    CustomerSQLiteMemoryStore, PublicApprovedMemoryStore,
    WorkspaceSQLiteMemoryStore, content_hash, utcnow,
)
from agent.tools.customer_public import CustomerPublicKnowledgeTool


def customer_store():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    return CustomerSQLiteMemoryStore(connection)


def actor(account="account-a", tenant="tenant-a"):
    return ActorContext("customer", account, tenant, frozenset(), True)


def create_active(service, current, *, content="Preferred destination Hamburg", conversation_id=None):
    consent = service.grant_consent(
        current, purpose="customer_support", categories=("semantic",), expires_at=None,
    )
    candidate = service.create_candidate(
        current, content=content, summary=content, memory_type="semantic",
        purpose="customer_support", source_refs=("message-a",),
        conversation_id=conversation_id, confidence=.9, importance=.7,
    )
    active = service.activate_candidate(current, candidate.memory_id, consent.consent_record_id, 1)
    return consent, candidate, active


def test_candidate_cannot_be_active_without_matching_consent():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    candidate = service.create_candidate(
        current, content="CIF Hamburg", summary="Destination preference",
        memory_type="semantic", purpose="customer_support", source_refs=("message-a",),
        conversation_id=None, confidence=.8, importance=.6,
    )
    assert candidate.status == "pending_consent"
    assert store.search(
        current, MemoryScope("customer_private", "tenant-a", account_id="account-a",
                             purpose="customer_support"), "Hamburg", 3,
    ) == []
    wrong = service.grant_consent(
        current, purpose="complaint_resolution", categories=("semantic",), expires_at=None,
    )
    with pytest.raises(ValueError, match="customer_consent_invalid"):
        service.activate_candidate(current, candidate.memory_id, wrong.consent_record_id, 1)


def test_cross_account_memory_id_is_uniformly_denied():
    store = customer_store()
    service = CustomerMemoryService(store)
    _, _, active = create_active(service, actor("account-a"))
    with pytest.raises(MemoryAccessDenied):
        store.get_owned(actor("account-b"), active.memory_id)
    with pytest.raises(MemoryAccessDenied):
        store.export_scope(
            actor("account-b"),
            MemoryScope("customer_private", "tenant-a", account_id="account-a",
                        purpose="customer_support"),
        )
    unauthenticated = ActorContext(
        "customer", "account-a", "tenant-a", frozenset(), False,
    )
    with pytest.raises(MemoryAccessDenied):
        store.get_owned(unauthenticated, active.memory_id)


def test_correction_creates_new_version_and_supersedes_old():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    _, _, active = create_active(service, current)
    corrected = service.correct(
        current, active.memory_id, content="Preferred destination Rotterdam",
        summary="Destination corrected to Rotterdam", source_refs=("message-b",),
        expected_version=active.version,
    )
    assert corrected.supersedes == active.memory_id
    assert corrected.status == "active"
    assert store.get_owned(current, active.memory_id).status == "superseded"
    hits = store.search(current, corrected.scope, "Rotterdam", 3)
    assert [hit.item.memory_id for hit in hits] == [corrected.memory_id]
    with pytest.raises(MemoryVersionConflict):
        service.correct(
            current, active.memory_id, content="Old correction", summary="stale",
            source_refs=("message-c",), expected_version=active.version,
        )


def test_consent_withdrawal_immediately_stops_recall():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    consent, _, active = create_active(service, current)
    assert store.search(current, active.scope, "Hamburg", 3)
    assert service.withdraw_consent(current, consent.consent_record_id) == 1
    assert store.search(current, active.scope, "Hamburg", 3) == []
    assert store.get_owned(current, active.memory_id).status == "invalid"


def test_export_delete_scope_is_owned_and_idempotent():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    create_active(service, current, content="MOQ preference 100")
    scope = MemoryScope(
        "customer_private", "tenant-a", account_id="account-a", purpose="customer_support"
    )
    exported = store.export_scope(current, scope)
    assert len(exported.items) == 1
    first = store.delete_scope(current, scope, "delete-request-a")
    second = store.delete_scope(current, scope, "delete-request-a")
    assert first == second
    assert first.status == "completed"
    assert store.export_scope(current, scope).items == ()


def test_export_and_delete_honor_purpose_scope():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    create_active(service, current, content="Support preference")
    consent = service.grant_consent(
        current, purpose="complaint_resolution", categories=("semantic",), expires_at=None,
    )
    candidate = service.create_candidate(
        current, content="Complaint preference", summary="Complaint preference",
        memory_type="semantic", purpose="complaint_resolution",
        source_refs=("message-b",), conversation_id=None, confidence=.8, importance=.6,
    )
    complaint = service.activate_candidate(
        current, candidate.memory_id, consent.consent_record_id, candidate.version,
    )
    support_scope = MemoryScope(
        "customer_private", "tenant-a", account_id="account-a", purpose="customer_support",
    )
    assert [item.content for item in store.export_scope(current, support_scope).items] == [
        "Support preference"
    ]
    store.delete_scope(current, support_scope, "delete-support-only")
    assert store.get_owned(current, complaint.memory_id).status == "active"


def test_cross_account_invalidation_is_denied_before_version_check():
    store = customer_store()
    service = CustomerMemoryService(store)
    _, _, active = create_active(service, actor("account-a"))
    with pytest.raises(MemoryAccessDenied):
        store.invalidate(actor("account-b"), active.memory_id, "probe", active.version)


def test_single_memory_delete_erases_content_and_hides_export():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    _, _, active = create_active(service, current)
    store.delete_owned(current, active.memory_id, active.version)
    deleted = store.get_owned(current, active.memory_id)
    assert deleted.status == "deleted"
    assert deleted.content == ""
    assert deleted.summary == ""
    assert store.export_scope(current, active.scope).items == ()


def test_account_and_conversation_memory_both_recall_for_current_conversation():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    create_active(service, current, content="Preferred Incoterm CIF")
    create_active(service, current, content="Current inquiry is 500 units", conversation_id="conversation-a")
    create_active(service, current, content="Other inquiry is 900 units", conversation_id="conversation-b")
    scope = MemoryScope(
        "customer_conversation", "tenant-a", account_id="account-a",
        conversation_id="conversation-a", purpose="customer_support",
    )
    contents = [hit.item.content for hit in store.search(current, scope, "preferred inquiry units", 10)]
    assert "Preferred Incoterm CIF" in contents
    assert "Current inquiry is 500 units" in contents
    assert "Other inquiry is 900 units" not in contents


def test_public_markdown_import_is_idempotent_and_physically_separate(tmp_path):
    markdown = tmp_path / "PUBLIC_MEMORY.md"
    markdown.write_text("# Public\n\n- Approved product help.\n- Staff confirms quotations.\n", encoding="utf-8")
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = PublicApprovedMemoryStore(connection)
    assert store.import_approved_markdown(markdown) == 2
    assert store.import_approved_markdown(markdown) == 0
    assert store.search("quotation", 3) == ["Staff confirms quotations."]
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "public_memory_item" in tables
    assert "customer_memory_item" not in tables
    assert "workspace_memory_item" not in tables


def test_workspace_store_has_no_account_column_and_customer_cannot_read():
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    store = WorkspaceSQLiteMemoryStore(connection)
    workspace_actor = ActorContext(
        "workspace_operator", "operator-a", "tenant-a",
        frozenset({"workspace_memory_reader", "workspace_memory_writer"}), True,
    )
    from agent.memory_runtime.models import MemoryItem
    now = utcnow()
    scope = MemoryScope(
        "workspace_private", "tenant-a", subject_id="operator-a",
        project_id="project-a", purpose="project_assistance",
    )
    item = MemoryItem(
        "workspace-memory-a", scope, "semantic", "Internal project fact",
        "Project fact", ("message-internal",), "active", .9, .8, "internal",
        None, 1, None, now, now, now, None, content_hash("Internal project fact"), None,
    )
    store.create_candidate(workspace_actor, item)
    assert store.search(workspace_actor, scope, "project fact", 3)[0].item.memory_id == item.memory_id
    columns = {row[1] for row in connection.execute("PRAGMA table_info(workspace_memory_item)")}
    assert "account_id" not in columns
    with pytest.raises(MemoryAccessDenied):
        store.search(actor(), scope, "project fact", 3)
    other_operator = ActorContext(
        "workspace_operator", "operator-b", "tenant-a",
        frozenset({"workspace_memory_reader", "workspace_memory_writer"}), True,
    )
    with pytest.raises(MemoryAccessDenied):
        store.invalidate(other_operator, item.memory_id, "probe", item.version)


def test_active_customer_memory_is_injected_as_structured_top_k_context():
    store = customer_store()
    service = CustomerMemoryService(store)
    current = actor()
    create_active(service, current, content="Preferred destination Hamburg")

    class SessionManager:
        async def prepare_active_history(self, _key):
            return [{"role": "user", "content": "earlier"}]

    lifecycle = BoundedWorkingMemoryLifecycle(
        SessionManager(), long_term_store=store, recall_top_k=3,
    )
    request = TurnRequest(
        "request-a", current,
        MemoryScope(
            "customer_conversation", "tenant-a", account_id="account-a",
            conversation_id="conversation-a", purpose="customer_support",
        ),
        "What is my Hamburg destination preference?", (), "customer:conversation-a",
    )
    prepared = asyncio.run(lifecycle.prepare_turn(request))
    messages = StructuredWorkingMemoryContextProvider().build_context_messages(prepared)
    long_term = [
        message["content"] for message in messages
        if message["content"].startswith("Trusted scoped long-term memory")
    ]
    assert len(prepared.recalled) == 1
    assert len(long_term) == 1
    assert "Preferred destination Hamburg" in long_term[0]
    assert "authoritative inventory" in long_term[0]


def test_public_knowledge_tool_reads_approved_store_without_markdown_prompt_injection(tmp_path):
    markdown = tmp_path / "PUBLIC_MEMORY.md"
    markdown.write_text("# Public\n\n- Standard samples ship in five days.\n", encoding="utf-8")
    store = PublicApprovedMemoryStore(sqlite3.connect(":memory:", check_same_thread=False))
    assert store.import_approved_markdown(markdown) == 1

    class EmptyRepository:
        def load_published(self):
            return []

    tool = CustomerPublicKnowledgeTool(
        repository=EmptyRepository(), public_memory_store=store,
    )
    result = json.loads(asyncio.run(tool.execute(query="When do standard samples ship?")))
    assert result["answer"] == "Standard samples ship in five days."
    assert result["status"] == "ANSWERED"
