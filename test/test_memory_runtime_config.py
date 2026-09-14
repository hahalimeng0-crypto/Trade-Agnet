from config import load_config
import pytest


def test_memory_runtime_defaults_are_disabled(tmp_path, monkeypatch):
    for name in (
        "NANOCLAW_CUSTOMER_AUTH_ENABLED",
        "NANOCLAW_CUSTOMER_REGISTRATION_ENABLED",
        "NANOCLAW_WORKSPACE_MEMORY_ENABLED",
        "NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED",
        "NANOCLAW_WORKSPACE_CUSTOMER_MEMORY_READ_ENABLED",
        "NANOCLAW_WORKSPACE_OPERATOR_ID",
        "NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID",
        "NANOCLAW_MEMORY_HYBRID_RETRIEVAL_ENABLED",
        "NANOCLAW_MEMORY_EMBEDDING_BACKEND",
    ):
        monkeypatch.delenv(name, raising=False)

    config = load_config(str(tmp_path / "missing.json"))

    assert config.customer_auth_enabled is False
    assert config.customer_registration_enabled is False
    assert config.workspace_memory_enabled is False
    assert config.workspace_memory_auto_extract_enabled is False
    assert config.workspace_memory_hybrid_enabled is False
    assert config.workspace_memory_governance_enabled is False
    assert config.workspace_memory_review_enabled is False
    assert config.customer_long_term_memory_enabled is False
    assert config.customer_conversation_memory_enabled is False
    assert config.workspace_customer_memory_read_enabled is False
    assert config.workspace_operator_id == ""
    assert config.workspace_operator_tenant_id == ""
    assert config.memory_hybrid_retrieval_enabled is False
    assert config.memory_embedding_backend == "local_hash"
    assert config.memory_max_turns == 10
    assert config.memory_recall_top_k == 3


def test_memory_runtime_release_switches_use_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_ID", "operator-a")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID", "tenant-a")
    monkeypatch.setenv("NANOCLAW_MEMORY_MAX_TURNS", "7")
    monkeypatch.setenv("NANOCLAW_MEMORY_RECALL_TOP_K", "2")

    config = load_config(str(tmp_path / "missing.json"))

    assert config.workspace_memory_enabled is True
    assert config.memory_max_turns == 7
    assert config.memory_recall_top_k == 2


def test_workspace_memory_requires_trusted_operator_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_ENABLED", "true")
    monkeypatch.delenv("NANOCLAW_WORKSPACE_OPERATOR_ID", raising=False)
    monkeypatch.delenv("NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID", raising=False)
    with pytest.raises(ValueError, match="requires trusted workspace operator identity"):
        load_config(str(tmp_path / "missing.json"))


def test_customer_conversation_memory_requires_server_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_AUTH_ENABLED", "false")
    with pytest.raises(ValueError, match="requires NANOCLAW_CUSTOMER_AUTH_ENABLED"):
        load_config(str(tmp_path / "missing.json"))


def test_customer_long_term_memory_requires_bounded_conversation_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_CUSTOMER_AUTH_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED", "false")
    with pytest.raises(ValueError, match="requires NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED"):
        load_config(str(tmp_path / "missing.json"))


def test_workspace_customer_read_requires_long_term_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_WORKSPACE_CUSTOMER_MEMORY_READ_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED", "false")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_ID", "operator-a")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID", "tenant-a")
    with pytest.raises(ValueError, match="requires NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED"):
        load_config(str(tmp_path / "missing.json"))


def test_workspace_customer_read_requires_trusted_operator_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_CUSTOMER_AUTH_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_CUSTOMER_MEMORY_READ_ENABLED", "true")
    monkeypatch.delenv("NANOCLAW_WORKSPACE_OPERATOR_ID", raising=False)
    monkeypatch.delenv("NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID", raising=False)
    with pytest.raises(ValueError, match="requires trusted workspace operator identity"):
        load_config(str(tmp_path / "missing.json"))


def test_hybrid_retrieval_requires_long_term_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_MEMORY_HYBRID_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED", "false")
    with pytest.raises(ValueError, match="requires NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED"):
        load_config(str(tmp_path / "missing.json"))


def test_external_embedding_backend_fails_closed_without_approved_adapter(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_CUSTOMER_AUTH_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_CONVERSATION_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_LONG_TERM_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_MEMORY_HYBRID_RETRIEVAL_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_MEMORY_EMBEDDING_BACKEND", "external_api")
    with pytest.raises(ValueError, match="requires explicit approved adapter"):
        load_config(str(tmp_path / "missing.json"))


def test_workspace_review_requires_enabled_governance(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_ID", "operator-a")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_OPERATOR_TENANT_ID", "tenant-a")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_REVIEW_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_GOVERNANCE_ENABLED", "false")
    with pytest.raises(ValueError, match="review requires workspace memory and governance"):
        load_config(str(tmp_path / "missing.json"))


def test_workspace_external_embedding_requires_approval_and_complete_config(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_EMBEDDING_BACKEND", "openai_compatible")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_EXTERNAL_TRANSFER_APPROVED", "false")
    with pytest.raises(ValueError, match="external transfer requires explicit approval"):
        load_config(str(tmp_path / "missing.json"))

    monkeypatch.setenv("NANOCLAW_WORKSPACE_MEMORY_EXTERNAL_TRANSFER_APPROVED", "true")
    monkeypatch.delenv("NANOCLAW_WORKSPACE_MEMORY_EMBEDDING_API_KEY", raising=False)
    with pytest.raises(ValueError, match="external embedding configuration is incomplete"):
        load_config(str(tmp_path / "missing.json"))


def test_dedicated_workspace_web_uses_an_independent_port(tmp_path, monkeypatch):
    monkeypatch.setenv("NANOCLAW_WEB_PORT", "8765")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_WEB_ENABLED", "true")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("NANOCLAW_WORKSPACE_WEB_PORT", "8767")
    monkeypatch.setenv("NANOCLAW_CUSTOMER_PORTAL_PORT", "8766")
    config = load_config(str(tmp_path / "missing.json"))
    assert config.workspace_web_enabled is True
    assert config.workspace_web_host == "127.0.0.1"
    assert config.workspace_web_port == 8767

    monkeypatch.setenv("NANOCLAW_WORKSPACE_WEB_PORT", "8765")
    with pytest.raises(ValueError, match="dedicated workspace port must differ"):
        load_config(str(tmp_path / "missing.json"))
