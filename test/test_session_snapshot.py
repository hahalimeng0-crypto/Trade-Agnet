import json
from pathlib import Path

from session.snapshot import inspect_sessions, render_summary


def test_snapshot_reports_only_aggregate_validity(tmp_path: Path):
    secret = "private-message-body"
    (tmp_path / "web_alpha.jsonl").write_text(
        json.dumps({"role": "user", "content": secret}) + "\n", encoding="utf-8"
    )
    (tmp_path / "web_beta.jsonl").write_text("not-json\n", encoding="utf-8")

    rendered = render_summary(inspect_sessions(tmp_path))

    assert secret not in rendered
    assert "web_alpha" not in rendered
    assert json.loads(rendered) == {
        "file_count": 2,
        "invalid_file_count": 1,
        "invalid_record_count": 1,
        "mode": "dry-run",
        "valid_file_count": 1,
        "valid_record_count": 1,
    }


def test_snapshot_handles_missing_directory(tmp_path: Path):
    assert inspect_sessions(tmp_path / "missing").file_count == 0
