from __future__ import annotations
from .contracts import QueryRequest, SearchResult

class QueryRouter:
    dynamic_terms = ("价格", "库存", "汇率", "报价", "price", "inventory", "exchange rate", "quote")
    calculation_terms = ("计算报价", "报价总额", "calculate quote", "quote total")
    human_review_terms = ("批准报价", "发送报价", "正式报价", "承诺交期",
                          "approve quote", "send quotation", "commit delivery")
    def route(self, query: str) -> str:
        normalized = query.lower()
        if any(term in normalized for term in self.human_review_terms):
            return "human_review"
        if any(term in normalized for term in self.calculation_terms):
            return "calculator"
        return "mysql" if any(term in normalized for term in self.dynamic_terms) else "rag"

class QualityGate:
    def classify(self, results: list[SearchResult]) -> str:
        if not results: return "NO_EVIDENCE"
        if results[0].score <= 0: return "NO_EVIDENCE"
        if results[0].score < 0.15: return "AMBIGUOUS"
        # Overlapping children from the same parent are corroborating passages,
        # not competing answers. Compare confidence with the first distinct
        # parent to avoid false ambiguity on long documents.
        competitor = next((row for row in results[1:]
                           if row.child.parent_id != results[0].child.parent_id), None)
        if competitor is not None and abs(results[0].score-competitor.score) < 0.02:
            return "AMBIGUOUS"
        return "HIGH_CONFIDENCE"

def reciprocal_rank_fusion(result_sets: list[list[SearchResult]], limit: int, k: int = 60) -> list[SearchResult]:
    """按稳定 child_id 融合多查询结果，避免重复父/子命中膨胀。"""
    scores: dict[str, float] = {}
    relevance: dict[str, float] = {}
    rows: dict[str, SearchResult] = {}
    for results in result_sets:
        for rank, result in enumerate(results, start=1):
            key = result.child.child_id
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            relevance[key] = max(relevance.get(key, float("-inf")), result.score)
            rows.setdefault(key, result)
    fused = sorted(rows.values(), key=lambda item: scores[item.child.child_id], reverse=True)
    for item in fused:
        item.score = relevance[item.child.child_id]
        item.rrf_score = scores[item.child.child_id]
    return fused[:limit]
