import { ExternalLink, FileImage, FileSpreadsheet, FileText, MessageSquarePlus, RotateCcw, ScanText, Trash2, UploadCloud } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { AnomalyList } from "../components/AnomalyList";
import { Badge, Drawer, Empty, ErrorBox, Excerpt, PageHeader, Segmented, StatusPill } from "../components/ui";
import { api, type Anomaly, type Doc } from "../lib/api";
import { go, useApi } from "../lib/hooks";
import { DOC_TYPE_LABEL, ago, bytes, metricTitle, money } from "../lib/format";

interface DocsResp {
  items: Doc[];
  next: { before_ts: number; before_id: string } | null;
  counts: Record<string, number>;
}

interface DocDetail {
  document: Doc;
  pages: { page: number; method: string; confidence: number | null; chars: number; text: string }[];
  chunks: { id: number; idx: number; page: number; section: string | null; header: string; text: string }[];
  metrics: { id: number; name: string; label: string; value: number; currency: string; period: string; page: number; excerpt: string; source: string }[];
  invoices: { number: string; vendor: string; customer: string; issue_date: string; due_date: string; subtotal: number; tax: number; total: number; currency: string }[];
  transactions: { id: number; date: string; description: string; counterparty: string; amount: number; direction: string; category: string | null }[];
  entities: { id: number; name: string; type: string }[];
  anomalies: Anomaly[];
}

function FileIcon({ ext }: { ext: string }) {
  if ([".png", ".jpg", ".jpeg"].includes(ext)) return <FileImage size={18} className="text-info" />;
  if (ext === ".docx") return <FileSpreadsheet size={18} className="text-brand" />;
  return <FileText size={18} className="text-bad" />;
}

export default function Library({ openId }: { openId: string | null }) {
  const docs = useApi<DocsResp>("/api/documents?limit=100", {
    pollMs: 1500,
    shouldPoll: (d) => d.items.some((x) => x.status === "queued" || x.status === "processing"),
  });
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<{ tone: "good" | "bad"; text: string }[]>([]);
  const [drag, setDrag] = useState(false);
  const [filter, setFilter] = useState<"all" | "attention">("all");
  const [confirm, setConfirm] = useState<Doc | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (files: File[]) => {
      if (!files.length) return;
      setUploading(true);
      try {
        const res = await api.upload(files);
        setMessages(
          res.results.map((r) =>
            r.ok ? { tone: "good" as const, text: `${r.document!.filename} queued for processing` } : { tone: "bad" as const, text: `${r.filename}: ${r.error}` },
          ),
        );
        await docs.reload();
      } catch (e) {
        setMessages([{ tone: "bad", text: (e as Error).message }]);
      } finally {
        setUploading(false);
      }
    },
    [docs],
  );

  const remove = async (d: Doc) => {
    setConfirm(null);
    try {
      await api.del(`/api/documents/${d.id}`);
      setMessages([{ tone: "good", text: `${d.filename} removed from the knowledge base (chunks, vectors, graph edges and facts).` }]);
      if (openId === d.id) go("library");
      docs.reload();
    } catch (e) {
      setMessages([{ tone: "bad", text: (e as Error).message }]);
    }
  };

  const retry = async (d: Doc) => {
    await api.post(`/api/documents/${d.id}/retry`);
    docs.reload();
  };

  const items = (docs.data?.items ?? []).filter((d) => filter === "all" || d.status === "failed" || d.status === "limited" || (d.ocr_confidence ?? 1) < 0.6);

  return (
    <div className="mx-auto max-w-[1280px] p-6 md:p-8">
      <PageHeader
        title="Documents"
        subtitle="PDF, DOCX, JPG and PNG. Scanned pages are read with OCR. Each file is indexed in a single transaction."
        actions={<Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "attention", label: "Needs attention" }]} />}
      />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          upload(Array.from(e.dataTransfer.files));
        }}
        onClick={() => inputRef.current?.click()}
        className={`mb-4 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition ${drag ? "border-brand bg-brand-soft" : "border-line bg-surface hover:border-brand/50"}`}
      >
        <UploadCloud size={26} className={drag ? "text-brand" : "text-ink-3"} />
        <div className="text-sm font-medium">{uploading ? "Uploading…" : "Drop files here or click to upload"}</div>
        <div className="text-xs text-ink-3">PDF · DOCX · JPG · PNG · up to 25 MB each · duplicates are detected by content hash</div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.png,.jpg,.jpeg,.txt,.md,.csv"
          className="hidden"
          onChange={(e) => {
            upload(Array.from(e.target.files ?? []));
            e.target.value = "";
          }}
        />
      </div>

      {messages.length > 0 && (
        <div className="mb-4 space-y-1.5">
          {messages.map((m, i) => (
            <div key={i} className={`rounded-lg px-3 py-2 text-sm ${m.tone === "good" ? "bg-good-soft text-good" : "bg-bad-soft text-bad"}`}>{m.text}</div>
          ))}
        </div>
      )}

      {docs.error && <ErrorBox message={docs.error} onRetry={docs.reload} />}

      <div className="card overflow-hidden">
        {docs.loading && !docs.data ? (
          <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-10" />)}</div>
        ) : items.length === 0 ? (
          <Empty icon={<FileText size={22} />} title={filter === "all" ? "No documents yet" : "Nothing needs attention"}>
            {filter === "all" ? "Upload the synthetic samples from samples/docs to try every feature." : "All documents were processed successfully."}
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-ink-3">
                  <th className="px-4 py-2.5 font-medium">Document</th>
                  <th className="px-3 py-2.5 font-medium">Type</th>
                  <th className="px-3 py-2.5 font-medium">Company · period</th>
                  <th className="px-3 py-2.5 font-medium">Pages</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-3 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {items.map((d) => (
                  <tr key={d.id} className="group hover:bg-sunken/60">
                    <td className="px-4 py-3">
                      <button className="flex items-center gap-2.5 text-left" onClick={() => go("library", { doc: d.id })} disabled={d.status === "queued" || d.status === "processing"}>
                        <FileIcon ext={d.ext} />
                        <div className="min-w-0">
                          <div className="max-w-[340px] truncate font-medium group-hover:text-brand">{d.filename}</div>
                          <div className="text-xs text-ink-3">{bytes(d.size)} · {ago(d.created_at)}{d.processing_ms ? ` · ${(d.processing_ms / 1000).toFixed(1)}s` : ""}</div>
                        </div>
                      </button>
                    </td>
                    <td className="px-3 py-3 text-ink-2">{d.doc_type ? DOC_TYPE_LABEL[d.doc_type] ?? d.doc_type : "–"}</td>
                    <td className="px-3 py-3 text-ink-2">
                      <div className="max-w-[220px] truncate">{d.company ?? "–"}</div>
                      <div className="text-xs text-ink-3">{d.period ?? ""}{d.currency && d.period ? ` · ${d.currency}` : ""}</div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5 text-ink-2">
                        {d.pages ?? "–"}
                        {d.ocr_pages > 0 && (
                          <Badge tone={(d.ocr_confidence ?? 1) < 0.6 ? "warn" : "info"} title={`${d.ocr_pages} page(s) read with OCR, lowest confidence ${Math.round((d.ocr_confidence ?? 0) * 100)}%`}>
                            <ScanText size={11} /> OCR {d.ocr_confidence != null ? `${Math.round(d.ocr_confidence * 100)}%` : ""}
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <StatusPill status={d.status} stage={d.stage} error={d.error} />
                      {d.status === "failed" && <div className="mt-1 max-w-[240px] text-xs text-bad">{d.error}</div>}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex justify-end gap-1 opacity-70 group-hover:opacity-100">
                        {(d.status === "failed" || d.status === "limited") && (
                          <button className="rounded-md p-1.5 hover:bg-surface" title="Retry processing" onClick={() => retry(d)}><RotateCcw size={15} /></button>
                        )}
                        <button className="rounded-md p-1.5 text-ink-3 hover:bg-bad-soft hover:text-bad" title="Remove from knowledge base" onClick={() => setConfirm(d)}><Trash2 size={15} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {confirm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/30 p-4" onClick={() => setConfirm(null)}>
          <div className="card w-full max-w-md p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="font-semibold">Remove “{confirm.filename}”?</div>
            <p className="mt-2 text-sm text-ink-2">Its chunks, vectors, extracted figures and graph connections are deleted in one transaction. Anomalies that depended on it disappear automatically.</p>
            <div className="mt-5 flex justify-end gap-2">
              <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
              <button className="inline-flex items-center gap-1.5 rounded-lg bg-bad px-3 py-1.5 text-sm font-medium text-white" onClick={() => remove(confirm)}><Trash2 size={15} /> Remove</button>
            </div>
          </div>
        </div>
      )}

      <DocDrawer id={openId} onClose={() => go("library")} />
    </div>
  );
}

function DocDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const detail = useApi<DocDetail>(id ? `/api/documents/${id}` : null);
  const [tab, setTab] = useState<"facts" | "text" | "chunks">("facts");
  const d = detail.data;
  return (
    <Drawer open={!!id} onClose={onClose} width={720} title={d ? <span className="flex items-center gap-2"><FileIcon ext={d.document.ext} /> <span className="truncate">{d.document.filename}</span></span> : "Document"}>
      {detail.error && <ErrorBox message={detail.error} />}
      {!d ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-16" />)}</div>
      ) : (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={d.document.status} error={d.document.error} />
            {d.document.doc_type && <Badge tone="brand">{DOC_TYPE_LABEL[d.document.doc_type] ?? d.document.doc_type}</Badge>}
            {d.document.period && <Badge>{d.document.period}</Badge>}
            {d.document.currency && <Badge>{d.document.currency}</Badge>}
            <div className="flex-1" />
            <a className="btn" href={`/api/documents/${d.document.id}/file`} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Original</a>
            <button className="btn" onClick={() => go("ask", { scope: d.document.id })}><MessageSquarePlus size={14} /> Ask about it</button>
          </div>
          {d.document.summary && <p className="rounded-lg bg-sunken px-4 py-3 text-sm leading-relaxed">{d.document.summary}</p>}
          {d.document.error && d.document.status === "limited" && <div className="rounded-lg bg-warn-soft px-3 py-2 text-xs text-warn">{d.document.error}</div>}
          {d.anomalies.length > 0 && (
            <div className="card overflow-hidden"><div className="border-b border-line px-4 py-2 text-sm font-semibold text-bad">Anomalies involving this document</div><AnomalyList items={d.anomalies} compact /></div>
          )}
          <Segmented value={tab} onChange={setTab} options={[{ value: "facts", label: "Extracted data" }, { value: "text", label: `Pages (${d.pages.length})` }, { value: "chunks", label: `Chunks (${d.chunks.length})` }]} />

          {tab === "facts" && (
            <div className="space-y-5">
              {d.metrics.length > 0 && (
                <div>
                  <div className="label mb-2">Financial line items</div>
                  <table className="w-full text-sm">
                    <tbody className="divide-y divide-line">
                      {d.metrics.map((m) => (
                        <tr key={m.id}>
                          <td className="py-1.5 pr-2">{metricTitle(m.name)}<div className="text-[11px] text-ink-3">“{m.excerpt}” · p.{m.page}</div></td>
                          <td className="tabular py-1.5 text-right font-medium">{money(m.value, m.currency)}</td>
                          <td className="py-1.5 pl-2 text-right"><Badge tone={m.source === "rules" ? "neutral" : "info"} title={m.source === "rules" ? "Parsed by deterministic rules" : "Proposed by the LLM and verified against the text"}>{m.source === "rules" ? "rule" : "LLM ✓"}</Badge></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {d.invoices.map((inv) => (
                <div key={inv.number}>
                  <div className="label mb-2">Invoice</div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-lg border border-line p-4 text-sm">
                    {([["Number", inv.number], ["Vendor", inv.vendor], ["Customer", inv.customer], ["Issued", inv.issue_date], ["Due", inv.due_date], ["Subtotal", money(inv.subtotal, inv.currency)], ["Tax", money(inv.tax, inv.currency)], ["Total", money(inv.total, inv.currency)]] as const).map(([k, v]) => (
                      <div key={k}><div className="text-[11px] text-ink-3">{k}</div><div className="font-medium">{v ?? "–"}</div></div>
                    ))}
                  </div>
                </div>
              ))}
              {d.transactions.length > 0 && (
                <div>
                  <div className="label mb-2">Transactions ({d.transactions.length})</div>
                  <table className="w-full text-sm">
                    <tbody className="divide-y divide-line">
                      {d.transactions.map((t) => (
                        <tr key={t.id}>
                          <td className="tabular py-1.5 pr-3 text-ink-3">{t.date}</td>
                          <td className="py-1.5">{t.counterparty}{t.category && <span className="ml-1.5 text-[11px] text-ink-3">{t.category}</span>}</td>
                          <td className={`tabular py-1.5 text-right font-medium ${t.direction === "debit" ? "" : "text-good"}`}>{t.direction === "debit" ? "−" : "+"}{money(t.amount)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {d.entities.length > 0 && (
                <div>
                  <div className="label mb-2">Entities in the knowledge graph</div>
                  <div className="flex flex-wrap gap-1.5">
                    {d.entities.map((e) => (
                      <button key={e.id} onClick={() => go("graph", { entity: e.name })} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-sunken"><span className="text-ink-3">{e.type} ·</span> {e.name}</button>
                    ))}
                  </div>
                </div>
              )}
              {!d.metrics.length && !d.invoices.length && !d.transactions.length && <div className="text-sm text-ink-3">No structured financial figures in this document; it is still searchable in Wiki Ask.</div>}
            </div>
          )}
          {tab === "text" &&
            d.pages.map((p) => (
              <div key={p.page}>
                <div className="flex items-center gap-2 text-sm font-medium">
                  Page {p.page}
                  <Badge tone={p.method === "ocr" ? "info" : "neutral"}>{p.method === "ocr" ? `OCR · ${Math.round((p.confidence ?? 0) * 100)}% confidence` : p.method === "docx" ? "DOCX text" : "Text layer"}</Badge>
                </div>
                <Excerpt text={p.text} />
              </div>
            ))}
          {tab === "chunks" &&
            d.chunks.map((c) => (
              <div key={c.id} className="rounded-lg border border-line p-3">
                <div className="font-mono text-[11px] text-brand">{c.header}</div>
                <Excerpt text={c.text} />
              </div>
            ))}
        </div>
      )}
    </Drawer>
  );
}
