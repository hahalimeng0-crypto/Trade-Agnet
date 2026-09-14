import copy
from pathlib import Path

from trade_rag.knowledge_repository import KnowledgeRepository


class MemoryMetadataStore:
    def __init__(self):
        self.value = {
            "schema_version": "knowledge-import-v4",
            "documents": [],
            "_storage_revision": 0,
        }

    def read(self):
        return copy.deepcopy(self.value)

    def write(self, manifest):
        value = copy.deepcopy(manifest)
        value["_storage_revision"] = int(value.get("_storage_revision", 0)) + 1
        self.value = value
        manifest["_storage_revision"] = value["_storage_revision"]


def test_repository_uses_metadata_authority_without_writing_manifest(tmp_path: Path):
    store = MemoryMetadataStore()
    repository = KnowledgeRepository(tmp_path / "knowledge", metadata_store=store)

    imported = repository.import_bytes("guide.md", b"Enterprise shipping policy")

    assert imported["document_id"] == store.value["documents"][0]["document_id"]
    assert store.value["_storage_revision"] == 1
    assert not repository.manifest_path.exists()
    assert any(repository.documents_dir.iterdir())


def test_mysql_migration_separates_metadata_jobs_and_parent_chunks():
    migration = (Path(__file__).parents[2] / "trade_rag" / "migrations" / "002_mysql_metadata.sql").read_text("utf-8")
    assert "rag_document_metadata" in migration
    assert "rag_index_job" in migration
    assert "rag_parent_chunk" in migration
    assert "parent_text MEDIUMTEXT" in migration
