"""FastAPI app: REST API under /api, and the built React app (web/dist) at /."""

from __future__ import annotations

import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .answer import WikiAsk
from .config import ROOT, Settings
from .evals import monitoring, run_answer_eval, run_retrieval_eval, save_run
from .finance import Finance
from .graph import Graph
from .ingest import DuplicateFile, Ingestor
from .models import ModelRegistry
from .reports import anomalies_csv, html_report, markdown_report, metrics_csv
from .retrieval import Retriever
from .router import Router
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class App:
    """Wires the components together (also used directly by tests and scripts)."""

    def __init__(self, s: Settings | None = None):
        self.s = s or Settings()
        self.s.ensure_dirs()
        self.store = Store(self.s.db_path)
        self.models = ModelRegistry(self.s)
        self.ingestor = Ingestor(self.s, self.store, self.models)
        self.retriever = Retriever(self.s, self.store, self.models)
        self.finance = Finance(self.store)
        self.router = Router(self.finance, self.store)
        self.ask = WikiAsk(self.s, self.store, self.models, self.retriever, self.router)
        self.graph = Graph(self.store, self.finance)


class AskBody(BaseModel):
    question: str
    doc_ids: list[str] | None = None


class ConvBody(BaseModel):
    title: str | None = None
    scope: list[str] | None = None


class PlaygroundBody(BaseModel):
    query: str
    mode: str = "hybrid"
    rerank: bool = True
    k: int = 8
    doc_ids: list[str] | None = None


class SettingsBody(BaseModel):
    llm: str | None = None
    use_reranker: bool | None = None


class CompareBody(BaseModel):
    metric: str
    companies: list[str] | None = None
    periods: list[str] | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    core = App(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        core.ingestor.start()
        yield

    app = FastAPI(title="FinGraph AI", version="0.1.0", lifespan=lifespan)
    app.state.core = core
    st = core.store

    # ------------------------------------------------------------ health / settings
    @app.get("/api/health")
    def health():
        avail = core.models.available()
        return {"ok": True, "models": avail, "documents": st.scalar("SELECT count(*) FROM documents"),
                "worker_busy": not core.ingestor.idle(), "queue": core.ingestor.q.qsize()}

    @app.get("/api/settings")
    def get_settings():
        return {**core.models.available(), "use_reranker": core.s.use_reranker,
                "min_similarity": core.s.min_similarity, "min_rerank": core.s.min_rerank,
                "index_embedder": st.meta("embedder"), "ocr": core.s.ocr}

    @app.post("/api/settings")
    def set_settings(body: SettingsBody):
        if body.llm:
            avail = core.models.available()
            if body.llm not in avail["local"] + avail["cloud"] and not core.s.fake_models:
                raise HTTPException(400, f"Model {body.llm} is not available")
            core.models.switch_chat(body.llm)
        if body.use_reranker is not None:
            core.s.use_reranker = body.use_reranker
        return get_settings()

    # ------------------------------------------------------------ documents
    @app.get("/api/documents")
    def list_documents(limit: int = Query(50, le=200), before_ts: float | None = None, before_id: str | None = None,
                       status: str | None = None):
        before = (before_ts, before_id) if before_ts is not None and before_id else None
        docs = st.list_documents(limit, before, status)
        nxt = {"before_ts": docs[-1]["created_at"], "before_id": docs[-1]["id"]} if len(docs) == limit else None
        counts = {r["status"]: r["n"] for r in st.rows("SELECT status, count(*) AS n FROM documents GROUP BY status")}
        return {"items": docs, "next": nxt, "counts": counts}

    @app.post("/api/documents")
    async def upload(files: list[UploadFile] = File(...)):
        out = []
        for f in files:
            data = await f.read()
            try:
                out.append({"ok": True, "document": core.ingestor.submit(f.filename or "upload", data)})
            except DuplicateFile as e:
                out.append({"ok": False, "filename": f.filename, "error": "This exact file is already uploaded.",
                            "existing_id": e.existing["id"]})
            except ValueError as e:
                out.append({"ok": False, "filename": f.filename, "error": str(e)})
        return {"results": out}

    @app.get("/api/documents/{doc_id}")
    def document(doc_id: str):
        d = st.get_document(doc_id)
        if not d:
            raise HTTPException(404, "Document not found")
        return {
            "document": d,
            "pages": st.rows("SELECT page, method, confidence, length(text) AS chars, text FROM pages WHERE doc_id=? "
                             "ORDER BY page", (doc_id,)),
            "chunks": st.rows("SELECT id, idx, page, section, header, text FROM chunks WHERE doc_id=? ORDER BY idx",
                              (doc_id,)),
            "metrics": st.rows("SELECT * FROM metrics WHERE doc_id=?", (doc_id,)),
            "invoices": st.rows("SELECT * FROM invoices WHERE doc_id=?", (doc_id,)),
            "transactions": st.rows("SELECT * FROM transactions WHERE doc_id=? ORDER BY date", (doc_id,)),
            "entities": st.rows("SELECT e.id, e.name, e.type FROM entities e JOIN mentions m ON m.entity_id = e.id "
                                "WHERE m.doc_id=? ORDER BY e.type, e.name", (doc_id,)),
            "anomalies": [a for a in core.finance.anomalies() if doc_id in a["doc_ids"]],
        }

    @app.get("/api/documents/{doc_id}/file")
    def document_file(doc_id: str):
        d = st.get_document(doc_id)
        if not d:
            raise HTTPException(404, "Document not found")
        return FileResponse(core.ingestor.file_path(d), filename=d["filename"],
                            content_disposition_type="inline")

    @app.delete("/api/documents/{doc_id}")
    def delete_document(doc_id: str):
        try:
            core.ingestor.delete(doc_id)
        except KeyError:
            raise HTTPException(404, "Document not found")
        return {"ok": True}

    @app.post("/api/documents/{doc_id}/retry")
    def retry(doc_id: str):
        d = st.get_document(doc_id)
        if not d:
            raise HTTPException(404, "Document not found")
        if d["status"] not in ("failed", "limited"):
            raise HTTPException(409, f"Document is {d['status']}")
        core.ingestor.retry(doc_id)
        return {"ok": True}

    # ------------------------------------------------------------ conversations / Wiki Ask
    @app.get("/api/conversations")
    def conversations(limit: int = Query(50, le=200), before: float | None = None):
        sql = "SELECT c.*, (SELECT count(*) FROM messages m WHERE m.conv_id = c.id) AS messages FROM conversations c"
        args: list = []
        if before:
            sql += " WHERE updated_at < ?"
            args.append(before)
        return st.rows(sql + " ORDER BY updated_at DESC LIMIT ?", [*args, limit])

    @app.post("/api/conversations")
    def create_conversation(body: ConvBody):
        return core.ask.new_conversation(body.title or "New conversation", body.scope)

    @app.patch("/api/conversations/{cid}")
    def rename_conversation(cid: str, body: ConvBody):
        if body.title:
            st.execute("UPDATE conversations SET title=? WHERE id=?", (body.title[:120], cid))
        if body.scope is not None:
            st.execute("UPDATE conversations SET scope=? WHERE id=?", (json.dumps(body.scope), cid))
        return st.row("SELECT * FROM conversations WHERE id=?", (cid,))

    @app.delete("/api/conversations/{cid}")
    def delete_conversation(cid: str):
        st.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
        st.execute("DELETE FROM conversations WHERE id=?", (cid,))
        return {"ok": True}

    @app.get("/api/conversations/{cid}/messages")
    def messages(cid: str):
        conv = st.row("SELECT * FROM conversations WHERE id=?", (cid,))
        if not conv:
            raise HTTPException(404, "Conversation not found")
        rows = st.rows("SELECT * FROM messages WHERE conv_id=? ORDER BY id", (cid,))
        for r in rows:
            r["meta"] = json.loads(r["meta"] or "{}")
        return {"conversation": conv, "messages": rows}

    @app.post("/api/conversations/{cid}/ask")
    def ask(cid: str, body: AskBody):
        if not st.row("SELECT 1 FROM conversations WHERE id=?", (cid,)):
            raise HTTPException(404, "Conversation not found")
        if not body.question.strip():
            raise HTTPException(400, "Question is empty")
        return core.ask.ask(cid, body.question[:2000], body.doc_ids)

    # ------------------------------------------------------------ graph
    @app.get("/api/graph")
    def graph(include_docs: bool = False, types: str | None = None, q: str | None = None, limit: int = 300):
        return core.graph.graph(include_docs, types.split(",") if types else None, q, limit)

    @app.get("/api/graph/node/{entity_id}")
    def graph_node(entity_id: int):
        n = core.graph.node(entity_id)
        if not n:
            raise HTTPException(404, "Entity not found")
        return n

    @app.get("/api/graph/node/{entity_id}/neighbours")
    def graph_neighbours(entity_id: int):
        return core.graph.neighbours(entity_id)

    # ------------------------------------------------------------ financial intelligence
    @app.get("/api/finance/overview")
    def overview():
        return {**core.finance.overview(), "companies": core.finance.companies(),
                "metrics": core.finance.metric_names(), "anomalies": core.finance.anomalies()}

    @app.get("/api/finance/anomalies")
    def anomalies():
        return core.finance.anomalies()

    @app.post("/api/finance/compare")
    def compare(body: CompareBody):
        return core.finance.compare(body.metric, body.companies, body.periods)

    @app.get("/api/finance/compare-documents")
    def compare_documents(a: str, b: str):
        try:
            return core.finance.compare_documents(a, b)
        except KeyError:
            raise HTTPException(404, "Document not found")

    _summary_cache: dict = {}

    @app.get("/api/finance/summary")
    def summary(refresh: bool = False, llm: bool = True):
        stamp = (st.scalar("SELECT max(processed_at) FROM documents"), st.scalar("SELECT count(*) FROM documents"), llm)
        if refresh or _summary_cache.get("stamp") != stamp:
            _summary_cache.update(stamp=stamp, value=core.finance.summary(core.models.chat if llm else None),
                                  at=time.time())
        return {**_summary_cache["value"], "generated_at": _summary_cache["at"]}

    # ------------------------------------------------------------ playground / eval / monitoring
    @app.post("/api/playground")
    def playground(body: PlaygroundBody):
        route = core.router.route(body.query)
        sr = core.retriever.search(body.query, mode=body.mode, rerank=body.rerank, k=body.k, doc_ids=body.doc_ids)
        res = sr.public()
        ids = {x["chunk_id"] for x in res["vector"] + res["keyword"] + res["fused"]}
        rows = st.chunks_by_id(list(ids))
        res["chunks"] = {cid: {"filename": r["filename"], "page": r["page"], "header": r["header"],
                               "text": r["text"][:500]} for cid, r in rows.items()}
        res["route"] = route.public()
        return res

    @app.post("/api/eval/retrieval")
    def eval_retrieval():
        out = run_retrieval_eval(st, core.retriever)
        save_run(st, out)
        return out

    @app.post("/api/eval/answers")
    def eval_answers(limit: int = 30):
        out = run_answer_eval(st, core.ask, limit=limit)
        save_run(st, out)
        return out

    @app.get("/api/monitoring")
    def monitor():
        return monitoring(st)

    # ------------------------------------------------------------ exports
    @app.get("/api/export/report.md")
    def report_md():
        md = markdown_report(st, core.finance, summary())
        return PlainTextResponse(md, headers={"Content-Disposition": "attachment; filename=fingraph-report.md"})

    @app.get("/api/export/report.html")
    def report_html():
        return HTMLResponse(html_report(markdown_report(st, core.finance, summary())))

    @app.get("/api/export/metrics.csv")
    def export_metrics():
        return Response(metrics_csv(st), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=fingraph-metrics.csv"})

    @app.get("/api/export/anomalies.csv")
    def export_anomalies():
        return Response(anomalies_csv(core.finance), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=fingraph-anomalies.csv"})

    # ------------------------------------------------------------ web app
    dist = ROOT / "web" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            f = dist / path
            if path and f.is_file():
                return FileResponse(f)
            # index.html must never be cached: it points at the hashed bundle of the current build
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
