# Demo script (about 6 minutes)

Before the call: `ollama serve` is running, the app is started (`./run.sh`), the 10 sample documents are loaded,
and the browser is on http://127.0.0.1:8720.

## 1. Upload and processing (1 min) · Documents
1. Open **Documents**. Remove `atlas_invoice_INV-1042_phone_scan.jpg` (confirm dialog), then drag it back in.
2. Point at the live stages: *Reading → OCR → Extracting → Chunking → Embedding → Ready*.
3. Say: *"Upload returns immediately; one background worker processes files. Everything is built in memory and
   committed in a single SQLite transaction, so a crash never leaves half a document in the index."*
4. Drag the same file again → "This exact file is already uploaded" (sha256).
5. Open the **bank statement**: page 1 is a text layer, page 2 is a scan (**OCR 100%** badge). Show the extracted
   transactions and the two anomalies on this document.

## 2. Dashboard (1 min)
- KPI cards: Nova revenue **−10.4%**, net loss, margins, current ratio from the balance sheet.
- **Key findings**: "AI summary · numbers verified". The LLM only narrates a fact sheet built by code; if it
  writes a number that is not in the fact sheet, the rule-based bullets are shown instead.
- **Anomalies**: open "Invoice CC-311 total does not add up" → evidence with the exact source line.
- Chart: Revenue by period shows the currency warning (USD vs SAR): no silent conversion.

## 3. Knowledge graph (1 min)
- Click **Atlas Logistics LLC**: red ring (duplicate invoice + duplicate payment), connections grouped by relation,
  each with its supporting document and excerpt. Payments are aggregated into one edge: "paid · 2× · 46,000".
- Toggle **Show documents**; double-click a node to expand neighbours.

## 4. Wiki Ask (2 min)
1. "How did Nova Retail's revenue change from Q1 to Q2 2026?" → **Calculation box** computed by Python:
   `(1,120,000 − 1,250,000) / 1,250,000 = −10.4%`, cited from both statements.
2. Follow-up: "And net income?" → "🔎 Searched for: …" shows the rewritten standalone question.
3. "Did we pay Atlas Logistics twice for invoice INV-1042?" → multi-document answer (bank statement page 2 via OCR
   + invoice + board memo).
4. "Compare revenue of Nova and Helix in Q2 2026" → refuses to compare SAR and USD amounts, suggests margins.
5. "What was Nova Retail's revenue in Q4 2026?" → scope check: only Q1–Q2 2026 exist.
6. "Who is the CEO of Tesla?" → refused in about 0.1 s **without calling the LLM** (retrieval gate).
7. Optional: Arabic question «ما هو صافي دخل شركة نوفا في الربع الثاني؟» → Arabic answer with citations.

## 5. Engineering pages (1 min)
- **RAG playground**: vector vs BM25 vs fused/reranked candidates, gate decision, per-stage timings.
- **Evaluation**: golden-set results (hit@k, MRR, refusals), answer accuracy, live latency p50/p95.
- **Settings**: switch qwen3.5 4b → 9b (or a cloud model) at runtime; ask the same question again and compare
  the model tag and latency on the answer.

## Likely questions and short answers
- **Why SQLite?** Atomic ingest/delete across vectors, keyword index, graph and facts; zero setup. The repository
  layer (`fingraph/store.py`) is the only place to change for Postgres + pgvector. Measured: KNN ~1 ms per 1k
  chunks (100 ms at 100k), so beyond roughly 200–500k chunks I'd switch to an HNSW index.
- **How do you stop hallucinations?** Four layers: gate before the LLM, scope check, partial answers, post-check
  of citations, numbers and dates (retry once, else "unverified" banner).
- **Why not let the LLM extract numbers?** It can, but only fills gaps and only with numbers literally present in
  the text. Rules extract first; every number keeps its page and source line.
- **What breaks first at scale?** The LLM (about 10 answers/min on a laptop), then brute-force vector search,
  then the single SQLite writer. Fixes: vLLM/cloud with batching, pgvector HNSW, a job queue with many workers.
- **Enterprise next steps:** SSO + row-level access control per document, audit log, PII redaction, layout-aware
  table extraction, multilingual reranker, LLM-judge strict mode, observability (OpenTelemetry traces per stage).
