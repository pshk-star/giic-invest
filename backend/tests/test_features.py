"""Pruebas de features multivariables por sesión (sin red ni deps pesadas)."""
from app.research.features import (correlation, daily_log_returns, drawdown_from_high_at,
                                   momentum_12_1, reversal, trailing_return, trailing_vol,
                                   volume_ratio)


def test_trailing_return_and_lookahead():
    closes = [100, 110, 121]
    assert round(trailing_return(closes, 1, 1), 6) == 0.1
    assert trailing_return(closes, 0, 1) is None   # no hay pasado suficiente


def test_momentum_12_1_needs_history():
    assert momentum_12_1([1.0] * 100, 50) is None   # < 252 sesiones
    closes = [100.0 + i for i in range(300)]
    assert momentum_12_1(closes, 299) is not None


def test_reversal_is_negative_of_return():
    closes = [100, 90]   # cayó 10%
    assert round(reversal(closes, 1, 1), 6) == 0.1   # reversión positiva


def test_drawdown_from_high():
    assert round(drawdown_from_high_at([100, 120, 90], 2, win=10), 6) == round(90 / 120 - 1, 6)


def test_trailing_vol_flat_is_zero():
    assert trailing_vol([100.0] * 30, 29, 20) == 0.0


def test_volume_ratio():
    vols = [100.0] * 40 + [200.0] * 20   # recientes el doble
    r = volume_ratio(vols, 59, short=20, long=60)
    assert r is not None and r > 1.0


def test_correlation_perfect():
    assert round(correlation([1, 2, 3], [2, 4, 6]), 6) == 1.0


def test_daily_log_returns_len():
    assert len(daily_log_returns([100, 110, 121])) == 2
