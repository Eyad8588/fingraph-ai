"""Generate the synthetic test dataset (fictional companies, fictional numbers).

    uv run python samples/generate.py

Writes 10 documents to samples/docs/ in PDF, DOCX, JPG and PNG, including scanned images and a PDF whose
second page is a scan, with deliberate anomalies to detect (see samples/README.md).
"""

from __future__ import annotations

import io
import random
from pathlib import Path

from docx import Document
from docx.shared import Pt
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).parent / "docs"
BANNER = "SYNTHETIC DOCUMENT - FICTIONAL DATA FOR TESTING ONLY"
FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
random.seed(7)


def money(v: float) -> str:
    return f"({abs(v):,.0f})" if v < 0 else f"{v:,.0f}"


# ---------------------------------------------------------------- PDF helpers
def pdf_statement(path: Path, company: str, title: str, subtitle: str, currency_note: str,
                  sections: list[tuple[str | None, list[tuple[str, float, bool]]]], notes: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#b91c1c"))
    c.drawString(20 * mm, h - 12 * mm, BANNER)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, company)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(20 * mm, h - 33 * mm, title)
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 40 * mm, subtitle)
    c.drawString(20 * mm, h - 46 * mm, currency_note)
    y = h - 60 * mm
    for heading, rows in sections:
        if heading:
            c.setFont("Helvetica-Bold", 10)
            c.drawString(20 * mm, y, heading)
            y -= 7 * mm
        for label, value, bold in rows:
            c.setFont("Helvetica-Bold" if bold else "Helvetica", 10)
            c.drawString(24 * mm, y, label)
            c.drawRightString(170 * mm, y, money(value))
            y -= 6 * mm
        y -= 3 * mm
    c.setFont("Helvetica", 9)
    for n in notes:
        c.drawString(20 * mm, y, n)
        y -= 5 * mm
    c.showPage()
    c.save()


def income_rows(rev, cogs, salaries, marketing, rent, logistics, interest, tax, gp_override=None):
    gp = rev - cogs if gp_override is None else gp_override
    opex = salaries + marketing + rent + logistics
    op = gp - opex
    net = op - interest - tax
    return [
        (None, [("Revenue", rev, False), ("Cost of goods sold", -cogs, False), ("Gross profit", gp, True)]),
        ("Operating expenses", [("Salaries", salaries, False), ("Marketing", marketing, False), ("Rent", rent, False),
                                ("Logistics", logistics, False), ("Total operating expenses", opex, True)]),
        (None, [("Operating income", op, True), ("Interest expense", interest, False), ("Income tax", tax, False),
                ("Net income", net, True)]),
    ]


# ---------------------------------------------------------------- image helpers ("scans")
def scan_image(lines: list[tuple[str, int, bool]], size=(1700, 2200), angle=0.8, noise=True) -> Image.Image:
    img = Image.new("RGB", size, (252, 251, 247))
    d = ImageDraw.Draw(img)
    y = 90
    for text, fs, bold in lines:
        if text == "---":
            d.line((100, y + 10, size[0] - 100, y + 10), fill=(60, 60, 60), width=2)
            y += 30
            continue
        f = ImageFont.truetype(FONT_B if bold else FONT, fs)
        if "\t" in text:
            left, right = text.split("\t")
            d.text((110, y), left, font=f, fill=(25, 25, 25))
            rw = d.textlength(right, font=f)
            d.text((size[0] - 140 - rw, y), right, font=f, fill=(25, 25, 25))
        else:
            d.text((110, y), text, font=f, fill=(25, 25, 25))
        y += int(fs * 1.75)
    if noise:
        px = img.load()
        for _ in range(9000):
            x, yy = random.randrange(size[0]), random.randrange(size[1])
            g = random.randrange(150, 230)
            px[x, yy] = (g, g, g)
    img = img.rotate(angle, expand=False, fillcolor=(245, 244, 240), resample=Image.BICUBIC)
    return img.filter(ImageFilter.GaussianBlur(0.6))


INV_1042_LINES = [
    (BANNER, 22, False), ("ATLAS LOGISTICS LLC", 46, True), ("12 Harbor Road, Port District", 28, False),
    ("---", 0, False), ("INVOICE", 40, True), ("Invoice No: INV-1042", 32, False),
    ("Invoice Date: 2026-06-03", 32, False), ("Due Date: 2026-07-03", 32, False), ("Bill To: Nova Retail Ltd", 32, False),
    ("---", 0, False), ("Description\tAmount", 30, True), ("Freight services - May 2026\t16,000.00", 30, False),
    ("Warehousing - May 2026\t4,000.00", 30, False), ("---", 0, False), ("Subtotal\t20,000.00", 30, False),
    ("VAT 15%\t3,000.00", 30, False), ("Total Due\tUSD 23,000.00", 32, True), ("---", 0, False),
    ("Payment terms: 30 days. Reference the invoice number with payment.", 26, False),
]


def make_invoice_pdf(path: Path) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#b91c1c"))
    c.drawString(20 * mm, h - 12 * mm, BANNER)
    c.setFillColor(colors.black)
    y = h - 25 * mm
    for text, fs, bold in INV_1042_LINES[1:]:
        if text == "---":
            c.line(20 * mm, y + 2 * mm, 190 * mm, y + 2 * mm)
            y -= 4 * mm
            continue
        size = max(8, fs // 3)
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        if "\t" in text:
            left, right = text.split("\t")
            c.drawString(20 * mm, y, left)
            c.drawRightString(190 * mm, y, right)
        else:
            c.drawString(20 * mm, y, text)
        y -= size * 0.55 * mm + 3 * mm
    c.showPage()
    c.save()


def bank_statement_pdf(path: Path) -> None:
    """Page 1 has a text layer; page 2 is an embedded scan (no text layer) -> exercises per-page OCR."""
    rows1 = [
        ("2026-06-01", "Opening balance", None, 310000.00),
        ("2026-06-02", "Deposit from customer Bright Mart Inc", 84500.00, 394500.00),
        ("2026-06-05", "Payment to Cedar Cloud Services Ltd ref CC-311", -9500.00, 385000.00),
        ("2026-06-10", "Payroll June first half", -102500.00, 282500.00),
        ("2026-06-12", "Payment to Atlas Logistics LLC ref INV-1042", -23000.00, 259500.00),
        ("2026-06-15", "Deposit from customer Bright Mart Inc", 91200.00, 350700.00),
    ]
    rows2 = [
        ("2026-06-18", "Payment to Atlas Logistics LLC ref INV-1042", "-23,000.00", "327,700.00"),
        ("2026-06-20", "Wire transfer to Orion Consulting", "-25,000.00", "302,700.00"),
        ("2026-06-24", "Rent payment Harbor Properties", "-30,000.00", "272,700.00"),
        ("2026-06-25", "Payroll June second half", "-102,500.00", "170,200.00"),
        ("2026-06-28", "Deposit from customer Lumen Stores", "56,300.00", "226,500.00"),
        ("2026-06-30", "Closing balance", "", "226,500.00"),
    ]
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#b91c1c"))
    c.drawString(20 * mm, h - 12 * mm, BANNER)
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(20 * mm, h - 25 * mm, "Meridian Bank PLC")
    c.setFont("Helvetica-Bold", 11)
    c.drawString(20 * mm, h - 33 * mm, "Bank Statement")
    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, h - 40 * mm, "Account holder: Nova Retail Ltd    Account: ****4417    Currency: USD")
    c.drawString(20 * mm, h - 46 * mm, "Statement period: June 2026 (2026-06-01 to 2026-06-30)")
    y = h - 60 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Date")
    c.drawString(45 * mm, y, "Description")
    c.drawRightString(160 * mm, y, "Amount")
    c.drawRightString(190 * mm, y, "Balance")
    y -= 7 * mm
    c.setFont("Helvetica", 9)
    for d, desc, amt, bal in rows1:
        c.drawString(20 * mm, y, d)
        c.drawString(45 * mm, y, desc)
        if amt is not None:
            c.drawRightString(160 * mm, y, f"{amt:,.2f}")
        c.drawRightString(190 * mm, y, f"{bal:,.2f}")
        y -= 6 * mm
    c.drawString(20 * mm, y - 4 * mm, "Continued on page 2")
    c.showPage()
    lines = [(BANNER, 22, False), ("Meridian Bank PLC - Bank Statement (page 2)", 34, True),
             ("Account holder: Nova Retail Ltd   Account ****4417", 28, False), ("---", 0, False)]
    img = Image.new("RGB", (1700, 2200), (252, 251, 247))
    dr = ImageDraw.Draw(img)
    f, fb = ImageFont.truetype(FONT, 28), ImageFont.truetype(FONT_B, 28)
    y2 = 90
    for text, fs, bold in lines:
        if text == "---":
            dr.line((100, y2 + 10, 1600, y2 + 10), fill=(60, 60, 60), width=2)
            y2 += 30
            continue
        dr.text((110, y2), text, font=ImageFont.truetype(FONT_B if bold else FONT, fs), fill=(25, 25, 25))
        y2 += int(fs * 1.75)
    for d, desc, amt, bal in rows2:
        dr.text((110, y2), d, font=f, fill=(25, 25, 25))
        dr.text((330, y2), desc, font=f, fill=(25, 25, 25))
        if amt:
            dr.text((1330 - dr.textlength(amt, font=f), y2), amt, font=f, fill=(25, 25, 25))
        dr.text((1600 - dr.textlength(bal, font=fb), y2), bal, font=fb, fill=(25, 25, 25))
        y2 += 52
    img = img.rotate(0.5, fillcolor=(245, 244, 240), resample=Image.BICUBIC).filter(ImageFilter.GaussianBlur(0.5))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    buf.seek(0)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(buf), 0, 0, width=w, height=h)
    c.showPage()
    c.save()


# ---------------------------------------------------------------- DOCX
def docx_doc(path: Path, title: str, blocks: list) -> None:
    d = Document()
    d.styles["Normal"].font.size = Pt(10.5)
    p = d.add_paragraph(BANNER)
    p.runs[0].font.size = Pt(7)
    d.add_heading(title, level=1)
    for b in blocks:
        if isinstance(b, tuple) and b[0] == "h":
            d.add_heading(b[1], level=2)
        elif isinstance(b, tuple) and b[0] == "table":
            t = d.add_table(rows=0, cols=len(b[1][0]))
            t.style = "Light Grid Accent 1"
            for row in b[1]:
                cells = t.add_row().cells
                for i, v in enumerate(row):
                    cells[i].text = v
        else:
            d.add_paragraph(b)
    d.save(str(path))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    note = "All amounts in USD"
    # 1-2. Nova Retail income statements (Q1 and Q2 2026). Marketing +62.9%, revenue -10.4%.
    pdf_statement(OUT / "nova_retail_income_statement_q1_2026.pdf", "Nova Retail Ltd", "Income Statement",
                  "For the three months ended March 31, 2026 (Q1 2026)", note,
                  income_rows(1_250_000, 700_000, 205_000, 175_000, 60_000, 48_000, 6_000, 14_000),
                  ["Prepared by Finance. Unaudited management accounts."])
    pdf_statement(OUT / "nova_retail_income_statement_q2_2026.pdf", "Nova Retail Ltd", "Income Statement",
                  "For the three months ended June 30, 2026 (Q2 2026)", note,
                  income_rows(1_120_000, 650_000, 205_000, 285_000, 60_000, 69_000, 6_000, 0),
                  ["Marketing includes the Summer Launch campaign.", "Unaudited management accounts."])
    # 3. Nova balance sheet (DOCX table)
    docx_doc(OUT / "nova_retail_balance_sheet_2026-06-30.docx", "Nova Retail Ltd - Balance Sheet", [
        "Statement of financial position as at June 30, 2026 (Q2 2026). All amounts in USD.",
        ("h", "Assets"),
        ("table", [["Line item", "June 30, 2026"], ["Cash and cash equivalents", "226,500"],
                   ["Accounts receivable", "148,000"], ["Inventory", "392,000"], ["Total current assets", "766,500"],
                   ["Property and equipment", "610,000"], ["Total assets", "1,376,500"]]),
        ("h", "Liabilities and equity"),
        ("table", [["Line item", "June 30, 2026"], ["Accounts payable", "214,000"], ["Total current liabilities", "301,000"],
                   ["Long-term debt", "420,000"], ["Total liabilities", "721,000"], ["Total equity", "655,500"]]),
        "Total liabilities and equity equal total assets.",
    ])
    # 4. Helix Foods income statement, Q2 2026, in SAR (currency edge case) - with a gross profit mismatch
    pdf_statement(OUT / "helix_foods_income_statement_q2_2026.pdf", "Helix Foods Company", "Income Statement",
                  "For the three months ended June 30, 2026 (Q2 2026)", "All amounts in SAR (Saudi riyal)",
                  income_rows(3_400_000, 2_210_000, 420_000, 160_000, 140_000, 95_000, 12_000, 38_000,
                              gp_override=1_210_000),
                  ["Gross profit as reported by the regional finance team."])
    # 5. Atlas invoice INV-1042 (PDF) and 6. the same invoice photographed (JPG) -> duplicate invoice
    make_invoice_pdf(OUT / "atlas_logistics_invoice_INV-1042.pdf")
    scan_image(INV_1042_LINES, angle=1.2).save(OUT / "atlas_invoice_INV-1042_phone_scan.jpg", quality=78)
    # 7. Cedar Cloud invoice (PNG): 8,000 + 1,200 != 9,500 -> invoice math anomaly
    scan_image([
        (BANNER, 22, False), ("Cedar Cloud Services Ltd", 46, True), ("Cloud hosting and support", 28, False),
        ("---", 0, False), ("TAX INVOICE", 40, True), ("Invoice Number: CC-311", 32, False),
        ("Invoice Date: 2026-05-28", 32, False), ("Bill To: Nova Retail Ltd", 32, False), ("---", 0, False),
        ("Item\tAmount", 30, True), ("Hosting plan - June 2026\t6,500.00", 30, False),
        ("Premium support\t1,500.00", 30, False), ("---", 0, False), ("Subtotal\t8,000.00", 30, False),
        ("VAT 15%\t1,200.00", 30, False), ("Total\t9,500.00", 32, True),
    ], angle=-0.6).save(OUT / "cedar_cloud_invoice_CC-311.png")
    # 8. Bank statement (page 2 scanned): Atlas paid twice, $25,000 Saturday wire to unknown Orion Consulting
    bank_statement_pdf(OUT / "nova_retail_bank_statement_june_2026.pdf")
    # 9. Service agreement Nova <-> Atlas (DOCX)
    docx_doc(OUT / "nova_atlas_service_agreement.docx", "Logistics Service Agreement", [
        "This Logistics Service Agreement is made on January 15, 2026 between Nova Retail Ltd (the Customer) and "
        "Atlas Logistics LLC (the Provider).",
        ("h", "Services"),
        "Atlas Logistics LLC provides freight and warehousing services to Nova Retail Ltd for all retail stores.",
        ("h", "Fees and payment"),
        "Monthly fees are invoiced in arrears and are capped at USD 25,000 per month including VAT. "
        "Invoices are payable within 30 days. Each invoice must be paid once, referencing the invoice number.",
        ("h", "Term"),
        "The agreement runs for 24 months from February 1, 2026 and renews automatically unless either party "
        "gives 60 days notice. Contact person for the Provider: Omar Haddad, Account Director.",
    ])
    # 10. Board memo (DOCX), narrative only
    docx_doc(OUT / "nova_retail_board_memo_q2_2026.docx", "Board Memo - Q2 2026 Review", [
        "To: Board of Directors, Nova Retail Ltd. From: Sara Malik, Chief Financial Officer. Date: July 8, 2026.",
        ("h", "Highlights"),
        "Revenue softened in Q2 2026 as foot traffic declined in June. Management increased marketing for the "
        "Summer Launch campaign to recover demand in Q3 2026.",
        ("h", "Suppliers"),
        "Logistics costs rose because Atlas Logistics LLC handled extra warehouse volume. Finance is reviewing a "
        "possible duplicate payment to Atlas Logistics LLC identified during the June bank reconciliation. "
        "Cedar Cloud Services Ltd remains our hosting provider.",
        ("h", "Outlook"),
        "Management expects revenue to recover in Q3 2026. No guidance is given for Q4 2026.",
    ])
    print("wrote", len(list(OUT.iterdir())), "files to", OUT)


if __name__ == "__main__":
    main()
