import json
from pathlib import Path

from trade_rag.chunking import PDF_SPLITTER_VERSION, PdfAwareParentChildSplitter
from trade_rag.contracts import (
    Actor,
    CanonicalDocument,
    DocumentStatus,
    ParseResult,
    ParsedBlock,
    ParsedBlockType,
    ProcessingStatus,
    SourceLocation,
)
from trade_rag.knowledge_repository import KnowledgeRepository
from trade_rag.stores import InMemoryParentStore

from pdf_fixture_factory import build_fixture


FIXTURE_MANIFEST = Path(__file__).parents[1] / "fixtures" / "pdf" / "manifest.json"


def _cases():
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return {case["id"]: case for case in manifest["cases"]}


def _document() -> CanonicalDocument:
    return CanonicalDocument(
        document_id="pdf-doc",
        version=2,
        source_uri="knowledge://pdf-doc",
        title="Freight Guide",
        content="synthetic parsed content",
        content_hash="content-hash",
        content_type="application/pdf",
        location="pages:1-3",
        language="en",
        business_unit_id="trade",
        allowed_roles=frozenset({"sales"}),
        classification="internal",
        status=DocumentStatus.PUBLISHED,
        metadata={"source_hash": "source-sha256"},
    )


def _parsed() -> ParseResult:
    section = ("Shipping Terms",)
    blocks = (
        ParsedBlock("Shipping Terms", SourceLocation(1, 1, section, ParsedBlockType.HEADING), 0),
        ParsedBlock(
            "DDP Madrid requires an agreed delivery scope and named destination. " * 4,
            SourceLocation(1, 1, section, ParsedBlockType.PARAGRAPH), 1,
        ),
        ParsedBlock(
            "FOB Shanghai transfers risk at the named port.",
            SourceLocation(2, 2, section, ParsedBlockType.PARAGRAPH), 2,
        ),
        ParsedBlock(
            "Destination | Lead time | Unit\nMadrid | 12 | days\nHamburg | 10 | days\n"
            "Rotterdam | 9 | days\nAntwerp | 8 | days",
            SourceLocation(2, 2, ("Freight Table",), ParsedBlockType.TABLE), 3,
        ),
        ParsedBlock("Page 3", SourceLocation(3, 3, (), ParsedBlockType.PARAGRAPH), 4),
    )
    return ParseResult(
        parser="fixture",
        parser_version="fixture-1",
        pages=3,
        text_chars=sum(len(block.text) for block in blocks),
        text_page_ratio=1.0,
        needs_ocr=False,
        status=ProcessingStatus.READY,
        blocks=blocks,
        page_char_counts=(200, 200, 6),
    )


def test_pdf_splitter_has_stable_ids_exact_page_links_and_required_metadata():
    splitter = PdfAwareParentChildSplitter(parent_chars=500, child_chars=130, overlap=20)
    parents, children = splitter.split(_document(), _parsed())
    repeated_parents, repeated_children = splitter.split(_document(), _parsed())

    assert [parent.parent_id for parent in parents] == [parent.parent_id for parent in repeated_parents]
    assert [child.child_id for child in children] == [child.child_id for child in repeated_children]
    parent_ids = {parent.parent_id for parent in parents}
    assert children and all(child.parent_id in parent_ids for child in children)
    assert not any("Page 3" in parent.text or "Page 3" in child.text for parent in parents for child in children)
    for child in children:
        metadata = child.metadata
        assert metadata["page_start"] <= metadata["page_end"]
        assert metadata["business_unit_id"] == "trade"
        assert metadata["allowed_roles"] == ("sales",)
        assert metadata["classification"] == "internal"
        assert metadata["parent_id"] == child.parent_id
        assert metadata["source_hash"] == "source-sha256"
        assert metadata["splitter_version"] == PDF_SPLITTER_VERSION


def test_long_table_children_repeat_header_and_do_not_cross_unrelated_blocks():
    splitter = PdfAwareParentChildSplitter(parent_chars=240, child_chars=90, overlap=10)
    parents, children = splitter.split(_document(), _parsed())
    table_children = [child for child in children if child.metadata["block_type"] == "table"]
    assert len(table_children) >= 2
    assert all(child.text.startswith("Destination | Lead time | Unit") for child in table_children)
    table_parent_ids = {child.parent_id for child in table_children}
    assert all(parent.metadata["block_type"] == "table"
               for parent in parents if parent.parent_id in table_parent_ids)


def test_parent_store_enforces_acl_and_document_version_delete():
    splitter = PdfAwareParentChildSplitter()
    parents, _ = splitter.split(_document(), _parsed())
    store = InMemoryParentStore()
    assert store.upsert(parents, _document()) == len(parents)
    allowed = Actor("sales-user", frozenset({"sales"}), "trade")
    denied_role = Actor("finance-user", frozenset({"finance"}), "trade")
    denied_unit = Actor("sales-user", frozenset({"sales"}), "other")
    assert store.get(parents[0].parent_id, allowed) == parents[0]
    assert store.get(parents[0].parent_id, denied_role) is None
    assert store.get(parents[0].parent_id, denied_unit) is None
    assert store.delete_by_document("pdf-doc", 1) == 0
    assert store.delete_by_document("pdf-doc", 2) == len(parents)


def test_repository_chunks_indexable_pdf_and_restart_preview_is_stable(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    payload = build_fixture(_cases()["table_units"])
    imported = repository.import_bytes("freight.pdf", payload, content_type="application/pdf")

    assert imported["chunk_status"] == "ready"
    assert imported["index_status"] == "pending" and imported["indexed_count"] == 0
    assert imported["splitter_version"] == PDF_SPLITTER_VERSION
    assert imported["parent_count"] > 0 and imported["child_count"] >= imported["parent_count"]
    assert repository.load_published() == []  # PDF uses prepared chunks instead of the text loader.

    preview = repository.preview_pdf_chunks(imported["document_id"])
    restarted = KnowledgeRepository(repository.root)
    assert restarted.preview_pdf_chunks(imported["document_id"]) == preview
    assert preview["parent_count"] == imported["parent_count"]
    assert preview["child_count"] == imported["child_count"]
    serialized = json.dumps(preview)
    assert "stored_name" not in serialized and str(tmp_path) not in serialized
    table_children = [row for row in preview["children"] if row["block_type"] == "table"]
    assert table_children and all("Destination | Lead time | Unit" in row["text"] for row in table_children)


def test_review_required_pdf_is_not_chunked(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    payload = build_fixture(_cases()["mixed_text_scan"])
    imported = repository.import_bytes("mixed.pdf", payload, content_type="application/pdf")
    assert imported["status"] == "review_required"
    assert imported["chunk_status"] == "pending" and imported["parent_count"] is None
    try:
        repository.preview_pdf_chunks(imported["document_id"])
    except ValueError as exc:
        assert str(exc) == "knowledge_pdf_not_chunkable"
    else:
        raise AssertionError("review-required PDF must not expose a chunk preview")
