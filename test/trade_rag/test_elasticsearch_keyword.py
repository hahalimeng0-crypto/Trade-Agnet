import json
import httpx

from trade_rag.config import RagKeywordConfig
from trade_rag.contracts import Actor, CanonicalDocument, ChildChunk, DocumentStatus
from trade_rag.elasticsearch_store import ElasticsearchKeywordStore
from trade_rag.elasticsearch_reindex import rebuild_elasticsearch_keyword_index
from trade_rag.knowledge_repository import KnowledgeRepository


def _config():
    return RagKeywordConfig(
        backend="elasticsearch",
        url="http://127.0.0.1:9201",
        username="elastic",
        password="secret",
        index="trade_knowledge_child_v1",
        timeout_seconds=3,
    )


def _source():
    return CanonicalDocument(
        "doc-1", 2, "sample://guide", "出口产品指南", "body", "source-hash",
        business_unit_id="sales", allowed_roles=frozenset({"sales"}),
        status=DocumentStatus.PUBLISHED,
    )


def _child():
    return ChildChunk(
        "child-1", "parent-1", "doc-1", "蓝色阳极氧化外壳 SKU-42", "page:1", "child-hash"
    )


def test_elasticsearch_document_preserves_image_ocr_metadata():
    metadata = {"block_type": "image", "image_id": "img-1", "image_index": 1,
                "page_number": 1, "page_image_index": 1, "ocr_confidence": 0.97}
    child = ChildChunk(
        "image-child", "image-parent", "doc-1", "SKU image text",
        "page:1#image:1", "image-hash", metadata,
    )
    assert ElasticsearchKeywordStore._document(child, _source())["child_metadata"] == metadata


def test_elasticsearch_bulk_mapping_search_filters_and_delete():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "HEAD" and path == "/trade_knowledge_child_v1":
            return httpx.Response(404)
        if request.method == "PUT" and path == "/trade_knowledge_child_v1":
            captured["mapping"] = json.loads(request.content)
            return httpx.Response(200, json={"acknowledged": True})
        if path == "/_bulk":
            captured["bulk"] = request.content.decode("utf-8")
            return httpx.Response(200, json={"errors": False, "items": []})
        if path == "/trade_knowledge_child_v1/_search":
            captured["search"] = json.loads(request.content)
            row = ElasticsearchKeywordStore._document(_child(), _source())
            return httpx.Response(200, json={
                "hits": {"hits": [{"_score": 7.5, "_source": row}]}
            })
        if path == "/trade_knowledge_child_v1/_delete_by_query":
            captured["delete"] = json.loads(request.content)
            return httpx.Response(200, json={"deleted": 1})
        raise AssertionError(f"unexpected request: {request.method} {path}")

    client = httpx.Client(base_url=_config().url, transport=httpx.MockTransport(handler))
    store = ElasticsearchKeywordStore(_config(), client=client)
    assert store.upsert([_child()], _source()) == 1
    results = store.search("蓝色 SKU-42", Actor("u", frozenset({"sales"}), "sales"), 5)
    assert len(results) == 1
    assert results[0].child.child_id == "child-1"
    assert results[0].retrieval_source == "keyword"
    assert results[0].score == 7.5
    assert store.delete_by_document("doc-1", 2) == 1

    properties = captured["mapping"]["mappings"]["properties"]
    assert captured["mapping"]["settings"] == {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    }
    assert properties["child_text"]["analyzer"] == "cjk"
    assert '"_id": "child-1"' in captured["bulk"]
    filters = captured["search"]["query"]["bool"]["filter"]
    assert {"term": {"business_unit_id": "sales"}} in filters
    assert any("terms" in choice for choice in filters[2]["bool"]["should"])
    assert captured["delete"]["query"]["bool"]["filter"][-1] == {
        "term": {"document_version": 2}
    }


def test_elasticsearch_readiness_and_bulk_failure_are_explicit():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_cluster/health":
            return httpx.Response(200, json={"status": "yellow", "timed_out": False})
        if request.method == "HEAD":
            return httpx.Response(200)
        if request.url.path == "/_bulk":
            return httpx.Response(200, json={"errors": True, "items": [{"index": {"status": 400}}]})
        raise AssertionError(request.url.path)

    store = ElasticsearchKeywordStore(
        _config(), client=httpx.Client(base_url=_config().url, transport=httpx.MockTransport(handler))
    )
    store.check_ready()
    try:
        store.upsert([_child()], _source())
        raise AssertionError("bulk failure must not be accepted")
    except RuntimeError as exc:
        assert str(exc) == "elasticsearch_bulk_index_failed"


def test_keyword_config_rejects_missing_credentials_and_unsafe_index():
    try:
        RagKeywordConfig("elasticsearch", url="http://localhost:9201").validate()
        raise AssertionError("missing credentials must fail")
    except ValueError as exc:
        assert "missing Elasticsearch configuration" in str(exc)

    try:
        RagKeywordConfig(
            "elasticsearch", "http://localhost:9201", "elastic", "secret", "Upper Case"
        ).validate()
        raise AssertionError("unsafe index name must fail")
    except ValueError as exc:
        assert "INDEX is invalid" in str(exc)


def test_reindex_is_dry_run_by_default_and_cleans_stale_versions(tmp_path):
    repository = KnowledgeRepository(tmp_path / "knowledge")
    active = repository.import_bytes("active.md", b"active export guide")
    stale = repository.import_bytes("stale.md", b"withdrawn export guide")
    repository.revoke(stale["document_id"], delete_index=lambda *_args: None)

    class FakeStore:
        def __init__(self):
            self.ready = False
            self.upserts = []
            self.deletes = []

        def check_ready(self):
            self.ready = True

        def upsert(self, children, document):
            rows = list(children)
            self.upserts.append((document.document_id, len(rows)))
            return len(rows)

        def delete_by_document(self, document_id, version):
            self.deletes.append((document_id, version))
            return 3

    store = FakeStore()
    preview = rebuild_elasticsearch_keyword_index(repository, store)
    assert preview["mode"] == "dry_run"
    assert preview["active_documents"] == 1
    assert preview["stale_documents"] == 1
    assert not store.ready and not store.upserts and not store.deletes

    applied = rebuild_elasticsearch_keyword_index(repository, store, apply=True)
    assert store.ready
    assert store.upserts[0][0] == active["document_id"]
    assert store.deletes == [(stale["document_id"], 1)]
    assert applied["indexed_chunks"] == preview["active_chunks"]
    assert applied["deleted_chunks"] == 3
