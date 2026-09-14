from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def disable_real_ocr_by_default(monkeypatch):
    """Unit tests opt into fake OCR explicitly; real models belong to smoke tests."""
    monkeypatch.setenv("RAG_OCR_ENABLED", "false")
