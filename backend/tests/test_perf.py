"""Pruebas de métricas de desempeño (valores conocidos)."""
import math

from app.research import perf


def test_cumulative_and_cagr():
    r = [0.10, 0.10, 0.10]           # +33.1% acumulado
    assert abs(perf.cumulative(r) - 0.331) < 1e-9
    # 3 periodos a ppy=3 -> 1 año -> CAGR = 33.1%
    assert abs(perf.cagr(r, 3) - 0.331) < 1e-9


def test_vol_and_sharpe():
    r = [0.02, -0.01, 0.03, 0.00, 0.01]
    v = perf.ann_vol(r, 12)
    assert v is not None and v > 0
    sh = perf.sharpe(r, 12)
    assert sh is not None
    # Sharpe = mean/std * sqrt(ppy)
    import statistics
    exp = (statistics.mean(r) / statistics.stdev(r)) * math.sqrt(12)
    assert abs(sh - exp) < 1e-6


def test_sortino_only_downside():
    r = [0.02, -0.02, 0.02, -0.02]
    s = perf.sortino(r, 12)
    assert s is not None
    # downside dev = sqrt(mean of squared negatives) = sqrt((0.02^2+0.02^2)/4)
    dd = math.sqrt((0.0004 + 0.0004) / 4)
    exp = (sum(r) / 4 / dd) * math.sqrt(12)
    assert abs(s - exp) < 1e-6


def test_max_drawdown():
    # +10%, -50%, ... peak 1.1 -> trough 0.55 -> DD = -0.5
    r = [0.10, -0.50, 0.20]
    assert abs(perf.max_drawdown(r) - (-0.5)) < 1e-9


def test_tracking_error_and_ir():
    strat = [0.03, 0.01, 0.02, 0.00]
    bench = [0.01, 0.01, 0.01, 0.01]
    e = perf.excess_series(strat, bench)
    assert all(abs(a - b) < 1e-9 for a, b in zip(e, [0.02, 0.00, 0.01, -0.01]))
    te = perf.tracking_error(strat, bench, 12)
    ir = perf.information_ratio(strat, bench, 12)
    assert te is not None and ir is not None


def test_bootstrap_ci_detects_positive_and_zero():
    # serie claramente positiva -> lo > 0 (defendible)
    pos = [0.02] * 40
    m, lo, hi, p = perf.block_bootstrap_ci(pos)
    assert lo is not None and lo > 0 and p == 0.0
    # serie centrada en 0 -> IC cruza 0
    import random as _r
    _r.seed(1)
    noise = [(_r.random() - 0.5) * 0.04 for _ in range(60)]
    m2, lo2, hi2, p2 = perf.block_bootstrap_ci(noise)
    assert lo2 is not None and lo2 < 0 < hi2


def test_summarize_and_vs_benchmark_shapes():
    r = [0.01, 0.02, -0.01, 0.03, 0.00, 0.01, 0.02, -0.02]
    s = perf.summarize(r, 12.6, turnover=0.4, cost_bps=10)
    assert set(["cagr", "sharpe", "sortino", "max_drawdown", "ann_vol"]).issubset(s)
    vb = perf.vs_benchmark(r, [0.005] * len(r), 12.6)
    assert "information_ratio" in vb and "excess_ci90" in vb and "defendable_at_90" in vb
