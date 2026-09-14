import json
import multiprocessing
from dataclasses import replace
from pathlib import Path

import pytest

from pdf_fixture_factory import build_fixture
from trade_rag.config import load_pdf_ingestion_config
from trade_rag.contracts import PdfErrorCode, PdfWarningCode
from trade_rag.parsers import PdfProcessingError, parse_document_bytes
from trade_rag.parsers import pdf as pdf_parser

FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def test_m1_parser_matches_all_fixture_routes_and_quality_contracts():
    cases = _cases()
    for fixture_id in (
        "text_english", "text_bilingual", "table_units", "two_column",
        "repeated_header", "scanned_only", "mixed_text_scan",
    ):
        case = cases[fixture_id]
        result = parse_document_bytes(
            f"{fixture_id}.pdf", build_fixture(case), content_type="application/pdf"
        )
        expected = case["expected"]
        assert result.parser == "pdfplumber"
        assert result.pages == expected["pages"]
        assert result.needs_ocr is expected["needs_ocr"]
        assert result.route.value == expected["route"]
        assert len(result.page_char_counts) == result.pages
        assert set(expected.get("warning_codes", [])) <= {item.value for item in result.warnings}
        for term in expected.get("required_terms", []):
            assert term in result.content


def test_repeated_boundaries_are_removed_without_losing_page_locations():
    case = _cases()["repeated_header"]
    result = pdf_parser._parse_pdf_bytes_in_process("guide.pdf", build_fixture(case))
    assert "NANOCLAW TRADE GUIDE" not in result.content
    assert "Internal fixture" not in result.content
    assert {block.location.page_start for block in result.blocks} == {1, 2, 3, 4}
    assert PdfWarningCode.REPEATED_HEADER_REMOVED in result.warnings
    assert PdfWarningCode.REPEATED_FOOTER_REMOVED in result.warnings


def test_pdfplumber_failure_uses_pypdf_without_hiding_the_fallback(monkeypatch):
    case = _cases()["text_english"]

    def fail_primary(*_args, **_kwargs):
        raise RuntimeError("synthetic parser failure")

    monkeypatch.setattr(pdf_parser, "_extract_with_pdfplumber", fail_primary)
    result = pdf_parser._parse_pdf_bytes_in_process("guide.pdf", build_fixture(case))
    assert result.parser == "pypdf"
    assert result.parser_version.startswith("pypdf-6.14.2+")
    assert PdfWarningCode.FALLBACK_PARSER_USED in result.warnings
    assert "DDP Madrid" in result.content


@pytest.mark.parametrize(
    ("filename", "content_type", "payload"),
    [
        ("guide.txt", "application/pdf", b"%PDF-1.7\ninvalid"),
        ("guide.pdf", "text/plain", b"%PDF-1.7\ninvalid"),
        ("guide.pdf", "application/pdf", b"not-a-pdf"),
    ],
)
def test_extension_mime_and_magic_conflicts_fail_closed(filename, content_type, payload):
    with pytest.raises(PdfProcessingError) as caught:
        parse_document_bytes(filename, payload, content_type=content_type)
    assert caught.value.code == PdfErrorCode.SIGNATURE_MISMATCH
    assert str(caught.value) == PdfErrorCode.SIGNATURE_MISMATCH.value


def test_adversarial_fixtures_return_stable_body_free_errors():
    cases = _cases()
    for fixture_id in ("encrypted", "malformed", "page_limit", "size_limit"):
        case = cases[fixture_id]
        with pytest.raises(PdfProcessingError) as caught:
            parse_document_bytes(f"{fixture_id}.pdf", build_fixture(case), content_type="application/octet-stream")
        assert caught.value.code.value == case["expected"]["error_code"]
        assert str(caught.value) == case["expected"]["error_code"]


def test_text_and_timeout_limits_are_enforced_before_a_result_is_returned():
    case = _cases()["text_english"]
    payload = build_fixture(case)
    defaults = load_pdf_ingestion_config()
    tiny_text_limit = replace(defaults, max_chars_per_page=10, max_total_chars=100)
    with pytest.raises(PdfProcessingError) as caught:
        parse_document_bytes("guide.pdf", payload, config=tiny_text_limit)
    assert caught.value.code == PdfErrorCode.TEXT_LIMIT_EXCEEDED

    immediate_timeout = replace(defaults, parse_timeout_seconds=0.001)
    children_before = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(PdfProcessingError) as caught:
        parse_document_bytes("guide.pdf", payload, config=immediate_timeout)
    assert caught.value.code == PdfErrorCode.PARSE_TIMEOUT
    assert {child.pid for child in multiprocessing.active_children()} <= children_before


def test_normalization_removes_layout_noise_but_preserves_semantic_hyphens():
    value = "RE-\nWARDS\r\nSKU-Z\t  FOB\u00ad\x00\n\n\nNext"
    assert pdf_parser._normalize_text(value) == "REWARDS\nSKU-Z FOB\n\nNext"
