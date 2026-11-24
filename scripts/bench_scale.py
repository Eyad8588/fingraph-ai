"""Where does the embedded vector store stop being enough? Measures sqlite-vec KNN and FTS5 BM25 latency at
growing corpus sizes with random 1024-d vectors (same dimension as qwen3-embedding:0.6b).

    uv run python scripts/bench_scale.py            # 10k, 50k, 100k chunks
"""

from __future__ import annotations

import random
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import sqlite_vec

DIM = 1024
WORDS = ("revenue invoice vendor payment marketing logistics salaries rent tax margin profit loss quarter cash "
         "assets liabilities equity contract freight warehouse customer deposit transfer statement balance").split()


def build(path: Path, n: int) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.execute(f"CREATE VIRTUAL TABLE v USING vec0(embedding float[{DIM}] distance_metric=cosine)")
    db.execute("CREATE VIRTUAL TABLE f USING fts5(text, tokenize='porter unicode61')")
    rng = np.random.default_rng(0)
    batch = 5000
    for start in range(0, n, batch):
        vecs = rng.standard_normal((min(batch, n - start), DIM)).astype(np.float32)
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        db.executemany("INSERT INTO v(rowid, embedding) VALUES (?,?)",
                       [(start + i + 1, vecs[i].tobytes()) for i in range(len(vecs))])
        db.executemany("INSERT INTO f(rowid, text) VALUES (?,?)",
                       [(start + i + 1, " ".join(random.choices(WORDS, k=60))) for i in range(len(vecs))])
        db.commit()
    return db


def bench(db: sqlite3.Connection, runs: int = 20) -> tuple[float, float]:
    q = np.random.default_rng(1).standard_normal(DIM).astype(np.float32)
    q /= np.linalg.norm(q)
    knn, kw = [], []
    for _ in range(runs):
        t = time.perf_counter()
        db.execute("SELECT rowid, distance FROM v WHERE embedding MATCH ? AND k = 30", (q.tobytes(),)).fetchall()
        knn.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        db.execute("SELECT rowid FROM f WHERE f MATCH '\"revenue\" OR \"invoice\" OR \"vendor\"' "
                   "ORDER BY bm25(f) LIMIT 30").fetchall()
        kw.append((time.perf_counter() - t) * 1000)
    return statistics.median(knn), statistics.median(kw)


def main() -> None:
    sizes = [int(x) for x in sys.argv[1:]] or [10_000, 50_000, 100_000]
    print(f"{'chunks':>8} | {'vector KNN p50':>14} | {'BM25 p50':>9} | {'vector bytes':>12}")
    for n in sizes:
        with tempfile.TemporaryDirectory() as d:
            db = build(Path(d) / "bench.sqlite3", n)
            v, k = bench(db)
            print(f"{n:>8} | {v:>11.1f} ms | {k:>6.1f} ms | {n * DIM * 4 / 1e6:>9.0f} MB")
            db.close()


if __name__ == "__main__":
    main()
