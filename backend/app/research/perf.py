"""Métricas de desempeño de una SERIE de retornos por periodo (no solapados).

Puras y determinísticas (sin red), para evaluación económica confirmatoria. Todas las
anualizaciones usan `ppy` (periodos por año); con rebalanceo cada 20 sesiones NYSE,
ppy = 252/20 = 12.6. Supuesto explícito: tasa libre de riesgo = 0 (se documenta).
"""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Sequence


def equity_curve(returns: Sequence[float]) -> List[float]:
    eq = [1.0]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return eq


def cumulative(returns: Sequence[float]) -> float:
    p = 1.0
    for r in returns:
        p *= (1.0 + r)
    return p - 1.0


def cagr(returns: Sequence[float], ppy: float) -> Optional[float]:
    if not returns:
        return None
    growth = 1.0
    for r in returns:
        growth *= (1.0 + r)
    if growth <= 0:
        return None
    years = len(returns) / ppy
    return growth ** (1.0 / years) - 1.0 if years > 0 else None


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _std(xs: Sequence[float], ddof: int = 1) -> Optional[float]:
    n = len(xs)
    if n - ddof <= 0:
        return None
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - ddof))


def ann_vol(returns: Sequence[float], ppy: float) -> Optional[float]:
    s = _std(returns)
    return s * math.sqrt(ppy) if s is not None else None


def sharpe(returns: Sequence[float], ppy: float, rf_per_period: float = 0.0) -> Optional[float]:
    ex = [r - rf_per_period for r in returns]
    s = _std(ex)
    if s is None or s == 0:
        return None
    return (_mean(ex) / s) * math.sqrt(ppy)


def sortino(returns: Sequence[float], ppy: float, target_per_period: float = 0.0) -> Optional[float]:
    ex = [r - target_per_period for r in returns]
    downside = [min(e, 0.0) ** 2 for e in ex]
    dd = math.sqrt(sum(downside) / len(downside)) if downside else None
    if dd is None or dd == 0:
        return None
    return (_mean(ex) / dd) * math.sqrt(ppy)


def max_drawdown(returns: Sequence[float]) -> float:
    eq = equity_curve(returns)
    peak = eq[0]
    mdd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def excess_series(strategy: Sequence[float], benchmark: Sequence[float]) -> List[float]:
    n = min(len(strategy), len(benchmark))
    return [strategy[i] - benchmark[i] for i in range(n)]


def tracking_error(strategy: Sequence[float], benchmark: Sequence[float], ppy: float) -> Optional[float]:
    e = excess_series(strategy, benchmark)
    s = _std(e)
    return s * math.sqrt(ppy) if s is not None else None


def information_ratio(strategy: Sequence[float], benchmark: Sequence[float], ppy: float) -> Optional[float]:
    e = excess_series(strategy, benchmark)
    s = _std(e)
    if s is None or s == 0:
        return None
    return (_mean(e) / s) * math.sqrt(ppy)


def ann_excess_return(strategy: Sequence[float], benchmark: Sequence[float], ppy: float) -> Optional[float]:
    e = excess_series(strategy, benchmark)
    return _mean(e) * ppy if e else None


def block_bootstrap_ci(series: Sequence[float], nb: int = 2000, block: int = 3,
                       lo_q: float = 0.05, hi_q: float = 0.95, seed: int = 42):
    """IC del valor medio por bootstrap de bloques (respeta dependencia temporal).
    Devuelve (media, lo, hi, p_two_sided_vs_0). None si la muestra es muy corta."""
    xs = list(series)
    n = len(xs)
    if n < 6:
        return (None, None, None, None)
    rnd = random.Random(seed)
    nblk = (n + block - 1) // block
    means = []
    for _ in range(nb):
        s: List[float] = []
        for _b in range(nblk):
            st = rnd.randrange(0, max(1, n - block))
            s.extend(xs[st:st + block])
        s = s[:n]
        means.append(sum(s) / len(s))
    means.sort()
    m = _mean(xs)
    lo = means[int(lo_q * nb)]
    hi = means[int(hi_q * nb)]
    # p-valor bilateral aproximado: fracción de medias remuestreadas al otro lado de 0
    frac_le0 = sum(1 for x in means if x <= 0) / nb
    p = 2 * min(frac_le0, 1 - frac_le0)
    return (m, lo, hi, round(p, 4))


def holm_adjust(pvalues: Dict[str, float]) -> Dict[str, Dict]:
    """Corrección de Holm-Bonferroni (step-down) con monotonicidad impuesta.
    Devuelve, por hipótesis, {p_raw, p_holm, rank}. p_holm es no decreciente en el rango."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    out: Dict[str, Dict] = {}
    running = 0.0
    for rank, (k, p) in enumerate(items):
        adj = min(1.0, p * (m - rank))
        running = max(running, adj)          # monotonicidad: no puede decrecer
        out[k] = {"p_raw": round(p, 4), "p_holm": round(running, 4), "rank": rank + 1}
    return out


def summarize(returns: Sequence[float], ppy: float, turnover: Optional[float] = None,
              cost_bps: Optional[float] = None) -> Dict[str, Optional[float]]:
    return {
        "n_periods": len(returns),
        "cum_return": round(cumulative(returns), 4),
        "cagr": (round(cagr(returns, ppy), 4) if cagr(returns, ppy) is not None else None),
        "ann_vol": (round(ann_vol(returns, ppy), 4) if ann_vol(returns, ppy) is not None else None),
        "sharpe": (round(sharpe(returns, ppy), 3) if sharpe(returns, ppy) is not None else None),
        "sortino": (round(sortino(returns, ppy), 3) if sortino(returns, ppy) is not None else None),
        "max_drawdown": round(max_drawdown(returns), 4),
        "avg_turnover": (round(turnover, 3) if turnover is not None else None),
        "cost_bps": cost_bps,
    }


def vs_benchmark(strategy: Sequence[float], benchmark: Sequence[float], ppy: float) -> Dict[str, Optional[float]]:
    ae = ann_excess_return(strategy, benchmark, ppy)
    te = tracking_error(strategy, benchmark, ppy)
    ir = information_ratio(strategy, benchmark, ppy)
    m, lo, hi, p = block_bootstrap_ci(excess_series(strategy, benchmark))
    return {
        "ann_excess_return": (round(ae, 4) if ae is not None else None),
        "tracking_error": (round(te, 4) if te is not None else None),
        "information_ratio": (round(ir, 3) if ir is not None else None),
        "excess_mean_per_period": (round(m, 5) if m is not None else None),
        "excess_ci90_per_period": ([round(lo, 5), round(hi, 5)] if lo is not None else None),
        # Anualización LINEAL del IC (mean*ppy); aproximación, no recompone.
        "excess_ci90_annualized": ([round(lo * ppy, 4), round(hi * ppy, 4)] if lo is not None else None),
        "excess_p_value": p,
        "defendable_at_90_unadjusted": bool(lo is not None and lo > 0),
    }
