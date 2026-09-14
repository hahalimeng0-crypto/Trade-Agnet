import json
import unittest

from trade_rag.contracts import HistoryMessage
from trade_rag.query_rewriter import QueryRewriter


class QueryRewriterTests(unittest.TestCase):
    def test_history_window_prompt_and_deduplication(self):
        prompts = []
        def generate(prompt):
            prompts.append(prompt)
            return json.dumps({"queries": ["DAG Runtime 如何实现", "dag runtime 如何实现", "图式运行时实现方法"]}, ensure_ascii=False)
        history = tuple(HistoryMessage("user", str(i) * 250) for i in range(8))
        result = QueryRewriter(generate, 3).rewrite("那个怎么实现", history)
        self.assertEqual(result, ["DAG Runtime 如何实现", "图式运行时实现方法", "那个怎么实现"])
        self.assertNotIn("0" * 20, prompts[0]); self.assertIn("2" * 200, prompts[0]); self.assertNotIn("2" * 201, prompts[0])

    def test_json_fence_and_fallbacks(self):
        fenced = QueryRewriter(lambda _: '```json\n{"queries":["混合检索实现"]}\n```', 3)
        self.assertEqual(fenced.rewrite("怎么实现"), ["混合检索实现", "怎么实现"])
        self.assertEqual(QueryRewriter(lambda _: "bad json").rewrite("原问题"), ["原问题"])
        self.assertEqual(QueryRewriter().rewrite("原问题"), ["原问题"])
        self.assertEqual(QueryRewriter().rewrite("  "), [])

    def test_invalid_structure_and_long_item(self):
        generate = lambda _: json.dumps({"queries": ["x" * 51, "有效查询"]}, ensure_ascii=False)
        self.assertEqual(QueryRewriter(generate).rewrite("原始问题"), ["有效查询", "原始问题"])
        self.assertEqual(QueryRewriter(lambda _: '{"queries":"bad"}').rewrite("原问题"), ["原问题"])


if __name__ == "__main__": unittest.main()
