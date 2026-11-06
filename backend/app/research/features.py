"""Features multivariables por SESIÓN bursátil (no días calendario), puras y testeables.

Operan sobre listas de cierres/volúmenes alineadas por sesión (índice = sesión). Todas
usan solo información hasta el índice t (sin look-ahead) y devuelven None si faltan datos.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence

SESSION_HORIZONS = [1, 5, 20, 60, 120]   # sesiones bursátiles


def trailing_return(closes: Sequence[float], i: int, lag: int) -> Optional[float]:
    if i - lag < 0 or i >= len(closes):
        return None
    a, b = closes[i - lag], closes[i]
    if a <= 0:
        return None
    return b / a - 1.0


def trailing_vol(closes: Sequence[float], i: int, win: int) -> Optional[float]:
    """Volatilidad anualizada de retornos log diarios en las últimas `win` sesiones."""
    if i - win < 0:
        return None
    rets = []
    for k in range(i - win + 1, i + 1):
        if closes[k - 1] > 0 and closes[k] > 0:
            rets.append(math.log(closes[k] / closes[k - 1]))
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def momentum_12_1(closes: Sequence[float], i: int) -> Optional[float]:
    """Momentum 12-1 en sesiones: retorno de t-252 a t-21 (omite el último mes)."""
    if i - 252 < 0 or i - 21 < 0:
        return None
    a, b = closes[i - 252], closes[i - 21]
    if a <= 0:
        return None
    return b / a - 1.0


def reversal(closes: Sequence[float], i: int, win: int = 5) -> Optional[float]:
    r = trailing_return(closes, i, win)
    return None if r is None else -r


def drawdown_from_high_at(closes: Sequence[float], i: int, win: int = 252) -> Optional[float]:
    if i < 0 or i >= len(closes):
        return None
    start = max(0, i - win)
    hi = max(closes[start:i + 1])
    return closes[i] / hi - 1.0 if hi > 0 else None


def volume_ratio(volumes: Sequence[Optional[float]], i: int, short: int = 20, long: int = 60) -> Optional[float]:
    if i - long + 1 < 0 or i >= len(volumes):
        return None
    s = [v for v in volumes[i - short + 1:i + 1] if v]
    l = [v for v in volumes[i - long + 1:i + 1] if v]
    if not s or not l:
        return None
    ma_s = sum(s) / len(s)
    ma_l = sum(l) / len(l)
    return ma_s / ma_l if ma_l > 0 else None


def correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 3 or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    cov = sum((a[k] - ma) * (b[k] - mb) for k in range(n))
    va = sum((a[k] - ma) ** 2 for k in range(n))
    vb = sum((b[k] - mb) ** 2 for k in range(n))
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def daily_log_returns(closes: Sequence[float]) -> List[float]:
    out = []
    for k in range(1, len(closes)):
        if closes[k - 1] > 0 and closes[k] > 0:
            out.append(math.log(closes[k] / closes[k - 1]))
    return out
