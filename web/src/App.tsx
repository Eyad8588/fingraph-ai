import { BarChart3, Bug, FileStack, FlaskConical, LayoutDashboard, MessagesSquare, Network, Settings as SettingsIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useApi, useHashRoute } from "./lib/hooks";
import Analysis from "./pages/Analysis";
import Dashboard from "./pages/Dashboard";
import Evaluation from "./pages/Evaluation";
import GraphPage from "./pages/Graph";
import Library from "./pages/Library";
import Playground from "./pages/Playground";
import Settings from "./pages/Settings";
import WikiAsk from "./pages/WikiAsk";

interface Health {
  ok: boolean;
  documents: number;
  worker_busy: boolean;
  queue: number;
  models: { ollama_reachable: boolean; current: string; embedder: string; reranker: string | null };
}

const NAV: { id: string; label: string; icon: ReactNode; group?: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: <LayoutDashboard size={17} /> },
  { id: "library", label: "Documents", icon: <FileStack size={17} /> },
  { id: "graph", label: "Knowledge graph", icon: <Network size={17} /> },
  { id: "ask", label: "Wiki Ask", icon: <MessagesSquare size={17} /> },
  { id: "analysis", label: "Analysis", icon: <BarChart3 size={17} /> },
  { id: "playground", label: "RAG playground", icon: <Bug size={17} />, group: "Engineering" },
  { id: "evaluation", label: "Evaluation", icon: <FlaskConical size={17} />, group: "Engineering" },
  { id: "settings", label: "Settings", icon: <SettingsIcon size={17} />, group: "Engineering" },
];

export default function App() {
  const route = useHashRoute();
  const health = useApi<Health>("/api/health", { pollMs: 5000 });
  const h = health.data;
  const page = route.page;

  let content: ReactNode;
  switch (page) {
    case "library":
      content = <Library openId={route.params.get("doc")} />;
      break;
    case "graph":
      content = <GraphPage focus={route.params.get("entity")} />;
      break;
    case "ask":
      content = <WikiAsk convId={route.params.get("c")} />;
      break;
    case "analysis":
      content = <Analysis />;
      break;
    case "playground":
      content = <Playground initialQuery={route.params.get("q") ?? ""} />;
      break;
    case "evaluation":
      content = <Evaluation />;
      break;
    case "settings":
      content = <Settings />;
      break;
    default:
      content = <Dashboard />;
  }

  let lastGroup: string | undefined;
  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-surface md:flex">
        <div className="flex items-center gap-2.5 px-5 pb-6 pt-5">
          <div className="grid h-8 w-8 place-items-center rounded-lg bg-brand text-white">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round">
              <path d="M4 17l5-6 4 3 7-9" />
            </svg>
          </div>
          <div>
            <div className="text-[15px] font-semibold leading-tight">FinGraph AI</div>
            <div className="text-[11px] text-ink-3">Financial intelligence</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3">
          {NAV.map((n) => {
            const header = n.group && n.group !== lastGroup ? n.group : null;
            lastGroup = n.group;
            const active = page === n.id || (page === "" && n.id === "dashboard");
            return (
              <div key={n.id}>
                {header && <div className="label px-3 pb-1.5 pt-5">{header}</div>}
                <a
                  href={`#/${n.id}`}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${active ? "bg-brand-soft font-medium text-brand-ink" : "text-ink-2 hover:bg-sunken hover:text-ink"}`}
                >
                  {n.icon}
                  {n.label}
                </a>
              </div>
            );
          })}
        </nav>
        <div className="m-3 rounded-lg border border-line p-3 text-xs">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${!h ? "bg-ink-3" : h.models.ollama_reachable || h.models.current.startsWith("openai") ? "bg-good" : "bg-bad"}`} />
            <span className="font-medium">{!h ? "Connecting…" : h.models.ollama_reachable ? "Models online" : "Ollama offline"}</span>
          </div>
          {h && (
            <div className="mt-1.5 space-y-0.5 text-ink-3">
              <div className="truncate" title={h.models.current}>LLM: {h.models.current.replace("ollama:", "")}</div>
              <div className="truncate" title={h.models.embedder}>Embed: {h.models.embedder.replace("ollama:", "")}</div>
              {h.worker_busy && <div className="text-info">Processing {h.queue > 0 ? `· ${h.queue} queued` : "…"}</div>}
            </div>
          )}
          <div className="mt-2 border-t border-line pt-2 text-[10.5px] text-ink-3">Synthetic data only · runs locally</div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex gap-1 overflow-x-auto border-b border-line bg-surface px-3 py-2 md:hidden">
          {NAV.map((n) => (
            <a key={n.id} href={`#/${n.id}`} className={`flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs ${page === n.id ? "bg-brand-soft text-brand-ink" : "text-ink-2"}`}>
              {n.icon}
              {n.label}
            </a>
          ))}
        </div>
        <main className={`min-h-0 flex-1 ${page === "ask" || page === "graph" ? "" : "scroll-thin overflow-y-auto"}`}>{content}</main>
      </div>
    </div>
  );
}
