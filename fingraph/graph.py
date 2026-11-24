"""Knowledge graph read API. Transactions are aggregated into one edge per (payer, payee) so a bank statement
adds a single 'paid' edge with a count and a total, not 40 nodes. Every edge keeps its source documents."""

from __future__ import annotations

from collections import defaultdict

from .finance import Finance
from .store import Store
from .textutil import fmt_money, norm_name, period_key

MAX_NODES = 300


class Graph:
    def __init__(self, store: Store, finance: Finance):
        self.store, self.finance = store, finance

    def _anomaly_index(self) -> dict[str, list[dict]]:
        idx = defaultdict(list)
        for a in self.finance.anomalies():
            for name in a["entities"]:
                if name:
                    idx[norm_name(name)].append({"id": a["id"], "title": a["title"], "severity": a["severity"]})
        return idx

    def graph(self, include_docs: bool = False, types: list[str] | None = None, q: str | None = None,
              limit: int = MAX_NODES) -> dict:
        limit = min(limit, MAX_NODES)
        ents = self.store.rows("""
            SELECT e.*, (SELECT count(*) FROM edges WHERE src = e.id OR dst = e.id) AS degree,
                   (SELECT count(DISTINCT doc_id) FROM mentions WHERE entity_id = e.id) AS docs
            FROM entities e ORDER BY degree DESC, docs DESC LIMIT ?""", (limit * 3,))
        if types:
            ents = [e for e in ents if e["type"] in types]
        if q:
            ql = q.lower()
            ents = [e for e in ents if ql in e["name"].lower()]
        ents = ents[:limit]
        keep = {e["id"] for e in ents}
        anomalies = self._anomaly_index()
        nodes = [{"id": f"e{e['id']}", "entity_id": e["id"], "label": e["name"], "type": e["type"],
                  "degree": e["degree"], "docs": e["docs"], "anomalies": anomalies.get(e["norm"], [])} for e in ents]
        edges = []
        if keep:
            marks = ",".join("?" * len(keep))
            rows = self.store.rows(f"""
                SELECT src, dst, relation, count(*) AS n, sum(amount) AS total, count(DISTINCT doc_id) AS docs
                FROM edges WHERE src IN ({marks}) AND dst IN ({marks}) GROUP BY src, dst, relation""",
                                   [*keep, *keep])
            for r in rows:
                label = r["relation"].replace("_", " ")
                if r["relation"] == "paid" and r["total"]:
                    label = f"paid · {r['n']}× · {fmt_money(r['total'])}"
                edges.append({"id": f"{r['src']}-{r['dst']}-{r['relation']}", "source": f"e{r['src']}",
                              "target": f"e{r['dst']}", "relation": r["relation"], "label": label, "count": r["n"],
                              "total": r["total"], "docs": r["docs"]})
        if include_docs and keep:
            marks = ",".join("?" * len(keep))
            docs = self.store.rows(f"""SELECT DISTINCT d.id, d.filename, d.doc_type FROM documents d
                                       JOIN mentions m ON m.doc_id = d.id WHERE m.entity_id IN ({marks})""", list(keep))
            nodes += [{"id": f"d{d['id']}", "doc_id": d["id"], "label": d["filename"], "type": "document",
                       "doc_type": d["doc_type"], "degree": 0, "docs": 1, "anomalies": []} for d in docs]
            for m in self.store.rows(f"SELECT entity_id, doc_id FROM mentions WHERE entity_id IN ({marks})", list(keep)):
                edges.append({"id": f"m{m['entity_id']}-{m['doc_id']}", "source": f"e{m['entity_id']}",
                              "target": f"d{m['doc_id']}", "relation": "mentioned_in", "label": "", "count": 1,
                              "total": None, "docs": 1})
        total = self.store.scalar("SELECT count(*) FROM entities")
        return {"nodes": nodes, "edges": edges, "total_entities": total, "truncated": total > len(ents),
                "types": [r["type"] for r in self.store.rows("SELECT DISTINCT type FROM entities ORDER BY type")]}

    def node(self, entity_id: int) -> dict | None:
        e = self.store.row("SELECT * FROM entities WHERE id=?", (entity_id,))
        if not e:
            return None
        rels = self.store.rows("""
            SELECT ed.*, s.name AS src_name, s.type AS src_type, t.name AS dst_name, t.type AS dst_type,
                   d.filename FROM edges ed JOIN entities s ON s.id = ed.src JOIN entities t ON t.id = ed.dst
            JOIN documents d ON d.id = ed.doc_id WHERE ed.src = ? OR ed.dst = ? ORDER BY ed.relation, ed.date""",
                               (entity_id, entity_id))
        groups: dict[tuple, dict] = {}
        for r in rels:
            outgoing = r["src"] == entity_id
            other_id = r["dst"] if outgoing else r["src"]
            key = (r["relation"], other_id, outgoing)
            g = groups.setdefault(key, {
                "relation": r["relation"], "direction": "out" if outgoing else "in", "other_id": other_id,
                "other": r["dst_name"] if outgoing else r["src_name"],
                "other_type": r["dst_type"] if outgoing else r["src_type"], "count": 0, "total": 0.0, "evidence": []})
            g["count"] += 1
            g["total"] += r["amount"] or 0
            g["evidence"].append({"doc_id": r["doc_id"], "filename": r["filename"], "page": r["page"],
                                  "excerpt": r["excerpt"], "amount": r["amount"], "date": r["date"]})
        docs = self.store.rows("""SELECT m.doc_id, m.page, m.excerpt, d.filename, d.doc_type, d.period
                                  FROM mentions m JOIN documents d ON d.id = m.doc_id WHERE m.entity_id = ?""",
                               (entity_id,))
        metrics = []
        if e["kind"] == "org":
            for (cn, period), g in sorted(self.finance.facts().items(), key=lambda kv: period_key(kv[0][1])):
                if cn == e["norm"]:
                    metrics.append({"period": period, "currency": g["currency"],
                                    "values": {k: v["value"] for k, v in g["metrics"].items()}})
        return {"entity": e, "relations": list(groups.values()), "documents": docs, "metrics": metrics,
                "anomalies": self._anomaly_index().get(e["norm"], [])}

    def neighbours(self, entity_id: int) -> dict:
        ids = {entity_id} | {r["x"] for r in self.store.rows(
            "SELECT dst AS x FROM edges WHERE src=? UNION SELECT src FROM edges WHERE dst=?", (entity_id, entity_id))}
        marks = ",".join("?" * len(ids))
        ents = self.store.rows(f"SELECT * FROM entities WHERE id IN ({marks})", list(ids))
        anomalies = self._anomaly_index()
        nodes = [{"id": f"e{e['id']}", "entity_id": e["id"], "label": e["name"], "type": e["type"], "degree": 0,
                  "docs": 0, "anomalies": anomalies.get(e["norm"], [])} for e in ents]
        rows = self.store.rows(f"""SELECT src, dst, relation, count(*) AS n, sum(amount) AS total FROM edges
                                   WHERE src IN ({marks}) AND dst IN ({marks}) GROUP BY src, dst, relation""",
                               [*ids, *ids])
        edges = [{"id": f"{r['src']}-{r['dst']}-{r['relation']}", "source": f"e{r['src']}", "target": f"e{r['dst']}",
                  "relation": r["relation"], "label": r["relation"].replace("_", " "), "count": r["n"],
                  "total": r["total"]} for r in rows]
        return {"nodes": nodes, "edges": edges}
