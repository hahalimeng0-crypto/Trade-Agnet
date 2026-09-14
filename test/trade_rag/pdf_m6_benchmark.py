"""Reproducible synthetic 20/100/300-page PDF benchmark for the M6 local gate."""

from __future__ import annotations

import json
import sys
import tempfile
import tracemalloc
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pdf_fixture_factory import build_fixture
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.pipeline import RagPipeline


PAGE_SIZES = (20, 100, 300)


def _case(page_count: int) -> dict:
    pages = [[
        f"Synthetic performance page {page}. Controlled de-identified logistics guidance "
        f"for benchmark page {page}; no customer, credential, price, inventory or shipment data."
    ] for page in range(1, page_count + 1)]
    return {"build": {"kind": "text", "pages": pages}}


def run_benchmark(root: Path) -> dict:
    rows = []
    for page_count in PAGE_SIZES:
        repository = KnowledgeRepository(root / str(page_count))
        payload = build_fixture(_case(page_count))
        tracemalloc.start()
        started = perf_counter()
        imported = repository.import_bytes(
            f"synthetic-{page_count}.pdf", payload, content_type="application/pdf"
        )
        parse_ms = (perf_counter() - started) * 1000
        pipeline = RagPipeline()
        started = perf_counter()
        indexed = repository.index_pdf(
            imported["document_id"], index_prepared=pipeline.index_prepared
        )
        index_ms = (perf_counter() - started) * 1000
        peak_bytes = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        rows.append({
            "pages": page_count,
            "source_bytes": len(payload),
            "parents": indexed["parent_count"],
            "children": indexed["child_count"],
            "indexed": indexed["indexed_count"],
            "parse_ms": round(parse_ms, 3),
            "index_ms": round(index_ms, 3),
            "python_peak_bytes": peak_bytes,
        })
    return {
        "schema_version": "pdf-m6-local-baseline-v1",
        "scope": "synthetic local pdfplumber plus Mock Embedding and in-memory stores",
        "memory_scope": "parent Python allocations measured by tracemalloc; parser child RSS excluded",
        "production_ready": False,
        "rows": rows,
    }


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="nanoclaw-pdf-m6-") as temp:
        print(json.dumps(run_benchmark(Path(temp)), ensure_ascii=False, indent=2))
