from __future__ import annotations

from .config import RagVectorConfig, load_rag_vector_config
from .stores import InMemoryParentStore


def create_application_parent_store(config: RagVectorConfig | None = None):
    current = config or load_rag_vector_config()
    current.validate()
    if current.backend == "sqlite":
        from .sqlite_store import SqliteParentStore
        return SqliteParentStore(current)
    from .mysql_metadata import load_rag_metadata_config
    metadata_config = load_rag_metadata_config()
    if metadata_config.backend == "mysql":
        from .mysql_parent_store import MySQLParentStore
        return MySQLParentStore(metadata_config)
    return InMemoryParentStore()
