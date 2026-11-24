import cytoscape, { type Core, type ElementDefinition } from "cytoscape";
import fcose from "cytoscape-fcose";
import { AlertTriangle, ChevronDown, ChevronRight, FileText, Maximize2, Network, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Empty, ErrorBox, Excerpt, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { go, useApi } from "../lib/hooks";
import { DOC_TYPE_LABEL, metricTitle, metricValue, money } from "../lib/format";

cytoscape.use(fcose);

interface GNode {
  id: string;
  entity_id?: number;
  doc_id?: string;
  label: string;
  type: string;
  degree: number;
  docs: number;
  anomalies: { id: string; title: string; severity: string }[];
}
interface GEdge {
  id: string;
  source: string;
  target: string;
  relation: string;
  label: string;
  count: number;
  total: number | null;
}
interface GraphResp {
  nodes: GNode[];
  edges: GEdge[];
  total_entities: number;
  truncated: boolean;
  types: string[];
}
interface NodeDetail {
  entity: { id: number; name: string; type: string; kind: string };
  relations: {
    relation: string;
    direction: "in" | "out";
    other_id: number;
    other: string;
    other_type: string;
    count: number;
    total: number;
    evidence: { doc_id: string; filename: string; page: number | null; excerpt: string; amount: number | null; date: string | null }[];
  }[];
  documents: { doc_id: string; page: number | null; excerpt: string; filename: string; doc_type: string; period: string | null }[];
  metrics: { period: string; currency: string; values: Record<string, number> }[];
  anomalies: { id: string; title: string; severity: string }[];
}

const TYPE_STYLE: Record<string, { color: string; shape: string; label: string }> = {
  company: { color: "#0f766e", shape: "ellipse", label: "Company" },
  vendor: { color: "#3659c9", shape: "ellipse", label: "Vendor" },
  customer: { color: "#15803d", shape: "ellipse", label: "Customer" },
  organization: { color: "#64748b", shape: "ellipse", label: "Organization" },
  bank: { color: "#7c3aed", shape: "diamond", label: "Bank" },
  invoice: { color: "#b45309", shape: "round-rectangle", label: "Invoice" },
  period: { color: "#475569", shape: "hexagon", label: "Period" },
  person: { color: "#db2777", shape: "ellipse", label: "Person" },
  contract: { color: "#0891b2", shape: "tag", label: "Contract" },
  product: { color: "#a16207", shape: "round-triangle", label: "Product" },
  document: { color: "#94a3b8", shape: "round-rectangle", label: "Document" },
};

function css(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export default function GraphPage({ focus }: { focus: string | null }) {
  const [includeDocs, setIncludeDocs] = useState(false);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const g = useApi<GraphResp>(`/api/graph?include_docs=${includeDocs}`);
  const [selected, setSelected] = useState<GNode | null>(null);
  const cyRef = useRef<Core | null>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  const elements = useMemo<ElementDefinition[]>(() => {
    if (!g.data) return [];
    const nodes = g.data.nodes.filter((n) => !hidden.has(n.type));
    const ids = new Set(nodes.map((n) => n.id));
    return [
      ...nodes.map((n) => ({
        data: { ...n, color: (TYPE_STYLE[n.type] ?? TYPE_STYLE.organization).color, shape: (TYPE_STYLE[n.type] ?? TYPE_STYLE.organization).shape, size: n.type === "document" ? 18 : 22 + Math.min(n.degree, 12) * 2.2, flagged: n.anomalies.length > 0 ? 1 : 0 },
      })),
      ...g.data.edges.filter((e) => ids.has(e.source) && ids.has(e.target)).map((e) => ({ data: { ...e } })),
    ];
  }, [g.data, hidden]);

  useEffect(() => {
    if (!boxRef.current || !elements.length) return;
    const ink2 = css("--ink-2");
    const line = css("--line");
    const surface = css("--surface");
    const cy = cytoscape({
      container: boxRef.current,
      elements,
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            "background-color": "data(color)",
            shape: "data(shape)" as never,
            width: "data(size)",
            height: "data(size)",
            label: "data(label)",
            "font-size": 10.5,
            "font-family": "Inter, system-ui, sans-serif",
            color: ink2,
            "text-valign": "bottom",
            "text-margin-y": 5,
            "text-wrap": "ellipsis",
            "text-max-width": "120px",
            "text-background-color": surface,
            "text-background-opacity": 0.85,
            "text-background-padding": "2px",
            "border-width": 2,
            "border-color": surface,
          },
        },
        { selector: "node[flagged = 1]", style: { "border-width": 4, "border-color": "#dc2626", "border-style": "double" } },
        { selector: "node:selected", style: { "border-width": 4, "border-color": css("--brand-ink") || "#0f766e", "font-weight": 600, color: css("--ink") } },
        {
          selector: "edge",
          style: {
            width: 1.4,
            "line-color": line,
            "target-arrow-color": line,
            "target-arrow-shape": "triangle",
            "arrow-scale": 0.8,
            "curve-style": "bezier",
            label: "data(label)",
            "font-size": 8.5,
            color: css("--ink-3"),
            "text-rotation": "autorotate",
            "text-background-color": surface,
            "text-background-opacity": 0.9,
            "text-background-padding": "1px",
          },
        },
        { selector: "edge[relation = 'paid']", style: { "line-color": "#3659c9", "target-arrow-color": "#3659c9", width: 2 } },
        { selector: "edge[relation = 'mentioned_in']", style: { "line-style": "dashed", label: "", width: 1 } },
        { selector: ".faded", style: { opacity: 0.15 } },
        { selector: ".hl", style: { opacity: 1 } },
      ],
      layout: { name: "fcose", animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 110, padding: 30 } as never,
    });
    cy.on("tap", "node", (evt) => {
      const n = evt.target;
      setSelected(n.data() as GNode);
      cy.elements().addClass("faded").removeClass("hl");
      n.closedNeighborhood().removeClass("faded").addClass("hl");
    });
    cy.on("tap", (evt) => {
      if (evt.target === cy) {
        cy.elements().removeClass("faded hl");
        setSelected(null);
      }
    });
    cy.on("dbltap", "node", async (evt) => {
      const n = evt.target.data() as GNode;
      if (!n.entity_id) return;
      const nb = await api.get<{ nodes: GNode[]; edges: GEdge[] }>(`/api/graph/node/${n.entity_id}/neighbours`);
      const add: ElementDefinition[] = [];
      nb.nodes.forEach((x) => {
        if (!cy.getElementById(x.id).length) add.push({ data: { ...x, color: (TYPE_STYLE[x.type] ?? TYPE_STYLE.organization).color, shape: (TYPE_STYLE[x.type] ?? TYPE_STYLE.organization).shape, size: 22, flagged: x.anomalies.length ? 1 : 0 } });
      });
      nb.edges.forEach((e) => !cy.getElementById(e.id).length && add.push({ data: e }));
      if (add.length) {
        cy.add(add);
        cy.layout({ name: "fcose", animate: true, randomize: false } as never).run();
      }
    });
    cyRef.current = cy;
    return () => cy.destroy();
  }, [elements]);

  // focus from ?entity=Name (links from documents, anomalies, answers)
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !focus) return;
    const n = cy.nodes().filter((x) => (x.data("label") as string).toLowerCase() === focus.toLowerCase());
    if (n.length) {
      n.select();
      n.emit("tap");
      cy.animate({ center: { eles: n }, zoom: 1.4 }, { duration: 300 });
    }
  }, [focus, elements]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const q = query.trim().toLowerCase();
    cy.nodes().removeClass("faded");
    if (q) cy.nodes().filter((n) => !(n.data("label") as string).toLowerCase().includes(q)).addClass("faded");
  }, [query, elements]);

  const types = g.data ? [...new Set(g.data.nodes.map((n) => n.type))] : [];

  return (
    <div className="flex h-full min-h-0">
      <div className="relative flex min-w-0 flex-1 flex-col">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface px-4 py-3">
          <div className="mr-2">
            <div className="font-semibold">Knowledge graph</div>
            <div className="text-xs text-ink-3">{g.data ? `${g.data.nodes.length} nodes · ${g.data.edges.length} connections${g.data.truncated ? ` · top ${g.data.nodes.length} of ${g.data.total_entities}` : ""}` : "Loading…"}</div>
          </div>
          <div className="relative w-56">
            <Search size={14} className="absolute left-2.5 top-2.5 text-ink-3" />
            <input className="input py-1.5 pl-8" placeholder="Find entity…" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-line px-2.5 py-1.5 text-xs">
            <input type="checkbox" checked={includeDocs} onChange={(e) => setIncludeDocs(e.target.checked)} className="accent-[var(--brand)]" /> Show documents
          </label>
          <button className="btn py-1" onClick={() => cyRef.current?.fit(undefined, 30)}><Maximize2 size={14} /> Fit</button>
          <div className="flex flex-wrap gap-1.5">
            {types.map((t) => {
              const st = TYPE_STYLE[t] ?? TYPE_STYLE.organization;
              const off = hidden.has(t);
              return (
                <button
                  key={t}
                  onClick={() => setHidden((h) => { const n = new Set(h); if (n.has(t)) n.delete(t); else n.add(t); return n; })}
                  className={`flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] transition ${off ? "border-line text-ink-3 line-through" : "border-line bg-surface text-ink-2"}`}
                >
                  <span className="h-2 w-2 rounded-full" style={{ background: st.color, opacity: off ? 0.3 : 1 }} /> {st.label}
                </button>
              );
            })}
          </div>
        </div>
        {g.error && <div className="p-6"><ErrorBox message={g.error} onRetry={g.reload} /></div>}
        {g.data && g.data.nodes.length === 0 ? (
          <Empty icon={<Network size={22} />} title="The graph is empty">Upload documents: companies, vendors, invoices, payments and periods are extracted automatically.</Empty>
        ) : (
          <div ref={boxRef} className="min-h-0 flex-1" style={{ background: "radial-gradient(circle at 1px 1px, var(--line) 1px, transparent 0) 0 0 / 22px 22px" }} />
        )}
        <div className="pointer-events-none absolute bottom-3 left-4 rounded-md bg-surface/90 px-2 py-1 text-[11px] text-ink-3">
          Click a node for details · double-click to expand neighbours · <span className="text-bad">red ring</span> = involved in an anomaly
        </div>
      </div>
      <aside className="scroll-thin hidden w-[400px] shrink-0 overflow-y-auto border-l border-line bg-surface lg:block">
        {selected ? <NodePanel node={selected} /> : <div className="p-6 text-sm text-ink-3">Select a node to see its connections and the documents that support them.</div>}
      </aside>
    </div>
  );
}

function NodePanel({ node }: { node: GNode }) {
  const detail = useApi<NodeDetail>(node.entity_id ? `/api/graph/node/${node.entity_id}` : null);
  const [open, setOpen] = useState<number | null>(0);
  const st = TYPE_STYLE[node.type] ?? TYPE_STYLE.organization;
  if (node.type === "document")
    return (
      <div className="space-y-3 p-5">
        <Badge>Document</Badge>
        <div className="font-semibold">{node.label}</div>
        <button className="btn" onClick={() => go("library", { doc: node.doc_id! })}><FileText size={14} /> Open document</button>
      </div>
    );
  const d = detail.data;
  return (
    <div className="space-y-5 p-5">
      <div>
        <div className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: st.color }} /><span className="text-xs text-ink-3">{st.label}</span></div>
        <div className="mt-1 text-lg font-semibold">{node.label}</div>
      </div>
      {node.anomalies.length > 0 && (
        <div className="space-y-1.5 rounded-lg bg-bad-soft p-3">
          {node.anomalies.map((a) => <div key={a.id} className="flex gap-2 text-xs text-bad"><AlertTriangle size={13} className="mt-0.5 shrink-0" /> {a.title}</div>)}
        </div>
      )}
      {!d ? <Spinner label="Loading connections…" /> : (
        <>
          {d.metrics.length > 0 && (
            <div>
              <div className="label mb-2">Reported figures</div>
              <table className="w-full text-xs">
                <thead><tr className="text-ink-3"><th className="py-1 text-left font-medium">Metric</th>{d.metrics.map((m) => <th key={m.period} className="py-1 text-right font-medium">{m.period}</th>)}</tr></thead>
                <tbody className="divide-y divide-line">
                  {["revenue", "gross_profit", "net_income", "gross_margin", "net_margin", "total_assets"].filter((k) => d.metrics.some((m) => k in m.values)).map((k) => (
                    <tr key={k}><td className="py-1">{metricTitle(k)}</td>{d.metrics.map((m) => <td key={m.period} className="tabular py-1 text-right">{metricValue(k, m.values[k], null, true)}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div>
            <div className="label mb-2">Connections ({d.relations.length})</div>
            <div className="space-y-1.5">
              {d.relations.map((r, i) => (
                <div key={i} className="rounded-lg border border-line">
                  <button className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm" onClick={() => setOpen(open === i ? null : i)}>
                    {open === i ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    <span className="text-ink-3">{r.direction === "out" ? "→" : "←"} {r.relation.replace(/_/g, " ")}</span>
                    <span className="truncate font-medium">{r.other}</span>
                    {r.count > 1 && <Badge>{r.count}×</Badge>}
                    {r.total > 0 && <span className="tabular ml-auto text-xs text-ink-2">{money(r.total)}</span>}
                  </button>
                  {open === i && (
                    <div className="space-y-2 border-t border-line px-3 py-2">
                      {r.evidence.map((e, j) => (
                        <div key={j}>
                          <button className="text-xs font-medium text-brand hover:underline" onClick={() => go("library", { doc: e.doc_id })}>{e.filename}{e.page ? ` · p.${e.page}` : ""}{e.date ? ` · ${e.date}` : ""}</button>
                          <Excerpt text={e.excerpt} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
          <div>
            <div className="label mb-2">Supporting documents ({d.documents.length})</div>
            <div className="space-y-2">
              {d.documents.map((doc) => (
                <div key={doc.doc_id} className="rounded-lg border border-line p-3">
                  <button className="flex items-center gap-1.5 text-sm font-medium text-brand hover:underline" onClick={() => go("library", { doc: doc.doc_id })}><FileText size={13} /> {doc.filename}</button>
                  <div className="text-[11px] text-ink-3">{DOC_TYPE_LABEL[doc.doc_type] ?? doc.doc_type}{doc.period ? ` · ${doc.period}` : ""}{doc.page ? ` · page ${doc.page}` : ""}</div>
                  {doc.excerpt && <Excerpt text={doc.excerpt} highlight={node.label} />}
                </div>
              ))}
            </div>
          </div>
          <button className="btn w-full justify-center" onClick={() => go("ask", { q: `What do the documents say about ${node.label}?` })}>Ask about {node.label}</button>
        </>
      )}
    </div>
  );
}
