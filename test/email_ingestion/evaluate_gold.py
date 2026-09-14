"""Evaluate the de-identified email corpus offline and optionally with the configured LLM."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from agent.business.config import load_business_config
from agent.business.email_ingestion import EmailIngestionService
from agent.business.email_repository import EmailRepository
from agent.business.rfq_extractor import extract_rfq_fields, pending_result
from channels.email.mock_source import MockEmailSource


ROOT = Path(__file__).parent
CORPUS = ROOT / "golden"


def _manifest() -> dict:
    return json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))


def _pending_paths(value, prefix="") -> set[str]:
    result = set()
    if isinstance(value, dict):
        if value.get("status") == "pending_confirmation":
            result.add(prefix)
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else key
            result.update(_pending_paths(child, child_prefix))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.update(_pending_paths(child, f"{prefix}[{index}]"))
    return result


def evaluate_offline() -> dict:
    manifest = _manifest()
    envelopes = MockEmailSource(CORPUS, account_id="gold-corpus").fetch_after(0, limit=100)
    by_file = {case["file"]: case for case in manifest["cases"]}
    failures = []
    message_ids = set()
    evidence_total = 0
    evidence_found = 0
    attachment_cases = 0
    for index, envelope in enumerate(envelopes, 1):
        case = by_file[f"gold_{index:02d}.eml"]
        if envelope.internet_message_id in message_ids:
            failures.append(f"{case['case_id']}: duplicate Message-ID")
        message_ids.add(envelope.internet_message_id)
        source = f"{envelope.subject}\n{envelope.text_body}"
        for evidence in case["evidence"]:
            evidence_total += 1
            if evidence in source:
                evidence_found += 1
            else:
                failures.append(f"{case['case_id']}: evidence not found: {evidence}")
        if "<script" in envelope.text_body.lower() or "tracker.example.invalid" in envelope.text_body:
            failures.append(f"{case['case_id']}: unsafe HTML survived")
        if case["contains_attachment"]:
            attachment_cases += 1
            if not envelope.attachments or envelope.attachments[0].processing_status != "not_processed":
                failures.append(f"{case['case_id']}: attachment metadata missing")

    async def stub_extractor(body, context):
        return pending_result()

    import sqlite3
    repository = EmailRepository(sqlite3.connect(":memory:"))
    service = EmailIngestionService(repository, stub_extractor)
    first = [asyncio.run(service.ingest(item)) for item in envelopes]
    second = [asyncio.run(service.ingest(item)) for item in envelopes]
    created_first = sum(bool(item["created"]) for item in first)
    created_second = sum(bool(item["created"]) for item in second)
    if created_first != len(envelopes) or created_second != 0:
        failures.append("idempotency mismatch")
    return {
        "mode": "offline", "case_count": len(envelopes), "manifest_count": manifest["count"],
        "mime_success_rate": len(envelopes) / manifest["count"] if manifest["count"] else 0,
        "evidence_backreference_rate": evidence_found / evidence_total if evidence_total else 1,
        "unique_message_ids": len(message_ids), "attachment_cases": attachment_cases,
        "first_pass_created": created_first, "duplicate_pass_created": created_second,
        "passed": not failures and len(envelopes) == manifest["count"], "failures": failures,
    }


async def evaluate_live() -> dict:
    cfg = load_business_config()
    if not cfg.api_key:
        return {"mode": "live", "passed": False, "skipped": True, "reason": "NANOCLAW_API_KEY is not configured"}
    manifest = _manifest()
    envelopes = MockEmailSource(CORPUS, account_id="gold-corpus").fetch_after(0, limit=100)
    cases = manifest["cases"]
    rows = []
    for case, envelope in zip(cases, envelopes):
        try:
            result = await extract_rfq_fields(envelope.text_body, {"subject": envelope.subject,
                                                                    "from_address": envelope.from_address})
            pending = _pending_paths(result)
            expected_pending = set(case["pending_fields"])
            rows.append({"case_id": case["case_id"], "valid": True,
                         "item_count_ok": len(result["items"]) == case["item_count"],
                         "required_pending_found": sorted(expected_pending & pending),
                         "required_pending_missing": sorted(expected_pending - pending)})
        except Exception as exc:
            rows.append({"case_id": case["case_id"], "valid": False, "error_code": type(exc).__name__})
    valid = sum(row["valid"] for row in rows)
    item_ok = sum(row.get("item_count_ok", False) for row in rows)
    pending_expected = sum(len(case["pending_fields"]) for case in cases)
    pending_found = sum(len(row.get("required_pending_found", [])) for row in rows)
    return {"mode": "live", "model": cfg.llm_model, "case_count": len(rows),
            "schema_valid_rate": valid / len(rows), "item_count_accuracy": item_ok / len(rows),
            "required_pending_recall": pending_found / pending_expected if pending_expected else 1,
            "passed": valid == len(rows) and item_ok == len(rows) and pending_found == pending_expected,
            "cases": rows}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="call the configured business LLM for all 40 cases")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(evaluate_live()) if args.live else evaluate_offline()
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    raise SystemExit(0 if report.get("passed") or report.get("skipped") else 1)


if __name__ == "__main__":
    main()
