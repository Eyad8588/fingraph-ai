"""Question router + deterministic calculator.

Labels a question 'doc' (answer from text), 'metric' (needs verified numbers) or 'both', resolves the
companies / periods / metrics it mentions, checks they exist (scope check), and computes the numbers in
Python. The LLM later only explains these results; it never does the arithmetic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .extract import METRIC_LABELS
from .finance import PERCENT_RATIOS, RATIOS, Finance, title
from .textutil import fmt_money, norm_name, period_key

METRIC_WORDS: dict[str, list[str]] = {m: sorted(set(labels), key=len, reverse=True) for m, labels in METRIC_LABELS.items()}
METRIC_WORDS["revenue"] += ["revenues", "sales", "top line", "income from sales"]
METRIC_WORDS["net_income"] += ["profit", "net profit", "bottom line", "earnings"]
METRIC_WORDS["operating_expenses"] += ["opex", "expenses", "operating costs"]
METRIC_WORDS["gross_margin"] = ["gross margin", "gross profit margin"]
METRIC_WORDS["net_margin"] = ["net margin", "profit margin", "net profit margin"]
METRIC_WORDS["operating_margin"] = ["operating margin"]
METRIC_WORDS["current_ratio"] = ["current ratio", "liquidity ratio"]
METRIC_WORDS["debt_to_equity"] = ["debt to equity", "debt-to-equity", "leverage", "gearing"]

CALC_WORDS = re.compile(r"\b(compare|comparison|vs\.?|versus|change|changed|growth|grow|grew|increase|decrease|"
                        r"drop|differ|difference|higher|lower|more|less|ratio|margin|percent|%|total|sum|trend|"
                        r"how much|what was|what is|what's)\b", re.I)
FOLLOW_UP = re.compile(r"^\s*(and|what about|how about|also|then|same for|it|its|they|their|that|those|"
                       r"this|these|why|and in|for)\b", re.I)
QUARTER_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4}


@dataclass
class Fact:
    label: str
    value: float
    display: str
    doc_id: str | None = None
    filename: str | None = None
    page: int | None = None
    excerpt: str | None = None
    chunk_id: int | None = None


@dataclass
class Route:
    route: str  # doc | metric | both
    metrics: list[str] = field(default_factory=list)
    companies: list[dict] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    calculations: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {"route": self.route, "metrics": self.metrics, "companies": [c["company"] for c in self.companies],
                "periods": self.periods, "calculations": self.calculations, "missing": self.missing,
                "notes": self.notes, "facts": [f.__dict__ for f in self.facts]}


def looks_like_follow_up(q: str) -> bool:
    return bool(FOLLOW_UP.match(q)) or len(q.split()) <= 4


def find_metrics(q: str) -> list[str]:
    ql = f" {q.lower()} "
    found: list[tuple[int, str]] = []
    taken: list[tuple[int, int]] = []
    for metric, words in sorted(METRIC_WORDS.items(), key=lambda kv: -max(len(w) for w in kv[1])):
        for w in words:
            for m in re.finditer(rf"(?<![a-z]){re.escape(w)}(?:s|es)?(?![a-z])", ql):
                span = (m.start(), m.end())
                if any(a < span[1] and span[0] < b for a, b in taken):
                    continue
                taken.append(span)
                found.append((m.start(), metric))
    seen, out = set(), []
    for _, m in sorted(found):
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def find_periods(q: str, known: list[str]) -> list[str]:
    out = []
    for m in re.finditer(r"\bQ([1-4])\s*(?:of\s*)?(20\d\d)?\b", q, re.I):
        out.append((int(m.group(1)), m.group(2)))
    for m in re.finditer(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter(?:\s+(?:of\s+)?(20\d\d))?", q, re.I):
        out.append((QUARTER_WORDS[m.group(1).lower()], m.group(2)))
    years = re.findall(r"\b(20\d\d)\b", q)
    default_year = years[0] if years else (max((period_key(p)[0] for p in known), default=None))
    periods = []
    for quarter, year in out:
        p = f"Q{quarter} {year or default_year}"
        if p not in periods:
            periods.append(p)
    m = re.search(r"\b(?:FY|fiscal year)\s*(20\d\d)\b", q, re.I)
    if m:
        periods.append(f"FY {m.group(1)}")
    return periods


def find_companies(q: str, companies: list[dict]) -> list[dict]:
    qn = f" {norm_name(q)} "
    out = []
    for c in companies:
        full = c["company_norm"]
        first = full.split(" ")[0]
        # first-word alias is only used for lookup when it is unique among known companies
        unique_first = sum(1 for o in companies if o["company_norm"].split(" ")[0] == first) == 1
        if f" {full} " in qn or (unique_first and len(first) >= 4 and f" {first} " in qn):
            out.append(c)
    return out


class Router:
    def __init__(self, finance: Finance, store):
        self.finance, self.store = finance, store

    def route(self, question: str) -> Route:
        companies = self.finance.companies()
        all_periods = sorted({p for c in companies for p in c["periods_list"]}, key=period_key)
        metrics = find_metrics(question)
        comps = find_companies(question, companies)
        periods = find_periods(question, all_periods)
        is_calc = bool(CALC_WORDS.search(question))
        if not metrics or not (comps or periods or is_calc):
            return Route("doc", metrics, comps, periods)
        r = Route("both", metrics, comps, periods)
        facts = self.finance.facts()
        targets = comps or companies
        if not comps and len(companies) > 1 and not re.search(r"\b(all|each|every|companies|both)\b", question, re.I):
            r.notes.append("No company named; showing every company that reports this metric.")
        for metric in metrics:
            for c in targets:
                avail = [p for p in c["periods_list"] if metric in facts.get((c["company_norm"], p), {}).get("metrics", {})]
                want = periods if periods else avail[-4:]
                series = []
                for p in want:
                    f = facts.get((c["company_norm"], p), {}).get("metrics", {}).get(metric)
                    if f is None:
                        if comps or periods:
                            have = ", ".join(avail) or "no periods"
                            r.missing.append(f"{title(metric)} for {c['company']} in {p} is not in the uploaded "
                                             f"documents (available: {have}).")
                        continue
                    series.append((p, f))
                    r.facts += self._facts_for(metric, c, p, f, facts[(c['company_norm'], p)]["currency"])
                if len(series) >= 2:
                    (p0, f0), (p1, f1) = series[0], series[-1]
                    if metric in RATIOS:
                        r.calculations.append(f"{title(metric)} {c['company']}: {fmt_ratio(metric, f0['value'])} ({p0}) → "
                                              f"{fmt_ratio(metric, f1['value'])} ({p1}), "
                                              f"{(f1['value'] - f0['value']) * (100 if metric in PERCENT_RATIOS else 1):+.2f}"
                                              f"{' pp' if metric in PERCENT_RATIOS else ''}")
                    elif f0["value"]:
                        pct = (f1["value"] - f0["value"]) / abs(f0["value"])
                        r.calculations.append(f"{title(metric)} change for {c['company']} {p0} → {p1}: "
                                              f"({fmt_money(f1['value'])} − {fmt_money(f0['value'])}) / "
                                              f"{fmt_money(abs(f0['value']))} = {pct:+.1%}")
            # cross-company comparison for the same period
            same_period = {}
            for f in r.facts:
                if f.label.startswith(title(metric) + " |"):
                    _, comp, per = [x.strip() for x in f.label.split("|")]
                    same_period.setdefault(per, []).append((comp, f))
            for per, items in same_period.items():
                if len(items) >= 2:
                    currencies = {c["currency"] for c in targets}
                    if metric not in RATIOS and len(currencies) > 1:
                        r.notes.append(f"{title(metric)} is reported in different currencies "
                                       f"({', '.join(sorted(currencies))}); amounts are not converted. "
                                       "Compare margins instead.")
                        continue
                    best = max(items, key=lambda x: x[1].value)
                    r.calculations.append(f"{title(metric)} in {per}: " + " vs ".join(
                        f"{comp} {f.display}" for comp, f in items) + f" → highest: {best[0]}")
        if not r.facts and not r.missing:
            return Route("doc", metrics, comps, periods)
        r.route = "metric" if r.facts and not r.missing else "both"
        return r

    def _facts_for(self, metric, company, period, f, currency) -> list[Fact]:
        lab = f"{title(metric)} | {company['company']} | {period}"
        if f.get("computed"):
            out = [Fact(lab, f["value"], fmt_ratio(metric, f["value"]))]
            r_inputs = f["inputs"]
            names = RATIOS[metric][:2]
            for name, inp in zip(names, r_inputs):
                out.append(self._raw_fact(f"{title(name)} | {company['company']} | {period}", inp, currency))
            out[0].excerpt = f["formula"] + f" = {fmt_ratio(metric, f['value'])}"
            return out
        return [self._raw_fact(lab, f, currency)]

    def _raw_fact(self, label, f, currency) -> Fact:
        chunk = self.store.row("SELECT id FROM chunks WHERE doc_id=? AND page=? AND instr(text, ?) > 0 LIMIT 1",
                               (f["doc_id"], f["page"], (f.get("excerpt") or "")[:60]))
        return Fact(label, f["value"], fmt_money(f["value"], currency), f["doc_id"], f.get("filename"), f.get("page"),
                    f.get("excerpt"), chunk["id"] if chunk else None)


def fmt_ratio(metric: str, v: float) -> str:
    return f"{v:.1%}" if metric in PERCENT_RATIOS else (f"{v:.2f}" if metric in RATIOS else fmt_money(v))
