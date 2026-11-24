import { Activity, FlaskConical, Play } from "lucide-react";
import { useState } from "react";
import { Badge, ErrorBox, PageHeader, Stat } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";
import { ago } from "../lib/format";

interface RetrievalEval {
  n_answerable: number;
  n_unanswerable: number;
  results: { config: string; "hit@1": number; "hit@3": number; mrr: number; ms_per_query: number; gate: null | { unanswerable_refused: number; unanswerable_total: number; answerable_wrongly_refused: number; answerable_total: number }; [k: string]: unknown }[];
  suggested_thresholds: { min_similarity: number; min_rerank: number; correct: number; total: number } | null;
  current_thresholds: { min_similarity: number; min_rerank: number };
}
interface AnswerEval {
  n: number;
  model: string;
  accuracy: number;
  citation_accuracy: number;
  unverified_rate: number;
  latency_p50_ms: number;
  latency_p95_ms: number;
  rows: { id: string; question: string; answerable: boolean; correct: boolean | null; citation_ok: boolean | null; abstained: boolean; unverified: boolean; latency_ms: number; answer: string }[];
}
interface Monitor {
  queries: number;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  retrieval_p50_ms: number | null;
  abstain_rate: number | null;
  unverified_rate: number | null;
  avg_top_similarity: number | null;
  routes: Record<string, number>;
  by_model: Record<string, { n: number; p50_ms: number | null }>;
  documents: { status: string; n: number; avg_ms: number | null }[];
  recent: { ts: number; question: string; route: string; model: string; latency_ms: number; abstained: number; unverified: number; top_similarity: number }[];
  last_eval: { retrieval?: RetrievalEval; answers?: AnswerEval };
}

const p = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);
const s = (ms: number | null | undefined) => (ms == null ? "–" : `${(ms / 1000).toFixed(1)}s`);

export default function Evaluation() {
  const mon = useApi<Monitor>("/api/monitoring");
  const [ret, setRet] = useState<RetrievalEval | null>(null);
  const [ans, setAns] = useState<AnswerEval | null>(null);
  const [busy, setBusy] = useState<"" | "ret" | "ans">("");
  const [error, setError] = useState<string | null>(null);
  const retrieval = ret ?? mon.data?.last_eval.retrieval ?? null;
  const answers = ans ?? mon.data?.last_eval.answers ?? null;

  const runRet = async () => {
    setBusy("ret");
    setError(null);
    try { setRet(await api.post<RetrievalEval>("/api/eval/retrieval")); } catch (e) { setError((e as Error).message); } finally { setBusy(""); mon.reload(); }
  };
  const runAns = async () => {
    setBusy("ans");
    setError(null);
    try { setAns(await api.post<AnswerEval>("/api/eval/answers?limit=30")); } catch (e) { setError((e as Error).message); } finally { setBusy(""); mon.reload(); }
  };
  const m = mon.data;

  return (
    <div className="mx-auto max-w-[1280px] p-6 md:p-8">
      <PageHeader title="Evaluation & monitoring" subtitle="Golden-set retrieval metrics, answer accuracy and live query monitoring (eval/golden.json)." actions={<>
        <button className="btn" onClick={runRet} disabled={!!busy}><FlaskConical size={15} /> {busy === "ret" ? "Running retrieval eval…" : "Run retrieval eval"}</button>
        <button className="btn-primary" onClick={runAns} disabled={!!busy}><Play size={15} /> {busy === "ans" ? "Answering golden set… (~2 min)" : "Run answer eval"}</button>
      </>} />
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}

      <section className="card mb-6 p-5">
        <div className="mb-4 flex items-center gap-2 font-semibold"><FlaskConical size={16} className="text-brand" /> Retrieval quality {retrieval && <span className="text-xs font-normal text-ink-3">{retrieval.n_answerable} answerable + {retrieval.n_unanswerable} unanswerable questions</span>}</div>
        {!retrieval ? <div className="text-sm text-ink-3">Not run yet.</div> : (
          <>
            <table className="w-full text-sm">
              <thead><tr className="border-b border-line text-left text-ink-3"><th className="py-2 font-medium">Configuration</th><th className="py-2 text-right font-medium">Hit@1</th><th className="py-2 text-right font-medium">Hit@3</th><th className="py-2 text-right font-medium">MRR</th><th className="py-2 text-right font-medium">ms / query</th><th className="py-2 pl-4 font-medium">Answer gate</th></tr></thead>
              <tbody className="divide-y divide-line">
                {retrieval.results.map((r) => {
                  const best = Math.max(...retrieval.results.map((x) => x.mrr));
                  return (
                    <tr key={r.config} className={r.mrr === best ? "bg-brand-soft/40" : ""}>
                      <td className="py-2 font-medium">{r.config}</td>
                      <td className="tabular py-2 text-right">{p(r["hit@1"])}</td>
                      <td className="tabular py-2 text-right">{p(r["hit@3"])}</td>
                      <td className="tabular py-2 text-right font-semibold">{r.mrr.toFixed(3)}</td>
                      <td className="tabular py-2 text-right text-ink-2">{r.ms_per_query}</td>
                      <td className="py-2 pl-4 text-xs text-ink-2">{r.gate ? `refused ${r.gate.unanswerable_refused}/${r.gate.unanswerable_total} unanswerable · wrongly refused ${r.gate.answerable_wrongly_refused}/${r.gate.answerable_total}` : "–"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {retrieval.suggested_thresholds && (
              <div className="mt-4 rounded-lg bg-info-soft px-4 py-3 text-xs text-info">
                Threshold calibration: best split on this golden set is cosine &lt; {retrieval.suggested_thresholds.min_similarity} and rerank &lt; {retrieval.suggested_thresholds.min_rerank} ({retrieval.suggested_thresholds.correct}/{retrieval.suggested_thresholds.total} correct gate decisions). Current: {retrieval.current_thresholds.min_similarity} / {retrieval.current_thresholds.min_rerank}.
              </div>
            )}
          </>
        )}
      </section>

      <section className="card mb-6 p-5">
        <div className="mb-4 flex items-center gap-2 font-semibold"><Play size={16} className="text-brand" /> Answer quality {answers && <Badge>{answers.model.replace("ollama:", "")}</Badge>}</div>
        {!answers ? <div className="text-sm text-ink-3">Not run yet. Runs the full Wiki Ask pipeline on every golden question.</div> : (
          <>
            <div className="mb-4 grid grid-cols-2 gap-4 md:grid-cols-5">
              <Stat label="Answer accuracy" value={p(answers.accuracy)} sub="expected facts present" />
              <Stat label="Citation accuracy" value={p(answers.citation_accuracy)} sub="cites the right file" />
              <Stat label="Unverified" value={p(answers.unverified_rate)} sub="failed number check" />
              <Stat label="Latency p50" value={s(answers.latency_p50_ms)} />
              <Stat label="Latency p95" value={s(answers.latency_p95_ms)} />
            </div>
            <div className="scroll-thin max-h-[380px] overflow-y-auto">
              <table className="w-full text-sm">
                <tbody className="divide-y divide-line">
                  {answers.rows.map((r) => (
                    <tr key={r.id} className="align-top">
                      <td className="py-2 pr-3">{r.correct ? <Badge tone="good">pass</Badge> : <Badge tone="bad">fail</Badge>}</td>
                      <td className="py-2"><div className="font-medium">{r.question}</div><div className="mt-0.5 line-clamp-2 text-xs text-ink-3">{r.answer}</div></td>
                      <td className="py-2 pl-3 text-right text-xs text-ink-3">{r.answerable ? "" : "unanswerable · "}{s(r.latency_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="card p-5">
        <div className="mb-4 flex items-center gap-2 font-semibold"><Activity size={16} className="text-brand" /> Live monitoring <span className="text-xs font-normal text-ink-3">last 7 days</span></div>
        {!m ? <div className="skeleton h-20" /> : (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-6">
              <Stat label="Questions" value={m.queries} />
              <Stat label="Latency p50" value={s(m.latency_p50_ms)} sub={`p95 ${s(m.latency_p95_ms)}`} />
              <Stat label="Retrieval p50" value={m.retrieval_p50_ms == null ? "–" : `${m.retrieval_p50_ms} ms`} />
              <Stat label="Abstain rate" value={p(m.abstain_rate)} />
              <Stat label="Unverified rate" value={p(m.unverified_rate)} />
              <Stat label="Avg top cosine" value={m.avg_top_similarity?.toFixed(2) ?? "–"} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-ink-2">
              {Object.entries(m.by_model).map(([k, v]) => <Badge key={k}>{k.replace("ollama:", "")}: {v.n} q · p50 {s(v.p50_ms)}</Badge>)}
              {m.documents.map((d) => <Badge key={d.status}>{d.status}: {d.n} docs{d.avg_ms ? ` · avg ${s(d.avg_ms)}` : ""}</Badge>)}
            </div>
            {m.recent.length > 0 && (
              <table className="mt-4 w-full text-sm">
                <thead><tr className="border-b border-line text-left text-ink-3"><th className="py-2 font-medium">Question</th><th className="py-2 font-medium">Route</th><th className="py-2 text-right font-medium">Latency</th><th className="py-2 text-right font-medium">When</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {m.recent.map((r, i) => (
                    <tr key={i}>
                      <td className="max-w-[460px] truncate py-2">{r.question} {r.abstained ? <Badge tone="warn">abstained</Badge> : null} {r.unverified ? <Badge tone="bad">unverified</Badge> : null}</td>
                      <td className="py-2 text-ink-2">{r.route}</td>
                      <td className="tabular py-2 text-right">{s(r.latency_ms)}</td>
                      <td className="py-2 text-right text-xs text-ink-3">{ago(r.ts)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        )}
      </section>
    </div>
  );
}
