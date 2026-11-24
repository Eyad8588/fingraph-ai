import { CheckCircle2, Play, ShieldX } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, ErrorBox, PageHeader, Segmented } from "../components/ui";
import { api, type RouteInfo } from "../lib/api";

interface PlayResp {
  hits: { chunk_id: number; filename: string; page: number; header: string; text: string; similarity: number | null; bm25: number | null; rrf: number; rerank: number | null; found_by: string[] }[];
  vector: { chunk_id: number; similarity: number }[];
  keyword: { chunk_id: number; bm25: number }[];
  fused: { chunk_id: number; rrf: number; rerank: number | null }[];
  reranked: boolean;
  rerank_skipped_reason: string | null;
  top_similarity: number;
  top_rerank: number | null;
  gate_passed: boolean;
  gate_reason: string;
  timings_ms: Record<string, number>;
  chunks: Record<string, { filename: string; page: number; header: string; text: string }>;
  route: RouteInfo;
}

export default function Playground({ initialQuery }: { initialQuery: string }) {
  const [q, setQ] = useState(initialQuery || "Did we pay Atlas Logistics twice?");
  const [mode, setMode] = useState<"hybrid" | "vector" | "keyword">("hybrid");
  const [rerank, setRerank] = useState(true);
  const [k, setK] = useState(8);
  const [res, setRes] = useState<PlayResp | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setRes(await api.post<PlayResp>("/api/playground", { query: q, mode, rerank, k }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (initialQuery) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  const total = res ? Object.values(res.timings_ms).reduce((a, b) => a + b, 0) : 0;
  return (
    <div className="mx-auto max-w-[1400px] p-6 md:p-8">
      <PageHeader title="RAG playground" subtitle="See every retrieval stage for a query: vector and BM25 candidates, RRF fusion, cross-encoder rerank, per-document cap and the answer gate. No LLM call is made here." />
      <div className="card mb-6 flex flex-wrap items-center gap-3 p-4">
        <input className="input min-w-[280px] flex-1" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && run()} placeholder="Type a query…" />
        <Segmented value={mode} onChange={setMode} options={[{ value: "hybrid", label: "Hybrid" }, { value: "vector", label: "Vector" }, { value: "keyword", label: "BM25" }]} />
        <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" className="accent-[var(--brand)]" checked={rerank} onChange={(e) => setRerank(e.target.checked)} /> Rerank</label>
        <label className="flex items-center gap-1.5 text-sm">k <input type="number" min={1} max={20} className="input w-16 py-1.5" value={k} onChange={(e) => setK(Number(e.target.value))} /></label>
        <button className="btn-primary" onClick={run} disabled={busy || !q.trim()}><Play size={15} /> {busy ? "Running…" : "Run"}</button>
      </div>
      {error && <ErrorBox message={error} />}
      {res && (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-4">
            <div className={`card flex items-start gap-3 p-4 md:col-span-2 ${res.gate_passed ? "" : "border-warn"}`}>
              {res.gate_passed ? <CheckCircle2 className="text-good" size={20} /> : <ShieldX className="text-warn" size={20} />}
              <div>
                <div className="font-semibold">{res.gate_passed ? "Gate passed: the LLM would be called" : "Gate closed: answer 'not found' without calling the LLM"}</div>
                <div className="mt-0.5 text-xs text-ink-2">{res.gate_reason}</div>
              </div>
            </div>
            <div className="card p-4">
              <div className="label">Scores</div>
              <div className="tabular mt-1 text-sm">top cosine <b>{res.top_similarity.toFixed(3)}</b></div>
              <div className="tabular text-sm">top rerank <b>{res.top_rerank ?? "–"}</b></div>
              {res.rerank_skipped_reason && <div className="text-xs text-warn">rerank skipped: {res.rerank_skipped_reason}</div>}
            </div>
            <div className="card p-4">
              <div className="label">Timings · {total} ms</div>
              <div className="mt-1 space-y-0.5 text-xs text-ink-2">{Object.entries(res.timings_ms).map(([s, v]) => <div key={s} className="flex justify-between"><span>{s}</span><span className="tabular">{v} ms</span></div>)}</div>
            </div>
          </div>
          {res.route.route !== "doc" && (
            <div className="card p-4 text-sm">
              <div className="label mb-1">Router: {res.route.route}</div>
              <div className="text-ink-2">metrics {res.route.metrics.join(", ") || "–"} · companies {res.route.companies.join(", ") || "–"} · periods {res.route.periods.join(", ") || "–"}</div>
              {res.route.calculations.map((c, i) => <div key={i} className="mt-1 font-mono text-xs">{c}</div>)}
              {res.route.missing.map((c, i) => <div key={i} className="mt-1 text-xs text-warn">{c}</div>)}
            </div>
          )}
          <div className="grid gap-4 lg:grid-cols-3">
            <Column title="1 · Vector (cosine)" items={res.vector.map((v) => ({ id: v.chunk_id, score: v.similarity.toFixed(3) }))} chunks={res.chunks} />
            <Column title="2 · Keyword (BM25)" items={res.keyword.map((v) => ({ id: v.chunk_id, score: v.bm25.toFixed(2) }))} chunks={res.chunks} />
            <Column title={`3 · Fused (RRF)${res.reranked ? " → reranked" : ""}`} items={res.fused.map((v) => ({ id: v.chunk_id, score: res.reranked && v.rerank != null ? `rr ${v.rerank}` : v.rrf.toFixed(4) }))} chunks={res.chunks} final={new Set(res.hits.map((h) => h.chunk_id))} />
          </div>
        </div>
      )}
    </div>
  );
}

function Column({ title, items, chunks, final }: { title: string; items: { id: number; score: string }[]; chunks: PlayResp["chunks"]; final?: Set<number> }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line px-4 py-2.5 text-sm font-semibold">{title}</div>
      <div className="scroll-thin max-h-[560px] divide-y divide-line overflow-y-auto">
        {items.length === 0 && <div className="p-4 text-sm text-ink-3">No candidates.</div>}
        {items.map((it, i) => {
          const c = chunks[String(it.id)];
          return (
            <div key={it.id} className={`px-4 py-2.5 ${final?.has(it.id) ? "bg-brand-soft/50" : ""}`}>
              <div className="flex items-center gap-2 text-xs">
                <span className="tabular w-5 text-ink-3">{i + 1}</span>
                <span className="truncate font-medium">{c?.filename}</span>
                <span className="text-ink-3">p.{c?.page}</span>
                <span className="tabular ml-auto font-mono text-ink-2">{it.score}</span>
                {final?.has(it.id) && <Badge tone="brand">top-k</Badge>}
              </div>
              <div className="mt-1 line-clamp-2 font-mono text-[11px] text-ink-3">{c?.text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
