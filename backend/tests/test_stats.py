"""Pruebas del núcleo estadístico de forecasting (sin red ni deps)."""
from app.research.stats import (drawdown_from_high, forward_return, max_drawdown,
                                pearson, quantiles, ranks, sharpe, spearman_ic)


def test_ranks_with_ties():
    assert ranks([10, 20, 20, 40]) == [1.0, 2.5, 2.5, 4.0]


def test_spearman_ic_monotonic():
    # señal perfectamente ordenada con el retorno futuro => IC = 1
    sig = [1, 2, 3, 4, 5]
    fwd = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert round(spearman_ic(sig, fwd), 6) == 1.0
    # inversa => -1
    assert round(spearman_ic(sig, fwd[::-1]), 6) == -1.0


def test_spearman_ic_insufficient():
    assert spearman_ic([1, 2], [0.1, 0.2]) is None


def test_forward_return_no_lookahead_bounds():
    prices = [100, 110, 121]
    assert round(forward_return(prices, 0, 1), 6) == 0.1
    assert forward_return(prices, 2, 1) is None   # no hay dato futuro (no inventa)


def test_max_drawdown():
    assert round(max_drawdown([100, 120, 90, 100]), 6) == round(90 / 120 - 1, 6)


def test_sharpe_zero_when_flat():
    assert sharpe([0.0, 0.0, 0.0]) is None   # sin varianza


def test_quantiles_median():
    q = quantiles([1, 2, 3, 4, 5], [0.5])
    assert q["p50"] == 3


def test_drawdown_from_high():
    dd = drawdown_from_high([100, 120, 90], lookback=10)
    assert dd[0] == 0.0 and dd[1] == 0.0
    assert round(dd[2], 6) == round(90 / 120 - 1, 6)


def test_pearson_perfect():
    assert round(pearson([1, 2, 3], [2, 4, 6]), 6) == 1.0
