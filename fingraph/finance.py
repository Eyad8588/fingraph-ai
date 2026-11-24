"""Financial intelligence over the verified facts: metric tables, ratios, comparisons, anomaly rules,
and the key-findings summary.

Anomalies are computed at READ time from the fact tables, never stored, so deleting a document can never
leave a stale warning behind.
"""

from __future__ import annotations

import hashlib
import statistics
from collections import defaultdict
from datetime import date

from .extract import METRIC_TITLES
from .models import ChatModel, ModelError
from .store import Store
from .textutil import fmt_money, norm_name, number_tokens, period_key

RATIOS = {
    "gross_margin": ("gross_profit", "revenue", "Gross margin"),
    "operating_margin": ("operating_income", "revenue", "Operating margin"),
    "net_margin": ("net_income", "revenue", "Net margin"),
    "current_ratio": ("current_assets", "current_liabilities", "Current ratio"),
    "debt_to_equity": ("total_liabilities", "total_equity", "Debt to equity"),
}
PERCENT_RATIOS = {"gross_margin", "operating_margin", "net_margin"}
SWING_THRESHOLD = 0.25
SWING_METRICS = {"revenue", "cost_of_revenue", "gross_profit", "salaries", "marketing", "rent", "logistics",
                 "operating_expenses", "operating_income", "net_income"}


def title(metric: str) -> str:
    return RATIOS[metric][2] if metric in RATIOS else METRIC_TITLES.get(metric, metric.replace("_", " ").capitalize())


class Finance:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------ facts
    def facts(self) -> dict[tuple[str, str], dict]:
        """(company_norm, period) -> {company, currency, metrics: {name: fact}}. Rules beat LLM-verified."""
        rows = self.store.rows("""SELECT m.*, d.filename FROM metrics m JOIN documents d ON d.id = m.doc_id
                                  WHERE m.company_norm != '' AND m.period IS NOT NULL
                                  ORDER BY (m.source = 'rules'), d.created_at""")
        out: dict[tuple[str, str], dict] = {}
        for r in rows:
            key = (r["company_norm"], r["period"])
            g = out.setdefault(key, {"company": r["company"], "company_norm": r["company_norm"], "period": r["period"],
                                     "currency": r["currency"], "metrics": {}})
            g["metrics"][r["name"]] = {"value": r["value"], "doc_id": r["doc_id"], "filename": r["filename"],
                                       "page": r["page"], "excerpt": r["excerpt"], "metric_id": r["id"],
                                       "source": r["source"]}
        for g in out.values():
            for name, (num, den, _) in RATIOS.items():
                a, b = g["metrics"].get(num), g["metrics"].get(den)
                if a and b and b["value"]:
                    g["metrics"][name] = {"value": a["value"] / b["value"], "computed": True,
                                          "formula": f"{title(num)} / {title(den)} = {fmt_money(a['value'])} / "
                                                     f"{fmt_money(b['value'])}", "inputs": [a, b]}
        return out

    def companies(self) -> list[dict]:
        rows = self.store.rows("""SELECT company_norm, company, currency, count(DISTINCT period) AS periods
                                  FROM metrics WHERE company_norm != '' GROUP BY company_norm""")
        for r in rows:
            r["periods_list"] = sorted({p["period"] for p in self.store.rows(
                "SELECT DISTINCT period FROM metrics WHERE company_norm=? AND period IS NOT NULL",
                (r["company_norm"],))}, key=period_key)
        return rows

    def metric_names(self) -> list[str]:
        names = [r["name"] for r in self.store.rows("SELECT DISTINCT name FROM metrics")]
        order = list(METRIC_TITLES)
        names.sort(key=lambda n: order.index(n) if n in order else 99)
        facts = self.facts()
        ratios = [r for r in RATIOS if any(r in g["metrics"] for g in facts.values())]
        return names + ratios

    def series(self, metric: str, company_norm: str | None = None) -> list[dict]:
        out = []
        for (cn, period), g in self.facts().items():
            if company_norm and cn != company_norm:
                continue
            f = g["metrics"].get(metric)
            if f:
                out.append({"company": g["company"], "company_norm": cn, "period": period, "currency": g["currency"],
                            "value": f["value"], "fact": strip_inputs(f)})
        out.sort(key=lambda x: (x["company_norm"], period_key(x["period"])))
        return out

    def changes(self) -> list[dict]:
        """Period-over-period change for every company and metric."""
        out = []
        by = defaultdict(list)
        for (cn, period), g in self.facts().items():
            for name, f in g["metrics"].items():
                by[(cn, name)].append((period_key(period), period, f, g))
        for (cn, name), items in by.items():
            items.sort(key=lambda x: x[0])
            for (_, p0, f0, g0), (_, p1, f1, g1) in zip(items, items[1:]):
                if not f0["value"]:
                    continue
                pct = None if name in RATIOS else (f1["value"] - f0["value"]) / abs(f0["value"])
                out.append({"company": g1["company"], "company_norm": cn, "metric": name, "from_period": p0,
                            "to_period": p1, "from": f0["value"], "to": f1["value"], "change": f1["value"] - f0["value"],
                            "pct": pct, "currency": g1["currency"], "evidence": [strip_inputs(f0), strip_inputs(f1)]})
        return out

    def compare(self, metric: str, companies: list[str] | None = None, periods: list[str] | None = None) -> dict:
        rows = [r for r in self.series(metric)
                if (not companies or r["company_norm"] in {norm_name(c) for c in companies})
                and (not periods or r["period"] in periods)]
        currencies = {r["currency"] for r in rows if metric not in RATIOS}
        note = None
        if len(currencies) > 1:
            note = (f"Values are in different currencies ({', '.join(sorted(currencies))}); amounts are not "
                    f"converted. Compare ratios such as gross or net margin instead.")
        return {"metric": metric, "title": title(metric), "is_ratio": metric in RATIOS,
                "is_percent": metric in PERCENT_RATIOS, "rows": rows, "currency_note": note,
                "changes": [c for c in self.changes() if c["metric"] == metric
                            and (not companies or c["company_norm"] in {norm_name(x) for x in companies})]}

    def compare_documents(self, a: str, b: str) -> dict:
        def doc_side(doc_id):
            d = self.store.get_document(doc_id)
            if not d:
                raise KeyError(doc_id)
            metrics = {m["name"]: m for m in self.store.rows("SELECT * FROM metrics WHERE doc_id=?", (doc_id,))}
            ents = {e["norm"]: e for e in self.store.rows(
                "SELECT e.* FROM entities e JOIN mentions m ON m.entity_id = e.id WHERE m.doc_id=?", (doc_id,))}
            inv = self.store.rows("SELECT * FROM invoices WHERE doc_id=?", (doc_id,))
            return d, metrics, ents, inv

        da, ma, ea, ia = doc_side(a)
        db, mb, eb, ib = doc_side(b)
        rows = []
        for name in [n for n in METRIC_TITLES if n in ma or n in mb]:
            va, vb = ma.get(name, {}).get("value"), mb.get(name, {}).get("value")
            rows.append({"metric": name, "title": title(name), "a": va, "b": vb,
                         "diff": (vb - va) if va is not None and vb is not None else None,
                         "pct": ((vb - va) / abs(va)) if va not in (None, 0) and vb is not None else None})
        inv_rows = []
        if ia and ib:
            for f in ("number", "vendor", "customer", "issue_date", "subtotal", "tax", "total"):
                inv_rows.append({"field": f, "a": ia[0][f], "b": ib[0][f], "same": ia[0][f] == ib[0][f]})
        return {"a": da, "b": db, "metrics": rows, "invoice_fields": inv_rows,
                "shared_entities": sorted(ea[k]["name"] for k in ea.keys() & eb.keys()),
                "only_a": sorted(ea[k]["name"] for k in ea.keys() - eb.keys()),
                "only_b": sorted(eb[k]["name"] for k in eb.keys() - ea.keys()),
                "currency_note": None if da["currency"] == db["currency"] else
                f"Different currencies: {da['currency']} vs {db['currency']}. Amounts are not converted."}

    # ------------------------------------------------------------ anomaly rules
    def anomalies(self) -> list[dict]:
        found: list[dict] = []
        docs = {d["id"]: d for d in self.store.rows("SELECT id, filename FROM documents")}

        def ev(doc_id, page, excerpt):
            return {"doc_id": doc_id, "filename": docs.get(doc_id, {}).get("filename"), "page": page, "excerpt": excerpt}

        def add(rule, severity, title_, detail, evidence, entities):
            key = hashlib.sha1(f"{rule}|{title_}".encode()).hexdigest()[:10]
            found.append({"id": key, "rule": rule, "severity": severity, "title": title_, "detail": detail,
                          "evidence": evidence, "entities": entities,
                          "doc_ids": sorted({e["doc_id"] for e in evidence})})

        invoices = self.store.rows("SELECT * FROM invoices")
        # 1. same invoice number in more than one document
        by_num = defaultdict(list)
        for inv in invoices:
            if inv["number_norm"]:
                by_num[inv["number_norm"]].append(inv)
        for num, group in by_num.items():
            if len({g["doc_id"] for g in group}) > 1:
                add("duplicate_invoice", "high", f"Invoice {num} appears in {len(group)} documents",
                    f"The same invoice number from {group[0]['vendor']} was uploaded more than once "
                    f"(total {fmt_money(group[0]['total'], group[0]['currency'])}). Risk of paying it twice.",
                    [ev(g["doc_id"], g["page"], g["excerpt"]) for g in group], [num, group[0]["vendor"]])
        # 2. same vendor + same amount, different number, within 30 days
        by_vendor_total = defaultdict(list)
        for inv in invoices:
            if inv["vendor_norm"] and inv["total"]:
                by_vendor_total[(inv["vendor_norm"], round(inv["total"], 2))].append(inv)
        for (_, total), group in by_vendor_total.items():
            nums = {g["number_norm"] for g in group}
            if len(group) > 1 and len(nums) > 1 and _within_days([g["issue_date"] for g in group], 30):
                add("possible_duplicate_invoice", "medium", f"{group[0]['vendor']} billed {fmt_money(total)} twice",
                    f"Invoices {', '.join(sorted(n for n in nums if n))} have the same vendor and amount within 30 days.",
                    [ev(g["doc_id"], g["page"], g["excerpt"]) for g in group], [group[0]["vendor"]])
        # 3. invoice arithmetic
        for inv in invoices:
            if inv["subtotal"] is not None and inv["tax"] is not None and inv["total"] is not None:
                expected = round(inv["subtotal"] + inv["tax"], 2)
                if abs(expected - inv["total"]) > 0.01:
                    add("invoice_math", "high", f"Invoice {inv['number']} total does not add up",
                        f"Subtotal {fmt_money(inv['subtotal'])} + tax {fmt_money(inv['tax'])} = {fmt_money(expected)}, "
                        f"but the invoice total is {fmt_money(inv['total'])} (difference "
                        f"{fmt_money(inv['total'] - expected)}).",
                        [ev(inv["doc_id"], inv["page"], inv["excerpt"])], [inv["number_norm"], inv["vendor"]])
        # 4. statement arithmetic
        for (cn, period), g in self.facts().items():
            m = g["metrics"]
            if all(k in m for k in ("revenue", "cost_of_revenue", "gross_profit")):
                exp = m["revenue"]["value"] - m["cost_of_revenue"]["value"]
                if abs(exp - m["gross_profit"]["value"]) > max(1.0, abs(exp) * 0.005):
                    add("statement_math", "high", f"{g['company']} {period}: gross profit does not reconcile",
                        f"Revenue {fmt_money(m['revenue']['value'])} − cost of revenue "
                        f"{fmt_money(m['cost_of_revenue']['value'])} = {fmt_money(exp)}, but the statement reports "
                        f"{fmt_money(m['gross_profit']['value'])}.",
                        [ev(m[k]["doc_id"], m[k]["page"], m[k]["excerpt"]) for k in ("revenue", "cost_of_revenue", "gross_profit")],
                        [g["company"]])
            if all(k in m for k in ("total_assets", "total_liabilities", "total_equity")):
                exp = m["total_liabilities"]["value"] + m["total_equity"]["value"]
                if abs(exp - m["total_assets"]["value"]) > max(1.0, abs(exp) * 0.005):
                    add("statement_math", "high", f"{g['company']} {period}: balance sheet does not balance",
                        f"Liabilities + equity = {fmt_money(exp)}, total assets = {fmt_money(m['total_assets']['value'])}.",
                        [ev(m[k]["doc_id"], m[k]["page"], m[k]["excerpt"]) for k in ("total_assets", "total_liabilities", "total_equity")],
                        [g["company"]])
        # 5. large period-over-period swings
        for c in self.changes():
            if c["metric"] not in SWING_METRICS or c["pct"] is None:
                continue
            if c["from"] > 0 > c["to"] or c["from"] < 0 < c["to"]:
                if c["metric"] == "net_income":
                    turned = "a loss" if c["to"] < 0 else "a profit"
                    add("sign_change", "high", f"{c['company']} turned to {turned} in {c['to_period']}",
                        f"Net income went from {fmt_money(c['from'], c['currency'])} ({c['from_period']}) to "
                        f"{fmt_money(c['to'], c['currency'])} ({c['to_period']}).",
                        [ev(e["doc_id"], e["page"], e["excerpt"]) for e in c["evidence"]], [c["company"]])
                continue
            if abs(c["pct"]) < SWING_THRESHOLD:
                continue
            sev = "medium" if abs(c["pct"]) < 0.5 else "high"
            word = "increased" if c["pct"] > 0 else "decreased"
            add("period_swing", sev, f"{c['company']}: {title(c['metric']).lower()} {word} {abs(c['pct']):.0%}",
                f"{title(c['metric'])} went from {fmt_money(c['from'], c['currency'])} ({c['from_period']}) to "
                f"{fmt_money(c['to'], c['currency'])} ({c['to_period']}), a change of {c['pct']:+.1%}.",
                [ev(e["doc_id"], e["page"], e["excerpt"]) for e in c["evidence"]], [c["company"]])
        # 6-8. bank transactions
        txs = self.store.rows("SELECT * FROM transactions ORDER BY date")
        known = {i["vendor_norm"] for i in invoices if i["vendor_norm"]}
        known |= {e["norm"] for e in self.store.rows(
            "SELECT DISTINCT e.norm FROM entities e JOIN mentions m ON m.entity_id = e.id "
            "JOIN documents d ON d.id = m.doc_id WHERE d.doc_type = 'contract'")}
        pairs = defaultdict(list)
        for t in txs:
            if t["direction"] != "debit":
                continue
            pairs[(t["counterparty_norm"], round(t["amount"], 2))].append(t)
            reasons = []
            if t["amount"] >= 1000 and t["counterparty_norm"] not in known and not t["category"]:
                reasons.append("no invoice or contract on file for this counterparty")
            d = date.fromisoformat(t["date"])
            if d.weekday() >= 5 and t["amount"] >= 1000 and not t["category"]:
                reasons.append(f"made on a {d.strftime('%A')}")
            if t["amount"] >= 10000 and t["amount"] % 1000 == 0:
                reasons.append("large round amount")
            if reasons and (len(reasons) >= 2 or "no invoice" in reasons[0]):
                add("suspicious_payment", "high" if len(reasons) >= 2 else "medium",
                    f"Payment of {fmt_money(t['amount'], t['currency'])} to {t['counterparty']}",
                    f"{t['date']}: " + "; ".join(reasons) + ".", [ev(t["doc_id"], t["page"], t["excerpt"])],
                    [t["counterparty"]])
        for (_, amount), group in pairs.items():
            if group[0]["category"]:
                continue  # payroll / rent / tax repeat by design
            if len(group) > 1 and _within_days([g["date"] for g in group], 45):
                add("duplicate_payment", "high", f"{group[0]['counterparty']} paid {fmt_money(amount)} {len(group)} times",
                    "Same counterparty and same amount on " + ", ".join(g["date"] for g in group) +
                    ". Check whether one invoice was paid twice.",
                    [ev(g["doc_id"], g["page"], g["excerpt"]) for g in group], [group[0]["counterparty"]])
        # 9. statistical outlier per counterparty (only with enough history)
        hist = defaultdict(list)
        for t in txs:
            if t["direction"] == "debit":
                hist[t["counterparty_norm"]].append(t)
        for _, group in hist.items():
            if len(group) >= 5:
                vals = [g["amount"] for g in group]
                mu, sd = statistics.mean(vals), statistics.pstdev(vals)
                for g in group:
                    if sd and abs(g["amount"] - mu) / sd > 3:
                        add("amount_outlier", "medium", f"Unusual amount to {g['counterparty']}",
                            f"{fmt_money(g['amount'])} is more than 3 standard deviations from the usual "
                            f"{fmt_money(mu)}.", [ev(g["doc_id"], g["page"], g["excerpt"])], [g["counterparty"]])
        order = {"high": 0, "medium": 1, "low": 2}
        return sorted(found, key=lambda a: order[a["severity"]])

    # ------------------------------------------------------------ dashboard + summary
    def overview(self) -> dict:
        facts = self.facts()
        latest: dict[str, dict] = {}
        for (cn, period), g in facts.items():
            if cn not in latest or period_key(period) > period_key(latest[cn]["period"]):
                latest[cn] = g
        kpis = []
        for cn, g in latest.items():
            m = g["metrics"]
            kpis.append({"company": g["company"], "company_norm": cn, "period": g["period"], "currency": g["currency"],
                         "values": {k: m[k]["value"] for k in ("revenue", "net_income", "gross_margin", "net_margin",
                                                                "total_assets", "current_ratio", "debt_to_equity")
                                    if k in m}})
        inv = self.store.row("SELECT count(*) AS n, sum(total) AS total FROM invoices")
        tx = self.store.row("SELECT count(*) AS n, sum(CASE WHEN direction='debit' THEN amount END) AS out, "
                            "sum(CASE WHEN direction='credit' THEN amount END) AS inflow FROM transactions")
        return {"kpis": kpis, "invoices": inv, "transactions": tx, "changes": self.changes()}

    def fact_sheet(self) -> list[str]:
        """Deterministic key findings. Also the only material the LLM may use for the narrative summary."""
        lines = []
        for k in self.overview()["kpis"]:
            v = k["values"]
            bits = [f"{title(n).lower()} {fmt_pct_or_money(n, v[n], k['currency'])}" for n in
                    ("revenue", "net_income", "gross_margin", "net_margin") if n in v]
            if bits:
                lines.append(f"{k['company']} ({k['period']}): " + ", ".join(bits) + ".")
        for c in self.changes():
            if c["metric"] in ("revenue", "net_income", "operating_expenses", "marketing") and c["pct"] is not None:
                if c["from"] > 0 > c["to"] or c["from"] < 0 < c["to"]:  # % change is meaningless across zero
                    lines.append(f"{c['company']} {title(c['metric']).lower()} went from {fmt_money(c['from'])} in "
                                 f"{c['from_period']} to {fmt_money(c['to'])} in {c['to_period']}.")
                    continue
                lines.append(f"{c['company']} {title(c['metric']).lower()} changed {c['pct']:+.1%} from "
                             f"{c['from_period']} to {c['to_period']} ({fmt_money(c['from'])} → {fmt_money(c['to'])}).")
        an = self.anomalies()
        if an:
            lines.append(f"{len(an)} anomalies detected ({sum(a['severity'] == 'high' for a in an)} high severity): "
                         + "; ".join(a["title"] for a in an[:4]) + ".")
        return lines

    def summary(self, llm: ChatModel | None) -> dict:
        facts = self.fact_sheet()
        if not facts:
            return {"bullets": [], "source": "empty", "facts": []}
        if llm is None:
            return {"bullets": facts, "source": "rules", "facts": facts}
        allowed = set().union(*(number_tokens(f) for f in facts))
        try:
            text = llm.complete(
                "You are a financial analyst. Write an executive summary of 3 to 5 bullet points using ONLY the "
                "facts provided. Do not add numbers that are not in the facts. Start each bullet with '- '.",
                "FACTS:\n" + "\n".join(f"- {f}" for f in facts), temperature=0.1)
        except ModelError:
            return {"bullets": facts, "source": "rules (LLM unavailable)", "facts": facts}
        bullets = [b.strip()[2:].strip() for b in text.split("\n") if b.strip().startswith(("- ", "* "))]
        used = set().union(*(number_tokens(b) for b in bullets)) if bullets else set()
        unknown = {n for n in used if n not in allowed and n >= 100 and not _pct_like(n, allowed)}
        if not bullets or unknown:
            return {"bullets": facts, "source": "rules (LLM summary rejected: unverified numbers)", "facts": facts}
        return {"bullets": bullets, "source": "llm (numbers verified against fact sheet)", "facts": facts}


def _pct_like(n: float, allowed: set[float]) -> bool:
    return any(abs(n - a) < 0.051 for a in allowed)


def fmt_pct_or_money(metric: str, value: float, currency: str | None) -> str:
    if metric in PERCENT_RATIOS:
        return f"{value:.1%}"
    if metric in RATIOS:
        return f"{value:.2f}"
    return fmt_money(value, currency)


def strip_inputs(f: dict) -> dict:
    return {k: v for k, v in f.items() if k != "inputs"} | (
        {"inputs": [{k: v for k, v in i.items() if k != "inputs"} for i in f["inputs"]]} if "inputs" in f else {})


def _within_days(dates: list[str | None], days: int) -> bool:
    ds = sorted(date.fromisoformat(d) for d in dates if d)
    if len(ds) < 2:
        return True  # undated duplicates are still suspicious
    return any((b - a).days <= days for a, b in zip(ds, ds[1:]))
