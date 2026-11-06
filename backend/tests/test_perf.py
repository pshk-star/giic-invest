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


def test_ci90_pvalue_coherence():
    """Verifica (no asume) que el IC90 bootstrap y el p-valor salen del MISMO remuestreo
    y son coherentes en el umbral: IC90 excluye 0  <=>  p < 0.10. Sin equivalencia exacta
    de valor, solo coherencia de decisión (ambos del mismo array de medias)."""
    import random as _r
    for seed in range(30):
        _r.seed(seed)
        mu = (_r.random() - 0.4) * 0.02            # media variable (a veces >0, a veces <0)
        series = [mu + (_r.random() - 0.5) * 0.04 for _ in range(80)]
        m, lo, hi, p = perf.block_bootstrap_ci(series, seed=seed)
        excludes_zero = (lo > 0) or (hi < 0)
        assert excludes_zero == (p < 0.10), (lo, hi, p)


def test_holm_monotonic_and_order():
    adj = perf.holm_adjust({"a": 0.006, "b": 0.007, "c": 0.059, "d": 0.074, "e": 0.347})
    # 5 pruebas: a -> 0.006*5=0.030 ; b -> 0.007*4=0.028 pero monotónico => >=0.030
    assert adj["a"]["p_holm"] == 0.03
    assert adj["b"]["p_holm"] >= adj["a"]["p_holm"]      # no decrece
    assert adj["c"]["p_holm"] >= adj["b"]["p_holm"]
    assert adj["e"]["p_holm"] >= adj["d"]["p_holm"]
    assert adj["a"]["rank"] == 1 and adj["e"]["rank"] == 5


def test_summarize_and_vs_benchmark_shapes():
    r = [0.01, 0.02, -0.01, 0.03, 0.00, 0.01, 0.02, -0.02]
    s = perf.summarize(r, 12.6, turnover=0.4, cost_bps=10)
    assert set(["cagr", "sharpe", "sortino", "max_drawdown", "ann_vol"]).issubset(s)
    vb = perf.vs_benchmark(r, [0.005] * len(r), 12.6)
    assert "information_ratio" in vb and "excess_ci90_per_period" in vb
    assert "excess_ci90_annualized" in vb and "defendable_at_90_unadjusted" in vb
