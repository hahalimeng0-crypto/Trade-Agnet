from pathlib import Path

from agent.memory_runtime.models import MemoryItem, MemoryScope
from agent.memory_runtime.stores.mysql import MySQLCompatConnection
from agent.memory_runtime.stores.vector import LocalHashEmbeddingAdapter, MilvusMemoryIndex


class FakeCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.description = (("value",),) if rows else None
        self.rowcount = len(self.rows) if rows else 1
        self.lastrowid = None
        self.statement = None
        self.parameters = None

    def execute(self, statement, parameters):
        self.statement, self.parameters = statement, parameters

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeRawConnection:
    def __init__(self):
        self.cursors = []
        self.begins = self.commits = self.rollbacks = 0

    def cursor(self):
        cursor = FakeCursor()
        self.cursors.append(cursor)
        return cursor

    def begin(self):
        self.begins += 1

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


def test_mysql_adapter_translates_sqlite_contract_and_commits():
    raw = FakeRawConnection()
    connection = MySQLCompatConnection(raw)
    with connection:
        result = connection.execute("INSERT OR IGNORE INTO t VALUES (?,?)", ("a", 2))
    assert raw.cursors[0].statement == "INSERT IGNORE INTO t VALUES (%s,%s)"
    assert raw.cursors[0].parameters == ("a", 2)
    assert result.rowcount == 1
    assert (raw.begins, raw.commits, raw.rollbacks) == (1, 1, 0)


class FakeMilvusClient:
    def __init__(self):
        self.entities = []
        self.deleted_filter = ""
        self.search_filter = ""

    def has_collection(self, **kwargs):
        return kwargs["collection_name"] == "memory_v1"

    def describe_collection(self, **kwargs):
        return {"fields": [{"name": "embedding", "params": {"dim": 8}}]}

    def load_collection(self, **kwargs):
        pass

    def upsert(self, **kwargs):
        self.entities.extend(kwargs["data"])

    def delete(self, **kwargs):
        self.deleted_filter = kwargs["filter"]

    def search(self, **kwargs):
        self.search_filter = kwargs["filter"]
        return [[{
            "distance": 0.9,
            "entity": {
                "memory_id": "m-1",
                "embedding_model": "local-hash-v1-8",
                "source_version": 1,
            },
        }]]


def memory_item():
    return MemoryItem(
        "m-1", MemoryScope(
            "workspace_private", "tenant-a", subject_id="operator-a",
            project_id="project-a", purpose="project_assistance",
        ),
        "semantic", "The customer prefers blue packaging", "Blue packaging",
        ("message-1",), "active", 0.9, 0.8, "internal", None, 1, None,
        "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z", None, "a" * 64, None,
    )


def test_milvus_index_contains_only_vector_scope_and_mysql_id():
    client = FakeMilvusClient()
    index = MilvusMemoryIndex(
        uri="http://milvus:19530", token="", database="default",
        collection="memory_v1", embedding=LocalHashEmbeddingAdapter(8), client=client,
    )
    item = memory_item()
    index.upsert(item)
    entity = client.entities[0]
    assert entity["memory_id"] == item.memory_id
    assert entity["tenant_id"] == item.scope.tenant_id
    assert "content" not in entity and "summary" not in entity

    hits = index.search(item.scope, "blue packaging", 3)
    assert [hit.memory_id for hit in hits] == ["m-1"]
    assert 'tenant_id == "tenant-a"' in client.search_filter
    assert 'project_id == "project-a"' in client.search_filter

    index.delete("m-1")
    assert client.deleted_filter == 'memory_id == "m-1"'


def test_mysql_migration_declares_all_authoritative_tables():
    migration = (
        Path(__file__).parents[1]
        / "agent/memory_runtime/migrations/001_long_term_memory.mysql.sql"
    ).read_text(encoding="utf-8")
    for table in (
        "customer_memory_consent", "customer_memory_item", "memory_index_outbox",
        "workspace_memory_item", "workspace_memory_index_outbox",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration
    assert "GENERATED ALWAYS" in migration
