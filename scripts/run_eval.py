"""Run retrieval + answer evaluation on eval/golden.json and write reports/eval.md.

    uv run python scripts/run_eval.py
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fingraph.api import App  # noqa: E402
from fingraph.evals import run_answer_eval, run_retrieval_eval, save_run  # noqa: E402

core = App()
ret = run_retrieval_eval(core.store, core.retriever)
save_run(core.store, ret)
ans = run_answer_eval(core.store, core.ask)
save_run(core.store, ans)

lines = [f"# Evaluation · {time.strftime('%Y-%m-%d')}", "",
         f"Golden set: `eval/golden.json`: {ret['n_answerable']} answerable + {ret['n_unanswerable']} unanswerable "
         f"questions over the 10 synthetic documents. Answer model: `{ans['model']}`. Hardware: Apple M5, 16 GB.", "",
         "## Retrieval", "", "| Configuration | Hit@1 | Hit@3 | MRR | ms/query | Gate on unanswerable | Answerable wrongly refused |",
         "|---|---|---|---|---|---|---|"]
for r in ret["results"]:
    g = r["gate"]
    lines.append(f"| {r['config']} | {r['hit@1']:.0%} | {r['hit@3']:.0%} | {r['mrr']:.3f} | {r['ms_per_query']} | "
                 + (f"{g['unanswerable_refused']}/{g['unanswerable_total']} refused | {g['answerable_wrongly_refused']}/{g['answerable_total']}"
                    if g else "– | –") + " |")
lines += ["", "Gate calibration (top cosine similarity / top reranker logit per question):", ""]
for k in ("answerable", "unanswerable"):
    vals = ret["calibration"][k]
    lines.append(f"- {k}: cosine {min(v['sim'] for v in vals):.2f}–{max(v['sim'] for v in vals):.2f}, "
                 f"rerank {min(v['rerank'] for v in vals):.1f}–{max(v['rerank'] for v in vals):.1f}")
lines += ["", "## Answers (full pipeline)", "",
          f"- Answer accuracy (expected facts present / correct refusal): **{ans['accuracy']:.0%}**",
          f"- Citation accuracy (cites an expected file): **{ans['citation_accuracy']:.0%}**",
          f"- Unverified rate (failed the number check): {ans['unverified_rate']:.0%}",
          f"- Latency p50 {ans['latency_p50_ms'] / 1000:.1f}s · p95 {ans['latency_p95_ms'] / 1000:.1f}s", "",
          "| id | pass | question | answer |", "|---|---|---|---|"]
for r in ans["rows"]:
    lines.append(f"| {r['id']} | {'✅' if r['correct'] else '❌'} | {r['question']} | {r['answer'][:160].replace('|', '/').replace(chr(10), ' ')} |")
(ROOT / "reports" / "eval.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines[:20]))
