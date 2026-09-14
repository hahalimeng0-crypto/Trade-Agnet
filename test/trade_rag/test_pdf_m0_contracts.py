import json
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader

from pdf_fixture_factory import build_fixture
from trade_rag.config import load_pdf_ingestion_config
from trade_rag.contracts import (
    ParseResult,
    ParsedBlock,
    ParsedBlockType,
    PdfErrorCode,
    PdfIngestionRoute,
    PdfWarningCode,
    ProcessingStatus,
    SourceLocation,
)

FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _block(text="DDP Madrid guidance", page_start=1, page_end=1):
    return ParsedBlock(
        text=text,
        location=SourceLocation(page_start, page_end, ("Shipping",), ParsedBlockType.PARAGRAPH),
        ordinal=0,
    )


def test_source_location_and_parse_result_contracts_are_strict():
    location = SourceLocation(2, 3, ("Trade", "Incoterms"), ParsedBlockType.TABLE, (0, 0, 100, 80))
    assert location.page_start == 2 and location.page_end == 3
    ready = ParseResult("pdfplumber", "pdfplumber-0.11.10+pdf-v1", 1, 19, 1.0, False,
                        ProcessingStatus.READY, blocks=(_block(),))
    assert ready.indexable is True
    needs_ocr = ParseResult("pdfplumber", "pdfplumber-0.11.10+pdf-v1", 3, 0, 0.0, True,
                            ProcessingStatus.NEEDS_OCR, (PdfWarningCode.EMPTY_PAGE,), ())
    assert needs_ocr.indexable is False

    with pytest.raises(ValueError): SourceLocation(0, 1)
    with pytest.raises(ValueError): SourceLocation(2, 1)
    with pytest.raises(ValueError): ParsedBlock(" ", SourceLocation(1, 1), 0)
    with pytest.raises(ValueError):
        ParseResult("pdfplumber", "v1", 1, 0, 0.0, False, ProcessingStatus.READY)
    with pytest.raises(ValueError):
        ParseResult("pdfplumber", "v1", 1, 0, 0.0, True, ProcessingStatus.FAILED)


def test_pdf_status_error_and_warning_vocabulary_is_frozen():
    assert {item.value for item in ProcessingStatus} == {"pending", "running", "ready", "failed", "needs_ocr"}
    assert {item.value for item in PdfErrorCode} == {
        "pdf_signature_mismatch", "pdf_encrypted", "pdf_page_limit_exceeded", "pdf_parse_timeout",
        "pdf_parse_failed", "pdf_needs_ocr", "pdf_text_limit_exceeded", "file_too_large",
        "knowledge_index_failed",
    }
    assert "pdf_partial_text_coverage" in {item.value for item in PdfWarningCode}
    assert {item.value for item in PdfIngestionRoute} == {"index", "review_required", "needs_ocr", "reject"}


def test_pdf_threshold_defaults_and_environment_validation():
    with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, {}, clear=True):
        config = load_pdf_ingestion_config()
    assert config.max_bytes == 20 * 1024 * 1024
    assert config.max_pages == 300
    assert config.min_text_page_ratio == 0.8
    assert config.max_concurrent_parses == 2

    invalid = {"RAG_PDF_MIN_TEXT_PAGE_RATIO": "1.1"}
    with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, invalid, clear=True):
        with pytest.raises(ValueError): load_pdf_ingestion_config()
    invalid = {"RAG_PDF_MAX_TOTAL_CHARS": "100", "RAG_PDF_MAX_CHARS_PER_PAGE": "200"}
    with patch("trade_rag.config._PROJECT_ENV", Path("missing.env")), patch.dict(os.environ, invalid, clear=True):
        with pytest.raises(ValueError): load_pdf_ingestion_config()


def test_fixture_manifest_covers_m0_matrix_and_contains_no_business_documents():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    cases = manifest["cases"]
    assert manifest["schema_version"] == "pdf-fixtures-v1"
    assert len(cases) == 11
    assert len({case["id"] for case in cases}) == len(cases)
    assert {case["category"] for case in cases} >= {
        "text", "bilingual", "table", "layout", "normalization", "ocr", "security", "limits"
    }
    serialized = json.dumps(manifest, ensure_ascii=False).casefold()
    for forbidden in ("customer@example", "api_key", "authorization code", "真实客户"):
        assert forbidden not in serialized
    valid_errors = {item.value for item in PdfErrorCode}
    valid_warnings = {item.value for item in PdfWarningCode}
    valid_routes = {item.value for item in PdfIngestionRoute}
    for case in cases:
        expected = case["expected"]
        assert {"route", "pages", "needs_ocr"} <= set(expected)
        assert expected["route"] in valid_routes
        if "error_code" in expected:
            assert expected["error_code"] in valid_errors
        assert set(expected.get("warning_codes", [])) <= valid_warnings


def test_fixture_factory_materializes_valid_and_adversarial_cases(tmp_path):
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in manifest["cases"]}
    config = load_pdf_ingestion_config()

    for fixture_id in ("text_english", "text_bilingual", "table_units", "two_column", "repeated_header",
                       "scanned_only", "mixed_text_scan"):
        case = by_id[fixture_id]
        payload = build_fixture(case)
        path = tmp_path / f"{fixture_id}.pdf"
        path.write_bytes(payload)
        reader = PdfReader(BytesIO(payload))
        assert len(reader.pages) == case["expected"]["pages"]
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        for term in case["expected"].get("required_terms", []):
            assert term in extracted

    encrypted = build_fixture(by_id["encrypted"])
    assert PdfReader(BytesIO(encrypted)).is_encrypted
    with pytest.raises(Exception): PdfReader(BytesIO(build_fixture(by_id["malformed"])))
    assert len(PdfReader(BytesIO(build_fixture(by_id["page_limit"]))).pages) == config.max_pages + 1
    assert len(build_fixture(by_id["size_limit"])) == config.max_bytes + 1
