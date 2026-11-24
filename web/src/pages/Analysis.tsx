import { ArrowRight, GitCompareArrows, LineChart as LineIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, ErrorBox, PageHeader, Segmented, Spinner } from "../components/ui";
import { api, type Doc } from "../lib/api";
import { useApi } from "../lib/hooks";
import { DOC_TYPE_LABEL, metricTitle, metricValue, money, pct, sortPeriods } from "../lib/format";

interface CompareResp {
  metric: string;
  title: string;
  is_ratio: boolean;
  is_percent: boolean;
  rows: { company: string; company_norm: string; period: string; currency: string; value: number; fact: { filename?: string; page?: number; excerpt?: string; formula?: string } }[];
  currency_note: string | null;
  changes: { company: string; from_period: string; to_period: string; from: number; to: number; change: number; pct: number | null; currency: string }[];
}
interface DocCompare {
  a: Doc;
  b: Doc;
  metrics: { metric: string; title: string; a: number | null; b: number | null; diff: number | null; pct: number | null }[];
  invoice_fields: { field: string; a: unknown; b: unknown; same: boolean }[];
  shared_entities: string[];
  only_a: string[];
  only_b: string[];
  currency_note: string | null;
}

const COLORS = ["var(--brand)", "var(--info)", "var(--warn)", "#a855f7"];

export default function Analysis() {
  const [tab, setTab] = useState<"metrics" | "docs">("metrics");
  return (
    <div className="mx-auto max-w-[1280px] p-6 md:p-8">
      <PageHeader title="Analysis" subtitle="Comparisons and calculations over verified figures. Every number links back to its source line." actions={<Segmented value={tab} onChange={setTab} options={[{ value: "metrics", label: "Metric explorer" }, { value: "docs", label: "Compare documents" }]} />} />
      {tab === "metrics" ? <MetricExplorer /> : <DocumentCompare />}
    </div>
  );
}

function MetricExplorer() {
  const ov = useApi<{ metrics: string[]; companies: { company: string; company_norm: string; currency: string }[] }>("/api/finance/overview");
  const [metric, setMetric] = useState("revenue");
  const [companies, setCompanies] = useState<string[]>([]);
  const [data, setData] = useState<CompareResp | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.post<CompareResp>("/api/finance/compare", { metric, companies: companies.length ? companies : null }).then(setData).catch((e) => setError(e.message));
  }, [metric, companies]);

  if (ov.error) return <ErrorBox message={ov.error} />;
  const periods = sortPeriods([...new Set(data?.rows.map((r) => r.period) ?? [])]);
  const names = [...new Set(data?.rows.map((r) => r.company) ?? [])];
  const chart = periods.map((p) => Object.fromEntries([["period", p], ...(data?.rows.filter((r) => r.period === p).map((r) => [r.company, r.value]) ?? [])]));
  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <div className="card h-fit p-4">
        <div className="label mb-2">Metric</div>
        <div className="scroll-thin max-h-[360px] space-y-0.5 overflow-y-auto">
          {ov.data?.metrics.map((m) => (
            <button key={m} onClick={() => setMetric(m)} className={`block w-full rounded-md px-2.5 py-1.5 text-left text-sm ${m === metric ? "bg-brand-soft font-medium text-brand-ink" : "text-ink-2 hover:bg-sunken"}`}>{metricTitle(m)}</button>
          ))}
        </div>
        <div className="label mb-2 mt-5">Companies</div>
        {ov.data?.companies.map((c) => (
          <label key={c.company_norm} className="flex items-center gap-2 py-1 text-sm">
            <input type="checkbox" className="accent-[var(--brand)]" checked={companies.length === 0 || companies.includes(c.company)} onChange={(e) => {
              const all = ov.data!.companies.map((x) => x.company);
              const cur = companies.length ? companies : all;
              const next = e.target.checked ? [...cur, c.company] : cur.filter((x) => x !== c.company);
              setCompanies(next.length === all.length ? [] : next);
            }} />
            {c.company} <span className="text-xs text-ink-3">{c.currency}</span>
          </label>
        ))}
      </div>
      <div className="space-y-6">
        {error && <ErrorBox message={error} />}
        {!data ? <Spinner label="Loading…" /> : (
          <>
            <div className="card p-5">
              <div className="mb-3 flex items-center gap-2 font-semibold"><LineIcon size={16} className="text-brand" /> {data.title}</div>
              {data.currency_note && <div className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{data.currency_note}</div>}
              {data.rows.length === 0 ? <div className="py-10 text-center text-sm text-ink-3">No values for this metric yet.</div> : (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chart}>
                      <CartesianGrid vertical={false} stroke="var(--line)" />
                      <XAxis dataKey="period" tickLine={false} axisLine={false} tick={{ fill: "var(--ink-3)", fontSize: 12 }} />
                      <YAxis tickLine={false} axisLine={false} width={72} tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickFormatter={(v: number) => metricValue(metric, v, null, true)} />
                      <Tooltip cursor={{ fill: "var(--sunken)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }} formatter={(v) => metricValue(metric, Number(v))} />
                      <Legend wrapperStyle={{ fontSize: 12 }} />
                      {names.map((n, i) => <Bar key={n} dataKey={n} fill={COLORS[i % COLORS.length]} radius={[5, 5, 0, 0]} maxBarSize={52} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
            {data.changes.length > 0 && (
              <div className="card p-5">
                <div className="mb-3 font-semibold">Period-over-period change</div>
                <div className="space-y-2">
                  {data.changes.map((c, i) => (
                    <div key={i} className="flex flex-wrap items-center gap-3 rounded-lg bg-sunken px-4 py-3 text-sm">
                      <span className="font-medium">{c.company}</span>
                      <span className="tabular text-ink-2">{c.from_period}: {metricValue(metric, c.from, c.currency)}</span>
                      <ArrowRight size={14} className="text-ink-3" />
                      <span className="tabular text-ink-2">{c.to_period}: {metricValue(metric, c.to, c.currency)}</span>
                      <span className="ml-auto">{c.pct != null ? <Badge tone={c.pct >= 0 ? "good" : "bad"}>{pct(c.pct)}</Badge> : <Badge>{data.is_percent ? `${((c.to - c.from) * 100).toFixed(1)} pp` : (c.to - c.from).toFixed(2)}</Badge>}</span>
                      <div className="w-full font-mono text-[11px] text-ink-3">{c.pct != null ? `(${money(c.to)} − ${money(c.from)}) / ${money(Math.abs(c.from))} = ${pct(c.pct)}` : "ratio difference"}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-line text-left text-ink-3"><th className="px-4 py-2.5 font-medium">Company</th><th className="px-3 py-2.5 font-medium">Period</th><th className="px-3 py-2.5 text-right font-medium">Value</th><th className="px-4 py-2.5 font-medium">Source</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {data.rows.map((r, i) => (
                    <tr key={i}>
                      <td className="px-4 py-2.5">{r.company}</td>
                      <td className="px-3 py-2.5 text-ink-2">{r.period}</td>
                      <td className="tabular px-3 py-2.5 text-right font-medium">{metricValue(metric, r.value, r.currency)}</td>
                      <td className="px-4 py-2.5 text-xs text-ink-3">{r.fact.formula ? <span className="font-mono">{r.fact.formula}</span> : <>{r.fact.filename} · p.{r.fact.page} · <span className="font-mono">“{r.fact.excerpt}”</span></>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function DocumentCompare() {
  const docs = useApi<{ items: Doc[] }>("/api/documents?limit=200&status=ready");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [res, setRes] = useState<DocCompare | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const items = docs.data?.items ?? [];
    const statements = items.filter((d) => d.doc_type === "income_statement");
    if (!a && statements.length >= 2) {
      setA(statements[1].id);
      setB(statements[0].id);
    }
  }, [docs.data, a]);
  useEffect(() => {
    if (!a || !b || a === b) return;
    setError(null);
    api.get<DocCompare>(`/api/finance/compare-documents?a=${a}&b=${b}`).then(setRes).catch((e) => setError(e.message));
  }, [a, b]);
  const sel = (v: string, set: (s: string) => void) => (
    <select className="input" value={v} onChange={(e) => set(e.target.value)}>
      <option value="">Choose a document…</option>
      {docs.data?.items.map((d) => <option key={d.id} value={d.id}>{d.filename} ({DOC_TYPE_LABEL[d.doc_type ?? "other"]})</option>)}
    </select>
  );
  return (
    <div className="space-y-6">
      <div className="card grid items-center gap-3 p-4 md:grid-cols-[1fr_auto_1fr]">
        {sel(a, setA)}
        <GitCompareArrows size={18} className="mx-auto text-ink-3" />
        {sel(b, setB)}
      </div>
      {error && <ErrorBox message={error} />}
      {res && (
        <>
          {res.currency_note && <div className="rounded-lg bg-warn-soft px-3 py-2 text-sm text-warn">{res.currency_note}</div>}
          <div className="grid gap-4 md:grid-cols-2">
            {[res.a, res.b].map((d) => (
              <div key={d.id} className="card p-4">
                <div className="font-semibold">{d.filename}</div>
                <div className="mt-1 text-xs text-ink-3">{DOC_TYPE_LABEL[d.doc_type ?? "other"]} · {d.company} · {d.period} · {d.currency}</div>
                <p className="mt-2 text-sm text-ink-2">{d.summary}</p>
              </div>
            ))}
          </div>
          {res.metrics.length > 0 && (
            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead><tr className="border-b border-line text-left text-ink-3"><th className="px-4 py-2.5 font-medium">Line item</th><th className="px-3 py-2.5 text-right font-medium">A</th><th className="px-3 py-2.5 text-right font-medium">B</th><th className="px-3 py-2.5 text-right font-medium">B − A</th><th className="px-4 py-2.5 text-right font-medium">Change</th></tr></thead>
                <tbody className="divide-y divide-line">
                  {res.metrics.map((m) => (
                    <tr key={m.metric}>
                      <td className="px-4 py-2">{m.title}</td>
                      <td className="tabular px-3 py-2 text-right">{money(m.a)}</td>
                      <td className="tabular px-3 py-2 text-right">{money(m.b)}</td>
                      <td className="tabular px-3 py-2 text-right">{m.diff != null ? money(m.diff) : "–"}</td>
                      <td className="px-4 py-2 text-right">{m.pct != null ? <Badge tone={Math.abs(m.pct) >= 0.25 ? "warn" : "neutral"}>{pct(m.pct)}</Badge> : "–"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {res.invoice_fields.length > 0 && (
            <div className="card overflow-hidden">
              <div className="border-b border-line px-4 py-2.5 font-semibold">Invoice fields</div>
              <table className="w-full text-sm"><tbody className="divide-y divide-line">
                {res.invoice_fields.map((f) => (
                  <tr key={f.field}><td className="px-4 py-2 capitalize text-ink-2">{f.field.replace("_", " ")}</td><td className="px-3 py-2">{String(f.a ?? "–")}</td><td className="px-3 py-2">{String(f.b ?? "–")}</td><td className="px-4 py-2 text-right">{f.same ? <Badge tone="warn">identical</Badge> : <Badge>differs</Badge>}</td></tr>
                ))}
              </tbody></table>
            </div>
          )}
          <div className="card grid gap-4 p-4 text-sm md:grid-cols-3">
            <div><div className="label mb-1.5">Shared entities</div>{res.shared_entities.join(", ") || "–"}</div>
            <div><div className="label mb-1.5">Only in A</div>{res.only_a.join(", ") || "–"}</div>
            <div><div className="label mb-1.5">Only in B</div>{res.only_b.join(", ") || "–"}</div>
          </div>
        </>
      )}
    </div>
  );
}
