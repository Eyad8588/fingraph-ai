export const PERCENT_METRICS = new Set(["gross_margin", "operating_margin", "net_margin"]);
export const RATIO_METRICS = new Set(["current_ratio", "debt_to_equity", ...PERCENT_METRICS]);

export function money(v: number | null | undefined, currency?: string | null, compact = false): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  const abs = Math.abs(v);
  let s: string;
  if (compact && abs >= 1_000_000) s = `${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 1 : 2)}M`;
  else if (compact && abs >= 10_000) s = `${(abs / 1_000).toFixed(0)}k`;
  else s = abs.toLocaleString("en-US", { maximumFractionDigits: abs % 1 ? 2 : 0 });
  return `${v < 0 ? "−" : ""}${currency ? currency + " " : ""}${s}`;
}

export function metricValue(metric: string, v: number | null | undefined, currency?: string | null, compact = false): string {
  if (v === null || v === undefined) return "–";
  if (PERCENT_METRICS.has(metric)) return `${(v * 100).toFixed(1)}%`;
  if (RATIO_METRICS.has(metric)) return v.toFixed(2);
  return money(v, currency, compact);
}

export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return "–";
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

export function metricTitle(m: string): string {
  const special: Record<string, string> = {
    cost_of_revenue: "Cost of revenue",
    net_income: "Net income",
    gross_margin: "Gross margin",
    net_margin: "Net margin",
    operating_margin: "Operating margin",
    current_ratio: "Current ratio",
    debt_to_equity: "Debt to equity",
    operating_expenses: "Operating expenses",
  };
  return special[m] ?? m.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export const DOC_TYPE_LABEL: Record<string, string> = {
  income_statement: "Income statement",
  balance_sheet: "Balance sheet",
  cash_flow: "Cash flow",
  invoice: "Invoice",
  bank_statement: "Bank statement",
  contract: "Contract",
  purchase_order: "Purchase order",
  report: "Report",
  other: "Document",
};

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function ago(ts: number): string {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

/** Chronological sort key for 'Q2 2026' / 'FY 2025' style periods. */
export function periodKey(p: string): number {
  const m = p.match(/(?:Q([1-4])|FY)\s*(\d{4})/);
  if (!m) return 0;
  return Number(m[2]) * 10 + (m[1] ? Number(m[1]) : 5);
}

export function sortPeriods(ps: string[]): string[] {
  return [...ps].sort((a, b) => periodKey(a) - periodKey(b));
}
