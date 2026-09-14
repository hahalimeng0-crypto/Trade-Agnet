import unittest
from trade_rag.contracts import Actor, CanonicalDocument, ChildChunk, DocumentStatus, SearchResult
from trade_rag.hybrid import HybridRetriever

def row(idx, score, source="semantic"):
    child=ChildChunk(f"c{idx}",f"p{idx}","d",f"SKU-{idx} content","loc",f"h{idx}")
    doc=CanonicalDocument("d",1,"sample://d","D","x","h",status=DocumentStatus.PUBLISHED)
    return SearchResult(child,score,doc,retrieval_source=source)

class Store:
    def __init__(self, rows=None, fail=False): self.rows=rows or []; self.fail=fail
    def search(self, *args):
        if self.fail: raise RuntimeError("unavailable")
        return self.rows

class Embedder:
    def embed(self, texts): return [[1.0] for _ in texts]

class HybridTests(unittest.TestCase):
    def test_weighted_rrf_accumulates_same_id(self):
        semantic=[row(0,.9),row(1,.8)]
        keyword=[row(1,10,"keyword"),row(2,8,"keyword")]
        retriever=HybridRetriever(Store(semantic),Store(keyword),Embedder(),semantic_weight=.7,rrf_k=60)
        result=retriever.search("SKU",Actor("u"),10)
        self.assertEqual(retriever.last_mode,"hybrid")
        self.assertEqual(result[0].child.child_id,"c1")
        self.assertAlmostEqual(result[0].rrf_score,.7/62+.3/61)

    def test_single_route_and_total_failure(self):
        semantic=[row(0,.9)]
        retriever=HybridRetriever(Store(semantic),Store(fail=True),Embedder())
        self.assertEqual(len(retriever.search("q",Actor("u"))),1); self.assertEqual(retriever.last_mode,"semantic")
        retriever=HybridRetriever(Store(fail=True),Store(fail=True),Embedder())
        self.assertEqual(retriever.search("q",Actor("u")),[]); self.assertEqual(retriever.last_mode,"unavailable")

    def test_weight_boundaries(self):
        semantic=[row(0,.9)]; keyword=[row(1,10,"keyword")]
        zero=HybridRetriever(Store(semantic),Store(keyword),Embedder(),semantic_weight=0).search("q",Actor("u"),10)
        one=HybridRetriever(Store(semantic),Store(keyword),Embedder(),semantic_weight=1).search("q",Actor("u"),10)
        self.assertEqual(zero[0].child.child_id,"c1"); self.assertEqual(one[0].child.child_id,"c0")

if __name__ == "__main__": unittest.main()
