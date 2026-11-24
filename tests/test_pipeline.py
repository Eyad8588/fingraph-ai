"""Offline tests: fake embedder/LLM/reranker, real parsing, OCR (macOS), extraction, storage, retrieval, anomalies."""

from __future__ import annotations

import platform
from pathlib import Path

import pytest

from fingraph.api import App
from fingraph.config import Settings
from fingraph.textutil import find_period, norm_id, norm_name, parse_amount

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "docs"
TEXT_ONLY = ["nova_retail_income_statement_q1_2026.pdf", "nova_retail_income_statement_q2_2026.pdf",
             "helix_foods_income_statement_q2_2026.pdf", "atlas_logistics_invoice_INV-1042.pdf",
             "nova_retail_balance_sheet_2026-06-30.docx", "nova_atlas_service_agreement.docx",
             "nova_retail_board_memo_q2_2026.docx"]
SCANS = ["atlas_invoice_INV-1042_phone_scan.jpg", "cedar_cloud_invoice_CC-311.png",
         "nova_retail_bank_statement_june_2026.pdf"]
ON_MAC = platform.system() == "Darwin"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    s = Settings(data_dir=tmp_path_factory.mktemp("data"), fake_models=True)
    core = App(s)
    core.ingestor.start()
    for name in TEXT_ONLY + (SCANS if ON_MAC else []):
        core.ingestor.submit(name, (SAMPLES / name).read_bytes())
    assert core.ingestor.wait_idle(300)
    return core


# ------------------------------------------------------------------ helpers
def test_amounts_and_ids():
    assert parse_amount("(85,000)") == -85000
    assert parse_amount("USD 23,000.00") == 23000
    assert parse_amount("0") == 0
    assert norm_id("INV-1O42") == "INV-1042"  # OCR confused zero with the letter O
    assert norm_name("NOVA RETAIL LIMITED") == norm_name("Nova Retail Ltd.") == "nova retail"


def test_periods():
    assert find_period("For the three months ended March 31, 2026") == "Q1 2026"
    assert find_period("Statement of financial position as at June 30, 2026") == "Q2 2026"
    assert find_period("Results for Q3 2026") == "Q3 2026"


# ------------------------------------------------------------------ ingestion
def test_all_documents_ready(app):
    docs = app.store.list_documents(100)
    assert docs and all(d["status"] == "ready" for d in docs), [(d["filename"], d["error"]) for d in docs]


def test_duplicate_upload_rejected(app):
    from fingraph.ingest import DuplicateFile
    with pytest.raises(DuplicateFile):
        app.ingestor.submit("again.pdf", (SAMPLES / TEXT_ONLY[0]).read_bytes())


def test_unsupported_type_rejected(app):
    with pytest.raises(ValueError):
        app.ingestor.submit("virus.exe", b"MZ...")


def test_statement_metrics_are_verified_numbers(app):
    rows = {r["name"]: r["value"] for r in app.store.rows(
        "SELECT m.name, m.value FROM metrics m JOIN documents d ON d.id = m.doc_id "
        "WHERE d.filename = 'nova_retail_income_statement_q2_2026.pdf'")}
    assert rows["revenue"] == 1_120_000
    assert rows["cost_of_revenue"] == 650_000  # shown as (650,000), stored as a positive cost
    assert rows["net_income"] == -155_000
    assert rows["income_tax"] == 0


def test_chunks_carry_context_header(app):
    h = app.store.row("SELECT header FROM chunks c JOIN documents d ON d.id = c.doc_id "
                      "WHERE d.filename = 'helix_foods_income_statement_q2_2026.pdf' LIMIT 1")["header"]
    assert "Helix Foods Company" in h and "Q2 2026" in h and "page 1" in h


# ------------------------------------------------------------------ retrieval + answers
def test_hybrid_retrieval_finds_the_right_document(app):
    res = app.retriever.search("monthly fee cap logistics agreement Atlas")
    assert res.hits[0].filename == "nova_atlas_service_agreement.docx"


def test_gate_refuses_off_topic(app):
    res = app.retriever.search("chocolate cake recipe with vanilla frosting")
    assert not res.gate_passed


def test_router_computes_change_in_python(app):
    r = app.router.route("How did Nova Retail's revenue change from Q1 to Q2 2026?")
    assert r.route in ("metric", "both")
    assert any("-10.4%" in c for c in r.calculations)


def test_router_scope_check_reports_missing_period(app):
    r = app.router.route("What was Nova Retail's revenue in Q4 2026?")
    assert r.missing and "Q4 2026" in r.missing[0]


def test_router_refuses_to_compare_different_currencies(app):
    r = app.router.route("Compare revenue of Nova and Helix in Q2 2026")
    assert any("different currencies" in n for n in r.notes)


def test_post_check_flags_invented_numbers(app):
    route = app.router.route("What was Nova Retail's revenue in Q1 2026?")
    hits = app.retriever.search("Nova Retail revenue Q1 2026").hits
    assert app.ask.check("Revenue was 1,250,000 [1].", hits, route) == []
    problems = app.ask.check("Revenue was 9,999,999 [1].", hits, route)
    assert any("not found in sources" in p for p in problems)
    assert any("non-existent" in p for p in app.ask.check("Revenue was 1,250,000 [42].", hits, route))


def test_post_check_flags_invented_dates(app):
    route = app.router.route("When was the wire transfer to Orion Consulting?")
    hits = app.retriever.search("wire transfer Orion Consulting").hits
    problems = app.ask.check("The transfer was made on March 3, 2026 [1].", hits, route)
    assert any("dates not found" in p for p in problems)


def test_conversation_flow(app):
    conv = app.ask.new_conversation()
    out = app.ask.ask(conv["id"], "What was Nova Retail's revenue in Q1 2026?")
    assert out["meta"]["citations"]
    assert len(app.store.history(conv["id"], 6)) == 2


# ------------------------------------------------------------------ financial intelligence
def test_anomalies(app):
    rules = {a["rule"] for a in app.finance.anomalies()}
    assert {"statement_math", "period_swing", "sign_change"} <= rules
    if ON_MAC:
        assert {"duplicate_invoice", "invoice_math", "duplicate_payment", "suspicious_payment"} <= rules


def test_ratios(app):
    g = app.finance.facts()[("nova retail", "Q2 2026")]["metrics"]
    assert round(g["gross_margin"]["value"], 3) == 0.420
    assert round(g["current_ratio"]["value"], 2) == 2.55


# ------------------------------------------------------------------ delete is atomic and complete (run last)
def test_zz_delete_removes_everything(app):
    doc = app.store.row("SELECT id FROM documents WHERE filename = 'helix_foods_income_statement_q2_2026.pdf'")
    app.ingestor.delete(doc["id"])
    for table in ("chunks", "metrics", "edges", "mentions", "pages"):
        assert app.store.scalar(f"SELECT count(*) FROM {table} WHERE doc_id = ?", (doc["id"],)) == 0
    assert app.store.scalar("SELECT count(*) FROM entities WHERE norm = 'helix foods'") == 0
    assert "statement_math" not in {a["rule"] for a in app.finance.anomalies()}  # computed at read time
    assert all(h.filename != "helix_foods_income_statement_q2_2026.pdf"
               for h in app.retriever.search("Helix Foods gross profit").hits)
