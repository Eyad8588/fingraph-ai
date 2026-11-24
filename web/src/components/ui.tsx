import { AlertTriangle, CheckCircle2, CircleDashed, Loader2, X, XCircle } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import type { DocStatus } from "../lib/api";

type Tone = "neutral" | "brand" | "good" | "warn" | "bad" | "info";

const toneCls: Record<Tone, string> = {
  neutral: "bg-sunken text-ink-2 border-line",
  brand: "bg-brand-soft text-brand-ink border-transparent",
  good: "bg-good-soft text-good border-transparent",
  warn: "bg-warn-soft text-warn border-transparent",
  bad: "bg-bad-soft text-bad border-transparent",
  info: "bg-info-soft text-info border-transparent",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${toneCls[tone]}`}>
      {children}
    </span>
  );
}

const STAGE_LABEL: Record<string, string> = {
  parsing: "Reading",
  ocr: "OCR",
  extracting: "Extracting",
  chunking: "Chunking",
  embedding: "Embedding",
};

export function StatusPill({ status, stage, error }: { status: DocStatus; stage?: string | null; error?: string | null }) {
  if (status === "ready")
    return (
      <Badge tone="good">
        <CheckCircle2 size={12} /> Ready
      </Badge>
    );
  if (status === "limited")
    return (
      <Badge tone="warn" title={error ?? ""}>
        <AlertTriangle size={12} /> Ready · limited
      </Badge>
    );
  if (status === "failed")
    return (
      <Badge tone="bad" title={error ?? ""}>
        <XCircle size={12} /> Failed
      </Badge>
    );
  if (status === "queued")
    return (
      <Badge>
        <CircleDashed size={12} /> Queued
      </Badge>
    );
  return (
    <Badge tone="info">
      <Loader2 size={12} className="animate-spin" /> {STAGE_LABEL[stage ?? ""] ?? "Processing"}…
    </Badge>
  );
}

export function Severity({ level }: { level: "high" | "medium" | "low" }) {
  const tone: Tone = level === "high" ? "bad" : level === "medium" ? "warn" : "neutral";
  return <Badge tone={tone}>{level}</Badge>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-ink-3">
      <Loader2 size={16} className="animate-spin" /> {label}
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-bad/30 bg-bad-soft p-4 text-sm text-bad">
      <XCircle size={18} className="mt-0.5 shrink-0" />
      <div className="flex-1">{message}</div>
      {onRetry && (
        <button className="btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <div className="mb-1 rounded-2xl bg-sunken p-3 text-ink-3">{icon}</div>
      <div className="font-semibold">{title}</div>
      {children && <div className="max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Drawer({ open, onClose, title, children, width = 560 }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: number }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[1px]" onClick={onClose} />
      <aside className="relative flex h-full w-full flex-col border-l border-line bg-surface shadow-2xl" style={{ maxWidth: width }}>
        <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-4">
          <div className="min-w-0 font-semibold">{title}</div>
          <button className="rounded-md p-1 text-ink-3 hover:bg-sunken hover:text-ink" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="scroll-thin flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "good" | "bad" }) {
  return (
    <div>
      <div className="label">{label}</div>
      <div className={`tabular mt-1 text-xl font-semibold ${tone === "good" ? "text-good" : tone === "bad" ? "text-bad" : ""}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-ink-3">{sub}</div>}
    </div>
  );
}

export function Excerpt({ text, highlight }: { text: string | null | undefined; highlight?: string }) {
  if (!text) return null;
  return (
    <pre className="scroll-thin mt-1.5 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-sunken px-3 py-2 font-mono text-[11.5px] leading-relaxed text-ink-2">
      {highlight ? markText(text, highlight) : text}
    </pre>
  );
}

function markText(text: string, needle: string) {
  const i = text.toLowerCase().indexOf(needle.toLowerCase());
  if (i < 0 || !needle) return text;
  return (
    <>
      {text.slice(0, i)}
      <mark className="rounded bg-warn-soft px-0.5 text-ink">{text.slice(i, i + needle.length)}</mark>
      {text.slice(i + needle.length)}
    </>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-sunken p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${value === o.value ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
