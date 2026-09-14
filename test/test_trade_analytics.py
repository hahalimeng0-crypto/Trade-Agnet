import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.business import analytics, sqlite_database
from agent.business.analytics import AnalyticsError
from agent.tools.query_trade_data import query_trade_data_impl
from agent.workflow import WorkflowService


@pytest.fixture
def analytics_db(tmp_path: Path, monkeypatch):
    sqlite_database.close_all()
    cfg = SimpleNamespace(database_backend="sqlite", database_path=str(tmp_path / "business.db"))
    monkeypatch.setattr(sqlite_database, "load_business_config", lambda: cfg)
    monkeypatch.setattr(analytics, "load_business_config", lambda: cfg)
    sqlite_database.init_db()
    connection = sqlite_database.get_connection()
    connection.executemany(
        "INSERT INTO products(sku,name_cn,name_en,category,specification,unit,moq,price_usd,inventory,lead_time_days,active) VALUES(?,?,?,?,?,?,?,?,?,?,1)",
        [("SKU-A", "A", "Adapter", "power", "", "pcs", 10, 2.0, 500, 5),
         ("SKU-B", "B", "Cable", "cable", "", "pcs", 20, 1.0, 900, 3),
         ("SKU-C", "C", "Charger", "power", "", "pcs", 10, 3.0, 100, 7)],
    )
    connection.executemany("INSERT INTO rfq_requests(session_key,status,created_at,updated_at) VALUES(?,?,datetime('now'),datetime('now'))",
                           [("web:1", "pending"), ("web:2", "extracted"), ("web:3", "pending")])
    connection.executemany("INSERT INTO quotes(rfq_id,status,created_at) VALUES(?,?,datetime('now'))",
                           [(1, "draft"), (2, "approved"), (3, "draft")])
    connection.executemany("INSERT INTO followup_tasks(quote_id,task_type,title,description,due_at,status) VALUES(?,?,?,?,?,?)",
                           [(1, "follow_up", "", "", "2026-07-25", "pending"),
                            (2, "approval_reminder", "", "", "2026-07-25", "pending")])
    connection.commit()
    yield tmp_path
    sqlite_database.close_all()


def test_fixed_inventory_query_is_parameterized_bounded_and_audited(analytics_db: Path):
    result = analytics.execute_fixed_query("inventory_top", {"category": "power", "limit": 2},
                                           audit_dir=analytics_db / "audit")
    assert [row["sku"] for row in result["rows"]] == ["SKU-A", "SKU-C"]
    assert result["row_count"] == 2
    assert len(result["sql_hash"]) == 64
    assert result["limitations"] == ["not_trade_dw", "fixed_query_only"]
    audit = json.loads((analytics_db / "audit" / "query_audit.jsonl").read_text(encoding="utf-8"))
    assert audit["query_id"] == result["query_id"]
    assert "rows" not in audit and "power" not in json.dumps(audit)


@pytest.mark.parametrize("code,expected", [
    ("rfq_status_summary", {"pending": 2, "extracted": 1}),
    ("quote_status_summary", {"draft": 2, "approved": 1}),
    ("pending_followups", {"approval_reminder": 1, "follow_up": 1}),
])
def test_fixed_summary_contracts(analytics_db: Path, code: str, expected: dict[str, int]):
    result = analytics.execute_fixed_query(code, {"limit": 10}, audit_dir=analytics_db / "audit")
    key, count = result["columns"]
    assert {row[key]: row[count] for row in result["rows"]} == expected


def test_arbitrary_sql_unknown_filters_and_injection_are_blocked(analytics_db: Path):
    with pytest.raises(AnalyticsError, match="arbitrary_sql_disabled"):
        analytics.execute_arbitrary_sql("DROP TABLE products")
    with pytest.raises(AnalyticsError, match="query_not_allowlisted"):
        analytics.execute_fixed_query("SELECT * FROM products", {}, audit_dir=analytics_db / "audit")
    with pytest.raises(AnalyticsError, match="filter_not_allowlisted"):
        analytics.execute_fixed_query("inventory_top", {"sql": "DROP TABLE products"}, audit_dir=analytics_db / "audit")
    injected = analytics.execute_fixed_query("inventory_top", {"category": "power' OR 1=1 --"}, audit_dir=analytics_db / "audit")
    assert injected["rows"] == []
    assert sqlite_database.get_connection().execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3
    with pytest.raises(AnalyticsError, match="invalid_limit"):
        analytics.execute_fixed_query("inventory_top", {"limit": 51}, audit_dir=analytics_db / "audit")


def test_tool_lists_contracts_and_returns_stable_errors(analytics_db: Path, monkeypatch):
    contracts = json.loads(query_trade_data_impl(list_contracts=True))
    assert contracts["nl2sql_enabled"] is False
    assert {item["query_code"] for item in contracts["contracts"]} == set(analytics.SPECS)
    assert json.loads(query_trade_data_impl("unknown", {}))["error_code"] == "query_not_allowlisted"
    assert json.loads(query_trade_data_impl("inventory_top", "not-json"))["error_code"] == "invalid_filters"


def test_analysis_workflow_is_separate_ordered_and_privacy_safe(tmp_path: Path):
    service = WorkflowService(tmp_path / "workflows")
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    result = {"query_id": "qid", "query_code": "inventory_top", "sql_hash": "a" * 64,
              "row_count": 2, "rows": [{"customer": "must-not-be-in-event"}]}
    asyncio.run(service.observe_analytics(f"web:local:{conversation_id}", json.dumps(result)))
    run = service.list_runs(conversation_id)[0]
    assert run.workflow_type == "trade_data_analysis"
    assert run.completed_nodes == ["intent", "contract", "authorize", "execute", "audit"]
    assert run.status == "completed"
    events = service.events(run.run_id)
    assert events[-1].type == "workflow.run.completed"
    serialized = json.dumps([event.safe_data for event in events])
    assert "must-not-be-in-event" not in serialized
    assert "inventory_top" in serialized


def test_analysis_workflow_fails_closed_for_disallowed_query(tmp_path: Path):
    service = WorkflowService(tmp_path / "workflows")
    conversation_id = "59c50f2b-3c09-4af9-95e3-c1ba305ff123"
    asyncio.run(service.observe_analytics(f"web:local:{conversation_id}",
                                         json.dumps({"error": "query_not_allowlisted", "error_code": "query_not_allowlisted"})))
    run = service.list_runs(conversation_id)[0]
    assert run.status == "failed" and run.current_node == "execute"
    assert service.events(run.run_id)[-1].safe_data == {"error_code": "query_not_allowlisted"}
