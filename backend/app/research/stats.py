"""Estadística pura para backtesting/forecasting (sin numpy/pandas: testeable en cualquier
entorno). Todo es determinístico y auditable; no inventa probabilidades.

Convención: retornos simples (fracción). Las funciones devuelven None cuando no hay
datos suficientes, nunca un valor inventado.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence


def ranks(xs: Sequence[float]) -> List[float]:
    """Rangos 1..n con promedio en empates."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # rango promedio (1-indexado)
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = len(a)
    if n < 2 or n != len(b):
        return None
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    va = sum((a[i] - ma) ** 2 for i in range(n))
    vb = sum((b[i] - mb) ** 2 for i in range(n))
    if va <= 0 or vb <= 0:
        return None
    return cov / math.sqrt(va * vb)


def spearman_ic(signal: Sequence[float], forward: Sequence[float]) -> Optional[float]:
    """Information Coefficient de rango: correlación de Spearman señal vs retorno futuro."""
    if len(signal) < 3 or len(signal) != len(forward):
        return None
    return pearson(ranks(signal), ranks(forward))


def forward_return(prices: Sequence[float], i: int, horizon: int) -> Optional[float]:
    if i < 0 or i + horizon >= len(prices):
        return None
    p0, p1 = prices[i], prices[i + horizon]
    if p0 <= 0:
        return None
    return p1 / p0 - 1.0


def max_drawdown(prices: Sequence[float]) -> Optional[float]:
    if len(prices) < 2:
        return None
    peak = prices[0]
    mdd = 0.0
    for p in prices:
        if p > peak:
            peak = p
        if peak > 0:
            mdd = min(mdd, p / peak - 1.0)
    return mdd


def sharpe(returns: Sequence[float], periods_per_year: int = 12) -> Optional[float]:
    """Sharpe (rf=0) a partir de retornos periódicos."""
    n = len(returns)
    if n < 2:
        return None
    m = sum(returns) / n
    var = sum((r - m) ** 2 for r in returns) / (n - 1)
    sd = math.sqrt(var)
    if sd <= 0:
        return None
    return (m / sd) * math.sqrt(periods_per_year)


def quantiles(xs: Sequence[float], qs: Sequence[float]) -> Dict[str, Optional[float]]:
    """Cuantiles empíricos (interpolación lineal). Base para distribuciones condicionales."""
    out: Dict[str, Optional[float]] = {}
    s = sorted(xs)
    n = len(s)
    for q in qs:
        key = f"p{int(round(q * 100))}"
        if n == 0:
            out[key] = None
            continue
        pos = q * (n - 1)
        lo = int(math.floor(pos))
        hi = int(math.ceil(pos))
        out[key] = s[lo] if lo == hi else s[lo] + (s[hi] - s[lo]) * (pos - lo)
    return out


def drawdown_from_high(prices: Sequence[float], lookback: int) -> List[float]:
    """Drawdown de cada punto respecto al máximo de las `lookback` observaciones previas."""
    out: List[float] = []
    for i in range(len(prices)):
        start = max(0, i - lookback)
        hi = max(prices[start:i + 1])
        out.append(prices[i] / hi - 1.0 if hi > 0 else 0.0)
    return out
