"""P1.7 Fase 1 — pruebas PURAS (sin red) de la captura de expectativas."""
from __future__ import annotations

from app.jobs.estimates_snapshot import (build_estimate_rows, revenue_scale_check,
                                         _dispersion, _parse_period_end, REV_SCALE_HI)


def _obj():
    return {
        "General": {"CurrencyCode": "USD", "UpdatedAt": "2026-11-09"},
        "Earnings": {"Trend": {
            "2027-12-31": {"date": "2027-12-31", "period": "+1y", "growth": "0.25",
                           "revenueEstimateAvg": "300000000000", "revenueEstimateLow": "280000000000",
                           "revenueEstimateHigh": "330000000000", "revenueEstimateNumberOfAnalysts": "40",
                           "revenueEstimateGrowth": "0.28",
                           "earningsEstimateAvg": "5.0", "earningsEstimateLow": "4.5",
                           "earningsEstimateHigh": "5.6", "earningsEstimateNumberOfAnalysts": "45",
                           "epsTrendCurrent": "5.0", "epsTrend7daysAgo": "4.9", "epsTrend30daysAgo": "4.7",
                           "epsRevisionsUpLast7days": "12", "epsRevisionsDownLast7days": "2",
                           "epsRevisionsUpLast30days": "20", "epsRevisionsDownLast30days": "5"},
        }},
        "AnalystRatings": {"Rating": "1.8", "TargetPrice": "220", "StrongBuy": "30", "Buy": "10",
                           "Hold": "5", "Sell": "1", "StrongSell": "0"},
        "Highlights": {"ForwardPE": "35.1", "PEGRatio": "1.4", "EPSEstimateCurrentYear": "4.0",
                       "EPSEstimateNextYear": "5.0"},
        "Valuation": {"ForwardPE": "35.0", "EnterpriseValueEbitda": "28.3", "PriceSalesTTM": "20.1"},
    }


def test_three_distinct_dates_and_fiscal_period():
    rows = build_estimate_rows("NVDA", _obj(), "2026-11-10", "2026-11-10T12:00:00Z",
                               reported_revenue=130_000_000_000)
    rev = [r for r in rows if r["kind"] == "estimate:revenue"][0]
    # captured_at (captura) != published_at (efectiva) != observation_date (fin período fiscal)
    assert rev["captured_at"] == "2026-11-10T12:00:00Z"
    assert rev["published_at"] == "2027-12-31"
    assert rev["observation_date"] == "2027-12-31"          # fin de período fiscal
    assert rev["payload"]["fiscal_period_label"] == "+1y"   # período fiscal textual preservado
    assert rev["snapshot_date"] == "2026-11-10"


def test_dedupe_key_is_stable_per_metric_period_day():
    rows = build_estimate_rows("NVDA", _obj(), "2026-11-10", "t", reported_revenue=1e11)
    keys = [(r["kind"], r["ticker"], r["observation_date"], r["snapshot_date"]) for r in rows]
    assert len(keys) == len(set(keys))  # el UNIQUE de pit_snapshots nunca colisiona entre métricas


def test_revisions_and_dispersion_and_analysts_captured():
    rows = build_estimate_rows("NVDA", _obj(), "2026-11-10", "t", reported_revenue=1e11)
    eps = [r for r in rows if r["kind"] == "estimate:eps"][0]
    assert eps["payload"]["n_analysts"] == 45
    assert eps["payload"]["revisions"]["up30"] == 20 and eps["payload"]["revisions"]["down30"] == 5
    assert eps["payload"]["trend"]["d30"] == 4.7
    assert eps["payload"]["dispersion"] == _dispersion(5.0, 4.5, 5.6)


def test_target_rating_and_forward_multiple_rows():
    rows = build_estimate_rows("NVDA", _obj(), "2026-11-10", "t", reported_revenue=1e11)
    assert any(r["kind"] == "analyst_target_rating" and r["payload"]["target_price"] == 220 for r in rows)
    fm = [r for r in rows if r["kind"] == "forward_multiple"][0]
    assert fm["payload"]["forward_pe"] == 35.0 and fm["payload"]["eps_ny"] == 5.0


def test_scale_guard_ok_for_plausible_multiyear_growth():
    # TSM #5: FY2027 ~2x FY2025 => ratio 2.0, dentro de rango => ok (NO es error de unidades)
    assert revenue_scale_check(7.69e12, 3.81e12)["status"] == "ok"
    assert revenue_scale_check(7.69e12, 3.81e12)["ratio_vs_reported"] == 2.0184


def test_scale_guard_flags_unit_mismatch():
    # estimación en 'miles' frente a reportado en 'unidades' => ratio ~1000 => revisar
    res = revenue_scale_check(3.81e15, 3.81e12)
    assert res["status"] == "revisar_escala"
    assert res["magnitude_hint"] == 3
    assert res["ratio_vs_reported"] > REV_SCALE_HI


def test_scale_guard_no_reference():
    assert revenue_scale_check(1e9, None)["status"] == "sin_referencia"
    assert revenue_scale_check(None, 1e9)["status"] == "sin_referencia"


def test_parse_period_end():
    assert _parse_period_end("2027-12-31", {}) == "2027-12-31"
    assert _parse_period_end("+1y", {"date": "2027-09-30"}) == "2027-09-30"
    assert _parse_period_end("+1y", {"date": None}) is None
