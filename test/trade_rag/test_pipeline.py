import tempfile
import unittest
from pathlib import Path

from trade_rag.contracts import Actor, DocumentStatus, QueryRequest
from trade_rag.chunking import ParentChildSplitter
from trade_rag.loaders import ApprovalWorkflow, DocumentLoader
from trade_rag.pipeline import RagPipeline

class PipelineTests(unittest.TestCase):
    def approved_doc(self):
        root = Path(tempfile.mkdtemp())
        p = root / "guide.md"
        p.write_text("# SKU-A\n\nSKU-A supports FOB shipping and warranty terms.", encoding="utf-8")
        doc = DocumentLoader().load(p, document_id="doc-1", allowed_roles={"sales"})
        flow = ApprovalWorkflow()
        flow.transition(doc, DocumentStatus.APPROVED)
        flow.transition(doc, DocumentStatus.PUBLISHED)
        return doc

    def test_index_query_and_acl(self):
        pipe = RagPipeline(); pipe.index(self.approved_doc())
        ok = pipe.query(QueryRequest("SKU-A warranty", Actor("u", frozenset({"sales"}))))
        self.assertEqual(ok["status"], "ANSWERED"); self.assertTrue(ok["citations"])
        self.assertEqual(ok["retrieval_mode"], "hybrid")
        denied = pipe.query(QueryRequest("SKU-A warranty", Actor("u", frozenset({"finance"}))))
        self.assertEqual(denied["status"], "NO_EVIDENCE")

    def test_dynamic_route(self):
        pipe = RagPipeline(); pipe.index(self.approved_doc())
        result = pipe.query(QueryRequest("当前 SKU-A 库存", Actor("u", frozenset({"sales"}))))
        self.assertEqual(result["status"], "BUSINESS_DATA_REQUIRED")

    def test_multi_query_fuses_before_single_rerank(self):
        class Rewriter:
            def rewrite(self, query, history): return [query, "warranty SKU-A"]
        class Reranker:
            calls = 0
            last_status = "not_called"
            def rerank(self, query, results, top_k=None): self.calls += 1; self.last_status = "success"; return results[:top_k]
        pipe = RagPipeline(rewriter=Rewriter(), splitter=ParentChildSplitter(parent_chars=100, child_chars=12, overlap=2)); pipe.index(self.approved_doc())
        reranker = Reranker(); pipe.reranker = reranker
        pipe.gate = type("HighConfidenceGate", (), {"classify": lambda self, results: "HIGH_CONFIDENCE"})()
        result = pipe.query(QueryRequest("SKU-A warranty", Actor("u", frozenset({"sales"}))))
        self.assertEqual(result["query_count"], 2)
        self.assertEqual(reranker.calls, 1)

if __name__ == "__main__": unittest.main()
