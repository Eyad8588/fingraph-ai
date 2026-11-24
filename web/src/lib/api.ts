// Typed client for the FastAPI backend.

export type DocStatus = "queued" | "processing" | "ready" | "limited" | "failed";

export interface Doc {
  id: string;
  filename: string;
  ext: string;
  size: number;
  status: DocStatus;
  stage: string | null;
  error: string | null;
  pages: number | null;
  ocr_pages: number;
  ocr_confidence: number | null;
  chars: number | null;
  doc_type: string | null;
  company: string | null;
  period: string | null;
  currency: string | null;
  summary: string | null;
  created_at: number;
  processed_at: number | null;
  processing_ms: number | null;
}

export interface Evidence {
  doc_id: string;
  filename: string | null;
  page: number | null;
  excerpt: string | null;
}

export interface Anomaly {
  id: string;
  rule: string;
  severity: "high" | "medium" | "low";
  title: string;
  detail: string;
  evidence: Evidence[];
  entities: string[];
  doc_ids: string[];
}

export interface Citation {
  n: number;
  used: boolean;
  chunk_id: number;
  doc_id: string;
  filename: string;
  page: number;
  section: string | null;
  method: string | null;
  excerpt: string;
  similarity: number | null;
  rerank: number | null;
  found_by: string[];
}

export interface RouteInfo {
  route: "doc" | "metric" | "both";
  metrics: string[];
  companies: string[];
  periods: string[];
  calculations: string[];
  missing: string[];
  notes: string[];
  facts: { label: string; value: number; display: string; filename: string | null; page: number | null; excerpt: string | null }[];
}

export interface AnswerMeta {
  standalone: string | null;
  route: RouteInfo;
  retrieval: { top_similarity: number; top_rerank: number | null; reranked: boolean; gate: string; timings_ms: Record<string, number> };
  model: string;
  scope: string[];
  citations: Citation[];
  abstained: boolean;
  unverified: boolean;
  problems?: string[];
  calculations: string[];
  latency_ms: number;
  model_error?: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  content: string;
  meta: Partial<AnswerMeta>;
  created_at?: number;
  pending?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  scope: string;
  created_at: number;
  updated_at: number;
  messages?: number;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, headers: {} };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError(0, "Cannot reach the FinGraph server. Is it running?");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T,>(url: string) => request<T>("GET", url),
  post: <T,>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  patch: <T,>(url: string, body: unknown) => request<T>("PATCH", url, body),
  del: <T,>(url: string) => request<T>("DELETE", url),
  upload: (files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return request<{ results: { ok: boolean; filename?: string; error?: string; document?: Doc }[] }>("POST", "/api/documents", fd);
  },
};
