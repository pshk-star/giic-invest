"""Pruebas de indicadores: validadas contra casos con resultado conocido."""
import numpy as np
import pandas as pd

from app.core import indicators as ind


def _series(values):
    idx = pd.bdate_range("2020-01-01", periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_rsi_all_gains_is_100():
    s = _series(list(range(1, 60)))  # monótona creciente
    assert ind.rsi(s, 14).iloc[-1] == 100.0


def test_rsi_bounds():
    rng = np.random.default_rng(0)
    s = _series(100 + np.cumsum(rng.normal(0, 1, 300)))
    r = ind.rsi(s, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()


def test_sma_known_value():
    s = _series([10, 20, 30, 40, 50])
    assert ind.sma(s, 5).iloc[-1] == 30.0


def test_distance_to_sma_sign():
    s = _series([10, 10, 10, 10, 20])  # último muy por encima de su media
    assert ind.distance_to_sma(s, 5) > 0


def test_drawdown_is_zero_at_new_high():
    s = _series([1, 2, 3, 4, 5])
    assert ind.current_drawdown(s) == 0.0


def test_max_drawdown_known():
    # sube a 100, cae a 50 => -50%
    s = _series([50, 100, 75, 50, 60])
    assert abs(ind.max_drawdown(s) - (-0.5)) < 1e-9


def test_momentum_known():
    s = _series([100, 110, 121])  # +10% cada paso
    assert abs(ind.momentum(s, 1) - 0.10) < 1e-9


def test_realized_vol_positive():
    rng = np.random.default_rng(1)
    s = _series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    v = ind.realized_volatility(s, 252)
    assert 0 < v < 2


def test_snapshot_keys():
    rng = np.random.default_rng(2)
    s = _series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    snap = ind.snapshot(s)
    for k in ("last", "rsi_14", "sma_50", "sma_200", "mom_6m", "drawdown", "vol_1y"):
        assert k in snap


def test_insufficient_history_returns_nan():
    s = _series([1, 2, 3])
    assert np.isnan(ind.distance_to_sma(s, 50))
    assert np.isnan(ind.momentum(s, 252))
