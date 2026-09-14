from __future__ import annotations

import io
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

from trade_rag.config import OcrConfig
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.ocr import PaddleOcrProvider
from trade_rag.pipeline import RagPipeline


pytestmark = pytest.mark.skipif(
    os.environ.get("NANOCLAW_TEST_REAL_OCR") != "1",
    reason="requires project-local PaddleOCR models",
)


def _config() -> OcrConfig:
    return OcrConfig(True, "paddleocr", "ch", "cpu", 0.60, 20, 20_000_000,
                     40_000_000, 20_000, 150, 32, 32)


def _label_image() -> Image.Image:
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 32)
    image = Image.new("RGB", (640, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 30), "SCAN SKU 2026", font=font, fill="black")
    draw.text((30, 90), "MOQ 100 UNITS", font=font, fill="black")
    return image


def test_real_paddleocr_image_and_scanned_pdf(tmp_path):
    image = _label_image()
    png = io.BytesIO(); image.save(png, format="PNG")
    pdf = io.BytesIO(); image.save(pdf, format="PDF", resolution=150)
    provider = PaddleOcrProvider(_config())

    direct = provider.recognize(png.getvalue())
    assert "SKU" in direct.text.upper()
    assert direct.status in {"ready", "low_confidence"}

    repository = KnowledgeRepository(
        tmp_path / "knowledge", ocr_config=_config(), ocr_provider=provider
    )
    imported = repository.import_bytes(
        "scan.pdf", pdf.getvalue(), content_type="application/pdf"
    )
    assert imported["image_count"] >= 1
    assert imported["images"][0]["image_index"] == 1
    if imported["status"] == "review_required":
        assert imported["review_type"] == "ocr_low_confidence"
        repository.approve_review(imported["document_id"])

    pipeline = RagPipeline()
    indexed = repository.index_pdf(
        imported["document_id"], index_prepared=pipeline.index_prepared
    )
    assert indexed["indexed_count"] > 0
    image_children = [
        entry.child for entry in pipeline.store._entries.values()
        if entry.child.metadata.get("image_index")
    ]
    assert image_children
    assert image_children[0].metadata["page_number"] == 1
