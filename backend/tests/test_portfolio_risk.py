"""P2.0 — pruebas del motor de riesgo de portafolio (puras, resultados conocidos)."""
from __future__ import annotations

import math
import random

from app.research import portfolio_risk as pr


def test_hhi_equal_weights():
    assert abs(pr.hhi({"a": 0.25, "b": 0.25, "c": 0.25, "d": 0.25}) - 0.25) < 1e-9
    assert abs(pr.hhi({"a": 1.0}) - 1.0) < 1e-9


def test_concentration_groups_by_sector():
    w = {"AAPL": 0.5, "MSFT": 0.3, "XOM": 0.2}
    meta = {"AAPL": {"sector": "Tech"}, "MSFT": {"sector": "Tech"}, "XOM": {"sector": "Energy"}}
    c = pr.concentration(w, meta, "sector")
    assert abs(c["por_grupo"]["Tech"] - 0.8) < 1e-9 and abs(c["por_grupo"]["Energy"] - 0.2) < 1e-9
    assert abs(c["hhi"] - (0.8**2 + 0.2**2)) < 1e-9


def test_economic_overlap_direct_plus_etf():
    # 50% AAPL directo + 50% ETF que tiene 40% AAPL => efectivo AAPL = 0.5 + 0.5*0.4 = 0.70
    w = {"AAPL": 0.5, "SPY": 0.5}
    lt = {"SPY": {"AAPL": 0.40, "MSFT": 0.60}}
    e = pr.economic_exposure(w, lt)
    assert abs(e["exposicion_efectiva"]["AAPL"] - 0.70) < 1e-9
    assert abs(e["exposicion_efectiva"]["MSFT"] - 0.30) < 1e-9
    assert "AAPL" in e["duplicada"]
    assert abs(e["suma_duplicada"] - 0.20) < 1e-9     # min(0.5 directo, 0.2 via etf)


def test_risk_contributions_euler_adds_to_sigma():
    random.seed(3)
    n = 400
    base = [random.gauss(0, 0.01) for _ in range(n)]
    returns = {
        "A": [base[k] + random.gauss(0, 0.005) for k in range(n)],
        "B": [base[k] + random.gauss(0, 0.008) for k in range(n)],
        "C": [random.gauss(0, 0.02) for k in range(n)],
    }
    w = {"A": 0.4, "B": 0.4, "C": 0.2}
    rc = pr.risk_contributions(w, returns)
    assert abs(rc["euler_check"] - rc["vol_portafolio_anual"]) < 1e-6   # Σ contrib == σ_p
    assert abs(sum(c["contrib_pct"] for c in rc["por_posicion"].values()) - 1.0) < 2e-3  # contrib_pct redondeado


def test_portfolio_variance_matches_manual():
    returns = {"A": [0.01, -0.02, 0.03, -0.01], "B": [0.02, -0.01, 0.00, 0.01]}
    tickers, M = pr.cov_matrix(returns)
    w = [0.6, 0.4]
    var = pr.portfolio_variance(w, M)
    man = (w[0]**2 * M[0][0] + w[1]**2 * M[1][1] + 2 * w[0] * w[1] * M[0][1])
    assert abs(var - man) < 1e-12


def test_max_drawdown_known():
    s = [100, 120, 90, 110, 60, 80]      # pico 120 -> valle 60 => -50%
    d = pr.max_drawdown(s)
    assert abs(d["max_drawdown"] + 0.5) < 1e-9
    assert d["valle_idx"] == 4


def test_beta_scaled_benchmark():
    bench = [0.01, -0.02, 0.015, -0.005, 0.02]
    asset = [2 * x for x in bench]
    assert abs(pr.beta(asset, bench) - 2.0) < 1e-9


def test_fx_exposure_non_base():
    w = {"AAPL": 0.6, "TSM": 0.25, "ASML": 0.15}
    meta = {"AAPL": {"currency": "USD"}, "TSM": {"currency": "TWD"}, "ASML": {"currency": "EUR"}}
    fx = pr.fx_exposure(w, meta, "USD")
    assert abs(fx["exposicion_no_base"] - 0.40) < 1e-9
    assert abs(fx["por_moneda"]["USD"] - 0.60) < 1e-9


def test_stress_sector_and_name_shocks():
    w = {"NVDA": 0.5, "XOM": 0.5}
    meta = {"NVDA": {"sector": "Tech"}, "XOM": {"sector": "Energy"}}
    sc = {"tech_selloff": {"by_sector": {"Tech": -0.30, "Energy": 0.05}}}
    out = pr.stress(w, {}, meta, sc)
    assert abs(out["tech_selloff"] - (0.5 * -0.30 + 0.5 * 0.05)) < 1e-9


def test_marginal_impact_adding_reduces_or_changes_vol():
    random.seed(5); n = 300
    returns = {"A": [random.gauss(0, 0.02) for _ in range(n)],
               "B": [random.gauss(0, 0.02) for _ in range(n)],
               "CASH": [0.0 for _ in range(n)]}
    meta = {"A": {"sector": "Tech"}, "B": {"sector": "Tech"}, "CASH": {"sector": "Cash"}}
    w = {"A": 0.5, "B": 0.5}
    mi = pr.marginal_impact(w, returns, "CASH", 0.5, meta)
    assert mi["vol_despues"] < mi["vol_antes"]          # añadir caja reduce vol
    assert mi["hhi_sector_despues"] < mi["hhi_sector_antes"]  # y diversifica sector
