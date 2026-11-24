"""Retrieval evaluation on a golden set, threshold calibration, answer evaluation and monitoring stats."""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from .answer import WikiAsk
from .config import ROOT
from .retrieval import Retriever
from .store import Store

GOLDEN = ROOT / "eval" / "golden.json"
CONFIGS = [("vector", "vector", False), ("keyword (BM25)", "keyword", False), ("hybrid (RRF)", "hybrid", False),
           ("hybrid + rerank", "hybrid", True)]


def load_golden(path: Path = GOLDEN) -> list[dict]:
    return json.loads(path.read_text())


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def run_retrieval_eval(store: Store, retriever: Retriever, golden: list[dict] | None = None) -> dict:
    golden = golden or load_golden()
    files = {r["filename"] for r in store.rows("SELECT filename FROM documents WHERE status IN ('ready','limited')")}
    answerable = [g for g in golden if g.get("answerable", True) and set(g["expected_files"]) & files]
    unanswerable = [g for g in golden if not g.get("answerable", True)]
    results = []
    calibration = {"answerable": [], "unanswerable": []}
    for name, mode, rerank in CONFIGS:
        hits1 = hits3 = hitsk = 0
        rr = []
        per_q = []
        t0 = time.perf_counter()
        for g in answerable:
            sr = retriever.search(g["question"], mode=mode, rerank=rerank)
            ranked = [h.filename for h in sr.hits]
            rank = next((i + 1 for i, f in enumerate(ranked) if f in g["expected_files"]), None)
            hits1 += rank == 1
            hits3 += bool(rank and rank <= 3)
            hitsk += bool(rank)
            rr.append(1 / rank if rank else 0)
            per_q.append({"id": g["id"], "rank": rank})
            if mode == "hybrid" and rerank:
                calibration["answerable"].append({"id": g["id"], "sim": sr.top_similarity, "rerank": sr.top_rerank})
        gate_ok = None
        if mode == "hybrid":
            correct = 0
            for g in unanswerable:
                sr = retriever.search(g["question"], mode=mode, rerank=rerank)
                correct += not sr.gate_passed
                if rerank:
                    calibration["unanswerable"].append({"id": g["id"], "sim": sr.top_similarity, "rerank": sr.top_rerank})
            wrongly_refused = sum(not retriever.search(g["question"], mode=mode, rerank=rerank).gate_passed
                                  for g in answerable)
            gate_ok = {"unanswerable_refused": correct, "unanswerable_total": len(unanswerable),
                       "answerable_wrongly_refused": wrongly_refused, "answerable_total": len(answerable)}
        n = max(len(answerable), 1)
        results.append({"config": name, "hit@1": hits1 / n, "hit@3": hits3 / n, f"hit@{retriever.s.top_k}": hitsk / n,
                        "mrr": sum(rr) / n, "ms_per_query": int((time.perf_counter() - t0) * 1000 / n),
                        "gate": gate_ok, "per_question": per_q})
    return {"kind": "retrieval", "n_answerable": len(answerable), "n_unanswerable": len(unanswerable),
            "results": results, "calibration": calibration, "suggested_thresholds": suggest(calibration),
            "current_thresholds": {"min_similarity": retriever.s.min_similarity, "min_rerank": retriever.s.min_rerank}}


def suggest(cal: dict) -> dict | None:
    """Pick the (similarity, rerank) pair that maximises correct gate decisions on the golden set."""
    pos, neg = cal["answerable"], cal["unanswerable"]
    if not pos or not neg:
        return None
    sims = sorted({round(x["sim"], 2) for x in pos + neg})
    reranks = sorted({round(x["rerank"], 1) for x in pos + neg if x["rerank"] is not None})
    best = None
    for s in sims:
        for r in reranks:
            ok = sum(not (x["rerank"] < r and x["sim"] < s) for x in pos) + sum(x["rerank"] < r and x["sim"] < s for x in neg)
            if best is None or ok > best[0]:
                best = (ok, s, r)
    return {"min_similarity": best[1], "min_rerank": best[2], "correct": best[0], "total": len(pos) + len(neg)}


def run_answer_eval(store: Store, ask: WikiAsk, golden: list[dict] | None = None, limit: int = 30) -> dict:
    golden = (golden or load_golden())[:limit]
    conv = ask.new_conversation("[eval run]")
    rows, lat = [], []
    for g in golden:
        # each question in a fresh conversation so follow-up rewriting does not leak between questions
        store.execute("DELETE FROM messages WHERE conv_id=?", (conv["id"],))
        out = ask.ask(conv["id"], g["question"])
        meta = out["meta"]
        text = out["content"].replace(",", "").lower()
        expected = [e.replace(",", "").lower() for e in g.get("expected_answer", [])]
        cited_files = {c["filename"] for c in meta.get("citations", []) if c["used"]}
        if g.get("answerable", True):
            correct = all(e in text for e in expected) if expected else None
            cite_ok = bool(cited_files & set(g["expected_files"]))
        else:
            correct = bool(meta.get("abstained")) or "not" in text[:200]
            cite_ok = None
        lat.append(meta["latency_ms"])
        rows.append({"id": g["id"], "question": g["question"], "answerable": g.get("answerable", True),
                     "correct": correct, "citation_ok": cite_ok, "abstained": meta.get("abstained"),
                     "unverified": meta.get("unverified"), "latency_ms": meta["latency_ms"],
                     "answer": out["content"][:400]})
    store.execute("DELETE FROM messages WHERE conv_id=?", (conv["id"],))
    store.execute("DELETE FROM conversations WHERE id=?", (conv["id"],))
    store.execute("DELETE FROM query_log WHERE conv_id=?", (conv["id"],))
    graded = [r for r in rows if r["correct"] is not None]
    cites = [r for r in rows if r["citation_ok"] is not None]
    return {"kind": "answers", "n": len(rows), "model": ask.models.chat.spec,
            "accuracy": sum(r["correct"] for r in graded) / max(len(graded), 1),
            "citation_accuracy": sum(r["citation_ok"] for r in cites) / max(len(cites), 1),
            "unverified_rate": sum(bool(r["unverified"]) for r in rows) / max(len(rows), 1),
            "latency_p50_ms": pct(lat, 0.5), "latency_p95_ms": pct(lat, 0.95), "rows": rows}


def save_run(store: Store, result: dict) -> None:
    store.execute("INSERT INTO eval_runs(ts, kind, result) VALUES (?,?,?)",
                  (time.time(), result["kind"], json.dumps(result)))


def monitoring(store: Store, since_hours: float = 24 * 7) -> dict:
    since = time.time() - since_hours * 3600
    rows = store.rows("SELECT * FROM query_log WHERE ts >= ? ORDER BY ts", (since,))
    lat = [r["latency_ms"] for r in rows]
    ret = [r["retrieval_ms"] for r in rows]
    docs = store.rows("SELECT status, count(*) AS n, avg(processing_ms) AS avg_ms FROM documents GROUP BY status")
    by_model: dict[str, list[int]] = {}
    for r in rows:
        by_model.setdefault(r["model"], []).append(r["latency_ms"])
    return {
        "queries": len(rows), "latency_p50_ms": pct(lat, .5), "latency_p95_ms": pct(lat, .95),
        "retrieval_p50_ms": pct(ret, .5), "retrieval_p95_ms": pct(ret, .95),
        "abstain_rate": (sum(r["abstained"] for r in rows) / len(rows)) if rows else None,
        "unverified_rate": (sum(r["unverified"] for r in rows) / len(rows)) if rows else None,
        "avg_top_similarity": statistics.mean([r["top_similarity"] for r in rows]) if rows else None,
        "routes": {k: sum(r["route"] == k for r in rows) for k in ("doc", "metric", "both")},
        "by_model": {m: {"n": len(v), "p50_ms": pct(v, .5)} for m, v in by_model.items()},
        "documents": docs,
        "recent": rows[-25:][::-1],
        "last_eval": {k: json.loads(r["result"]) for k in ("retrieval", "answers") for r in
                      store.rows("SELECT result FROM eval_runs WHERE kind=? ORDER BY id DESC LIMIT 1", (k,))},
    }
