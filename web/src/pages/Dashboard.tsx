import { Download, FileStack, RefreshCw, ShieldAlert, Sparkles, TrendingDown, TrendingUp, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AnomalyList } from "../components/AnomalyList";
import { Badge, Empty, ErrorBox, PageHeader, Segmented, Stat } from "../components/ui";
import { api, type Anomaly } from "../lib/api";
import { useApi } from "../lib/hooks";
import { metricTitle, metricValue, money, pct, sortPeriods } from "../lib/format";

interface Overview {
  kpis: { company: string; company_norm: string; period: string; currency: string; values: Record<string, number> }[];
  invoices: { n: number; total: number | null };
  transactions: { n: number; out: number | null; inflow: number | null };
  changes: { company: string; metric: string; from_period: string; to_period: string; from: number; to: number; pct: number | null; currency: string }[];
  companies: { company: string; company_norm: string; currency: string; periods_list: string[] }[];
  metrics: string[];
  anomalies: Anomaly[];
}
interface Summary {
  bullets: string[];
  source: string;
  generated_at: number;
}
interface DocsResp {
  counts: Record<string, number>;
}
interface CompareResp {
  rows: { company: string; period: string; value: number; currency: string }[];
  currency_note: string | null;
}

const PALETTE = ["var(--brand)", "var(--info)", "var(--warn)", "#a855f7", "#64748b"];

export default function Dashboard() {
  const ov = useApi<Overview>("/api/finance/overview");
  const docs = useApi<DocsResp>("/api/documents?limit=1", { pollMs: 4000, shouldPoll: (d) => (d.counts.processing ?? 0) + (d.counts.queued ?? 0) > 0 });
  const [refreshing, setRefreshing] = useState(false);
  const summary = useApi<Summary>("/api/finance/summary");
  const counts = docs.data?.counts ?? {};
  const totalDocs = Object.values(counts).reduce((a, b) => a + b, 0);
  const busy = (counts.processing ?? 0) + (counts.queued ?? 0);

  const refresh = async () => {
    setRefreshing(true);
    try {
      summary.setData(await api.get<Summary>("/api/finance/summary?refresh=true"));
      await ov.reload();
    } finally {
      setRefreshing(false);
    }
  };

  if (ov.error) return <div className="p-8"><ErrorBox message={ov.error} onRetry={ov.reload} /></div>;

  return (
    <div className="mx-auto max-w-[1280px] p-6 md:p-8">
      <PageHeader
        title="Dashboard"
        subtitle={totalDocs ? `${(counts.ready ?? 0) + (counts.limited ?? 0)} of ${totalDocs} documents indexed${busy ? ` · ${busy} processing` : ""}` : "Upload financial documents to get started"}
        actions={
          <>
            <a className="btn" href="/api/export/report.html" target="_blank" rel="noreferrer"><Download size={15} /> Report</a>
            <a className="btn" href="/api/export/metrics.csv"><Download size={15} /> Metrics CSV</a>
            <button className="btn" onClick={refresh} disabled={refreshing}><RefreshCw size={15} className={refreshing ? "animate-spin" : ""} /> Refresh</button>
          </>
        }
      />

      {ov.loading && !ov.data ? (
        <div className="grid gap-4 md:grid-cols-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-36" />)}</div>
      ) : !ov.data || ov.data.kpis.length === 0 ? (
        <div className="card">
          <Empty icon={<FileStack size={22} />} title="No financial data yet">
            Upload income statements, balance sheets, invoices or bank statements. Try the synthetic set in <code>samples/docs</code>.
            <div className="mt-4"><a className="btn-primary" href="#/library"><Upload size={15} /> Go to documents</a></div>
          </Empty>
        </div>
      ) : (
        <Content ov={ov.data} summary={summary.data} summaryLoading={summary.loading} />
      )}
    </div>
  );
}

function Content({ ov, summary, summaryLoading }: { ov: Overview; summary: Summary | null; summaryLoading: boolean }) {
  const high = ov.anomalies.filter((a) => a.severity === "high").length;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3">
        {ov.kpis.map((k) => (
          <KpiCard key={k.company_norm} k={k} changes={ov.changes.filter((c) => c.company === k.company && c.to_period === k.period)} />
        ))}
        <div className="card p-5">
          <div className="label">Activity</div>
          <div className="mt-3 grid grid-cols-2 gap-4">
            <Stat label="Invoices" value={ov.invoices.n} sub={money(ov.invoices.total, null, true) + " billed"} />
            <Stat label="Transactions" value={ov.transactions.n} sub={money(ov.transactions.out, null, true) + " paid out"} />
            <Stat label="Anomalies" value={ov.anomalies.length} sub={`${high} high severity`} tone={high ? "bad" : undefined} />
            <Stat label="Companies" value={ov.companies.length} sub={ov.companies.map((c) => c.currency).filter((v, i, a) => a.indexOf(v) === i).join(" · ")} />
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <section className="card lg:col-span-3">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <div className="flex items-center gap-2 font-semibold"><Sparkles size={16} className="text-brand" /> Key findings</div>
            {summary && <Badge tone={summary.source.startsWith("llm") ? "brand" : "neutral"} title={summary.source}>{summary.source.startsWith("llm") ? "AI summary · numbers verified" : "Rule-based"}</Badge>}
          </div>
          <div className="px-5 py-4">
            {summaryLoading && !summary ? (
              <div className="space-y-2">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-4" style={{ width: `${90 - i * 12}%` }} />)}<div className="pt-1 text-xs text-ink-3">Writing summary from the verified fact sheet…</div></div>
            ) : (
              <ul className="space-y-2.5">
                {summary?.bullets.map((b, i) => (
                  <li key={i} className="flex gap-2.5 text-sm leading-relaxed"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-brand" />{b}</li>
                ))}
              </ul>
            )}
          </div>
        </section>
        <section className="card lg:col-span-2">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <div className="flex items-center gap-2 font-semibold"><ShieldAlert size={16} className="text-bad" /> Anomalies</div>
            <span className="text-xs text-ink-3">{ov.anomalies.length} found</span>
          </div>
          <div className="scroll-thin max-h-[340px] overflow-y-auto">
            {ov.anomalies.length ? <AnomalyList items={ov.anomalies} compact /> : <div className="p-6 text-sm text-ink-3">No anomalies detected.</div>}
          </div>
        </section>
      </div>

      <MetricChart ov={ov} />
    </div>
  );
}

function KpiCard({ k, changes }: { k: Overview["kpis"][number]; changes: Overview["changes"] }) {
  const rev = changes.find((c) => c.metric === "revenue");
  const ni = k.values.net_income;
  return (
    <div className="card p-5">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-semibold">{k.company}</div>
          <div className="text-xs text-ink-3">{k.period} · {k.currency}</div>
        </div>
        {rev?.pct != null && (
          <Badge tone={rev.pct >= 0 ? "good" : "bad"} title={`Revenue vs ${rev.from_period}`}>
            {rev.pct >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {pct(rev.pct)}
          </Badge>
        )}
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        {k.values.revenue !== undefined && <Stat label="Revenue" value={money(k.values.revenue, null, true)} />}
        {ni !== undefined && <Stat label="Net income" value={money(ni, null, true)} tone={ni < 0 ? "bad" : undefined} />}
        {k.values.gross_margin !== undefined && <Stat label="Gross margin" value={metricValue("gross_margin", k.values.gross_margin)} />}
        {k.values.net_margin !== undefined && <Stat label="Net margin" value={metricValue("net_margin", k.values.net_margin)} tone={k.values.net_margin < 0 ? "bad" : undefined} />}
        {k.values.current_ratio !== undefined && <Stat label="Current ratio" value={metricValue("current_ratio", k.values.current_ratio)} />}
        {k.values.debt_to_equity !== undefined && <Stat label="Debt / equity" value={metricValue("debt_to_equity", k.values.debt_to_equity)} />}
      </div>
    </div>
  );
}

function MetricChart({ ov }: { ov: Overview }) {
  const options = ov.metrics.filter((m) => ["revenue", "gross_profit", "operating_expenses", "marketing", "net_income", "gross_margin", "net_margin"].includes(m));
  const [metric, setMetric] = useState(options.includes("revenue") ? "revenue" : options[0] ?? "revenue");
  const [rows, setRows] = useState<CompareResp | null>(null);
  useEffect(() => {
    api.post<CompareResp>("/api/finance/compare", { metric }).then(setRows).catch(() => setRows(null));
  }, [metric]);
  const periods = sortPeriods([...new Set(rows?.rows.map((r) => r.period) ?? [])]);
  const companies = [...new Set(rows?.rows.map((r) => r.company) ?? [])];
  const chart = periods.map((p) => {
    const o: Record<string, string | number> = { period: p };
    rows?.rows.filter((r) => r.period === p).forEach((r) => (o[r.company] = r.value));
    return o;
  });
  return (
    <section className="card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="font-semibold">{metricTitle(metric)} by period</div>
        <Segmented value={metric} onChange={setMetric} options={options.map((m) => ({ value: m, label: metricTitle(m) }))} />
      </div>
      {rows?.currency_note && <div className="mb-3 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{rows.currency_note}</div>}
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chart} barGap={6}>
            <CartesianGrid vertical={false} stroke="var(--line)" />
            <XAxis dataKey="period" tickLine={false} axisLine={false} tick={{ fill: "var(--ink-3)", fontSize: 12 }} />
            <YAxis tickLine={false} axisLine={false} width={70} tick={{ fill: "var(--ink-3)", fontSize: 12 }} tickFormatter={(v: number) => metricValue(metric, v, null, true)} />
            <Tooltip cursor={{ fill: "var(--sunken)" }} contentStyle={{ background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 8, fontSize: 12 }} formatter={(v) => metricValue(metric, Number(v))} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {companies.map((c, i) => <Bar key={c} dataKey={c} fill={PALETTE[i % PALETTE.length]} radius={[5, 5, 0, 0]} maxBarSize={48} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
