"""Hybrid retrieval: vector (sqlite-vec) + keyword (FTS5 BM25) -> RRF fusion -> per-document cap ->
cross-encoder rerank -> top-k, plus the retrieval gate that decides "not enough information".

`search()` returns every intermediate list so the RAG Playground can show exactly what happened.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Settings
from .models import ModelRegistry
from .store import Store
from .textutil import is_arabic


@dataclass
class Hit:
    chunk_id: int
    doc_id: str
    filename: str
    page: int
    section: str | None
    header: str
    text: str
    method: str | None
    similarity: float | None = None
    bm25: float | None = None
    rrf: float = 0.0
    rerank: float | None = None
    found_by: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in self.__dict__.items()}


@dataclass
class SearchResult:
    hits: list[Hit]
    vector: list[dict]
    keyword: list[dict]
    fused: list[dict]
    reranked: bool
    rerank_skipped_reason: str | None
    top_similarity: float
    top_rerank: float | None
    gate_passed: bool
    gate_reason: str
    timings_ms: dict

    def public(self) -> dict:
        return {"hits": [h.public() for h in self.hits], "vector": self.vector, "keyword": self.keyword,
                "fused": self.fused, "reranked": self.reranked, "rerank_skipped_reason": self.rerank_skipped_reason,
                "top_similarity": round(self.top_similarity, 4),
                "top_rerank": None if self.top_rerank is None else round(self.top_rerank, 3),
                "gate_passed": self.gate_passed, "gate_reason": self.gate_reason, "timings_ms": self.timings_ms}


class Retriever:
    def __init__(self, s: Settings, store: Store, models: ModelRegistry):
        self.s, self.store, self.models = s, store, models

    def search(self, query: str, *, mode: str = "hybrid", k: int | None = None, rerank: bool | None = None,
               doc_ids: list[str] | None = None, per_doc_cap: int | None = None,
               must_include: list[int] | None = None) -> SearchResult:
        k = k or self.s.top_k
        cap = per_doc_cap if per_doc_cap is not None else self.s.per_doc_cap
        rerank = self.s.use_reranker if rerank is None else rerank
        timings: dict[str, int] = {}
        t = time.perf_counter()

        vec_hits: list[tuple[int, float]] = []
        kw_hits: list[tuple[int, float]] = []
        if mode in ("hybrid", "vector"):
            qv = self.models.embeddings.encode([query])[0]
            timings["embed"] = ms(t)
            t = time.perf_counter()
            vec_hits = self.store.vector_search(qv, self.s.candidates, doc_ids)
            timings["vector"] = ms(t)
            t = time.perf_counter()
        if mode in ("hybrid", "keyword"):
            kw_hits = self.store.keyword_search(query, self.s.candidates, doc_ids)
            timings["keyword"] = ms(t)
            t = time.perf_counter()

        # Reciprocal Rank Fusion: score = sum 1 / (k + rank); robust to the two retrievers' different scales
        scores: dict[int, float] = {}
        sims = dict(vec_hits)
        bm = dict(kw_hits)
        for rank, (cid, _) in enumerate(vec_hits):
            scores[cid] = scores.get(cid, 0) + 1 / (self.s.rrf_k + rank + 1)
        for rank, (cid, _) in enumerate(kw_hits):
            scores[cid] = scores.get(cid, 0) + 1 / (self.s.rrf_k + rank + 1)
        for cid in must_include or []:
            scores[cid] = scores.get(cid, 0) + 1.0  # facts used by the calculator are always shown as sources
        ordered = sorted(scores, key=scores.get, reverse=True)
        rows = self.store.chunks_by_id(ordered + [c for c in (must_include or []) if c not in scores])
        candidates: list[Hit] = []
        for cid in ordered:
            r = rows.get(cid)
            if not r:
                continue
            found = (["vector"] if cid in sims else []) + (["keyword"] if cid in bm else [])
            candidates.append(Hit(cid, r["doc_id"], r["filename"], r["page"], r["section"], r["header"], r["text"],
                                  r["method"], sims.get(cid), bm.get(cid), scores[cid], None, found or ["fact"]))
        timings["fuse"] = ms(t)
        t = time.perf_counter()

        reranked, skip_reason, top_rerank = False, None, None
        if rerank and candidates:
            if is_arabic(query):
                skip_reason = "non-English question (English-only reranker)"
            else:
                out = self.models.reranker.scores(query, [f"{h.header}\n{h.text}" for h in candidates])
                if out is None:
                    skip_reason = f"reranker unavailable: {self.models.reranker.error}"
                else:
                    for h, sc in zip(candidates, out):
                        h.rerank = sc
                    pinned = set(must_include or [])
                    candidates.sort(key=lambda h: (h.chunk_id in pinned, h.rerank), reverse=True)
                    reranked = True
                    top_rerank = max(out)
            timings["rerank"] = ms(t)

        # per-document cap keeps multi-document questions from being crowded out by one long file
        final, per_doc = [], {}
        for h in candidates:
            if per_doc.get(h.doc_id, 0) >= cap and h.chunk_id not in (must_include or []):
                continue
            per_doc[h.doc_id] = per_doc.get(h.doc_id, 0) + 1
            final.append(h)
            if len(final) >= k:
                break

        top_sim = max((s for _, s in vec_hits), default=0.0)
        passed, reason = self.gate(top_sim, top_rerank, bool(kw_hits), reranked, bool(must_include))
        return SearchResult(
            hits=final,
            vector=[{"chunk_id": c, "similarity": round(s, 4)} for c, s in vec_hits[:15]],
            keyword=[{"chunk_id": c, "bm25": round(s, 3)} for c, s in kw_hits[:15]],
            fused=[{"chunk_id": h.chunk_id, "rrf": round(h.rrf, 5), "rerank": None if h.rerank is None else round(h.rerank, 3)}
                   for h in candidates[:20]],
            reranked=reranked, rerank_skipped_reason=skip_reason, top_similarity=top_sim, top_rerank=top_rerank,
            gate_passed=passed, gate_reason=reason, timings_ms=timings)

    def gate(self, top_sim: float, top_rerank: float | None, any_keyword: bool, reranked: bool,
             has_facts: bool) -> tuple[bool, str]:
        """Layer 1 of 'insufficient information': decide in code, before any LLM call."""
        if has_facts:
            return True, "verified facts found for this question"
        if reranked and top_rerank is not None:
            if top_rerank < self.s.min_rerank and top_sim < self.s.min_similarity:
                return False, (f"best reranker score {top_rerank:.2f} < {self.s.min_rerank} and best similarity "
                               f"{top_sim:.2f} < {self.s.min_similarity}")
            return True, "relevant passages found"
        if top_sim < self.s.min_similarity and not any_keyword:
            return False, f"best similarity {top_sim:.2f} < {self.s.min_similarity} and no keyword match"
        return True, "relevant passages found"


def ms(t: float) -> int:
    return int((time.perf_counter() - t) * 1000)
