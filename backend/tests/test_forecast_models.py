"""P1.8 — pruebas de los modelos de proyección y del backtest (puras, sin red)."""
from __future__ import annotations

from app.research.forecast_models import (project, growth_rule, rev_cagr, median_yoy,
                                          trailing_margin, rel_error)
from app.research.forecast_backtest import build_series, _agg, jackknife_coverage, backtest_company


def _series(growth=0.10, margin=0.30, n=12, rev0=1000.0):
    s = []
    rev = rev0
    for i in range(n):
        s.append({"year": f"{2010+i}-12-31", "revenue": rev, "ebit": rev * margin,
                  "ebit_margin": margin, "pretax": rev * margin, "tax": rev * margin * 0.15,
                  "capex": -(rev * 0.05), "dna": rev * 0.03, "wc_change": rev * 0.01})
        rev *= (1 + growth)
    return s


def test_cagr_and_median_recover_growth():
    s = _series(0.10)
    assert abs(rev_cagr(s, 8, 4) - 0.10) < 1e-6
    assert abs(median_yoy(s, 8, 4) - 0.10) < 1e-6


def test_models_project_near_actual_on_clean_trend():
    s = _series(0.10, 0.30)
    gT = 0.04
    for model in ("A", "D"):
        p = project(model, s, 7, gT, (1, 2, 3))
        # h=1 crecimiento ~10% (con leve fade); ingreso proyectado cerca del real
        actual = s[8]["revenue"]
        assert abs(rel_error(p[1]["revenue"], actual)) < 0.02
        assert abs(p[1]["ebit_margin"] - 0.30) < 1e-9


def test_pit_no_lookahead():
    # proyectar en ti no debe depender de datos posteriores
    s = _series(0.10)
    p_full = project("A", s, 7, 0.04, (1, 2, 3))
    p_trunc = project("A", s[:9], 7, 0.04, (1, 2, 3))   # sin años > ti+1
    assert abs(p_full[1]["revenue"] - p_trunc[1]["revenue"]) < 1e-9


def test_model_C_applicable_and_not():
    s = _series(0.10)
    gr = growth_rule("C", s, 8, 0.04)
    assert gr["applicable"] is True and gr["g1"] > 0
    # sin capex => C no aplicable
    s2 = [{**r, "capex": None} for r in s]
    assert growth_rule("C", s2, 8, 0.04)["applicable"] is False


def test_build_series_filters_and_orders():
    by = {"revenue": {"2021-12-31": 100, "2020-12-31": 90, "2019-12-31": 0},
          "operating_income": {"2021-12-31": 30, "2020-12-31": 27, "2019-12-31": 5}}
    s = build_series(by)
    assert [r["year"] for r in s] == ["2020-12-31", "2021-12-31"]   # ordena y descarta rev<=0
    assert abs(s[0]["ebit_margin"] - 0.3) < 1e-9


def test_backtest_clean_trend_low_error():
    s = _series(0.10, 0.30, n=12)
    pts = backtest_company("TEST", "USD", s, (1, 2, 3))
    revs = [abs(p["err_rev"]) for p in pts if p["model"] == "D" and p["err_rev"] is not None]
    assert revs and max(revs) < 0.05   # tendencia limpia => error bajo


def test_jackknife_coverage_insufficient_flagged():
    assert jackknife_coverage([0.1, -0.1, 0.05])["suficiente"] is False
    big = [0.05 * ((-1) ** i) for i in range(30)]
    cov = jackknife_coverage(big)
    assert cov["suficiente"] is True and "cov_90" in cov


def test_agg_mae_and_bias():
    a = _agg([0.1, -0.1, 0.2, -0.2])
    assert a["n"] == 4 and a["mae"] > 0
