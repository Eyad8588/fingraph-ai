"""Repository over ONE SQLite file: relational tables + FTS5 (keyword) + sqlite-vec (vectors).

Because everything lives in one database, ingesting or deleting a document is a single transaction:
either all of its chunks, vectors, graph edges and financial facts exist, or none do.
Every other module talks to the data only through this class, so moving to Postgres + pgvector
later means re-implementing this file, not the application.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path

import numpy as np
import sqlite_vec

from .textutil import norm_name

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY, filename TEXT NOT NULL, ext TEXT, size INTEGER, sha256 TEXT UNIQUE,
  status TEXT NOT NULL,            -- queued | processing | ready | limited | failed
  stage TEXT, error TEXT,
  pages INTEGER, ocr_pages INTEGER DEFAULT 0, ocr_confidence REAL, chars INTEGER,
  doc_type TEXT, company TEXT, period TEXT, currency TEXT, summary TEXT,
  created_at REAL NOT NULL, processed_at REAL, processing_ms INTEGER
);
CREATE INDEX IF NOT EXISTS documents_created ON documents(created_at DESC, id);
CREATE INDEX IF NOT EXISTS documents_status ON documents(status);

CREATE TABLE IF NOT EXISTS pages (
  doc_id TEXT, page INTEGER, method TEXT, confidence REAL, text TEXT, PRIMARY KEY (doc_id, page)
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT NOT NULL, idx INTEGER, page INTEGER,
  section TEXT, header TEXT, text TEXT NOT NULL, method TEXT
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(header, text, tokenize = 'porter unicode61');

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, norm TEXT, kind TEXT, type TEXT, UNIQUE(norm, kind)
);
CREATE TABLE IF NOT EXISTS mentions (
  entity_id INTEGER, doc_id TEXT, page INTEGER, excerpt TEXT, PRIMARY KEY (entity_id, doc_id)
);
CREATE INDEX IF NOT EXISTS mentions_doc ON mentions(doc_id);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, src INTEGER, dst INTEGER, relation TEXT, doc_id TEXT,
  page INTEGER, excerpt TEXT, amount REAL, date TEXT
);
CREATE INDEX IF NOT EXISTS edges_src ON edges(src);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE INDEX IF NOT EXISTS edges_doc ON edges(doc_id);

CREATE TABLE IF NOT EXISTS metrics (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, company TEXT, company_norm TEXT, period TEXT,
  name TEXT, label TEXT, value REAL, currency TEXT, page INTEGER, excerpt TEXT, source TEXT
);
CREATE INDEX IF NOT EXISTS metrics_lookup ON metrics(company_norm, name, period);
CREATE INDEX IF NOT EXISTS metrics_doc ON metrics(doc_id);

CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, number TEXT, number_norm TEXT, vendor TEXT,
  vendor_norm TEXT, customer TEXT, customer_norm TEXT, issue_date TEXT, due_date TEXT,
  subtotal REAL, tax REAL, total REAL, currency TEXT, page INTEGER, excerpt TEXT
);
CREATE INDEX IF NOT EXISTS invoices_number ON invoices(number_norm);
CREATE INDEX IF NOT EXISTS invoices_vendor_total ON invoices(vendor_norm, total);
CREATE INDEX IF NOT EXISTS invoices_doc ON invoices(doc_id);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, account_holder TEXT, date TEXT, description TEXT,
  counterparty TEXT, counterparty_norm TEXT, category TEXT, amount REAL, direction TEXT, currency TEXT, page INTEGER,
  excerpt TEXT
);
CREATE INDEX IF NOT EXISTS tx_counterparty ON transactions(counterparty_norm, date);
CREATE INDEX IF NOT EXISTS tx_doc ON transactions(doc_id);

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, title TEXT, scope TEXT, created_at REAL, updated_at REAL
);
CREATE INDEX IF NOT EXISTS conversations_updated ON conversations(updated_at DESC);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id TEXT, role TEXT, content TEXT, meta TEXT, created_at REAL
);
CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv_id, id);

CREATE TABLE IF NOT EXISTS query_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, conv_id TEXT, question TEXT, standalone TEXT, route TEXT,
  model TEXT, latency_ms INTEGER, retrieval_ms INTEGER, top_similarity REAL, top_rerank REAL,
  n_sources INTEGER, n_docs INTEGER, abstained INTEGER, unverified INTEGER
);
CREATE INDEX IF NOT EXISTS query_log_ts ON query_log(ts);
CREATE TABLE IF NOT EXISTS eval_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, result TEXT);
"""

ORG_TYPES = ("company", "vendor", "customer", "bank", "organization")
TYPE_PRIORITY = {"company": 4, "vendor": 3, "customer": 2, "bank": 2, "organization": 1}


KEEP_UPPER = {"LLC", "PLC", "LLP", "AG", "SA", "GMBH", "USA", "UK", "UAE", "KSA"}


def display_name(name: str) -> str:
    """'ATLAS LOGISTICS LLC' (from a scanned header) -> 'Atlas Logistics LLC'. IDs like INV-1042 untouched."""
    name = re.sub(r"\s+", " ", name.strip())
    if name.isupper() and not re.search(r"\d", name):
        return " ".join(w if w in KEEP_UPPER else w.capitalize() for w in name.split())
    return name


def entity_kind(etype: str) -> str:
    return "org" if etype in ORG_TYPES else etype


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.enable_load_extension(True)
        sqlite_vec.load(self.db)
        self.db.enable_load_extension(False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)

    # ------------------------------------------------------------ primitives
    def rows(self, sql: str, args=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def row(self, sql: str, args=()) -> dict | None:
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
            return dict(r) if r else None

    def scalar(self, sql: str, args=()):
        with self.lock:
            r = self.db.execute(sql, args).fetchone()
            return r[0] if r else None

    def execute(self, sql: str, args=()) -> int:
        with self.lock:
            return self.db.execute(sql, args).lastrowid

    def transaction(self):
        """Context manager: BEGIN IMMEDIATE ... COMMIT, ROLLBACK on any exception."""
        store = self

        class _Tx:
            def __enter__(self):
                store.lock.acquire()
                store.db.execute("BEGIN IMMEDIATE")
                return store.db

            def __exit__(self, exc_type, exc, tb):
                try:
                    store.db.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store.lock.release()
                return False

        return _Tx()

    # ------------------------------------------------------------ meta / vector table
    def meta(self, key: str) -> str | None:
        return self.scalar("SELECT value FROM meta WHERE key=?", (key,))

    def set_meta(self, key: str, value: str) -> None:
        self.execute("INSERT INTO meta(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, value))

    def ensure_vector_table(self, dim: int, embedder: str) -> None:
        """The vec0 table has a fixed dimension; it is created on first use and pinned to one embedder."""
        current = self.meta("embedder")
        if current and current != embedder:
            raise RuntimeError(f"Index was built with {current} but the configured embedder is {embedder}. "
                               "Re-index (POST /api/reindex) or switch the embedder back.")
        with self.lock:
            self.db.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0("
                            f"embedding float[{dim}] distance_metric=cosine)")
        self.set_meta("embedder", embedder)
        self.set_meta("embedding_dim", str(dim))

    def has_vectors(self) -> bool:
        return self.scalar("SELECT count(*) FROM sqlite_master WHERE name='chunk_vec'") == 1

    # ------------------------------------------------------------ documents
    def list_documents(self, limit: int = 50, before: tuple[float, str] | None = None,
                       status: str | None = None) -> list[dict]:
        """Keyset pagination on (created_at DESC, id): page N costs the same as page 1."""
        where, args = [], []
        if before:
            where.append("(created_at < ? OR (created_at = ? AND id < ?))")
            args += [before[0], before[0], before[1]]
        if status:
            where.append("status = ?")
            args.append(status)
        sql = "SELECT * FROM documents" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
        return self.rows(sql, [*args, limit])

    def get_document(self, doc_id: str) -> dict | None:
        return self.row("SELECT * FROM documents WHERE id=?", (doc_id,))

    def set_doc(self, doc_id: str, **fields) -> None:
        if fields:
            cols = ", ".join(f"{k}=?" for k in fields)
            self.execute(f"UPDATE documents SET {cols} WHERE id=?", [*fields.values(), doc_id])

    def commit_document(self, doc_id: str, result: dict, vectors: np.ndarray) -> None:
        """Write everything produced for one document in a single transaction."""
        with self.transaction() as db:
            if not db.execute("SELECT 1 FROM documents WHERE id=?", (doc_id,)).fetchone():
                raise LookupError("document was deleted while processing")
            self._purge(db, doc_id, keep_document=True)
            for p in result["pages"]:
                db.execute("INSERT INTO pages(doc_id, page, method, confidence, text) VALUES (?,?,?,?,?)",
                           (doc_id, p["page"], p["method"], p.get("confidence"), p["text"]))
            for c, vec in zip(result["chunks"], vectors):
                cid = db.execute("INSERT INTO chunks(doc_id, idx, page, section, header, text, method) "
                                 "VALUES (?,?,?,?,?,?,?)",
                                 (doc_id, c["idx"], c["page"], c.get("section"), c["header"], c["text"],
                                  c.get("method"))).lastrowid
                db.execute("INSERT INTO chunk_fts(rowid, header, text) VALUES (?,?,?)", (cid, c["header"], c["text"]))
                db.execute("INSERT INTO chunk_vec(rowid, embedding) VALUES (?,?)",
                           (cid, np.asarray(vec, dtype=np.float32).tobytes()))
            for m in result["metrics"]:
                db.execute("INSERT INTO metrics(doc_id, company, company_norm, period, name, label, value, currency, "
                           "page, excerpt, source) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                           (doc_id, m["company"], norm_name(m["company"] or ""), m["period"], m["name"],
                            m.get("label"), m["value"], m.get("currency"), m.get("page"), m.get("excerpt"),
                            m.get("source", "rules")))
            for inv in result["invoices"]:
                db.execute("INSERT INTO invoices(doc_id, number, number_norm, vendor, vendor_norm, customer, "
                           "customer_norm, issue_date, due_date, subtotal, tax, total, currency, page, excerpt) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (doc_id, inv.get("number"), inv.get("number_norm"), inv.get("vendor"),
                            norm_name(inv.get("vendor") or ""), inv.get("customer"),
                            norm_name(inv.get("customer") or ""), inv.get("issue_date"), inv.get("due_date"),
                            inv.get("subtotal"), inv.get("tax"), inv.get("total"), inv.get("currency"),
                            inv.get("page"), inv.get("excerpt")))
            for t in result["transactions"]:
                db.execute("INSERT INTO transactions(doc_id, account_holder, date, description, counterparty, "
                           "counterparty_norm, category, amount, direction, currency, page, excerpt) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                           (doc_id, t.get("account_holder"), t["date"], t["description"], t["counterparty"],
                            norm_name(t["counterparty"]), t.get("category"), t["amount"], t["direction"], t.get("currency"),
                            t.get("page"), t.get("excerpt")))
            ids: dict[tuple[str, str], int] = {}
            for e in result["entities"]:
                eid = self._upsert_entity(db, e["name"], e["type"])
                if eid:
                    ids[(norm_name(e["name"]), entity_kind(e["type"]))] = eid
                    db.execute("INSERT OR IGNORE INTO mentions(entity_id, doc_id, page, excerpt) VALUES (?,?,?,?)",
                               (eid, doc_id, e.get("page"), (e.get("excerpt") or "")[:400]))
            for r in result["edges"]:
                src = ids.get((norm_name(r["src"]), entity_kind(r["src_type"])))
                dst = ids.get((norm_name(r["dst"]), entity_kind(r["dst_type"])))
                if src and dst and src != dst:
                    db.execute("INSERT INTO edges(src, dst, relation, doc_id, page, excerpt, amount, date) "
                               "VALUES (?,?,?,?,?,?,?,?)",
                               (src, dst, r["relation"], doc_id, r.get("page"), (r.get("excerpt") or "")[:400],
                                r.get("amount"), r.get("date")))
            d = result["document"]
            db.execute("UPDATE documents SET status=?, stage=NULL, error=?, pages=?, ocr_pages=?, ocr_confidence=?, "
                       "chars=?, doc_type=?, company=?, period=?, currency=?, summary=?, processed_at=?, "
                       "processing_ms=? WHERE id=?",
                       (d["status"], d.get("error"), d["pages"], d["ocr_pages"], d.get("ocr_confidence"), d["chars"],
                        d.get("doc_type"), d.get("company"), d.get("period"), d.get("currency"), d.get("summary"),
                        time.time(), d.get("processing_ms"), doc_id))

    @staticmethod
    def _upsert_entity(db, name: str, etype: str) -> int | None:
        key = norm_name(name)
        if len(key) < 2:
            return None
        kind = entity_kind(etype)
        row = db.execute("SELECT id, type FROM entities WHERE norm=? AND kind=?", (key, kind)).fetchone()
        name = display_name(name)
        if row:
            # an org seen as 'vendor' in one doc and 'company' in another keeps the stronger role
            if kind == "org" and TYPE_PRIORITY.get(etype, 0) > TYPE_PRIORITY.get(row["type"], 0):
                db.execute("UPDATE entities SET type=? WHERE id=?", (etype, row["id"]))
            return row["id"]
        return db.execute("INSERT INTO entities(name, norm, kind, type) VALUES (?,?,?,?)",
                          (name, key, kind, etype)).lastrowid

    def delete_document(self, doc_id: str) -> None:
        with self.transaction() as db:
            self._purge(db, doc_id, keep_document=False)

    def _purge(self, db, doc_id: str, keep_document: bool) -> None:
        chunk_ids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE doc_id=?", (doc_id,))]
        for cid in chunk_ids:
            db.execute("DELETE FROM chunk_fts WHERE rowid=?", (cid,))
            if self.has_vectors_db(db):
                db.execute("DELETE FROM chunk_vec WHERE rowid=?", (cid,))
        for table in ("chunks", "pages", "metrics", "invoices", "transactions", "mentions", "edges"):
            db.execute(f"DELETE FROM {table} WHERE doc_id=?", (doc_id,))
        db.execute("DELETE FROM entities WHERE id NOT IN (SELECT entity_id FROM mentions) "
                   "AND id NOT IN (SELECT src FROM edges) AND id NOT IN (SELECT dst FROM edges)")
        if not keep_document:
            db.execute("DELETE FROM documents WHERE id=?", (doc_id,))

    @staticmethod
    def has_vectors_db(db) -> bool:
        return db.execute("SELECT count(*) FROM sqlite_master WHERE name='chunk_vec'").fetchone()[0] == 1

    # ------------------------------------------------------------ retrieval primitives
    def vector_search(self, query_vec: np.ndarray, k: int, doc_ids: list[str] | None = None) -> list[tuple[int, float]]:
        """Returns (chunk_id, cosine_similarity). Scoped searches compute distances only over the scope."""
        if not self.has_vectors():
            return []
        blob = np.asarray(query_vec, dtype=np.float32).tobytes()
        if doc_ids:
            marks = ",".join("?" * len(doc_ids))
            rows = self.rows(f"SELECT v.rowid AS id, vec_distance_cosine(v.embedding, ?) AS d FROM chunk_vec v "
                             f"JOIN chunks c ON c.id = v.rowid WHERE c.doc_id IN ({marks}) ORDER BY d LIMIT ?",
                             [blob, *doc_ids, k])
        else:
            rows = self.rows("SELECT rowid AS id, distance AS d FROM chunk_vec WHERE embedding MATCH ? AND k = ? "
                             "ORDER BY distance", [blob, k])
        return [(r["id"], 1.0 - r["d"]) for r in rows]

    def keyword_search(self, query: str, k: int, doc_ids: list[str] | None = None) -> list[tuple[int, float]]:
        """FTS5 BM25. Returns (chunk_id, bm25) where higher is better."""
        terms = fts_terms(query)
        if not terms:
            return []
        match = " OR ".join(f'"{t}"' for t in terms)
        sql = ("SELECT f.rowid AS id, -bm25(chunk_fts, 2.0, 1.0) AS s FROM chunk_fts f "
               "JOIN chunks c ON c.id = f.rowid WHERE chunk_fts MATCH ?")
        args: list = [match]
        if doc_ids:
            sql += f" AND c.doc_id IN ({','.join('?' * len(doc_ids))})"
            args += doc_ids
        sql += " ORDER BY bm25(chunk_fts, 2.0, 1.0) LIMIT ?"
        try:
            rows = self.rows(sql, [*args, k])
        except sqlite3.OperationalError:
            return []
        return [(r["id"], r["s"]) for r in rows]

    def chunks_by_id(self, ids: list[int]) -> dict[int, dict]:
        if not ids:
            return {}
        rows = self.rows(f"SELECT c.*, d.filename, d.doc_type, d.company, d.period FROM chunks c "
                         f"JOIN documents d ON d.id = c.doc_id WHERE c.id IN ({','.join('?' * len(ids))})", ids)
        return {r["id"]: r for r in rows}

    # ------------------------------------------------------------ conversations
    def add_message(self, conv_id: str, role: str, content: str, meta: dict | None = None) -> int:
        now = time.time()
        with self.transaction() as db:
            mid = db.execute("INSERT INTO messages(conv_id, role, content, meta, created_at) VALUES (?,?,?,?,?)",
                             (conv_id, role, content, json.dumps(meta or {}), now)).lastrowid
            db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
        return mid

    def history(self, conv_id: str, turns: int) -> list[dict]:
        rows = self.rows("SELECT role, content FROM messages WHERE conv_id=? ORDER BY id DESC LIMIT ?",
                         (conv_id, turns * 2))
        return list(reversed(rows))


STOP = set("""a an the of in on at to for from by with and or is are was were be been what which who whom whose how
why when where did do does doing can could would should will shall may might much many any some this that these those
it its our we us you your i me my they them their there here than then as about into over under per vs versus tell
show give list please""".split())


def fts_terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", query.lower())
    return [w for w in dict.fromkeys(words) if w not in STOP and (len(w) > 1 or w.isdigit())][:16]
