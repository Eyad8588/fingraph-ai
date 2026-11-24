# Synthetic test documents

All companies, people and numbers are **fictional** and every file is stamped "SYNTHETIC DOCUMENT - FICTIONAL DATA".
Regenerate with `uv run python samples/generate.py`.

| File | Format | What it exercises |
|---|---|---|
| nova_retail_income_statement_q1_2026.pdf | PDF (text) | Statement parsing, Q1 baseline |
| nova_retail_income_statement_q2_2026.pdf | PDF (text) | Revenue −10.4%, marketing +62.9%, net loss → swing + sign-change anomalies |
| nova_retail_balance_sheet_2026-06-30.docx | DOCX table | Table parsing, current ratio, debt-to-equity |
| helix_foods_income_statement_q2_2026.pdf | PDF (text), **SAR** | Cross-company comparison, currency handling, gross profit does not reconcile |
| atlas_logistics_invoice_INV-1042.pdf | PDF (text) | Invoice extraction |
| atlas_invoice_INV-1042_phone_scan.jpg | JPG, rotated + noisy | OCR + deskew, **duplicate invoice** |
| cedar_cloud_invoice_CC-311.png | PNG scan | OCR, **invoice arithmetic error** (8,000 + 1,200 ≠ 9,500) |
| nova_retail_bank_statement_june_2026.pdf | PDF: page 1 text, **page 2 scanned** | Per-page OCR, **duplicate payment** to Atlas, **$25,000 Saturday wire to unknown Orion Consulting** |
| nova_atlas_service_agreement.docx | DOCX | Contract relation in the graph, fee cap |
| nova_retail_board_memo_q2_2026.docx | DOCX | Narrative text, "why" questions, people |
