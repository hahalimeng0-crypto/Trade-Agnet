from __future__ import annotations

import re

from .contracts import Citation, SearchResult


def _citation_id(result: SearchResult) -> str:
    return ":".join((
        result.source.document_id,
        str(result.source.version),
        result.child.location,
        result.child.child_id,
    ))


def _claims(results: list[SearchResult]) -> list[dict]:
    """Build auditable claims from the exact selected evidence.

    The current generator is extractive.  Keeping each sentence tied to the
    source citation gives the evaluation runner a deterministic baseline and a
    stable contract for a future abstractive model.
    """
    claims: list[dict] = []
    for result in results:
        text = result.parent.text if result.parent is not None else result.child.text
        sentences = [row.strip() for row in re.split(r"(?<=[。！？.!?])\s+|\n+", text)
                     if row.strip()]
        for sentence in sentences:
            claims.append({
                "claim_id": f"claim-{len(claims) + 1}",
                "text": sentence,
                "citation_ids": [_citation_id(result)],
                "fact_type": "retrieved_evidence",
            })
    return claims


def answer_with_citations(query: str, results: list[SearchResult], status: str,
                          *, include_claims: bool = False) -> dict:
    if status != "HIGH_CONFIDENCE":
        response = {
            "status": status,
            "answer": "无法基于已批准且有权限的知识确定回答，请补充范围或转人工。",
            "citations": [],
        }
        if include_claims:
            response.update({"claims": [], "assumptions": [],
                             "missing_information": ["insufficient_evidence"],
                             "requires_human_confirmation": True})
        return response
    # The bundled generator is extractive, not a synthesis model. Returning the
    # strongest parent is safer than concatenating unrelated runners-up. A
    # future abstractive generator may explicitly select multiple evidence IDs.
    selected = results[:1]
    citations = []
    for result in selected:
        metadata = result.child.metadata
        citations.append(Citation(
            result.source.document_id,
            result.source.version,
            result.child.location,
            result.child.child_id,
            image_id=metadata.get("image_id"),
            image_index=metadata.get("image_index"),
            page_number=metadata.get("page_number"),
        ).__dict__)
    response = {
        "status": "ANSWERED",
        "answer": "\n\n".join(
            result.parent.text if result.parent is not None else result.child.text
            for result in selected
        ),
        "citations": citations,
    }
    if include_claims:
        response.update({"claims": _claims(selected), "assumptions": [],
                         "missing_information": [],
                         "requires_human_confirmation": False})
    return response
