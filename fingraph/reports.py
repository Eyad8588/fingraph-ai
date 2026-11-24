"""Exportable financial report (Markdown / HTML) and CSV exports."""

from __future__ import annotations

import csv
import html
import io
import time

from .finance import Finance, fmt_pct_or_money, title
from .store import Store
from .textutil import fmt_money


def markdown_report(store: Store, finance: Finance, summary: dict) -> str:
    out = ["# FinGraph AI · Financial intelligence report",
           f"_Generated {time.strftime('%Y-%m-%d %H:%M')} from {store.scalar('SELECT count(*) FROM documents WHERE status IN (\"ready\",\"limited\")')} "
           "documents. Synthetic data._", "", "## Key findings"]
    out += [f"- {b}" for b in summary["bullets"]] or ["- No findings yet."]
    out += ["", f"_Summary source: {summary['source']}_", "", "## Metrics by company and period"]
    for c in finance.companies():
        out += ["", f"### {c['company']} ({c['currency']})", ""]
        periods = c["periods_list"]
        names = finance.metric_names()
        facts = finance.facts()
        out.append("| Metric | " + " | ".join(periods) + " |")
        out.append("|---|" + "---|" * len(periods))
        for n in names:
            vals = [facts.get((c["company_norm"], p), {}).get("metrics", {}).get(n) for p in periods]
            if any(vals):
                out.append(f"| {title(n)} | " + " | ".join(
                    fmt_pct_or_money(n, v["value"], None) if v else "–" for v in vals) + " |")
    out += ["", "## Anomalies", ""]
    an = finance.anomalies()
    if not an:
        out.append("None detected.")
    for a in an:
        out.append(f"- **[{a['severity'].upper()}] {a['title']}**: {a['detail']}")
        for e in a["evidence"]:
            out.append(f"  - _{e['filename']}, p.{e['page']}_: `{(e['excerpt'] or '').splitlines()[0][:120]}`")
    out += ["", "## Invoices", "", "| Number | Vendor | Customer | Date | Total |", "|---|---|---|---|---|"]
    for i in store.rows("SELECT * FROM invoices ORDER BY issue_date"):
        out.append(f"| {i['number']} | {i['vendor']} | {i['customer']} | {i['issue_date'] or ''} | "
                   f"{fmt_money(i['total'], i['currency'])} |")
    out += ["", "## Source documents", ""]
    for d in store.rows("SELECT * FROM documents ORDER BY created_at"):
        out.append(f"- {d['filename']}: {d['doc_type']}, {d['company'] or ''} {d['period'] or ''} ({d['status']})")
    return "\n".join(out) + "\n"


def html_report(md: str) -> str:
    """Tiny Markdown-to-HTML for our own report format (headings, lists, tables, bold, code). Printable to PDF."""
    lines, body, in_table, in_list = md.split("\n"), [], False, False

    def inline(t: str) -> str:
        import re
        t = html.escape(t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
        return re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<em>\1</em>", t)

    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
                body.append("<tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
            else:
                body.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith(("- ", "  - ")):
            if not in_list:
                body.append("<ul>")
                in_list = True
            cls = ' class="sub"' if line.startswith("  ") else ""
            body.append(f"<li{cls}>{inline(line.strip()[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if line.startswith("### "):
            body.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.strip():
            body.append(f"<p>{inline(line)}</p>")
    if in_table:
        body.append("</table>")
    if in_list:
        body.append("</ul>")
    css = """body{font:14px/1.55 -apple-system,Segoe UI,Inter,sans-serif;max-width:900px;margin:40px auto;padding:0 24px;color:#111827}
h1{font-size:26px}h2{margin-top:32px;border-bottom:1px solid #e5e7eb;padding-bottom:6px}table{border-collapse:collapse;width:100%;margin:8px 0}
td,th{border:1px solid #e5e7eb;padding:6px 10px;text-align:left}th{background:#f9fafb}code{background:#f3f4f6;padding:1px 4px;border-radius:4px;font-size:12px}
li.sub{list-style:circle;margin-left:20px;color:#4b5563}@media print{body{margin:0}}"""
    return f"<!doctype html><html><head><meta charset='utf-8'><title>FinGraph report</title><style>{css}</style></head><body>{''.join(body)}</body></html>"


def metrics_csv(store: Store) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["company", "period", "metric", "value", "currency", "source_file", "page", "excerpt", "extracted_by"])
    for r in store.rows("SELECT m.*, d.filename FROM metrics m JOIN documents d ON d.id = m.doc_id "
                        "ORDER BY m.company, m.period, m.name"):
        w.writerow([r["company"], r["period"], r["name"], r["value"], r["currency"], r["filename"], r["page"],
                    r["excerpt"], r["source"]])
    return buf.getvalue()


def anomalies_csv(finance: Finance) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["severity", "rule", "title", "detail", "documents"])
    for a in finance.anomalies():
        w.writerow([a["severity"], a["rule"], a["title"], a["detail"], "; ".join(e["filename"] or "" for e in a["evidence"])])
    return buf.getvalue()
