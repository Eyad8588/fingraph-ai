import { Cloud, Cpu, Lock } from "lucide-react";
import { useState } from "react";
import { Badge, ErrorBox, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { useApi } from "../lib/hooks";

interface SettingsResp {
  ollama_reachable: boolean;
  local: string[];
  cloud: string[];
  current: string;
  embedder: string;
  reranker: string | null;
  use_reranker: boolean;
  min_similarity: number;
  min_rerank: number;
  index_embedder: string | null;
  ocr: string;
}

export default function Settings() {
  const st = useApi<SettingsResp>("/api/settings");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async (body: Record<string, unknown>) => {
    setSaving(true);
    setError(null);
    try {
      st.setData(await api.post<SettingsResp>("/api/settings", body));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };
  const s = st.data;
  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      <PageHeader title="Settings" subtitle="Switch the answer model at runtime: local for confidentiality, cloud when the data policy allows it." />
      {(error || st.error) && <div className="mb-4"><ErrorBox message={(error || st.error)!} /></div>}
      {!s ? <div className="skeleton h-40" /> : (
        <div className="space-y-6">
          <section className="card p-5">
            <div className="mb-1 font-semibold">Answer model</div>
            <p className="mb-4 text-sm text-ink-2">Applies to the next question; no restart needed. Every answer shows which model produced it.</p>
            <div className="space-y-2">
              {[...s.local.map((m) => ({ m, cloud: false })), ...s.cloud.map((m) => ({ m, cloud: true }))].map(({ m, cloud }) => (
                <label key={m} className={`flex cursor-pointer items-center gap-3 rounded-lg border px-4 py-3 ${s.current === m ? "border-brand bg-brand-soft" : "border-line hover:bg-sunken"}`}>
                  <input type="radio" name="llm" className="accent-[var(--brand)]" checked={s.current === m} disabled={saving} onChange={() => save({ llm: m })} />
                  {cloud ? <Cloud size={16} className="text-info" /> : <Cpu size={16} className="text-brand" />}
                  <span className="font-medium">{m.replace(/^(ollama|openai):/, "")}</span>
                  <Badge tone={cloud ? "info" : "brand"}>{cloud ? "Cloud · OpenAI-compatible" : "Local · Ollama"}</Badge>
                </label>
              ))}
              {s.cloud.length === 0 && <div className="rounded-lg bg-sunken px-4 py-3 text-xs text-ink-2">Cloud models appear here when <code>OPENAI_API_KEY</code> (and optionally <code>OPENAI_BASE_URL</code>, <code>OPENAI_MODELS</code>) are set. Any OpenAI-compatible endpoint works: OpenAI, Azure, Groq, vLLM, LM Studio.</div>}
              {!s.ollama_reachable && <div className="rounded-lg bg-bad-soft px-4 py-3 text-xs text-bad">Ollama is not reachable at the configured URL.</div>}
            </div>
          </section>
          <section className="card p-5">
            <div className="mb-3 font-semibold">Retrieval</div>
            <label className="flex items-center justify-between gap-4 py-2">
              <div><div className="text-sm font-medium">Cross-encoder reranking</div><div className="text-xs text-ink-3">{s.reranker ?? "–"} · skipped automatically for Arabic questions</div></div>
              <input type="checkbox" className="h-4 w-4 accent-[var(--brand)]" checked={s.use_reranker} disabled={saving} onChange={(e) => save({ use_reranker: e.target.checked })} />
            </label>
            <div className="flex items-center justify-between border-t border-line py-3 text-sm">
              <div><div className="flex items-center gap-1.5 font-medium"><Lock size={13} /> Embedding model</div><div className="text-xs text-ink-3">Fixed per index: changing it would make stored vectors incompatible (re-index required).</div></div>
              <Badge>{s.index_embedder ?? s.embedder}</Badge>
            </div>
            <div className="flex items-center justify-between border-t border-line py-3 text-sm">
              <div><div className="font-medium">Answer gate thresholds</div><div className="text-xs text-ink-3">Calibrated on the golden set (Evaluation page). Env: FINGRAPH_MIN_SIM, FINGRAPH_MIN_RERANK.</div></div>
              <Badge>cosine {s.min_similarity} · rerank {s.min_rerank}</Badge>
            </div>
            <div className="flex items-center justify-between border-t border-line pt-3 text-sm">
              <div><div className="font-medium">OCR engine</div><div className="text-xs text-ink-3">auto = Apple Vision on macOS, LLM vision elsewhere.</div></div>
              <Badge>{s.ocr}</Badge>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
