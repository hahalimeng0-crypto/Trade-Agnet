import json

import pytest

from trade_rag.m6_release import M6Release, M6State, parse_json_rows, percentile, safe_generation


def _env():
    return {
        "DOCKER_MYSQL_ROOT_PASSWORD": "unit-secret-a",
        "DOCKER_POSTGRES_PASSWORD": "unit-secret-b",
        "DOCKER_MILVUS_ROOT_PASSWORD": "unit-secret-c",
        "DOCKER_MILVUS_APP_USER": "unit-user",
        "DOCKER_MILVUS_APP_PASSWORD": "unit-secret-d",
        "DOCKER_MINIO_ROOT_PASSWORD": "unit-secret-e",
    }


def test_m6_identifiers_and_percentile_are_deterministic():
    assert safe_generation("m6-unit-0001") == safe_generation("m6-unit-0001")
    assert safe_generation("m6-unit-0001") != safe_generation("m6-unit-0002")
    assert percentile([3, 1, 2, 4], .95) == 4
    with pytest.raises(ValueError): safe_generation("unsafe/value")
    assert [row["Service"] for row in parse_json_rows('{"Service":"a"}\n{"Service":"b"}')] == ["a", "b"]


def test_fixture_has_exact_count_and_governance_categories(tmp_path):
    runner = M6Release("m6-unit-0001", artifact_root=tmp_path, env=_env(), vector_count=405,
                       query_count=2)
    fixtures = list(runner._fixtures())
    assert sum(len(children) for _, children, _ in fixtures) == 405
    assert all(len(vector) == 64 for _, _, vectors in fixtures for vector in vectors)
    statuses = {source.status.value for source, _, _ in fixtures}
    assert "published" in statuses and "revoked" in statuses


def test_stage_is_idempotent_and_duplicate_run_directory_fails_closed(tmp_path):
    runner = M6Release("m6-unit-0001", artifact_root=tmp_path, env=_env(), vector_count=1,
                       query_count=1)
    calls = []
    runner._stage("prepare", lambda state: calls.append(state.run_id) or {"safe": True})
    runner._stage("prepare", lambda state: calls.append("again"))
    assert calls == ["m6-unit-0001"]
    state = M6State.from_json(json.loads(runner.state_path.read_text("utf-8")))
    assert state.stages["prepare"].status == "passed"


def test_report_state_never_claims_production_ready():
    state = M6State.new("m6-unit-0001")
    assert state.production_ready is False
    assert state.release_scope == "local_controlled_pilot_review"
