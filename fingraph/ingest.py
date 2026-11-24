"""Background ingestion: upload returns immediately, one worker processes documents in order.

Stages: parsing -> ocr -> chunking -> embedding -> extracting -> ready. Everything is built in memory and
written in ONE transaction at the end (Store.commit_document), so a crash or a delete mid-way can never
leave half a document in the index. On startup, documents stuck in 'processing' are re-queued.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
import time
import uuid
from pathlib import Path

from .chunking import chunk_pages
from .config import Settings
from .extract import extract
from .models import ModelError, ModelRegistry
from .parsing import SUPPORTED, ParseError, make_ocr, parse_file
from .store import Store

log = logging.getLogger("fingraph.ingest")


class Cancelled(Exception):
    pass


class DuplicateFile(Exception):
    def __init__(self, existing: dict):
        super().__init__("already uploaded")
        self.existing = existing


class Ingestor:
    def __init__(self, s: Settings, store: Store, models: ModelRegistry):
        self.s, self.store, self.models = s, store, models
        self.q: queue.Queue[str] = queue.Queue()
        self.cancelled: set[str] = set()
        self.current: str | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        stuck = self.store.rows("SELECT id FROM documents WHERE status IN ('queued','processing') "
                                "ORDER BY created_at")
        for row in stuck:  # crash recovery: nothing of theirs was committed, so re-run them
            self.store.set_doc(row["id"], status="queued", stage=None)
            self.q.put(row["id"])
        self._thread = threading.Thread(target=self._loop, name="ingest-worker", daemon=True)
        self._thread.start()

    def idle(self) -> bool:
        return self.q.empty() and self.current is None

    def wait_idle(self, timeout: float = 600) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.idle():
                return True
            time.sleep(0.1)
        return False

    # ------------------------------------------------------------ public actions
    def submit(self, filename: str, data: bytes) -> dict:
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED:
            raise ValueError(f"Unsupported file type '{ext}'. Supported: PDF, DOCX, PNG, JPG (and TXT/MD/CSV).")
        if len(data) > self.s.max_file_mb * 1024 * 1024:
            raise ValueError(f"File is larger than {self.s.max_file_mb} MB.")
        if not data:
            raise ValueError("File is empty.")
        digest = hashlib.sha256(data).hexdigest()
        existing = self.store.row("SELECT * FROM documents WHERE sha256=?", (digest,))
        if existing:
            raise DuplicateFile(existing)
        doc_id = uuid.uuid4().hex[:12]
        (self.s.upload_dir / f"{doc_id}{ext}").write_bytes(data)
        self.store.execute("INSERT INTO documents(id, filename, ext, size, sha256, status, created_at) "
                           "VALUES (?,?,?,?,?, 'queued', ?)", (doc_id, Path(filename).name, ext, len(data), digest,
                                                               time.time()))
        self.q.put(doc_id)
        return self.store.get_document(doc_id)

    def retry(self, doc_id: str) -> None:
        self.store.set_doc(doc_id, status="queued", stage=None, error=None)
        self.q.put(doc_id)

    def delete(self, doc_id: str) -> None:
        doc = self.store.get_document(doc_id)
        if not doc:
            raise KeyError(doc_id)
        self.cancelled.add(doc_id)  # the worker checks this between stages and drops its results
        self.store.delete_document(doc_id)
        path = self.s.upload_dir / f"{doc_id}{doc['ext']}"
        path.unlink(missing_ok=True)

    def file_path(self, doc: dict) -> Path:
        return self.s.upload_dir / f"{doc['id']}{doc['ext']}"

    # ------------------------------------------------------------ worker
    def _loop(self) -> None:
        while True:
            doc_id = self.q.get()
            self.current = doc_id
            try:
                self._process(doc_id)
            except Cancelled:
                log.info("cancelled %s", doc_id)
            except Exception as e:  # never kill the worker
                log.exception("ingest failed for %s", doc_id)
                if self.store.get_document(doc_id):
                    self.store.set_doc(doc_id, status="failed", stage=None, error=friendly_error(e))
            finally:
                self.cancelled.discard(doc_id)
                self.current = None

    def _stage(self, doc_id: str, stage: str) -> None:
        if doc_id in self.cancelled or not self.store.get_document(doc_id):
            raise Cancelled()
        self.store.set_doc(doc_id, status="processing", stage=stage)

    def _process(self, doc_id: str) -> None:
        doc = self.store.get_document(doc_id)
        if not doc or doc["status"] not in ("queued", "processing"):
            return
        t0 = time.time()
        self._stage(doc_id, "parsing")
        ocr = make_ocr(self.s, self.models.vision)
        pages = parse_file(self.file_path(doc), self.s, ocr, on_stage=lambda st: self._stage(doc_id, st))
        if not any(p.text.strip() for p in pages):
            raise ParseError("No text could be read from this file (blank page or unreadable scan).")

        self._stage(doc_id, "extracting")
        facts = extract(pages, doc["filename"], self.models.chat)

        self._stage(doc_id, "chunking")
        meta = {"company": facts["company"], "doc_type": facts["doc_type"], "period": facts["period"],
                "filename": doc["filename"]}
        chunks = chunk_pages(pages, meta, self.s.chunk_max_chars, self.s.chunk_overlap)
        if not chunks:
            raise ParseError("Document produced no text chunks.")

        self._stage(doc_id, "embedding")
        vectors = with_retry(lambda: self.models.embeddings.encode([f"{c['header']}\n{c['text']}" for c in chunks]))
        self.store.ensure_vector_table(vectors.shape[1], self.models.embeddings.spec)

        ocr_pages = [p for p in pages if p.method == "ocr"]
        confs = [p.confidence for p in ocr_pages if p.confidence is not None]
        limited = facts["warnings"] and not facts["llm_used"]
        result = {
            "pages": [p.__dict__ for p in pages], "chunks": chunks, "metrics": facts["metrics"],
            "invoices": facts["invoices"], "transactions": facts["transactions"], "entities": facts["entities"],
            "edges": facts["edges"],
            "document": {
                "status": "limited" if limited else "ready",
                "error": "; ".join(facts["warnings"]) or None,
                "pages": len(pages), "ocr_pages": len(ocr_pages),
                "ocr_confidence": round(min(confs), 3) if confs else None,
                "chars": sum(len(p.text) for p in pages), "doc_type": facts["doc_type"], "company": facts["company"],
                "period": facts["period"], "currency": facts["currency"], "summary": facts["summary"],
                "processing_ms": int((time.time() - t0) * 1000),
            },
        }
        if doc_id in self.cancelled:
            raise Cancelled()
        try:
            self.store.commit_document(doc_id, result, vectors)
        except LookupError as e:
            raise Cancelled() from e


def with_retry(fn, attempts: int = 3, base_delay: float = 1.5):
    for i in range(attempts):
        try:
            return fn()
        except ModelError:
            if i == attempts - 1:
                raise
            time.sleep(base_delay * (2 ** i))


def friendly_error(e: Exception) -> str:
    if isinstance(e, ModelError):
        return f"Model service unavailable after 3 attempts. Is Ollama running? ({e})"[:500]
    if isinstance(e, ParseError):
        return str(e)
    return f"{type(e).__name__}: {e}"[:500]
