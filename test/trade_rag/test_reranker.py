import json
import unittest

from trade_rag.contracts import CanonicalDocument, ChildChunk, SearchResult
from trade_rag.reranker import ListwiseReranker, unique_parent_results


def result(idx, score, parent=None):
    child = ChildChunk(f"c{idx}", parent or f"p{idx}", "d", f"content {idx}", "page-1", f"h{idx}")
    doc = CanonicalDocument("d", 1, "sample://d", "D", "text", "hash")
    return SearchResult(child, score, doc, rrf_score=score, retrieval_source="hybrid")


class RerankerTests(unittest.TestCase):
    def test_scores_reorder_normalize_and_tag(self):
        generate = lambda _: json.dumps({"scores": [{"idx": 0, "score": 2}, {"idx": 1, "score": 9}]})
        ranked = ListwiseReranker(generate).rerank("q", [result(0, .9), result(1, .2)], 2)
        self.assertEqual([r.child.child_id for r in ranked], ["c1", "c0"])
        self.assertEqual(ranked[0].score, .9); self.assertEqual(ranked[0].rerank_score, .9)
        self.assertEqual(ranked[0].retrieval_source, "hybrid+rerank")

    def test_ties_use_rrf_then_input_order(self):
        generate = lambda _: '{"scores":[{"idx":0,"score":5},{"idx":1,"score":5},{"idx":2,"score":5}]}'
        ranked = ListwiseReranker(generate).rerank("q", [result(0, .4), result(1, .8), result(2, .8)], 3)
        self.assertEqual([r.child.child_id for r in ranked], ["c1", "c2", "c0"])

    def test_fallback_and_markdown_json(self):
        rows = [result(0, .9), result(1, .5)]
        self.assertEqual(ListwiseReranker().rerank("q", rows, 1), rows[:1])
        self.assertEqual(ListwiseReranker(lambda _: "bad").rerank("q", rows, 2), rows)
        reranker = ListwiseReranker(lambda _: '```json\n{"scores":[{"idx":1,"score":10}]}\n```')
        self.assertEqual(reranker.rerank("q", rows, 1)[0].child.child_id, "c1")

    def test_invalid_scores_preview_and_parent_dedupe(self):
        payload = {"scores": [{"idx": 0, "score": -1}, {"idx": 0, "score": 8}, {"idx": 0, "score": 9}, {"idx": 1, "score": 11}, {"idx": 2, "score": 7.5}, {"idx": 9, "score": 5}]}
        reranker = ListwiseReranker(lambda _: json.dumps(payload), preview_len=5)
        rows = [result(0, .8, "same"), result(1, .7, "same"), result(2, .6, "other")]
        ranked = reranker.rerank("q", rows, 3)
        scores = {r.child.child_id: r.rerank_score for r in ranked}
        self.assertEqual(scores, {"c0": .8, "c1": 0, "c2": 0})
        self.assertIn("conte...", reranker.build_prompt("q", rows))
        self.assertEqual([r.child.parent_id for r in unique_parent_results(ranked, 2)], ["same", "other"])


if __name__ == "__main__": unittest.main()
