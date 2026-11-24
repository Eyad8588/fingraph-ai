"""Financial extraction: rules first, the LLM proposes, code verifies.

1. Deterministic rules extract statement line items, invoice fields and bank transactions, each with
   the page and the exact source line (excerpt).
2. The LLM classifies the document and proposes entities, relations and a one-line summary. It may also
   propose metrics, but only where the rules found none.
3. Grounding check: an LLM-proposed number is accepted only if it literally appears in the source text;
   an LLM-proposed entity is accepted only if its name appears in the text.
"""

from __future__ import annotations

import json
import re

from .models import ChatModel, ModelError
from .parsing import Page
from .textutil import (detect_currency, find_dates, find_orgs, find_period, norm_id, norm_name,
                       number_tokens, parse_amount, parse_date)

# canonical metric -> labels as they appear in statements (matched against the whole line label)
METRIC_LABELS: dict[str, list[str]] = {
    "revenue": ["total revenue", "revenue", "revenues", "net revenue", "net sales", "sales", "turnover", "total sales"],
    "cost_of_revenue": ["cost of goods sold", "cost of revenue", "cost of sales", "cogs"],
    "gross_profit": ["gross profit", "gross margin amount"],
    "salaries": ["salaries", "salaries and wages", "payroll", "staff costs"],
    "marketing": ["marketing", "marketing and advertising", "advertising", "sales and marketing"],
    "rent": ["rent", "rent and utilities", "occupancy"],
    "logistics": ["logistics", "freight", "shipping and logistics", "distribution"],
    "operating_expenses": ["total operating expenses", "operating expenses", "total opex", "opex"],
    "operating_income": ["operating income", "operating profit", "ebit", "income from operations"],
    "interest_expense": ["interest expense", "finance costs"],
    "income_tax": ["income tax", "income tax expense", "zakat and income tax", "zakat", "tax expense"],
    "net_income": ["net income", "net profit", "profit for the period", "net loss", "net income (loss)"],
    "cash": ["cash and cash equivalents", "cash"],
    "accounts_receivable": ["accounts receivable", "trade receivables", "receivables"],
    "inventory": ["inventory", "inventories"],
    "current_assets": ["total current assets", "current assets"],
    "total_assets": ["total assets"],
    "accounts_payable": ["accounts payable", "trade payables", "payables"],
    "current_liabilities": ["total current liabilities", "current liabilities"],
    "long_term_debt": ["long-term debt", "long term debt", "long-term loans", "borrowings"],
    "total_liabilities": ["total liabilities"],
    "total_equity": ["total equity", "shareholders' equity", "shareholders equity", "total shareholders' equity",
                     "owners' equity"],
}
LABEL_TO_METRIC = {lbl: m for m, labels in METRIC_LABELS.items() for lbl in labels}
METRIC_TITLES = {m: m.replace("_", " ").capitalize() for m in METRIC_LABELS}
METRIC_TITLES.update({"cost_of_revenue": "Cost of revenue", "net_income": "Net income", "total_equity": "Total equity"})

# shown as (1,234) or -1,234 in statements, stored as positive costs
EXPENSE_METRICS = {"cost_of_revenue", "salaries", "marketing", "rent", "logistics", "operating_expenses",
                   "interest_expense", "income_tax"}

DOC_TYPES = ["income_statement", "balance_sheet", "cash_flow", "invoice", "bank_statement", "contract",
             "purchase_order", "report", "other"]
ENTITY_TYPES = {"company", "vendor", "customer", "bank", "organization", "person", "contract", "product"}

LINE_ITEM_RE = re.compile(r"^\s*(?P<label>[A-Za-z][A-Za-z '&/\-()]*?[A-Za-z)])\s*(?:\||:|\.{2,}|\s{2,}|\s)\s*"
                          r"(?P<rest>[(\-−]?\s*(?:USD|SAR|EUR|GBP|US\$|SR|\$|€|£)?\s?\d[\d,]*(?:\.\d+)?.*)$")


def clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\(.*?\)", "", label)).strip(" .:-").lower()


# ---------------------------------------------------------------- document type (rules)
def guess_doc_type(text: str) -> str | None:
    t = text[:2500].lower()
    if re.search(r"\binvoice\b", t) and re.search(r"\b(total|amount due)\b", t):
        return "invoice"
    if re.search(r"bank statement|statement of account|account statement", t):
        return "bank_statement"
    if re.search(r"balance sheet|statement of financial position", t):
        return "balance_sheet"
    if re.search(r"income statement|profit (and|&) loss|statement of (comprehensive )?income|p&l", t):
        return "income_statement"
    if re.search(r"cash flow", t):
        return "cash_flow"
    if re.search(r"\bagreement\b|\bcontract\b|terms and conditions", t):
        return "contract"
    if re.search(r"purchase order", t):
        return "purchase_order"
    if re.search(r"memo|report|minutes|summary", t):
        return "report"
    return None


def main_company(text: str, doc_type: str | None) -> str | None:
    """The reporting company: first organisation in the header, skipping the 'Bill To' party on invoices."""
    holder = re.search(r"account\s+holder\s*:?\s*([^\n]+)", text, re.I)
    if holder:
        orgs = find_orgs(holder.group(1))
        if orgs:
            return orgs[0]
    head = "\n".join(text.split("\n")[:15])
    orgs = find_orgs(head) or find_orgs(text[:4000])
    if doc_type == "invoice":
        return None
    return orgs[0] if orgs else None


# ---------------------------------------------------------------- statements
def statement_metrics(pages: list[Page], company: str | None, period: str | None, currency: str) -> list[dict]:
    out, seen = [], set()
    for p in pages:
        for line in p.text.split("\n"):
            m = LINE_ITEM_RE.match(line.strip())
            if not m:
                continue
            label = clean_label(m.group("label"))
            metric = LABEL_TO_METRIC.get(label)
            if not metric or metric in seen:
                continue
            value = parse_amount(m.group("rest"))  # current period is the first column
            if value is None:
                continue
            if metric in EXPENSE_METRICS:
                value = abs(value)
            elif metric == "net_income" and "loss" in label and value > 0:
                value = -value
            seen.add(metric)
            out.append({"name": metric, "label": m.group("label").strip(), "value": value, "company": company,
                        "period": period, "currency": currency, "page": p.page, "excerpt": line.strip(),
                        "source": "rules"})
    return out


# ---------------------------------------------------------------- invoices
def _field(text: str, pattern: str) -> re.Match | None:
    return re.search(pattern, text, re.I | re.M)


def invoice_fields(pages: list[Page], currency: str) -> dict | None:
    text = "\n".join(p.text for p in pages)
    num = _field(text, r"invoice\s*(?:no\.?|number|#|num)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{2,})")
    total_m = _field(text, r"^\s*(?:invoice\s+)?(?:total\s+due|total\s+amount|amount\s+due|grand\s+total|total)\b[^\n\d]*([\d,]+\.\d{2}|[\d,]{4,})")
    if not num and not total_m:
        return None

    def money(pattern: str) -> float | None:
        m = _field(text, pattern)
        return float(m.group(1).replace(",", "")) if m else None

    subtotal = money(r"^\s*sub\s*-?\s*total\b[^\n\d]*([\d,]+\.\d{2}|[\d,]{4,})")
    tax = money(r"^\s*(?:vat|tax|sales tax)\b[^\n]*?([\d,]+\.\d{2})\s*$")
    total = float(total_m.group(1).replace(",", "")) if total_m else None
    vendor = customer = None
    bill = _field(text, r"bill(?:ed)?\s+to\s*:?\s*\n?\s*([^\n]+)")
    if bill:
        orgs = find_orgs(bill.group(1))
        customer = orgs[0] if orgs else bill.group(1).strip()
    frm = _field(text, r"^\s*(?:from|vendor|supplier|issued by)\s*:?\s*([^\n]+)")
    if frm:
        orgs = find_orgs(frm.group(1))
        vendor = orgs[0] if orgs else frm.group(1).strip()
    if not vendor:
        orgs = [o for o in find_orgs(text[:1500]) if norm_name(o) != norm_name(customer or "")]
        vendor = orgs[0] if orgs else None
    issue = _field(text, r"(?:invoice\s+date|issue\s+date|date\s+issued|^\s*date)\s*:?\s*([^\n]+)")
    due = _field(text, r"due\s+date\s*:?\s*([^\n]+)")

    def iso(m):
        if not m:
            return None
        d = find_dates(m.group(1)) or ([parse_date(m.group(1).strip())] if parse_date(m.group(1).strip()) else [])
        return d[0].isoformat() if d else None

    page = next((p.page for p in pages if num and num.group(1) in p.text), pages[0].page)
    excerpt_lines = [line.strip() for line in text.split("\n")
                     if re.search(r"invoice|total|subtotal|tax|vat|bill to|due", line, re.I)][:8]
    return {"number": num.group(1) if num else None, "number_norm": norm_id(num.group(1)) if num else None,
            "vendor": vendor, "customer": customer, "issue_date": iso(issue), "due_date": iso(due),
            "subtotal": subtotal, "tax": tax, "total": total, "currency": currency, "page": page,
            "excerpt": "\n".join(excerpt_lines)}


# ---------------------------------------------------------------- bank transactions
TX_RE = re.compile(r"^\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\s+"
                   r"(?P<desc>.+?)\s+(?P<amount>[-−+]?\(?[\d,]+\.\d{2}\)?)(?:\s+(?P<balance>[-−]?[\d,]+\.\d{2}))?\s*$")
TX_PREFIX = re.compile(r"^(?:ach|wire|transfer|payment|card|pos|direct debit|dd|sepa|eft|incoming|outgoing|"
                       r"received|deposit|to|from|ref|purchase|customer|rent|supplier)\b[\s:\-]*", re.I)
TX_SKIP = re.compile(r"\b(opening|closing|brought forward|carried forward)\s+balance\b", re.I)
# internal / recurring categories: no counterparty entity, not 'unknown vendor' candidates
TX_CATEGORY = [("payroll", r"\b(payroll|salar(y|ies)|wages)\b"), ("tax", r"\b(tax|vat|zakat)\s+payment\b"),
               ("fees", r"\b(bank fee|service charge|fee)\b"), ("interest", r"\binterest\b"),
               ("rent", r"\brent\b"), ("loan", r"\bloan\b")]


def tx_category(desc: str) -> str | None:
    for name, pat in TX_CATEGORY:
        if re.search(pat, desc, re.I):
            return name
    return None


def counterparty_of(desc: str) -> str:
    d = desc.strip()
    for _ in range(4):
        d2 = TX_PREFIX.sub("", d)
        if d2 == d:
            break
        d = d2
    d = re.split(r"\s+(?:ref|reference|inv|invoice)\b[\s:#.\-]*|\s+INV-|\s+#", d, flags=re.I)[0]
    return d.strip(" -:,.") or desc.strip()


def bank_transactions(pages: list[Page], holder: str | None, currency: str) -> list[dict]:
    out = []
    for p in pages:
        for line in p.text.split("\n"):
            m = TX_RE.match(line)
            if not m:
                continue
            d = parse_date(m.group("date"))
            if not d:
                continue
            raw = m.group("amount").replace("−", "-")
            amount = float(raw.strip("()+-").replace(",", ""))
            desc = m.group("desc").strip()
            if TX_SKIP.search(desc):
                continue
            debit = raw.startswith("-") or raw.startswith("(") or bool(
                re.search(r"\b(payment to|wire transfer to|transfer to|card|debit|fee)\b", desc, re.I))
            if re.search(r"\b(deposit|received|incoming|from customer|credit)\b", desc, re.I) and not raw.startswith("-"):
                debit = False
            category = tx_category(desc)
            out.append({"date": d.isoformat(), "description": desc, "category": category,
                        "counterparty": "Payroll" if category == "payroll" else counterparty_of(desc),
                        "amount": amount, "direction": "debit" if debit else "credit", "currency": currency,
                        "account_holder": holder, "page": p.page, "excerpt": line.strip()})
    return out


# ---------------------------------------------------------------- LLM proposal + grounding
LLM_SYSTEM = """You extract structured data from ONE financial document. Reply with JSON only:
{"doc_type": one of %s,
 "company": "the organisation this document belongs to (reporting company, account holder, or invoice customer)",
 "entities": [{"name": "...", "type": "company|vendor|customer|bank|person|contract|product"}],
 "relations": [{"source": "...", "relation": "short_verb_phrase", "target": "..."}],
 "metrics": [{"name": "revenue|net_income|...", "value": 123.45}],
 "summary": "one factual sentence"}
Rules: use names exactly as written in the text; only include facts stated in the text; at most 12 entities
and 12 relations; relations connect entity names from your list (e.g. "Nova Retail Ltd" "has_contract_with"
"Atlas Logistics LLC"). Leave metrics empty unless the text states them.""" % DOC_TYPES


def llm_proposal(llm: ChatModel, text: str, filename: str) -> dict:
    raw = llm.complete(LLM_SYSTEM, f"File: {filename}\nTEXT:\n{text[:9000]}", json_out=True, temperature=0)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    return data if isinstance(data, dict) else {}


LINE_ITEM_WORDS = re.compile(r"\b(cash|assets?|liabilit|receivable|payable|inventor|equipment|equity|revenue|expense|"
                             r"income|profit|debt|capital|depreciation)\b", re.I)
NOT_PERSON = re.compile(r"\b(team|finance|department|board|committee|directors?|management|office|group)\b", re.I)


def plausible_entity(name: str, etype: str) -> bool:
    """Reject the typical small-model mistakes: line items as 'products', departments as 'people'."""
    if len(name) < 3 or len(name) > 80 or LABEL_TO_METRIC.get(clean_label(name)):
        return False
    if etype == "product" and LINE_ITEM_WORDS.search(name):
        return False
    if etype == "person" and (NOT_PERSON.search(name) or len(name.split()) < 2):
        return False
    return True


def grounded_name(name: str, text_norm: str) -> bool:
    n = norm_name(name)
    return len(n) >= 3 and f" {n} " in f" {text_norm} "


def grounded_number(value, text_numbers: set[float]) -> bool:
    try:
        return round(float(value), 2) in text_numbers
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------- orchestration
def extract(pages: list[Page], filename: str, llm: ChatModel | None) -> dict:
    text = "\n".join(p.text for p in pages)
    currency = detect_currency(text)
    doc_type = guess_doc_type(text)
    period = find_period(text)
    company = main_company(text, doc_type)
    warnings: list[str] = []

    metrics = statement_metrics(pages, company, period, currency) if doc_type in (
        "income_statement", "balance_sheet", "cash_flow", None, "report") else []
    invoice = invoice_fields(pages, currency) if doc_type in ("invoice", None) else None
    if invoice and doc_type is None:
        doc_type = "invoice"
    if doc_type == "invoice" and invoice:
        company = invoice.get("customer")
        if invoice.get("issue_date") and not period:
            from datetime import date
            d = date.fromisoformat(invoice["issue_date"])
            period = f"Q{(d.month - 1) // 3 + 1} {d.year}"
    transactions = bank_transactions(pages, company, currency) if doc_type in ("bank_statement", None) else []
    if transactions and doc_type is None:
        doc_type = "bank_statement"

    proposal: dict = {}
    if llm is not None:
        try:
            proposal = llm_proposal(llm, text, filename)
        except (ModelError, ValueError) as e:
            warnings.append(f"LLM extraction unavailable: {e}")
    text_norm = norm_name(text)
    numbers = number_tokens(text)

    if not doc_type and proposal.get("doc_type") in DOC_TYPES:
        doc_type = proposal["doc_type"]
    if not company and proposal.get("company") and grounded_name(proposal["company"], text_norm):
        company = proposal["company"]
    for m in metrics:
        m["company"] = m["company"] or company
    # LLM may only fill metrics the rules did not find, and only with numbers present in the text
    have = {m["name"] for m in metrics}
    for m in proposal.get("metrics") or []:
        name = str(m.get("name", "")).strip().lower().replace(" ", "_")
        if name in METRIC_LABELS and name not in have and grounded_number(m.get("value"), numbers):
            metrics.append({"name": name, "label": METRIC_TITLES.get(name, name), "value": float(m["value"]),
                            "company": company, "period": period, "currency": currency, "page": pages[0].page,
                            "excerpt": _line_with(text, m["value"]), "source": "llm-verified"})
            have.add(name)

    entities, edges = build_graph(doc_type, company, period, invoice, transactions, text, pages)
    names = {norm_name(e["name"]) for e in entities}
    llm_entities = {}
    for e in (proposal.get("entities") or [])[:12]:
        name, etype = str(e.get("name", "")).strip(), str(e.get("type", "organization")).lower()
        etype = etype if etype in ENTITY_TYPES else "organization"
        # rules own the 'company' role (reporting company / account holder); the LLM can only say organization
        etype = "organization" if etype == "company" else etype
        if not plausible_entity(name, etype):
            continue
        if grounded_name(name, text_norm) and norm_name(name) not in names:
            entities.append({"name": name, "type": etype, "page": _page_of(pages, name), "excerpt": _line_with(text, name)})
            names.add(norm_name(name))
        if grounded_name(name, text_norm):
            llm_entities[norm_name(name)] = (name, etype)
    type_of = {norm_name(e["name"]): e["type"] for e in entities}
    for r in (proposal.get("relations") or [])[:12]:
        s, t = str(r.get("source", "")), str(r.get("target", ""))
        rel = re.sub(r"[^a-z_]", "", str(r.get("relation", "related_to")).lower().replace(" ", "_"))[:40] or "related_to"
        if norm_name(s) in type_of and norm_name(t) in type_of:
            edges.append({"src": s, "src_type": type_of[norm_name(s)], "dst": t, "dst_type": type_of[norm_name(t)],
                          "relation": rel, "page": _page_of(pages, t), "excerpt": _line_with(text, t)})

    summary = proposal.get("summary") if isinstance(proposal.get("summary"), str) else None
    if summary and not all(grounded_number(n, numbers) or n < 100 for n in number_tokens(summary)):
        summary = None  # the summary mentions a number that is not in the document
    return {"doc_type": doc_type or "other", "company": company, "period": period, "currency": currency,
            "summary": summary or default_summary(doc_type, company, period, invoice, metrics, transactions),
            "metrics": metrics, "invoices": [invoice] if invoice else [], "transactions": transactions,
            "entities": entities, "edges": edges, "warnings": warnings, "llm_used": bool(proposal)}


def build_graph(doc_type, company, period, invoice, transactions, text, pages):
    """Structural graph facts that come from the rules, not the LLM."""
    entities: list[dict] = []
    edges: list[dict] = []

    def ent(name, etype, excerpt=""):
        if name and all(norm_name(e["name"]) != norm_name(name) or e["type"] != etype for e in entities):
            entities.append({"name": name, "type": etype, "page": _page_of(pages, name),
                             "excerpt": excerpt or _line_with(text, name)})

    if company:
        ent(company, "company")
    if period:
        ent(period, "period", f"Reporting period: {period}")
        if company and doc_type in ("income_statement", "balance_sheet", "cash_flow", "bank_statement", "report"):
            edges.append({"src": company, "src_type": "company", "dst": period, "dst_type": "period",
                          "relation": "reported_for", "excerpt": text.strip().split("\n")[0][:200]})
    if invoice and invoice.get("number"):
        num = invoice["number_norm"] or invoice["number"]
        ent(num, "invoice", invoice["excerpt"])
        if invoice.get("vendor"):
            ent(invoice["vendor"], "vendor")
            edges.append({"src": invoice["vendor"], "src_type": "vendor", "dst": num, "dst_type": "invoice",
                          "relation": "issued", "amount": invoice.get("total"), "excerpt": invoice["excerpt"],
                          "page": invoice["page"]})
        if invoice.get("customer"):
            ent(invoice["customer"], "company")
            edges.append({"src": num, "src_type": "invoice", "dst": invoice["customer"], "dst_type": "company",
                          "relation": "billed_to", "amount": invoice.get("total"), "excerpt": invoice["excerpt"],
                          "page": invoice["page"]})
        if period:
            edges.append({"src": num, "src_type": "invoice", "dst": period, "dst_type": "period",
                          "relation": "in_period", "excerpt": f"Issued {invoice.get('issue_date')}"})
    if doc_type == "contract":
        orgs = find_orgs(text)
        for o in orgs[:4]:
            ent(o, "company" if company and norm_name(o) == norm_name(company) else "vendor")
        others = [o for o in orgs if not company or norm_name(o) != norm_name(company)]
        if company and others:
            m = re.search(r"[^\n.]*(?:agreement|contract)[^\n.]*", text, re.I)
            edges.append({"src": company, "src_type": "company", "dst": others[0], "dst_type": "vendor",
                          "relation": "has_contract_with", "excerpt": m.group(0).strip()[:300] if m else ""})
    for t in transactions:
        if not company or not t["counterparty"] or t.get("category") in ("payroll", "tax", "fees", "interest"):
            continue
        ent(t["counterparty"], "vendor" if t["direction"] == "debit" else "customer", t["excerpt"])
        src, dst = (company, t["counterparty"]) if t["direction"] == "debit" else (t["counterparty"], company)
        st, dt = ("company", "vendor") if t["direction"] == "debit" else ("customer", "company")
        edges.append({"src": src, "src_type": st, "dst": dst, "dst_type": dt, "relation": "paid",
                      "amount": t["amount"], "date": t["date"], "excerpt": t["excerpt"], "page": t["page"]})
    return entities, edges


def _line_with(text: str, needle) -> str:
    n = str(needle)
    variants = {n, n.lower()}
    try:
        f = float(n)
        variants |= {f"{f:,.2f}", f"{f:,.0f}", f"{f:.2f}"}
    except ValueError:
        pass
    for line in text.split("\n"):
        if any(v and v in line or v in line.lower() for v in variants):
            return line.strip()[:300]
    return ""


def _page_of(pages: list[Page], needle: str) -> int:
    for p in pages:
        if needle and needle.lower() in p.text.lower():
            return p.page
    return pages[0].page if pages else 1


def default_summary(doc_type, company, period, invoice, metrics, transactions) -> str:
    kind = (doc_type or "document").replace("_", " ")
    if invoice:
        return (f"Invoice {invoice.get('number')} from {invoice.get('vendor')} to {invoice.get('customer')} "
                f"for {invoice.get('currency')} {invoice.get('total'):,.2f}." if invoice.get("total") else
                f"Invoice {invoice.get('number')}.")
    if transactions:
        return f"Bank statement for {company or 'the account holder'} with {len(transactions)} transactions."
    base = f"{kind.capitalize()} for {company or 'unknown company'}" + (f", {period}" if period else "")
    return base + (f", {len(metrics)} line items extracted." if metrics else ".")
