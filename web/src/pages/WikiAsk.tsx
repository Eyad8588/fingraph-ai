import { AlertTriangle, Calculator, ChevronDown, ChevronRight, Cpu, FileText, Filter, MessageSquarePlus, Pencil, Search, SendHorizontal, Sparkles, Trash2, X } from "lucide-react";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { Badge, ErrorBox, Excerpt } from "../components/ui";
import { api, type AnswerMeta, type Citation, type Conversation, type Doc, type Message } from "../lib/api";
import { go, useApi, useHashRoute } from "../lib/hooks";
import { ago } from "../lib/format";

const SUGGESTIONS = [
  "How did Nova Retail's revenue change from Q1 to Q2 2026?",
  "Compare the gross margin of Nova Retail and Helix Foods in Q2 2026",
  "Did we pay Atlas Logistics twice for invoice INV-1042?",
  "Which payments look suspicious in the June bank statement?",
  "What is the monthly fee cap in the Atlas agreement?",
  "Why did revenue soften in Q2 2026?",
];

export default function WikiAsk({ convId }: { convId: string | null }) {
  const route = useHashRoute();
  const convs = useApi<Conversation[]>("/api/conversations");
  const docs = useApi<{ items: Doc[] }>("/api/documents?limit=200&status=ready");
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadingMsgs, setLoadingMsgs] = useState(false);
  const [input, setInput] = useState(route.params.get("q") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scope, setScope] = useState<string[]>(route.params.get("scope") ? [route.params.get("scope")!] : []);
  const [scopeOpen, setScopeOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!convId) {
      setMessages([]);
      return;
    }
    setLoadingMsgs(true);
    api
      .get<{ messages: Message[]; conversation: Conversation }>(`/api/conversations/${convId}/messages`)
      .then((r) => {
        setMessages(r.messages);
        try {
          const s = JSON.parse(r.conversation.scope || "[]");
          if (Array.isArray(s) && s.length) setScope(s);
        } catch {
          /* ignore */
        }
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoadingMsgs(false));
  }, [convId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  const send = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setError(null);
    setBusy(true);
    setInput("");
    let cid = convId;
    try {
      if (!cid) {
        const c = await api.post<Conversation>("/api/conversations", { scope });
        cid = c.id;
        window.history.replaceState(null, "", `#/ask?c=${cid}`);
      }
      setMessages((m) => [...m, { id: -Date.now(), role: "user", content: q, meta: {} }]);
      const ans = await api.post<Message>(`/api/conversations/${cid}/ask`, { question: q, doc_ids: scope.length ? scope : null });
      setMessages((m) => [...m, ans]);
      convs.reload();
      if (!convId) go("ask", { c: cid });
    } catch (e) {
      setError((e as Error).message);
      setInput(q);
    } finally {
      setBusy(false);
    }
  };

  const rename = async (c: Conversation) => {
    const title = window.prompt("Rename conversation", c.title);
    if (title) {
      await api.patch(`/api/conversations/${c.id}`, { title });
      convs.reload();
    }
  };
  const remove = async (c: Conversation) => {
    if (!window.confirm(`Delete “${c.title}”?`)) return;
    await api.del(`/api/conversations/${c.id}`);
    convs.reload();
    if (c.id === convId) go("ask");
  };

  const docName = (id: string) => docs.data?.items.find((d) => d.id === id)?.filename ?? id;

  return (
    <div className="flex h-full min-h-0">
      <aside className="scroll-thin hidden w-64 shrink-0 flex-col overflow-y-auto border-r border-line bg-surface lg:flex">
        <div className="p-3">
          <button className="btn-primary w-full justify-center" onClick={() => { setScope([]); go("ask"); }}>
            <MessageSquarePlus size={15} /> New conversation
          </button>
        </div>
        <div className="label px-4 pb-1">History</div>
        <div className="flex-1 space-y-0.5 px-2 pb-3">
          {convs.data?.filter((c) => c.title !== "[eval run]").map((c) => (
            <div key={c.id} className={`group flex items-center rounded-lg ${c.id === convId ? "bg-brand-soft" : "hover:bg-sunken"}`}>
              <a href={`#/ask?c=${c.id}`} className="min-w-0 flex-1 px-3 py-2">
                <div className={`truncate text-sm ${c.id === convId ? "font-medium text-brand-ink" : ""}`}>{c.title}</div>
                <div className="text-[11px] text-ink-3">{ago(c.updated_at)} · {c.messages ?? 0} messages</div>
              </a>
              <div className="hidden gap-0.5 pr-1.5 group-hover:flex">
                <button className="rounded p-1 text-ink-3 hover:text-ink" title="Rename" onClick={() => rename(c)}><Pencil size={13} /></button>
                <button className="rounded p-1 text-ink-3 hover:text-bad" title="Delete" onClick={() => remove(c)}><Trash2 size={13} /></button>
              </div>
            </div>
          ))}
          {convs.data?.length === 0 && <div className="px-3 py-2 text-xs text-ink-3">No conversations yet.</div>}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="scroll-thin flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-4 py-6 md:px-6">
            {loadingMsgs ? (
              <div className="space-y-3">{[0, 1].map((i) => <div key={i} className="skeleton h-20" />)}</div>
            ) : messages.length === 0 ? (
              <div className="pt-10">
                <div className="mx-auto mb-2 grid h-11 w-11 place-items-center rounded-xl bg-brand-soft text-brand"><Sparkles size={20} /></div>
                <h2 className="text-center text-xl font-semibold">Ask your financial documents</h2>
                <p className="mx-auto mt-1.5 max-w-lg text-center text-sm text-ink-2">Answers cite the exact source passages. Calculations are done by code, not by the model, and every number is checked against the sources.</p>
                <div className="mt-7 grid gap-2 sm:grid-cols-2">
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => send(s)} className="card px-4 py-3 text-left text-sm text-ink-2 transition hover:border-brand/40 hover:text-ink">{s}</button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="space-y-6">
                {messages.map((m) => (m.role === "user" ? <UserBubble key={m.id} text={m.content} /> : <AnswerCard key={m.id} msg={m} />))}
                {busy && <Thinking />}
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="border-t border-line bg-surface px-4 py-3 md:px-6">
          <div className="mx-auto max-w-3xl">
            {error && <div className="mb-2"><ErrorBox message={error} /></div>}
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              <div className="relative">
                <button className={`flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs ${scope.length ? "border-brand bg-brand-soft text-brand-ink" : "border-line text-ink-2 hover:bg-sunken"}`} onClick={() => setScopeOpen((o) => !o)}>
                  <Filter size={12} /> {scope.length ? `${scope.length} document${scope.length > 1 ? "s" : ""}` : "All documents"}
                </button>
                {scopeOpen && (
                  <div className="card scroll-thin absolute bottom-9 left-0 z-20 max-h-72 w-80 overflow-y-auto p-2 shadow-xl">
                    <div className="label px-2 pb-1 pt-1">Limit this chat to</div>
                    {docs.data?.items.map((d) => (
                      <label key={d.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-sunken">
                        <input type="checkbox" className="accent-[var(--brand)]" checked={scope.includes(d.id)} onChange={(e) => setScope((s) => (e.target.checked ? [...s, d.id] : s.filter((x) => x !== d.id)))} />
                        <span className="truncate">{d.filename}</span>
                      </label>
                    ))}
                    <button className="mt-1 w-full rounded-md px-2 py-1.5 text-xs text-ink-3 hover:bg-sunken" onClick={() => { setScope([]); setScopeOpen(false); }}>Clear: search everything</button>
                  </div>
                )}
              </div>
              {scope.map((id) => (
                <span key={id} className="flex items-center gap-1 rounded-full bg-sunken px-2 py-0.5 text-[11px] text-ink-2">
                  {docName(id)} <button onClick={() => setScope((s) => s.filter((x) => x !== id))}><X size={11} /></button>
                </span>
              ))}
            </div>
            <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <textarea
                className="input min-h-[44px] resize-none py-2.5"
                rows={1}
                placeholder="Ask about revenue, invoices, payments, contracts…  (Arabic works too)"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
                disabled={busy}
                dir="auto"
              />
              <button className="btn-primary h-[44px] px-4" disabled={busy || !input.trim()} aria-label="Send"><SendHorizontal size={17} /></button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-sm text-white dark:text-[#06201d]" dir="auto">{text}</div>
    </div>
  );
}

function Thinking() {
  const steps = ["Rewriting follow-up", "Routing question", "Hybrid search + rerank", "Generating grounded answer", "Verifying numbers"];
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => Math.min(x + 1, steps.length - 1)), 1100);
    return () => clearInterval(t);
  }, [steps.length]);
  return (
    <div className="card p-4">
      <div className="flex items-center gap-2 text-sm text-ink-2"><span className="h-2 w-2 animate-pulse rounded-full bg-brand" /> {steps[i]}…</div>
      <div className="mt-3 space-y-2"><div className="skeleton h-3.5 w-11/12" /><div className="skeleton h-3.5 w-8/12" /></div>
    </div>
  );
}

function AnswerCard({ msg }: { msg: Message }) {
  const meta = msg.meta as AnswerMeta;
  const [active, setActive] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const cits = meta.citations ?? [];
  const used = cits.filter((c) => c.used);
  const shown = showAll ? cits : used.length ? used : cits.slice(0, 3);
  return (
    <div className="card overflow-hidden">
      <div className="px-5 pt-4">
        {meta.standalone && (
          <div className="mb-2 flex items-center gap-1.5 text-xs text-ink-3"><Search size={12} /> Searched for: <span className="italic text-ink-2">{meta.standalone}</span></div>
        )}
        {meta.unverified && (
          <div className="mb-3 flex items-start gap-2 rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <div><b>Unverified:</b> {meta.problems?.join("; ")}. Check the sources before relying on this answer.</div>
          </div>
        )}
        <div className="text-[14.5px] leading-relaxed" dir="auto">
          <RichText text={msg.content} onCite={(n) => setActive(n)} />
        </div>
        {meta.calculations && meta.calculations.length > 0 && (
          <div className="mt-4 rounded-lg border border-line bg-sunken px-4 py-3">
            <div className="label mb-1.5 flex items-center gap-1.5"><Calculator size={12} /> Calculation (computed by code)</div>
            {meta.calculations.map((c, i) => <div key={i} className="tabular font-mono text-[12px] text-ink-2">{c}</div>)}
          </div>
        )}
        {meta.route?.notes?.map((n, i) => <div key={i} className="mt-3 rounded-lg bg-info-soft px-3 py-2 text-xs text-info">{n}</div>)}
      </div>

      {cits.length > 0 && (
        <div className="mt-4 border-t border-line px-5 py-3">
          <div className="mb-2 flex items-center justify-between">
            <div className="label">Sources {used.length ? `· ${used.length} cited` : ""}</div>
            {cits.length > shown.length || showAll ? (
              <button className="text-xs text-ink-3 hover:text-ink" onClick={() => setShowAll((s) => !s)}>{showAll ? "Show cited only" : `Show all ${cits.length} retrieved`}</button>
            ) : null}
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {shown.map((c) => <SourceCard key={c.n} c={c} active={active === c.n} onClick={() => setActive(active === c.n ? null : c.n)} />)}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1.5 border-t border-line bg-sunken/50 px-5 py-2 text-[11px] text-ink-3">
        <Badge tone={meta.route?.route === "doc" ? "neutral" : "brand"} title="doc = text answer; metric/both = verified figures used">{meta.route?.route === "doc" ? "Document search" : "Verified figures"}</Badge>
        {meta.abstained && <Badge tone="warn">Not enough information</Badge>}
        <span className="flex items-center gap-1"><Cpu size={11} /> {meta.model?.replace("ollama:", "")}</span>
        <span>· {(meta.latency_ms / 1000).toFixed(1)}s</span>
        {meta.scope?.length > 0 && <span>· scoped to {meta.scope.length} doc(s)</span>}
        <button className="ml-auto flex items-center gap-0.5 hover:text-ink" onClick={() => setShowDebug((s) => !s)}>{showDebug ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Retrieval details</button>
      </div>
      {showDebug && meta.retrieval && (
        <div className="border-t border-line px-5 py-3 font-mono text-[11px] text-ink-2">
          <div>gate: {meta.retrieval.gate}</div>
          <div>top similarity {meta.retrieval.top_similarity} · top rerank {meta.retrieval.top_rerank ?? "–"} · reranked {String(meta.retrieval.reranked)}</div>
          <div>timings: {Object.entries(meta.retrieval.timings_ms).map(([k, v]) => `${k} ${v}ms`).join(" · ")}</div>
          {meta.route?.missing?.length > 0 && <div>missing: {meta.route.missing.join(" ")}</div>}
        </div>
      )}
    </div>
  );
}

function SourceCard({ c, active, onClick }: { c: Citation; active: boolean; onClick: () => void }) {
  return (
    <div id={`cite-${c.chunk_id}`} className={`rounded-lg border p-3 transition ${active ? "border-brand ring-2 ring-brand/15" : "border-line"} ${c.used ? "" : "opacity-70"}`}>
      <button className="flex w-full items-start gap-2 text-left" onClick={onClick}>
        <span className={`grid h-5 min-w-5 place-items-center rounded px-1 text-[11px] font-semibold ${c.used ? "bg-brand text-white dark:text-[#06201d]" : "bg-sunken text-ink-3"}`}>{c.n}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium">{c.filename}</div>
          <div className="text-[11px] text-ink-3">page {c.page}{c.section ? ` · ${c.section}` : ""}{c.method === "ocr" ? " · OCR" : ""}</div>
        </div>
      </button>
      <div className={active ? "" : "line-clamp-3"}>
        <Excerpt text={c.excerpt} />
      </div>
      {active && (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-ink-3">
          {c.similarity != null && <span>cosine {c.similarity}</span>}
          {c.rerank != null && <span>· rerank {c.rerank}</span>}
          <span>· found by {c.found_by.join(" + ")}</span>
          <button className="ml-auto flex items-center gap-1 text-brand hover:underline" onClick={() => go("library", { doc: c.doc_id })}><FileText size={11} /> Open</button>
        </div>
      )}
    </div>
  );
}

/** Minimal renderer: paragraphs, bullet lists, **bold**, and clickable [n] citations. */
function RichText({ text, onCite }: { text: string; onCite: (n: number) => void }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <div className="space-y-2.5">
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*([-*•]|\d+\.)\s+/.test(l))) {
          return (
            <ul key={i} className="ml-1 space-y-1.5">
              {lines.map((l, j) => (
                <li key={j} className="flex gap-2"><span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-ink-3" /><span>{inline(l.replace(/^\s*([-*•]|\d+\.)\s+/, ""), onCite)}</span></li>
              ))}
            </ul>
          );
        }
        return <p key={i}>{lines.map((l, j) => <Fragment key={j}>{j > 0 && <br />}{inline(l, onCite)}</Fragment>)}</p>;
      })}
    </div>
  );
}

function inline(s: string, onCite: (n: number) => void): ReactNode[] {
  const parts = s.split(/(\*\*[^*]+\*\*|\[\d+\])/g);
  return parts.map((p, i) => {
    const cite = p.match(/^\[(\d+)\]$/);
    if (cite)
      return (
        <button key={i} onClick={() => onCite(Number(cite[1]))} className="mx-0.5 inline-grid h-[18px] min-w-[18px] place-items-center rounded bg-brand-soft px-1 align-text-top text-[10.5px] font-semibold text-brand-ink hover:bg-brand hover:text-white">
          {cite[1]}
        </button>
      );
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i} className="font-semibold">{p.slice(2, -2)}</strong>;
    return <Fragment key={i}>{p}</Fragment>;
  });
}
