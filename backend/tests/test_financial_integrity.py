"""P0 regressions at the financial entry points; no network or market-price calibration."""
import math
import pytest
from tests.test_valuation_engine import _series
from app.research.edgar_series import build_series_from_rows
from app.research.ttm import ttm_by_quarters
from app.research.valuation_engine import evaluate, evaluate_ttm


def quarters(ends=("2025-12-31", "2026-03-31", "2026-06-30", "2026-09-30"), loss=False):
    return {"Financials": {
        "Income_Statement": {"currency_symbol": "USD", "quarterly": {
            d: {"totalRevenue": 40e9, "operatingIncome": (-8e9 if loss else 12e9),
                "incomeTaxExpense": 2e9, "incomeBeforeTax": 10e9} for d in ends}},
        "Cash_Flow": {"quarterly": {d: {"totalCashFromOperatingActivities": 10e9,
                                                      "capitalExpenditures": 2e9} for d in ends}}}}


def test_dual_currency_requires_explicit_reporting_currency_on_tie():
    rows = [{"concept": c, "unit": u, "value": v, "period_start": s,
             "period_end": "2025-12-31", "filing_date": "2026-02-01"}
            for c, u, v, s in [("Revenues", "TWD", 3200, "2025-01-01"),
                               ("Revenues", "USD", 100, "2025-01-01"),
                               ("StockholdersEquity", "TWD", 1600, None),
                               ("StockholdersEquity", "USD", 50, None)]]
    with pytest.raises(ValueError, match="moneda"):
        build_series_from_rows(rows)
    for seq in (rows, list(reversed(rows))):
        s = build_series_from_rows(seq, reporting_currency="TWD")
        assert s["by_field"]["equity"]["2025-12-31"] == 1600


@pytest.mark.parametrize("ccy,adr,px", [("USD", 1, 50), ("EUR", 1, 54), ("TWD", 5, 7.75), ("USD", .5, 25)])
def test_dimensions_are_equivalent_across_currencies_and_adr(ccy, adr, px):
    r = evaluate("DIM", _series(ccy=ccy), {}, px, adr=adr).result
    assert r is not None
    assert r.inputs["w_equity"] == pytest.approx(.625, abs=.0005)


def test_currency_conflict_and_missing_cash_cannot_emit_fv():
    assert evaluate("MIX", _series(), _series(ccy="EUR"), 50).result is None
    s = _series(); s["by_field"]["cash"] = {}
    assert evaluate("MISSING", s, {}, 50).result is None


def test_ttm_rejects_gaps_through_all_fallbacks():
    obj = quarters(("2025-03-31", "2025-06-30", "2025-12-31", "2026-03-31"))
    rejected = ttm_by_quarters({}, obj, {"10-Q"})
    out, _ = evaluate_ttm("GAP", _series(), {}, [], obj, 50, official_ttm=rejected)
    assert out.result is None


def test_latest_complete_window_beats_older_sec_window():
    ends = ("2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31")
    starts = ("2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01")
    sec = {"NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
        {"start": s, "end": e, "val": 1e9, "filed": "2025-02-01", "form": "10-Q"}
        for s, e in zip(starts, ends)]}}}
    out, info = evaluate_ttm("LATEST", _series(), {}, [], quarters(), 50,
                             official_ttm=ttm_by_quarters(sec, quarters(), {"10-Q"}))
    assert out.result is not None
    assert info["fin_ttm"] == "2026-09-30"
    assert out.result.inputs["revenue0"] == 160e9


def test_ttm_operating_loss_never_becomes_positive_margin():
    out, _ = evaluate_ttm("LOSS", _series(), {}, [], quarters(loss=True), 50)
    assert out.result is None


def test_ttm_cannot_mix_statement_currencies():
    obj = quarters()
    obj["Financials"]["Cash_Flow"]["currency_symbol"] = "EUR"
    out, _ = evaluate_ttm("CROSS_CCY", _series(), {}, [], obj, 50)
    assert out.result is None


def test_recovery_is_assessed_using_the_actual_ttm_base():
    s = _series(op_margin=-.1)
    out, _ = evaluate_ttm("RECOVERY", s, {}, [], quarters(), 50)
    assert out.result is not None
    assert out.result.inputs["op_margin"] == .3


def test_failed_ttm_control_is_not_silently_discarded():
    official = ttm_by_quarters({}, quarters(), {"10-Q"})
    official["controles"].append(("source_mismatch", False, "unresolved"))
    out, _ = evaluate_ttm("DISC", _series(), {}, [], quarters(), 50, official_ttm=official)
    assert out.result is None or not out.result.validated
    if out.result:
        assert any(c[0] == "source_mismatch" and not c[1] for c in out.result.controls)


def test_live_price_contract_is_explicit_and_finite():
    for kwargs in ({"price_currency": "EUR"}, {"shares_basis": "adr"}):
        assert evaluate("CONTRACT", _series(), {}, 50, **kwargs).result is None
    assert evaluate("NAN", _series(), {}, math.nan).result is None


def test_job_publishes_same_day_revisions_and_invalidations(monkeypatch):
    from app.jobs import valuation_engine_run as job
    from app.jobs import supabase_writer
    from app.providers.edgar import EDGARProvider
    publications = []
    class Writer:
        def __init__(self, *args): pass
        def select_rows(self, table, **kwargs):
            return ([{"ticker": "TEST", "currency": "USD", "adr_ratio": 1}]
                    if table == "instruments" else
                    [{"ticker": "TEST", "close": 50, "currency": "USD", "as_of": "2026-11-13"}])
        def publish_valuations(self, run_id, rows):
            publications.append((run_id, rows)); return len(rows)
        def insert_append(self, *a, **k):
            pytest.fail("governing valuation must not use legacy daily conflict key")
    monkeypatch.setattr(supabase_writer, "SupabaseWriter", Writer)
    monkeypatch.setattr(EDGARProvider, "_load_ciks", lambda self: (_ for _ in ()).throw(ValueError("offline")))
    monkeypatch.setattr(job, "fetch_edgar_rows", lambda *args: [])
    monkeypatch.setattr(job, "_eodhd_obj", lambda t: (_series(), quarters()))
    job.run(["TEST"], True, "2026-11-13")
    monkeypatch.setattr(job, "_eodhd_obj", lambda t: (_series(), quarters(loss=True)))
    job.run(["TEST"], True, "2026-11-13")
    assert len(publications) == 2
    assert publications[0][0] != publications[1][0]
    assert publications[1][1][0]["payload"]["status"] == "no_valorable"
    assert publications[1][1][0]["payload"]["modelos"][0]["fair_value_usd"] is None

