import pytest

from agent.memory_runtime.errors import MemoryAccessDenied, MemoryScopeInvalid
from agent.memory_runtime.models import ActorContext, MemoryScope
from agent.memory_runtime.policy import MemoryPolicy


TENANT = "tenant-a"


def customer(account_id: str = "customer-a", *, tenant_id: str = TENANT):
    return ActorContext(
        actor_kind="customer",
        actor_id=account_id,
        tenant_id=tenant_id,
        roles=frozenset(),
        authenticated=True,
    )


@pytest.mark.parametrize(
    "scope",
    [
        MemoryScope(realm="customer_private", tenant_id=TENANT),
        MemoryScope(
            realm="customer_private",
            tenant_id=TENANT,
            account_id="customer-a",
            project_id="project-a",
        ),
        MemoryScope(
            realm="customer_conversation",
            tenant_id=TENANT,
            account_id="customer-a",
        ),
        MemoryScope(realm="workspace_private", tenant_id=TENANT),
        MemoryScope(
            realm="workspace_private",
            tenant_id=TENANT,
            subject_id="operator-a",
            account_id="customer-a",
        ),
        MemoryScope(
            realm="public_approved",
            tenant_id=TENANT,
            account_id="customer-a",
        ),
    ],
)
def test_scope_realm_invariants_fail_closed(scope: MemoryScope):
    with pytest.raises(MemoryScopeInvalid):
        scope.validate()


def test_customer_can_search_only_own_customer_scope():
    policy = MemoryPolicy()
    own_scope = MemoryScope(
        realm="customer_private",
        tenant_id=TENANT,
        account_id="customer-a",
        purpose="customer_support",
    )
    policy.require_search(customer(), own_scope)

    for denied_scope in (
        MemoryScope(
            realm="customer_private",
            tenant_id=TENANT,
            account_id="customer-b",
            purpose="customer_support",
        ),
        MemoryScope(
            realm="customer_private",
            tenant_id="tenant-b",
            account_id="customer-a",
            purpose="customer_support",
        ),
        MemoryScope(
            realm="workspace_private",
            tenant_id=TENANT,
            project_id="project-a",
        ),
    ):
        with pytest.raises(MemoryAccessDenied) as exc_info:
            policy.require_search(customer(), denied_scope)
        assert exc_info.value.code == "memory_scope_denied"


def test_unauthenticated_customer_cannot_search_private_memory():
    actor = ActorContext(
        actor_kind="customer",
        actor_id="customer-a",
        tenant_id=TENANT,
        roles=frozenset(),
        authenticated=False,
    )
    scope = MemoryScope(
        realm="customer_conversation",
        tenant_id=TENANT,
        account_id="customer-a",
        conversation_id="conversation-a",
    )
    with pytest.raises(MemoryAccessDenied):
        MemoryPolicy().require_search(actor, scope)


def test_workspace_customer_read_requires_role_and_allowed_purpose():
    policy = MemoryPolicy()
    base = dict(
        actor_kind="workspace_operator",
        actor_id="operator-a",
        tenant_id=TENANT,
        authenticated=True,
    )
    without_role = ActorContext(roles=frozenset(), **base)
    with_role = ActorContext(roles=frozenset({"customer_memory_reader"}), **base)

    with pytest.raises(MemoryAccessDenied):
        policy.require_workspace_customer_read(without_role, "customer_support")
    with pytest.raises(MemoryAccessDenied):
        policy.require_workspace_customer_read(with_role, "unbounded_analysis")
    policy.require_workspace_customer_read(with_role, "rfq_review")


def test_service_roles_do_not_cross_realms():
    actor = ActorContext(
        actor_kind="service",
        actor_id="customer-memory-service",
        tenant_id=TENANT,
        roles=frozenset({"customer_memory_service"}),
        authenticated=True,
    )
    workspace_scope = MemoryScope(
        realm="workspace_private", tenant_id=TENANT, project_id="project-a"
    )
    with pytest.raises(MemoryAccessDenied):
        MemoryPolicy().require_search(actor, workspace_scope)

