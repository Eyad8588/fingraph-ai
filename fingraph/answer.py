"""Wiki Ask: conversational, cited answers.

Pipeline per question:
  1. follow-up rewriting (only when it looks like a follow-up) -> standalone question
  2. router: doc / metric / both, with the Python calculator and the scope check
  3. hybrid retrieval (+ the calculator's source chunks), retrieval gate decides BEFORE the LLM
  4. grounded generation with numbered sources, partial answers allowed
  5. post-check: every [n] must exist; every number must appear in a cited source or the calculation box,
     otherwise regenerate once with a stricter prompt, then mark the answer 'unverified'
"""

from __future__ import annotations

import re
import time
import uuid

from .config import Settings
from .models import ModelError, ModelRegistry
from .retrieval import Hit, Retriever
from .router import Route, Router, looks_like_follow_up
from .store import Store
from .textutil import find_dates, is_arabic, number_tokens

REWRITE_SYSTEM = ("Rewrite the user's follow-up as ONE standalone question that can be understood without the "
                  "conversation. Keep company names, periods and metrics explicit. Reply with the standalone question "
                  "only, nothing else.")

ANSWER_SYSTEM = """You are FinGraph, a financial analyst assistant. Answer ONLY from the numbered sources and the
verified calculations provided.
- Cite every factual sentence with the source number in square brackets, e.g. [2]. Use several when needed: [1][3].
- Copy numbers exactly as written in the sources or the calculations. Never compute new numbers yourself; use
  the verified calculations for changes, ratios and comparisons.
- If the sources cover only part of the question, answer that part and say clearly what is missing.
- If the sources do not contain the answer, say that the uploaded documents do not contain it.
- Be concise: 2 to 6 sentences, or a short bullet list for comparisons."""

NOT_FOUND = "I couldn't find information about this in the uploaded documents."


class WikiAsk:
    def __init__(self, s: Settings, store: Store, models: ModelRegistry, retriever: Retriever, router: Router):
        self.s, self.store, self.models, self.retriever, self.router = s, store, models, retriever, router

    # ------------------------------------------------------------ conversations
    def new_conversation(self, title: str = "New conversation", scope: list[str] | None = None) -> dict:
        cid = uuid.uuid4().hex[:12]
        now = time.time()
        import json
        self.store.execute("INSERT INTO conversations(id, title, scope, created_at, updated_at) VALUES (?,?,?,?,?)",
                           (cid, title, json.dumps(scope or []), now, now))
        return self.store.row("SELECT * FROM conversations WHERE id=?", (cid,))

    # ------------------------------------------------------------ main entry
    def ask(self, conv_id: str, question: str, doc_ids: list[str] | None = None) -> dict:
        t0 = time.perf_counter()
        question = question.strip()
        history = self.store.history(conv_id, self.s.history_turns)
        standalone = question
        if history and looks_like_follow_up(question):
            standalone = self._rewrite(history, question)

        route = self.router.route(standalone)
        pinned = [f.chunk_id for f in route.facts if f.chunk_id]
        t1 = time.perf_counter()
        sr = self.retriever.search(standalone, doc_ids=doc_ids or None, must_include=pinned)
        retrieval_ms = int((time.perf_counter() - t1) * 1000)

        meta: dict = {"standalone": standalone if standalone != question else None, "route": route.public(),
                      "retrieval": {"top_similarity": round(sr.top_similarity, 3), "top_rerank": sr.top_rerank,
                                    "reranked": sr.reranked, "gate": sr.gate_reason, "timings_ms": sr.timings_ms},
                      "model": self.models.chat.spec, "scope": doc_ids or []}

        if not sr.gate_passed or not sr.hits:
            text = NOT_FOUND
            if route.missing:
                text = " ".join(route.missing)
            elif sr.hits == [] and self.store.scalar("SELECT count(*) FROM chunks") == 0:
                text = "No documents have been processed yet. Upload documents in the Library first."
            meta.update(citations=[], abstained=True, unverified=False, calculations=route.calculations)
            return self._finish(conv_id, question, text, meta, t0, retrieval_ms, sr, route)

        sources = sr.hits
        prompt = self._prompt(standalone, sources, route, question)
        try:
            answer = self.models.chat.complete(ANSWER_SYSTEM, prompt, temperature=0.1)
            problems = self.check(answer, sources, route)
            if problems:
                stricter = (prompt + "\n\nYOUR PREVIOUS ANSWER HAD PROBLEMS: " + "; ".join(problems) +
                            ". Rewrite it: cite only existing source numbers and copy numbers exactly from the "
                            "sources or the verified calculations.")
                retry = self.models.chat.complete(ANSWER_SYSTEM, stricter, temperature=0)
                retry_problems = self.check(retry, sources, route)
                if len(retry_problems) <= len(problems):
                    answer, problems = retry, retry_problems
        except ModelError as e:
            answer, problems = (f"The language model is unavailable ({self.models.chat.spec}). "
                                "Here are the most relevant passages instead."), []
            meta["model_error"] = str(e)

        cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer) if 0 < int(n) <= len(sources)})
        meta.update(
            citations=[self._citation(i, sources[i - 1], answer, i in cited) for i in range(1, len(sources) + 1)],
            abstained=answer.strip().startswith(NOT_FOUND[:30]),
            unverified=bool(problems), problems=problems, calculations=route.calculations)
        return self._finish(conv_id, question, answer, meta, t0, retrieval_ms, sr, route)

    # ------------------------------------------------------------ steps
    def _rewrite(self, history: list[dict], question: str) -> str:
        convo = "\n".join(f"{m['role'].upper()}: {m['content'][:500]}" for m in history[-6:])
        try:
            out = self.models.chat.complete(REWRITE_SYSTEM, f"Conversation:\n{convo}\n\nFollow-up: {question}",
                                            temperature=0).strip().strip('"')
            return out.split("\n")[0][:400] or question
        except ModelError:
            return question

    def _prompt(self, standalone: str, sources: list[Hit], route: Route, original: str) -> str:
        parts = ["SOURCES:"]
        for i, h in enumerate(sources, 1):
            parts.append(f"[{i}] {h.header}\n{h.text}\n")
        if route.calculations or route.facts:
            parts.append("VERIFIED CALCULATIONS (computed by code from the sources; use these numbers as-is):")
            parts += [f"- {c}" for c in route.calculations]
            index = {h.chunk_id: i for i, h in enumerate(sources, 1)}
            parts += [f"- {f.label.replace(' | ', ', ')}: {f.display}"
                      + (f" (source [{index[f.chunk_id]}])" if f.chunk_id in index else "") for f in route.facts]
            parts.append("When you use a calculation, cite the sources of its input figures with [n].")
        if route.missing:
            parts.append("NOT AVAILABLE IN THE DOCUMENTS (say so in the answer):")
            parts += [f"- {m}" for m in route.missing]
        if route.notes:
            parts += [f"NOTE: {n}" for n in route.notes]
        parts.append(f"\nQUESTION: {standalone}")
        if is_arabic(original):
            parts.append("Answer in Arabic. Keep numbers as digits and keep the [n] citations.")
        return "\n".join(parts)

    def check(self, answer: str, sources: list[Hit], route: Route) -> list[str]:
        """Post-generation verification (layer 4)."""
        problems = []
        refs = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]
        bad = sorted({n for n in refs if n < 1 or n > len(sources)})
        if bad:
            problems.append(f"cited non-existent sources {bad}")
        if not refs and not answer.strip().startswith(NOT_FOUND[:30]) and "not contain" not in answer.lower():
            problems.append("no citations")
        allowed: set[float] = set()
        for h in sources:
            allowed |= number_tokens(h.text) | number_tokens(h.header)
        for c in route.calculations:
            allowed |= number_tokens(c)
        for f in route.facts:
            allowed |= number_tokens(f.display) | {round(f.value, 2)}
        body = re.sub(r"\[\d+\]", "", answer)
        unsupported = []
        for n in number_tokens(body):
            if n in allowed or (n < 100 and float(n).is_integer()) or 1900 <= n <= 2100:
                continue
            if any(abs(n - a) < 0.051 for a in allowed):  # rounding of a verified percentage
                continue
            unsupported.append(n)
        if unsupported:
            problems.append("numbers not found in sources: " + ", ".join(f"{u:g}" for u in unsupported[:5]))
        # dates are facts too: 'June 5, 2026' must appear (in any format) in a source
        source_dates = set()
        for h in sources:
            source_dates |= {d.isoformat() for d in find_dates(h.text)}
        bad_dates = sorted({d.isoformat() for d in find_dates(body)} - source_dates)
        if bad_dates:
            problems.append("dates not found in sources: " + ", ".join(bad_dates[:4]))
        return problems

    def _citation(self, n: int, h: Hit, answer: str, used: bool) -> dict:
        return {"n": n, "used": used, "chunk_id": h.chunk_id, "doc_id": h.doc_id, "filename": h.filename,
                "page": h.page, "section": h.section, "method": h.method, "excerpt": best_excerpt(h.text, answer),
                "similarity": None if h.similarity is None else round(h.similarity, 3),
                "rerank": None if h.rerank is None else round(h.rerank, 2), "found_by": h.found_by}

    def _finish(self, conv_id, question, text, meta, t0, retrieval_ms, sr, route) -> dict:
        latency = int((time.perf_counter() - t0) * 1000)
        meta["latency_ms"] = latency
        conv = self.store.row("SELECT * FROM conversations WHERE id=?", (conv_id,))
        if conv and conv["title"] in ("New conversation", "", None):
            self.store.execute("UPDATE conversations SET title=? WHERE id=?", (question[:70], conv_id))
        self.store.add_message(conv_id, "user", question)
        mid = self.store.add_message(conv_id, "assistant", text, meta)
        self.store.execute(
            "INSERT INTO query_log(ts, conv_id, question, standalone, route, model, latency_ms, retrieval_ms, "
            "top_similarity, top_rerank, n_sources, n_docs, abstained, unverified) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (time.time(), conv_id, question, meta.get("standalone"), route.route, meta["model"], latency, retrieval_ms,
             sr.top_similarity, sr.top_rerank, len(meta.get("citations", [])),
             len({c["doc_id"] for c in meta.get("citations", []) if c["used"]}), int(meta["abstained"]),
             int(meta.get("unverified", False))))
        return {"id": mid, "role": "assistant", "content": text, "meta": meta}


def best_excerpt(text: str, answer: str, width: int = 420) -> str:
    """The part of a chunk that best supports the answer: the window with the most shared numbers/words."""
    if len(text) <= width:
        return text
    nums = {f"{n:,.0f}" for n in number_tokens(answer) if n >= 100} | {str(int(n)) for n in number_tokens(answer) if n >= 100}
    words = set(re.findall(r"[a-z]{5,}", answer.lower()))
    lines = text.split("\n")
    best, best_score = 0, -1
    for i in range(len(lines)):
        window = "\n".join(lines[i:i + 6])
        score = sum(3 for n in nums if n in window) + sum(1 for w in words if w in window.lower())
        if score > best_score:
            best, best_score = i, score
    out = "\n".join(lines[best:best + 8])
    return out[:width] + ("…" if len(out) > width else "")
