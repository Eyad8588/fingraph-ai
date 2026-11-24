# FinGraph AI · Architecture

```mermaid
flowchart LR
  subgraph UI["React + TypeScript UI (Vite build, served by FastAPI)"]
    D[Dashboard] --- L[Documents] --- G[Knowledge graph] --- W[Wiki Ask] --- A[Analysis] --- P[RAG playground] --- E[Evaluation]
  end

  UI -- REST /api --> API[FastAPI]

  subgraph ING["Ingestion (background worker, one commit per document)"]
    direction TB
    U[Upload<br/>sha256 dedupe, size/type limits] --> PR[Parse<br/>PDF text layer · DOCX paragraphs+tables]
    PR -->|page has no text layer / image| OCR[OCR<br/>Apple Vision + deskew<br/>LLM-vision fallback]
    PR --> EX
    OCR --> EX[Extract<br/>rules: line items, invoices, transactions<br/>LLM: type, entities, relations, summary<br/>grounding check on every LLM number/name]
    EX --> CH[Chunk<br/>structure-aware, tables kept whole<br/>context header: company · type · period · page]
    CH --> EM[Embed<br/>qwen3-embedding:0.6b]
    EM --> TX[(ONE SQLite transaction)]
  end

  API --> ING

  subgraph DB["One SQLite file"]
    direction TB
    T1[(documents · pages · chunks)]
    T2[(FTS5 BM25 index)]
    T3[(sqlite-vec vectors)]
    T4[(entities · mentions · edges)]
    T5[(metrics · invoices · transactions)]
    T6[(conversations · messages · query_log · eval_runs)]
  end
  TX --> DB

  subgraph ASK["Wiki Ask (per question)"]
    direction TB
    Q[Question] --> RW[Follow-up rewrite<br/>only if it looks like a follow-up]
    RW --> RT[Router<br/>doc / metric / both<br/>scope check + Python calculator]
    RT --> HS[Hybrid search<br/>vector + BM25 → RRF → per-doc cap<br/>→ MiniLM cross-encoder rerank]
    HS --> GATE{Gate<br/>enough evidence?}
    GATE -- no --> NF[“Not in your documents”<br/>no LLM call]
    GATE -- yes --> LLM[Grounded generation<br/>qwen3.5:4b local · or cloud]
    LLM --> PC[Post-check<br/>citations exist · every number in a source or calculation<br/>→ retry once → else flag unverified]
  end
  API --> ASK
  ASK <--> DB

  subgraph FIN["Financial intelligence (read time)"]
    M[Metrics + ratios] --> AN[Anomaly rules<br/>duplicates · arithmetic · swings · suspicious payments]
    AN --> SUM[Key findings<br/>LLM narrates fact sheet; numbers verified]
  end
  API --> FIN
  FIN <--> DB
```

## Why these pieces

| Decision | Choice | Reason | Enterprise path |
|---|---|---|---|
| Storage | One SQLite file: tables + FTS5 + sqlite-vec | A document's chunks, vectors, graph edges and facts are written and deleted in **one transaction**; zero setup | Same repository interface on Postgres + pgvector (HNSW) + full-text search |
| Numbers | Rules first, LLM proposes, code verifies | A 4B model can misread numbers; every figure keeps its page and source line | Layout-aware parsers (e.g. Textract / Document Intelligence) behind the same extractor |
| Chunking | Structure-aware + context header | “Revenue 1,120,000” is meaningless without company and period | Same |
| Calculations | Router + Python calculator | LLMs are unreliable at arithmetic; formula shown to the user | Tool-calling agent with a stronger model |
| Hallucination control | Gate before LLM, scope check, partial answers, post-check | Refusal decided in code; numbers verified after generation | Optional LLM-judge “strict mode” |
| Ingestion | Background worker, stage in memory, commit once | No half-indexed documents; crash recovery re-queues | Job queue (Celery/Temporal) with many workers |
| OCR | Apple Vision with deskew, per page | Offline (data stays local), 0.3 s/page | Cloud OCR when the data policy allows |
| Models | Ollama local by default, OpenAI-compatible switch at runtime | Confidential data stays on the machine | vLLM/TGI GPU serving with batching |
| Anomalies | Deterministic rules, computed at read time | Explainable to an auditor; never stale after a delete | Statistical / ML detectors once there is volume |
