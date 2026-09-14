"""Create the two long-term memory collections with a Milvus admin token."""

from __future__ import annotations

import os

from config import load_config
from .stores.vector import LocalHashEmbeddingAdapter, MilvusMemoryIndex


def main() -> None:
    config = load_config()
    admin_token = os.environ.get("NANOCLAW_MEMORY_MILVUS_ADMIN_TOKEN", "").strip()
    if not admin_token:
        raise RuntimeError("NANOCLAW_MEMORY_MILVUS_ADMIN_TOKEN is required")
    dimensions = {
        config.memory_milvus_customer_collection: config.memory_embedding_dimensions,
        config.memory_milvus_workspace_collection: config.workspace_memory_embedding_dimensions,
    }
    for collection, size in dimensions.items():
        MilvusMemoryIndex(
            uri=config.memory_milvus_uri, token=admin_token,
            database=config.memory_milvus_database, collection=collection,
            embedding=LocalHashEmbeddingAdapter(size), create_collection=True,
        )
        print(f"ready: {config.memory_milvus_database}.{collection} ({size})")


if __name__ == "__main__":
    main()
