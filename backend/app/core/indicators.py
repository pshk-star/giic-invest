"""Indicadores técnicos y de riesgo sobre series de precios.

Entradas: pandas.Series de precios de cierre (idealmente ajustados por dividendos
y splits), indexadas por fecha y ordenadas ascendentemente. Todas las funciones son
puras y deterministas. No se inventan datos: si no hay suficiente historia para un
indicador, se devuelve NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _clean(prices: pd.Series) -> pd.Series:
    s = pd.Series(prices).astype(float).dropna()
    return s.sort_index()


def sma(prices: pd.Series, window: int) -> pd.Series:
    return _clean(prices).rolling(window).mean()


def distance_to_sma(prices: pd.Series, window: int) -> float:
    """Distancia porcentual del último precio respecto a su SMA (p.ej. +0.07 = 7% arriba)."""
    s = _clean(prices)
    if len(s) < window:
        return float("nan")
    m = s.rolling(window).mean().iloc[-1]
    if not np.isfinite(m) or m == 0:
        return float("nan")
    return float(s.iloc[-1] / m - 1.0)


def rsi(prices: pd.Series, window: int = 14) -> pd.Series:
    """RSI de Wilder. Devuelve la serie; usar .iloc[-1] para el valor actual."""
    s = _clean(prices)
    delta = s.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # media exponencial de Wilder (alpha = 1/window)
    avg_gain = gain.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    out[avg_loss == 0.0] = 100.0
    return out


def macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Devuelve (macd_line, signal_line, histogram)."""
    s = _clean(prices)
    ema_fast = s.ewm(span=fast, adjust=False).mean()
    ema_slow = s.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def daily_returns(prices: pd.Series) -> pd.Series:
    return _clean(prices).pct_change().dropna()


def realized_volatility(prices: pd.Series, window: int = TRADING_DAYS) -> float:
    """Volatilidad anualizada de los retornos diarios en la ventana."""
    r = daily_returns(prices).tail(window)
    if len(r) < 2:
        return float("nan")
    return float(r.std(ddof=1) * np.sqrt(TRADING_DAYS))


def momentum(prices: pd.Series, lookback_days: int) -> float:
    """Retorno simple en los últimos `lookback_days` (p.ej. 126 ≈ 6 meses)."""
    s = _clean(prices)
    if len(s) <= lookback_days:
        return float("nan")
    return float(s.iloc[-1] / s.iloc[-1 - lookback_days] - 1.0)


def drawdown_series(prices: pd.Series) -> pd.Series:
    """Serie de drawdown desde el máximo acumulado (valores <= 0)."""
    s = _clean(prices)
    peak = s.cummax()
    return s / peak - 1.0


def current_drawdown(prices: pd.Series) -> float:
    dd = drawdown_series(prices)
    return float(dd.iloc[-1]) if len(dd) else float("nan")


def max_drawdown(prices: pd.Series) -> float:
    dd = drawdown_series(prices)
    return float(dd.min()) if len(dd) else float("nan")


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> float:
    """Average True Range (Wilder) sobre OHLC. Devuelve el valor actual."""
    high, low, close = _clean(high), _clean(low), _clean(close)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    a = tr.ewm(alpha=1.0 / window, min_periods=window, adjust=False).mean()
    return float(a.iloc[-1]) if len(a) and np.isfinite(a.iloc[-1]) else float("nan")


def snapshot(prices: pd.Series) -> dict:
    """Resumen técnico de una serie de precios, listo para API/UI."""
    s = _clean(prices)
    if len(s) == 0:
        return {}
    return {
        "last": float(s.iloc[-1]),
        "rsi_14": _last(rsi(s, 14)),
        "sma_50": _last(sma(s, 50)),
        "sma_200": _last(sma(s, 200)),
        "dist_sma_50": distance_to_sma(s, 50),
        "dist_sma_200": distance_to_sma(s, 200),
        "mom_1m": momentum(s, 21),
        "mom_3m": momentum(s, 63),
        "mom_6m": momentum(s, 126),
        "mom_12m": momentum(s, 252),
        "vol_1y": realized_volatility(s, 252),
        "drawdown": current_drawdown(s),
        "max_drawdown": max_drawdown(s),
    }


def _last(series: pd.Series):
    if series is None or len(series) == 0:
        return float("nan")
    v = series.iloc[-1]
    return float(v) if np.isfinite(v) else float("nan")
