"""Small, deterministic helpers for financial text: amounts, periods, currencies, names, IDs."""

from __future__ import annotations

import re
from datetime import date, datetime

ORG_SUFFIX = r"(?:ltd|limited|inc|incorporated|llc|l\.l\.c|plc|corp|corporation|co|company|gmbh|sa|ag|group|holdings)"
ORG_SUFFIX_RE = re.compile(rf"\b{ORG_SUFFIX}\b\.?", re.I)
ORG_NAME_RE = re.compile(rf"\b([A-Z][A-Za-z&'\-]+(?:[ \t]+[A-Z][A-Za-z&'\-]+){{0,4}}[ \t]+(?i:{ORG_SUFFIX})\.?)(?![A-Za-z])")
ORG_NOISE = re.compile(r"^(?:(?:synthetic|document|fictional|data|for|testing|only|to|from|bill|billed|account|"
                       r"holder|between|and|the|customer|vendor|supplier|deposit|payment|wire|transfer|ref)[ \t:,-]+)+",
                       re.I)

# ---------------------------------------------------------------- names / ids


def norm_name(name: str) -> str:
    """'NOVA RETAIL LIMITED' and 'Nova Retail Ltd.' -> 'nova retail'. Conservative: no fuzzy merging."""
    n = name.lower().replace("&", " and ")
    n = ORG_SUFFIX_RE.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def norm_id(value: str) -> str:
    """Normalize document numbers; fixes common OCR confusions inside numeric runs (INV-1O42 -> INV-1042)."""
    v = value.upper().strip().replace(" ", "")
    v = re.sub(r"[‐-―]", "-", v)

    def fix(m: re.Match) -> str:
        return m.group(0).replace("O", "0").replace("I", "1").replace("L", "1")

    # characters between/after digits are the risky ones
    v = re.sub(r"(?<=\d)[OIL]+|[OIL]+(?=\d)", fix, v)
    return re.sub(r"[^A-Z0-9-]", "", v)


# ---------------------------------------------------------------- amounts

AMOUNT_RE = re.compile(
    r"(?P<neg>\()?\s*(?P<minus>[-−])?\s*(?:(?P<cur>USD|SAR|EUR|GBP|AED|US\$|SR|\$|€|£)\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d{2}|\d{4,}(?:\.\d+)?|\d{1,3})"
    r"(?:\s?(?P<cur2>USD|SAR|EUR|GBP|AED))?\s*(?P<close>\))?"
)


def parse_amount(text: str) -> float | None:
    m = AMOUNT_RE.search(text)
    if not m:
        return None
    value = float(m.group("num").replace(",", ""))
    if (m.group("neg") and m.group("close")) or m.group("minus"):
        value = -value
    return value


def amounts_in(text: str) -> list[float]:
    out = []
    for m in AMOUNT_RE.finditer(text):
        num = m.group("num")
        if len(num.replace(",", "").split(".")[0]) < 2 and "." not in num:
            continue
        v = float(num.replace(",", ""))
        if (m.group("neg") and m.group("close")) or m.group("minus"):
            v = -v
        out.append(v)
    return out


def number_tokens(text: str) -> set[float]:
    """Every number written in a text (used by the grounding checks)."""
    vals = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        try:
            vals.add(round(float(raw.replace(",", "")), 2))
        except ValueError:
            pass
    return vals


def fmt_money(v: float | None, currency: str | None = None) -> str:
    if v is None:
        return "n/a"
    s = f"{abs(v):,.2f}".rstrip("0").rstrip(".") if v % 1 else f"{abs(v):,.0f}"
    s = f"-{s}" if v < 0 else s
    return f"{currency} {s}" if currency else s


# ---------------------------------------------------------------- currency

CURRENCY_PATTERNS = [
    ("SAR", r"\bSAR\b|\bSR\b|saudi riyal"),
    ("EUR", r"\bEUR\b|€"),
    ("GBP", r"\bGBP\b|£"),
    ("AED", r"\bAED\b"),
    ("USD", r"\bUSD\b|US\$|\$"),
]


def detect_currency(text: str, default: str = "USD") -> str:
    head = text[:3000]
    m = re.search(r"(?:amounts?|figures?|presented|expressed|reported)\s+(?:are\s+)?in\s+([A-Z]{3})", head, re.I)
    if m:
        return m.group(1).upper()
    counts = {code: len(re.findall(p, text, re.I)) for code, p in CURRENCY_PATTERNS}
    best = max(counts, key=counts.get)
    return best if counts[best] else default


# ---------------------------------------------------------------- dates & periods

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
MONTHS.update({k[:3]: v for k, v in list(MONTHS.items())})


def parse_date(text: str) -> date | None:
    t = text.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


DATE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\b")


def find_dates(text: str) -> list[date]:
    out = []
    for raw in DATE_RE.findall(text):
        cleaned = re.sub(r"\s+", " ", raw.replace(",", " ")).strip()
        d = parse_date(raw) or parse_date(cleaned)
        if d is None:
            m = re.match(r"([A-Za-z]+) (\d{1,2}) (\d{4})$", cleaned)
            if m and m.group(1).lower() in MONTHS:
                d = date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))
        if d:
            out.append(d)
    return out


def quarter_of(d: date) -> str:
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def find_period(text: str) -> str | None:
    """Normalize the reporting period of a document to 'Q2 2026', 'FY 2025' or 'June 2026'."""
    head = text[:2500]
    m = re.search(r"\bQ([1-4])\s*[-/ ]?\s*(20\d\d)\b", head, re.I) or re.search(r"\b(20\d\d)\s*Q([1-4])\b", head, re.I)
    if m:
        a, b = m.groups()
        return f"Q{a} {b}" if len(a) == 1 else f"Q{b} {a}"
    ordinal = {"first": 1, "second": 2, "third": 3, "fourth": 4}
    m = re.search(r"\b(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:fiscal\s+)?(20\d\d)", head, re.I)
    if m:
        return f"Q{ordinal[m.group(1).lower()]} {m.group(2)}"
    m = re.search(r"(?:three|3)\s+months\s+ended\s+([A-Za-z]+\s+\d{1,2},?\s+20\d\d|\d{1,2}\s+[A-Za-z]+\s+20\d\d)", head, re.I)
    if m:
        d = find_dates(m.group(1))
        if d:
            return quarter_of(d[0])
    m = re.search(r"\b(?:as\s+(?:at|of)|quarter\s+ended|period\s+ended)\s+([A-Za-z]+\s+\d{1,2},?\s+20\d\d|\d{1,2}\s+[A-Za-z]+\s+20\d\d|20\d\d-\d\d-\d\d)",
                  head, re.I)
    if m:
        d = find_dates(m.group(1))
        if d:
            return quarter_of(d[0])
    m = re.search(r"\b(?:FY|fiscal\s+year)\s*(20\d\d)\b", head, re.I)
    if m:
        return f"FY {m.group(1)}"
    m = re.search(r"\b(?:statement\s+period|period)[:\s]+([A-Za-z]+)\s+(20\d\d)", head, re.I)
    if m and m.group(1).lower() in MONTHS:
        return quarter_of(date(int(m.group(2)), MONTHS[m.group(1).lower()], 1))
    return None


PERIOD_ORDER_RE = re.compile(r"(Q([1-4])|FY)\s*(20\d\d)")


def period_key(period: str | None) -> tuple:
    if not period:
        return (0, 0)
    m = PERIOD_ORDER_RE.search(period)
    if not m:
        return (0, 0)
    q = int(m.group(2)) if m.group(2) else 5
    return (int(m.group(3)), q)


# ---------------------------------------------------------------- organisations


def find_orgs(text: str) -> list[str]:
    seen, out = set(), []
    for m in ORG_NAME_RE.finditer(text):
        name = re.sub(r"\s+", " ", m.group(1)).strip(" .,")
        name = ORG_NOISE.sub("", name).strip()
        if len(name.split()) < 2:
            continue
        key = norm_name(name)
        if key and key not in seen and len(key) > 2:
            seen.add(key)
            out.append(name)
    return out


def is_arabic(text: str) -> bool:
    return bool(re.search(r"[؀-ۿ]", text))
