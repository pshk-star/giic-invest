"""P1.7.2 — pruebas del motor de expectativas (reconciliación, escenarios, degradación)."""
from __future__ import annotations

from app.research.fcff_forward import Assump, Base
from app.research.forward_forecast import (Consensus, reconcile_eps_to_ebit, consensus_path,
                                           giic_path, combined_path, consensus_from_eodhd,
                                           build_consensus_from_snapshots, COMBINED_WEIGHTS)


def _b():
    return Base("X", "USD", 1000.0, 0.30, 0.0, 100.0, tax_rate=0.20, interest=10.0)


def _a():
    return Assump(1.2, 0.05, 0.1, 0.15, 2.0, 0.12, 0.30, 0.20)


def test_reconcile_eps_to_ebit_not_direct():
    # eps=2, shares=100 => NI=200; pretax=200/0.8=250; EBIT=250+10=260; margin=260/1000=0.26
    r = reconcile_eps_to_ebit(2.0, 100.0, 1000.0, 10.0, 0.20)
    assert abs(r["ni"] - 200) < 1e-6 and abs(r["pretax"] - 250) < 1e-6
    assert abs(r["ebit"] - 260) < 1e-6 and abs(r["margin"] - 0.26) < 1e-9
    assert r["quality"] == "derived"
    assert reconcile_eps_to_ebit(None, 100, 1000, 10, 0.2) is None


def test_consensus_path_uses_consensus_then_fades():
    c = Consensus(currency="USD", rev_cy=1200.0, rev_ny=1400.0, g_cy=0.20, g_ny=0.1667,
                  eps_cy=2.0, eps_ny=2.5, n_analysts=30)
    p = consensus_path(_b(), _a(), c, gT=0.041)
    assert p["available"] and len(p["g"]) == 10
    assert abs(p["g"][0] - 0.20) < 1e-9 and abs(p["g"][1] - 0.1667) < 1e-9
    assert p["g"][-1] == 0.041 or abs(p["g"][-1] - 0.041) < 1e-9   # fade a gT
    assert p["g"][2] < p["g"][1]   # decae tras año 2


def test_consensus_missing_ny_degrades_confidence():
    c = Consensus(currency="USD", rev_cy=1200.0, g_cy=0.20, eps_cy=2.0)
    p = consensus_path(_b(), _a(), c, gT=0.041)
    assert p["available"] and p["confidence"] == "baja"


def test_consensus_currency_mismatch_abstains():
    c = Consensus(currency="TWD", rev_cy=1200.0, g_cy=0.2, eps_cy=2.0, rev_ny=1400.0)
    p = consensus_path(_b(), _a(), c, gT=0.041)   # base en USD
    assert p["available"] is False and p["confidence"] == "na"


def test_incoherent_implied_margin_falls_back_and_degrades():
    # eps enorme => margen implícito fuera de banda => usa m0 y degrada
    c = Consensus(currency="USD", rev_cy=1200.0, rev_ny=1400.0, g_cy=0.2, g_ny=0.17,
                  eps_cy=50.0, eps_ny=60.0, n_analysts=10)
    p = consensus_path(_b(), _a(), c, gT=0.041)
    assert p["confidence"] == "baja"
    assert abs(p["m"][0] - 0.30) < 1e-9   # cae a m0


def test_combined_weights_blend_documented():
    assert abs(COMBINED_WEIGHTS[0] - 0.70) < 1e-9 and COMBINED_WEIGHTS[4] == 0.0
    c = Consensus(currency="USD", rev_cy=1200.0, rev_ny=1400.0, g_cy=0.20, g_ny=0.17,
                  eps_cy=2.0, eps_ny=2.5, n_analysts=30)
    pA = consensus_path(_b(), _a(), c, 0.041)
    pB = giic_path(_b(), _a(), 0.041)
    pC = combined_path(pA, pB, 10)
    assert pC["available"]
    # año 1: 0.70*A + 0.30*B
    assert abs(pC["g"][0] - (0.70 * pA["g"][0] + 0.30 * pB["g"][0])) < 1e-9
    # año 5+: 100% B
    assert abs(pC["g"][5] - pB["g"][5]) < 1e-9


def test_combined_unavailable_without_consensus():
    pB = giic_path(_b(), _a(), 0.041)
    pC = combined_path({"available": False}, pB, 10)
    assert pC["available"] is False


def test_consensus_from_eodhd_parses_periods():
    obj = {"General": {"CurrencyCode": "USD"},
           "Earnings": {"Trend": {
               "2026-12-31": {"period": "0y", "revenueEstimateAvg": "1200", "revenueEstimateGrowth": "0.2",
                              "earningsEstimateAvg": "2.0", "revenueEstimateNumberOfAnalysts": "30", "date": "2026-12-31"},
               "2027-12-31": {"period": "+1y", "revenueEstimateAvg": "1400", "revenueEstimateGrowth": "0.167",
                              "earningsEstimateAvg": "2.5", "date": "2027-12-31"}}},
           "Highlights": {}}
    c = consensus_from_eodhd(obj)
    assert c.rev_cy == 1200 and c.rev_ny == 1400 and c.eps_cy == 2.0 and c.n_analysts == 30
    assert c.currency == "USD"


def test_build_consensus_from_snapshots():
    rows = [
        {"kind": "estimate:revenue", "payload": {"fiscal_period_end": "2026-12-31", "value": 1200,
         "growth": 0.2, "currency": "USD", "n_analysts": 30}},
        {"kind": "estimate:revenue", "payload": {"fiscal_period_end": "2027-12-31", "value": 1400,
         "growth": 0.167, "currency": "USD", "n_analysts": 28}},
        {"kind": "forward_multiple", "payload": {"eps_cy": 2.0, "eps_ny": 2.5}},
    ]
    c = build_consensus_from_snapshots(rows, "USD")
    assert c.rev_cy == 1200 and c.rev_ny == 1400 and c.eps_cy == 2.0 and c.fiscal_cy_end == "2026-12-31"
