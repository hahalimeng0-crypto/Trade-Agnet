import unittest
from trade_rag.chunking import RecursiveSplitter

class SplitterTests(unittest.TestCase):
    def test_empty_ids_and_overlap(self):
        self.assertEqual(RecursiveSplitter().split(""), [])
        chunks = RecursiveSplitter(10, 3).split("abcdefghij klmnopqrst")
        self.assertEqual([c.id for c in chunks], list(range(len(chunks))))
        self.assertTrue(chunks[1].content.startswith(chunks[0].content[-3:]))

    def test_fence_is_atomic_and_heading_joins(self):
        text = "## 标题\n正文内容\n```sql\nSELECT * FROM example;\n```"
        chunks = RecursiveSplitter(8, 0).split(text)
        self.assertTrue(any("```sql" in c.content and "```" in c.content for c in chunks))
        self.assertTrue(any("## 标题" in c.content and "正文内容" in c.content for c in chunks))

    def test_overlap_normalization(self):
        splitter = RecursiveSplitter(3, 99)
        self.assertEqual(splitter.chunk_overlap, 2)

if __name__ == "__main__": unittest.main()
