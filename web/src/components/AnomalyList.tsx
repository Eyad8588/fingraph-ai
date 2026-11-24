import { ChevronRight, FileText } from "lucide-react";
import { useState } from "react";
import type { Anomaly } from "../lib/api";
import { go } from "../lib/hooks";
import { Drawer, Excerpt, Severity } from "./ui";

const RULE_LABEL: Record<string, string> = {
  duplicate_invoice: "Duplicate invoice",
  possible_duplicate_invoice: "Possible duplicate",
  invoice_math: "Invoice arithmetic",
  statement_math: "Statement arithmetic",
  period_swing: "Large change",
  sign_change: "Profit → loss",
  suspicious_payment: "Suspicious payment",
  duplicate_payment: "Duplicate payment",
  amount_outlier: "Statistical outlier",
};

export function AnomalyList({ items, compact = false }: { items: Anomaly[]; compact?: boolean }) {
  const [open, setOpen] = useState<Anomaly | null>(null);
  return (
    <>
      <ul className="divide-y divide-line">
        {items.map((a) => (
          <li key={a.id}>
            <button onClick={() => setOpen(a)} className="flex w-full items-start gap-3 px-4 py-3 text-left transition hover:bg-sunken">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${a.severity === "high" ? "bg-bad" : a.severity === "medium" ? "bg-warn" : "bg-ink-3"}`} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium">{a.title}</span>
                </div>
                {!compact && <div className="mt-0.5 line-clamp-2 text-xs text-ink-2">{a.detail}</div>}
                <div className="mt-1 text-[11px] text-ink-3">
                  {RULE_LABEL[a.rule] ?? a.rule} · {a.evidence.length} source{a.evidence.length === 1 ? "" : "s"}
                </div>
              </div>
              <ChevronRight size={16} className="mt-1 shrink-0 text-ink-3" />
            </button>
          </li>
        ))}
      </ul>
      <Drawer open={!!open} onClose={() => setOpen(null)} title={open?.title ?? ""} width={600}>
        {open && (
          <div className="space-y-5">
            <div className="flex items-center gap-2">
              <Severity level={open.severity} />
              <span className="text-xs text-ink-3">Rule: {RULE_LABEL[open.rule] ?? open.rule}</span>
            </div>
            <p className="text-sm leading-relaxed">{open.detail}</p>
            <div className="rounded-lg bg-info-soft px-3 py-2 text-xs text-info">
              Detected by a deterministic rule over verified facts. No LLM judgement is involved, so the result is
              repeatable and auditable.
            </div>
            <div>
              <div className="label mb-2">Evidence</div>
              <div className="space-y-3">
                {open.evidence.map((e, i) => (
                  <div key={i} className="rounded-lg border border-line p-3">
                    <button onClick={() => go("library", { doc: e.doc_id })} className="flex items-center gap-1.5 text-sm font-medium text-brand hover:underline">
                      <FileText size={14} /> {e.filename}
                      <span className="font-normal text-ink-3">· page {e.page ?? 1}</span>
                    </button>
                    <Excerpt text={e.excerpt} />
                  </div>
                ))}
              </div>
            </div>
            {open.entities.filter(Boolean).length > 0 && (
              <div>
                <div className="label mb-2">Involved</div>
                <div className="flex flex-wrap gap-1.5">
                  {open.entities.filter(Boolean).map((n) => (
                    <button key={n} onClick={() => go("graph", { entity: n })} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-sunken">
                      {n} → graph
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>
    </>
  );
}
