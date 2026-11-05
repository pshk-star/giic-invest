"""Pruebas del scanner multifactor."""
import numpy as np

from app.core import scanner as sc
from app.core.types import Fundamentals


def _inp(ticker, **f):
    tech = {k: f.pop(k) for k in list(f) if k in ("mom_6m", "mom_12m", "vol_1y", "rsi_14", "drawdown")}
    return sc.ScanInput(ticker=ticker, fundamentals=Fundamentals(ticker=ticker, **f), technical=tech, is_sample=True)


def test_percentile_rank_direction():
    # higher_is_better=False => el valor más bajo obtiene el percentil más alto
    r = sc._percentile_rank({"a": 10, "b": 20, "c": 30}, higher_is_better=False)
    assert r["a"] > r["c"]


def test_cheaper_stock_scores_higher_on_value():
    universe = [
        _inp("CHEAP", pe_forward=8, ev_ebitda=6, fcf_yield=0.10),
        _inp("MID", pe_forward=20, ev_ebitda=14, fcf_yield=0.04),
        _inp("RICH", pe_forward=50, ev_ebitda=40, fcf_yield=0.01),
    ]
    scores = {s.ticker: s for s in sc.score_universe(universe)}
    assert scores["CHEAP"].value > scores["RICH"].value


def test_higher_growth_scores_higher():
    universe = [
        _inp("FAST", rev_growth_yoy=0.5, eps_growth_yoy=0.6),
        _inp("SLOW", rev_growth_yoy=0.02, eps_growth_yoy=0.01),
    ]
    scores = {s.ticker: s for s in sc.score_universe(universe)}
    assert scores["FAST"].growth > scores["SLOW"].growth


def test_composite_in_range_and_ranked():
    universe = [
        _inp("A", pe_forward=10, roic=0.3, rev_growth_yoy=0.3, mom_6m=0.2, mom_12m=0.3, vol_1y=0.2),
        _inp("B", pe_forward=40, roic=0.05, rev_growth_yoy=0.02, mom_6m=-0.1, mom_12m=-0.2, vol_1y=0.6),
        _inp("C", pe_forward=20, roic=0.15, rev_growth_yoy=0.15, mom_6m=0.05, mom_12m=0.1, vol_1y=0.4),
    ]
    ranking = sc.rank(universe)
    assert len(ranking) == 3
    comps = [r["composite"] for r in ranking]
    assert comps == sorted(comps, reverse=True)
    for r in ranking:
        assert 0 <= r["composite"] <= 100
        assert r["is_sample"] is True  # arrastra la marca de ejemplo


def test_missing_metric_is_neutral_not_crash():
    universe = [_inp("ONLYVAL", pe_forward=10), _inp("OTHER", pe_forward=30)]
    scores = sc.score_universe(universe)
    # growth sin datos => neutral 50, sin excepción
    assert all(np.isfinite(s.composite) for s in scores)


def test_opportunity_tags():
    universe = [
        _inp("VAL", pe_forward=6, ev_ebitda=5, fcf_yield=0.12, roic=0.2, net_margin=0.25,
             rsi_14=28, drawdown=-0.1),
        _inp("EXP", pe_forward=60, ev_ebitda=45, fcf_yield=0.005),
    ]
    scores = {s.ticker: s for s in sc.score_universe(universe)}
    tags = sc.classify_opportunity(scores["VAL"])
    assert "value" in tags


def test_custom_weights_shift_ranking():
    universe = [
        _inp("GROWTHY", rev_growth_yoy=0.8, eps_growth_yoy=0.9, pe_forward=45),
        _inp("CHEAPY", rev_growth_yoy=0.02, eps_growth_yoy=0.0, pe_forward=7),
    ]
    growth_tilt = sc.rank(universe, weights={"growth": 0.9, "value": 0.1,
                                             "quality": 0.0, "momentum": 0.0, "low_risk": 0.0})
    value_tilt = sc.rank(universe, weights={"value": 0.9, "growth": 0.1,
                                            "quality": 0.0, "momentum": 0.0, "low_risk": 0.0})
    assert growth_tilt[0]["ticker"] == "GROWTHY"
    assert value_tilt[0]["ticker"] == "CHEAPY"
