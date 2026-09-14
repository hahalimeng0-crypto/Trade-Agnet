from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trade_rag.migration_rehearsal import (
    M5Rehearsal,
    RehearsalError,
    canonical_sha256,
    redact,
    safe_database_name,
    validate_run_id,
)
from trade_rag.contracts import CanonicalDocument, ChildChunk, SearchResult


FAKE_ENV = {
    "DOCKER_MYSQL_ROOT_PASSWORD": "mysql-test-secret",
    "DOCKER_POSTGRES_PASSWORD": "postgres-test-secret",
    "DOCKER_MILVUS_ROOT_PASSWORD": "milvus-root-test-secret",
    "DOCKER_MILVUS_APP_USER": "m5-test",
    "DOCKER_MILVUS_APP_PASSWORD": "milvus-app-test-secret",
    "DOCKER_MINIO_ROOT_PASSWORD": "minio-test-secret",
}


def test_run_id_and_restore_targets_are_strictly_bounded():
    assert validate_run_id("m5-20260726-120000") == "m5-20260726-120000"
    assert safe_database_name("trade_ops_m5", "m5-20260726-120000") == \
        "trade_ops_m5_m5_20260726_120000"
    for invalid in ("M5-UPPER", "short", "m5_bad_name", "../escape", "m5-" + "x" * 50):
        with pytest.raises(ValueError):
            validate_run_id(invalid)


def test_canonical_hash_is_deterministic_and_hashes_binary_content():
    left = [{"amount": Decimal("10.00"), "at": datetime(2026, 1, 1, tzinfo=timezone.utc),
             "payload": b"deidentified"}]
    right = [{"payload": bytearray(b"deidentified"),
              "at": datetime(2026, 1, 1, tzinfo=timezone.utc), "amount": Decimal("10.00")}]
    assert canonical_sha256(left) == canonical_sha256(right)
    assert canonical_sha256(left) != canonical_sha256([{"amount": Decimal("11.00")}])


def test_report_redaction_removes_content_but_preserves_backend_metadata():
    payload = redact({
        "password": "secret", "milvus_token": "secret", "body_snapshot": "text",
        "recipient": "allowed@example.invalid", "embedding": [1.0],
        "default_vector_backend": "memory", "row_sha256": "abc",
    })
    assert payload["password"] == "[REDACTED]"
    assert payload["body_snapshot"] == "[REDACTED]"
    assert payload["embedding"] == "[REDACTED]"
    assert payload["default_vector_backend"] == "memory"
    assert payload["row_sha256"] == "abc"


def test_passed_stage_is_idempotent_and_duplicate_lock_fails_closed(tmp_path):
    runner = M5Rehearsal("m5-20260726-120001", artifact_root=tmp_path, env=FAKE_ENV)
    calls = []
    with runner._lock():
        state = runner._run_stage("prepare", lambda _: calls.append("called") or {"ok": True})
    assert state.stages["prepare"].status == "passed"
    with runner._lock():
        runner._run_stage("prepare", lambda _: calls.append("again"))
    assert calls == ["called"]
    lock = tmp_path / ".lock"
    lock.mkdir()
    with pytest.raises(RehearsalError, match="holds the lock"):
        with runner._lock():
            pass


def test_corrupt_or_missing_backup_manifest_fails_before_restore(tmp_path):
    runner = M5Rehearsal("m5-20260726-120002", artifact_root=tmp_path, env=FAKE_ENV)
    runner.run_dir.mkdir(parents=True)
    with pytest.raises(RehearsalError, match="manifest is missing"):
        runner._verify_manifest()
    (runner.run_dir / "mysql.sql").write_text("safe fixture", encoding="utf-8")
    runner.manifest_path.write_text(json.dumps({"files": {"mysql.sql": "0" * 64}}), encoding="utf-8")
    with pytest.raises(RehearsalError, match="checksum verification failed"):
        runner._verify_manifest()


def test_restore_stage_exceeding_rto_is_failed_and_never_passed(tmp_path, monkeypatch):
    runner = M5Rehearsal("m5-20260726-120003", artifact_root=tmp_path,
                         rto_seconds=0.5, env=FAKE_ENV)
    runner._run_stage("prepare", lambda _: {})
    ticks = iter((10.0, 11.0, 11.1))
    monkeypatch.setattr("trade_rag.migration_rehearsal.time.monotonic", lambda: next(ticks))
    with pytest.raises(RehearsalError, match="exceeded"):
        runner._run_stage("restore", lambda _: None)
    state = runner._load_state()
    assert state.stages["restore"].status == "failed"


def test_gold_comparison_is_scoped_to_the_current_rehearsal(tmp_path):
    runner = M5Rehearsal("m5-20260726-120004", artifact_root=tmp_path, env=FAKE_ENV)

    class Store:
        def search(self, vector, actor, limit):
            document = CanonicalDocument("doc", 1, "sample://doc", "doc", "text", "hash")
            return [
                SearchResult(ChildChunk("m5-20260726-120004-public-child", "p", "doc",
                                        "text", "p1", "h"), 1.0, document),
                SearchResult(ChildChunk("another-run-child", "p", "doc", "text", "p1", "h"),
                             0.9, document),
            ]

    assert all(ids == ["m5-20260726-120004-public-child"]
               for ids in runner._gold(Store()).values())
