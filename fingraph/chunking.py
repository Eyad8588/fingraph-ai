"""Structure-aware chunking with a context header.

In financial documents a line like 'Total revenue 1,250,000' is meaningless without its company and
period, so every chunk is prefixed (for embedding and keyword search only) with:
    [Nova Retail Ltd · Income statement · Q2 2026 · page 1 · section: Operating expenses]
Rules: never cross a page boundary (citations point at pages); keep tables whole; if a table must be
split, repeat its header row in every part; long prose is split on line/sentence boundaries with overlap.
"""

from __future__ import annotations

import re

from .parsing import Page
from .textutil import amounts_in

DOC_TYPE_LABEL = {
    "income_statement": "Income statement", "balance_sheet": "Balance sheet", "cash_flow": "Cash flow statement",
    "invoice": "Invoice", "bank_statement": "Bank statement", "contract": "Contract", "report": "Report",
    "purchase_order": "Purchase order", "other": "Document",
}


def is_heading(line: str) -> bool:
    s = line.strip()
    if s.startswith("## "):
        return True
    if not s or len(s) > 60 or amounts_in(s) or s.endswith((".", ",")):
        return False
    letters = re.sub(r"[^A-Za-z]", "", s)
    return len(letters) >= 4 and len(s.split()) <= 6 and (s.isupper() or s.endswith(":"))


def is_table_row(line: str) -> bool:
    s = line.strip()
    return " | " in s or bool(re.search(r"\S\s{2,}\(?[-$€£]?\s?\d[\d,]*(?:\.\d+)?\)?\s*$", s)) or \
        bool(re.search(r"^\d{4}-\d{2}-\d{2}\s", s))


def blocks_of(text: str) -> list[dict]:
    """Split a page into heading-scoped blocks of type 'table' or 'text'."""
    blocks: list[dict] = []
    section = None
    for raw in text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            if blocks and blocks[-1]["kind"] == "text":
                blocks[-1]["lines"].append("")
            continue
        if is_heading(line):
            section = line.strip().lstrip("#").strip().rstrip(":")
            blocks.append({"kind": "text", "section": section, "lines": [line.strip().lstrip("# ").strip()]})
            continue
        kind = "table" if is_table_row(line) else "text"
        if blocks and blocks[-1]["kind"] == kind and blocks[-1]["section"] == section:
            blocks[-1]["lines"].append(line)
        elif kind == "table" and blocks and blocks[-1]["kind"] == "text" and blocks[-1]["section"] == section \
                and len(blocks[-1]["lines"]) <= 2 and not blocks[-1]["lines"][-1].endswith("."):
            # a short line right above a table is its header row / caption: keep them together
            prev = blocks.pop()
            blocks.append({"kind": "table", "section": section, "lines": prev["lines"] + [line],
                           "header_rows": len(prev["lines"])})
        else:
            blocks.append({"kind": kind, "section": section, "lines": [line]})
    return [b for b in blocks if any(x.strip() for x in b["lines"])]


def split_long_text(text: str, max_chars: int, overlap: int) -> list[str]:
    pieces = re.split(r"(?<=[.!?])\s+|\n", text)
    out, cur = [], ""
    for p in pieces:
        if len(cur) + len(p) + 1 > max_chars and cur:
            out.append(cur.strip())
            cur = cur[-overlap:] + " " + p
        else:
            cur += (" " if cur else "") + p
    if cur.strip():
        out.append(cur.strip())
    return out


def split_table(lines: list[str], header_rows: int, max_chars: int) -> list[str]:
    head = lines[:header_rows]
    body = lines[header_rows:]
    parts, cur = [], list(head)
    for row in body:
        if sum(len(x) + 1 for x in cur) + len(row) > max_chars and len(cur) > len(head):
            parts.append("\n".join(cur))
            cur = list(head)  # repeat the header row in every part
        cur.append(row)
    if len(cur) > len(head) or not parts:
        parts.append("\n".join(cur))
    return parts


def context_header(meta: dict, page: int, section: str | None) -> str:
    bits = [meta.get("company"), DOC_TYPE_LABEL.get(meta.get("doc_type") or "", None), meta.get("period"),
            meta.get("filename"), f"page {page}"]
    if section:
        bits.append(f"section: {section}")
    return "[" + " · ".join(b for b in bits if b) + "]"


def chunk_pages(pages: list[Page], meta: dict, max_chars: int = 1200, overlap: int = 150) -> list[dict]:
    chunks: list[dict] = []
    for page in pages:
        units: list[tuple[str | None, str]] = []
        for b in blocks_of(page.text):
            body = "\n".join(b["lines"]).strip()
            if len(body) <= max_chars:
                units.append((b["section"], body))
            elif b["kind"] == "table":
                units += [(b["section"], t) for t in split_table(b["lines"], b.get("header_rows", 0), max_chars)]
            else:
                units += [(b["section"], t) for t in split_long_text(body, max_chars, overlap)]
        # pack small neighbouring units of the same page together (keeps context, fewer tiny chunks)
        cur_text, cur_section = "", None
        for section, text in units:
            if cur_text and len(cur_text) + len(text) + 2 > max_chars:
                chunks.append(_mk(len(chunks), page, cur_section, cur_text, meta))
                cur_text, cur_section = "", None
            cur_text = f"{cur_text}\n\n{text}" if cur_text else text
            cur_section = cur_section or section
        if cur_text.strip():
            chunks.append(_mk(len(chunks), page, cur_section, cur_text, meta))
    return chunks


def _mk(idx: int, page: Page, section: str | None, text: str, meta: dict) -> dict:
    return {"idx": idx, "page": page.page, "section": section, "text": text.strip(), "method": page.method,
            "header": context_header(meta, page.page, section)}
