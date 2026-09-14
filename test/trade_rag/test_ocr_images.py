from __future__ import annotations

import io
import time

import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bus import MessageBus
from channels.web import WebChannel
from trade_rag.config import OcrConfig
from trade_rag.contracts import (
    Actor, ImageSourceKind, ParseResult, ProcessingStatus, QueryRequest,
)
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.ocr import OcrOutput, extract_pdf_images, make_image_artifact
from trade_rag.pipeline import RagPipeline


def _config() -> OcrConfig:
    return OcrConfig(True, "paddleocr", "ch", "cpu", 0.6, 20, 2_000_000,
                     4_000_000, 20_000, 100, 32, 32)


def _png() -> bytes:
    image = Image.new("RGB", (200, 80), "white")
    output = io.BytesIO(); image.save(output, format="PNG")
    return output.getvalue()


def _encoded_image(image_format: str) -> bytes:
    image = Image.new("RGB", (200, 80), "white")
    output = io.BytesIO(); image.save(output, format=image_format)
    return output.getvalue()


def _image_pdf() -> bytes:
    image = Image.new("RGB", (300, 120), "white")
    output = io.BytesIO(); image.save(output, format="PDF")
    return output.getvalue()


class FakeOcr:
    model_id = "fake-ocr-v1"
    def recognize(self, payload: bytes) -> OcrOutput:
        assert payload
        return OcrOutput("SKU-Z MOQ 100 units", 0.98, "ready")


class FakeLowConfidenceOcr:
    model_id = "fake-ocr-low-v1"
    def recognize(self, payload: bytes) -> OcrOutput:
        return OcrOutput("SKU-LOW MOQ 50", 0.42, "low_confidence")


class FakeNoTextOcr:
    model_id = "fake-ocr-empty-v1"
    def recognize(self, payload: bytes) -> OcrOutput:
        return OcrOutput("", None, "no_text")


def _client(repository: KnowledgeRepository):
    channel = WebChannel(MessageBus())
    channel._knowledge_repository = repository
    channel._knowledge_pipeline = RagPipeline()
    channel._app = FastAPI()
    channel._register_routes()
    return channel, TestClient(channel._app)


def test_image_artifact_has_stable_one_based_index():
    payload = _png()
    first = make_image_artifact(
        document_source_hash="doc", image_index=1,
        source_kind=ImageSourceKind.STANDALONE, page_number=None,
        page_image_index=1, payload=payload, mime_type="image/png",
        width=200, height=80, output=OcrOutput("text", 0.9, "ready"),
    )
    second = make_image_artifact(
        document_source_hash="doc", image_index=1,
        source_kind=ImageSourceKind.STANDALONE, page_number=None,
        page_image_index=1, payload=payload, mime_type="image/png",
        width=200, height=80, output=OcrOutput("text", 0.9, "ready"),
    )
    assert first.image_index == 1 and first.image_id == second.image_id


def test_standalone_image_creates_image_child_metadata(tmp_path):
    repository = KnowledgeRepository(tmp_path, ocr_config=_config(), ocr_provider=FakeOcr())
    imported = repository.import_bytes("label.png", _png(), content_type="image/png")
    assert imported["image_count"] == imported["ocr_image_count"] == 1
    assert imported["images"][0]["image_index"] == 1
    document = repository._load_entry_document(imported)
    parents, children = repository.splitter.split(document)
    assert len(parents) == 1 and children
    assert children[0].metadata["image_id"] == imported["images"][0]["image_id"]
    assert children[0].metadata["image_index"] == 1
    assert children[0].metadata["block_type"] == "image"


def test_image_signature_mismatch_is_rejected(tmp_path):
    repository = KnowledgeRepository(tmp_path, ocr_config=_config(), ocr_provider=FakeOcr())
    try:
        repository.import_bytes("label.png", _png(), content_type="image/jpeg")
    except ValueError as exc:
        assert str(exc) == "image_signature_mismatch"
    else:
        raise AssertionError("MIME mismatch must be rejected")


@pytest.mark.parametrize(("filename", "mime_type", "image_format"), [
    ("label.png", "image/png", "PNG"),
    ("label.jpg", "image/jpeg", "JPEG"),
    ("label.webp", "image/webp", "WEBP"),
])
def test_standalone_image_formats_are_ocr_indexable(
        tmp_path, filename, mime_type, image_format):
    repository = KnowledgeRepository(
        tmp_path / image_format.lower(), ocr_config=_config(), ocr_provider=FakeOcr()
    )
    imported = repository.import_bytes(
        filename, _encoded_image(image_format), content_type=mime_type
    )
    assert imported["content_type"] == mime_type
    assert imported["images"][0]["image_index"] == 1
    assert imported["child_count"] > 0


def test_pdf_embedded_image_is_extracted_with_page_local_index():
    rows = extract_pdf_images(_image_pdf(), scanned_pages=set(), config=_config())
    assert len(rows) == 1
    assert rows[0]["source_kind"] == ImageSourceKind.PDF_EMBEDDED
    assert rows[0]["page_number"] == rows[0]["page_image_index"] == 1
    assert rows[0]["payload"].startswith(b"\x89PNG")


def test_no_text_image_keeps_index_but_creates_no_vector(tmp_path):
    repository = KnowledgeRepository(
        tmp_path, ocr_config=_config(), ocr_provider=FakeNoTextOcr()
    )
    channel, client = _client(repository)
    response = client.post(
        "/api/knowledge/import", content=_png(),
        headers={"X-File-Name": "blank.png", "Content-Type": "image/png"},
    )
    assert response.status_code == 200
    item = repository.get_document(response.json()["document_id"])
    assert item["images"][0]["image_index"] == 1
    assert item["images"][0]["ocr_status"] == "no_text"
    assert item["ocr_no_text_count"] == 1
    assert item["child_count"] == item["indexed_count"] == 0
    assert channel._knowledge_pipeline.store._entries == {}


def test_low_confidence_image_requires_approval_then_indexes_and_cites_image(tmp_path):
    repository = KnowledgeRepository(
        tmp_path, ocr_config=_config(), ocr_provider=FakeLowConfidenceOcr()
    )
    channel, client = _client(repository)
    imported = client.post(
        "/api/knowledge/import", content=_png(),
        headers={"X-File-Name": "label.png", "Content-Type": "image/png"},
    ).json()
    document_id = imported["document_id"]
    before = client.get(f"/api/knowledge/documents/{document_id}").json()
    assert before["status"] == "review_required"
    assert before["review_type"] == "ocr_low_confidence"
    assert before["review_approval_eligible"] is True
    assert channel._knowledge_pipeline.store._entries == {}

    approved = client.post(f"/api/knowledge/documents/{document_id}/approve-review")
    assert approved.status_code == 200, approved.text
    after = approved.json()
    assert after["status"] == "published" and after["index_status"] == "indexed"
    assert after["classification"] == "internal"
    child = next(iter(channel._knowledge_pipeline.store._entries.values())).child
    assert child.metadata["image_index"] == 1
    assert child.metadata["page_number"] is None

    channel._knowledge_pipeline.gate = type(
        "HighConfidenceGate", (), {"classify": lambda self, results: "HIGH_CONFIDENCE"}
    )()
    answer = channel._knowledge_pipeline.query(QueryRequest(
        "SKU-LOW", Actor("workspace", business_unit_id="default"), rerank=False
    ))
    citation = answer["citations"][0]
    assert citation["image_id"] == child.metadata["image_id"]
    assert citation["image_index"] == 1 and citation["page_number"] is None


def test_scanned_pdf_images_are_contiguous_and_become_image_chunks(tmp_path, monkeypatch):
    payload = b"%PDF-1.7 synthetic scan"
    parse_result = ParseResult(
        parser="fake", parser_version="fake-v1", pages=2, text_chars=0,
        text_page_ratio=0.0, needs_ocr=True, status=ProcessingStatus.NEEDS_OCR,
        page_char_counts=(0, 0), blank_pages=(1, 2),
    )
    monkeypatch.setattr(
        "trade_rag.knowledge_repository.parse_document_bytes",
        lambda *_args, **_kwargs: parse_result,
    )
    monkeypatch.setattr(
        "trade_rag.knowledge_repository.extract_pdf_images",
        lambda *_args, **_kwargs: [
            {"source_kind": ImageSourceKind.PDF_PAGE, "page_number": page,
             "page_image_index": 1, "payload": _png(), "mime_type": "image/png",
             "width": 200, "height": 80}
            for page in (1, 2)
        ],
    )
    repository = KnowledgeRepository(tmp_path, ocr_config=_config(), ocr_provider=FakeOcr())
    imported = repository.import_bytes("scan.pdf", payload, content_type="application/pdf")
    assert imported["needs_ocr"] is False and imported["status"] == "published"
    assert [row["image_index"] for row in imported["images"]] == [1, 2]
    document, parents, children = repository.load_pdf_chunks(imported["document_id"])
    assert document.metadata["images"][1]["page_number"] == 2
    assert {child.metadata["image_index"] for child in children} == {1, 2}
    assert {child.metadata["page_number"] for child in children} == {1, 2}


def test_low_confidence_scanned_pdf_cannot_index_until_review(tmp_path, monkeypatch):
    payload = b"%PDF-1.7 low confidence scan"
    parse_result = ParseResult(
        parser="fake", parser_version="fake-v1", pages=1, text_chars=0,
        text_page_ratio=0.0, needs_ocr=True, status=ProcessingStatus.NEEDS_OCR,
        page_char_counts=(0,), blank_pages=(1,),
    )
    monkeypatch.setattr(
        "trade_rag.knowledge_repository.parse_document_bytes",
        lambda *_args, **_kwargs: parse_result,
    )
    monkeypatch.setattr(
        "trade_rag.knowledge_repository.extract_pdf_images",
        lambda *_args, **_kwargs: [{
            "source_kind": ImageSourceKind.PDF_PAGE, "page_number": 1,
            "page_image_index": 1, "payload": _png(), "mime_type": "image/png",
            "width": 200, "height": 80,
        }],
    )
    repository = KnowledgeRepository(
        tmp_path, ocr_config=_config(), ocr_provider=FakeLowConfidenceOcr()
    )
    channel, client = _client(repository)
    imported = client.post(
        "/api/knowledge/import", content=payload,
        headers={"X-File-Name": "scan.pdf", "Content-Type": "application/pdf"},
    ).json()
    document_id = imported["document_id"]
    deadline = time.monotonic() + 5
    while True:
        detail = client.get(f"/api/knowledge/documents/{document_id}").json()
        if detail["status"] == "review_required" or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert detail["review_type"] == "ocr_low_confidence"
    assert detail["review_approval_eligible"] is True
    assert detail["status"] == "review_required"
    assert channel._knowledge_pipeline.store._entries == {}

    approved = client.post(f"/api/knowledge/documents/{document_id}/approve-review")
    assert approved.status_code == 200, approved.text
    assert approved.json()["index_status"] == "indexed"
    child = next(iter(channel._knowledge_pipeline.store._entries.values())).child
    assert child.metadata["image_index"] == child.metadata["page_number"] == 1
