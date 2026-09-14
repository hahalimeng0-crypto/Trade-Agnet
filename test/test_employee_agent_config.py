import pytest

from employee_agent import EmployeeAgentSettings


def test_redis_is_the_default_checkpoint_backend(monkeypatch, tmp_path):
    monkeypatch.delenv("EMPLOYEE_AGENT_CHECKPOINT_BACKEND", raising=False)
    monkeypatch.delenv("EMPLOYEE_AGENT_CHECKPOINT_PATH", raising=False)
    monkeypatch.delenv("EMPLOYEE_AGENT_REDIS_URL", raising=False)

    settings = EmployeeAgentSettings.from_environment(str(tmp_path))

    assert settings.checkpoint_backend == "redis"
    assert settings.checkpoint_redis_url == "redis://127.0.0.1:6379/1"
    assert settings.persistent_checkpoint_path is None
    assert settings.checkpoint_ttl_minutes == 10080


def test_sqlite_checkpoint_path_is_owned_by_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("EMPLOYEE_AGENT_CHECKPOINT_BACKEND", "sqlite")
    monkeypatch.delenv("EMPLOYEE_AGENT_CHECKPOINT_PATH", raising=False)

    settings = EmployeeAgentSettings.from_environment(str(tmp_path))

    assert settings.checkpoint_backend == "sqlite"
    assert settings.persistent_checkpoint_path == str(
        (tmp_path / "workspace/internal_agent/checkpoints.sqlite3").resolve()
    )
    assert settings.checkpoint_redis_url is None


def test_checkpointing_can_be_disabled_without_changing_other_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("EMPLOYEE_AGENT_CHECKPOINT_BACKEND", "off")
    monkeypatch.setenv("EMPLOYEE_AGENT_CHECKPOINT_PATH", "ignored.sqlite3")

    settings = EmployeeAgentSettings.from_environment(str(tmp_path))

    assert settings.checkpoint_backend == "off"
    assert settings.persistent_checkpoint_path is None


def test_invalid_checkpoint_backend_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("EMPLOYEE_AGENT_CHECKPOINT_BACKEND", "postgres")

    with pytest.raises(ValueError, match="must be redis, sqlite or off"):
        EmployeeAgentSettings.from_environment(str(tmp_path))


def test_invalid_redis_url_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("EMPLOYEE_AGENT_CHECKPOINT_BACKEND", "redis")
    monkeypatch.setenv("EMPLOYEE_AGENT_REDIS_URL", "http://127.0.0.1:6379")

    with pytest.raises(ValueError, match="must use redis:// or rediss://"):
        EmployeeAgentSettings.from_environment(str(tmp_path))
