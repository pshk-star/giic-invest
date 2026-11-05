"""Scanner multifactor: puntúa un universo de instrumentos por factores y los rankea.

Metodología: puntajes *transversales* (cross-sectional), no umbrales absolutos
arbitrarios. Cada métrica se convierte a percentil dentro del universo evaluado
(0-100, donde 100 = mejor), con la dirección correcta (p.ej. P/E bajo puntúa alto
en 'value'). El compuesto es una suma ponderada de los factores. Las ponderaciones
por defecto son un punto de partida razonable y quedan expuestas para calibrarse
luego contra el backtesting (no se afirma que estén validadas todavía).

Esto puntúa atractivo relativo; NO es una probabilidad. El motor predictivo
(fase posterior) producirá probabilidades calibradas por separado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from .types import FactorScore, Fundamentals

# Ponderaciones por defecto del compuesto. Suman 1.0. Calibrables vía backtesting.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "value": 0.25,
    "quality": 0.25,
    "growth": 0.20,
    "momentum": 0.20,
    "low_risk": 0.10,
}


@dataclass
class ScanInput:
    """Entrada por instrumento: fundamentales + técnicos ya calculados (snapshot)."""
    ticker: str
    fundamentals: Optional[Fundamentals] = None
    technical: Optional[dict] = None   # salida de indicators.snapshot()
    is_sample: bool = False
    sector: Optional[str] = None       # para ranking comparable por sector


def _percentile_rank(values: Mapping[str, float], higher_is_better: bool) -> Dict[str, float]:
    """Convierte métricas a percentil 0-100 dentro del universo. NaN -> no rankeado."""
    s = pd.Series({k: v for k, v in values.items()
                   if v is not None and np.isfinite(v)}, dtype=float)
    out: Dict[str, float] = {k: float("nan") for k in values}
    if len(s) == 0:
        return out
    if len(s) == 1:
        out[s.index[0]] = 50.0
        return out
    # escala a [0,100] completo: mejor = 100, peor = 0 ((rank-1)/(n-1))
    ranks = (s.rank(method="average") - 1.0) / (len(s) - 1.0) * 100.0
    if not higher_is_better:
        ranks = 100.0 - ranks
    for k, v in ranks.items():
        out[k] = float(v)
    return out


def _safe_mean(values) -> float:
    """Promedio de los valores finitos; NaN si no hay ninguno (sin warnings)."""
    finite = [v for v in values if v is not None and np.isfinite(v)]
    return float(np.mean(finite)) if finite else float("nan")


def _collect(inputs: List[ScanInput], getter) -> Dict[str, float]:
    vals: Dict[str, float] = {}
    for i in inputs:
        try:
            vals[i.ticker] = getter(i)
        except Exception:
            vals[i.ticker] = float("nan")
    return vals


def _f(i: ScanInput, attr: str):
    f = i.fundamentals
    v = getattr(f, attr, None) if f else None
    return float(v) if v is not None and np.isfinite(float(v)) else float("nan")


def _t(i: ScanInput, key: str):
    t = i.technical or {}
    v = t.get(key)
    return float(v) if v is not None and np.isfinite(float(v)) else float("nan")


def _neutral(x: float) -> float:
    return 50.0 if not np.isfinite(x) else x


def _rank_metric(inputs, getter, higher_is_better, by_sector=False) -> Dict[str, float]:
    """Percentil de una métrica, global o dentro de cada sector (ranking comparable).

    En modo sectorial, cada instrumento se compara solo con pares de su sector; los
    que no tienen sector se agrupan aparte. Un grupo de tamaño 1 recibe 50 (neutral).
    """
    if not by_sector:
        return _percentile_rank(_collect(inputs, getter), higher_is_better)
    groups: Dict[str, List] = {}
    for i in inputs:
        groups.setdefault(i.sector or "__none__", []).append(i)
    out: Dict[str, float] = {}
    for members in groups.values():
        out.update(_percentile_rank(_collect(members, getter), higher_is_better))
    return out


def score_universe(
    inputs: List[ScanInput],
    weights: Optional[Mapping[str, float]] = None,
    usable_factors: Optional[List[str]] = None,
    sector_relative: bool = False,
) -> List[FactorScore]:
    """Puntúa cada instrumento por factor (percentil transversal) y compuesto.

    - usable_factors: si se pasa, los factores ausentes de la lista reciben peso 0 y
      el compuesto se reponderra sobre los restantes (evita puntuar con un factor sin
      cobertura suficiente).
    - sector_relative: value/quality/growth se rankean DENTRO del sector (comparables
      entre pares); momentum y low_risk siguen siendo relativos al mercado completo.
    """
    if not inputs:
        return []
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    if usable_factors is not None:
        for k in list(w):
            if k not in usable_factors:
                w[k] = 0.0
    wsum = sum(w.values()) or 1.0
    w = {k: v / wsum for k, v in w.items()}

    sv = sector_relative
    # VALUE: P/E forward bajo, EV/EBITDA bajo, FCF yield alto
    pe = _rank_metric(inputs, lambda i: _f(i, "pe_forward"), False, sv)
    ev = _rank_metric(inputs, lambda i: _f(i, "ev_ebitda"), False, sv)
    fcf = _rank_metric(inputs, lambda i: _f(i, "fcf_yield"), True, sv)
    # QUALITY: ROIC, ROE, margen neto altos; deuda/equity baja
    roic = _rank_metric(inputs, lambda i: _f(i, "roic"), True, sv)
    roe = _rank_metric(inputs, lambda i: _f(i, "roe"), True, sv)
    margin = _rank_metric(inputs, lambda i: _f(i, "net_margin"), True, sv)
    de = _rank_metric(inputs, lambda i: _f(i, "debt_to_equity"), False, sv)
    # GROWTH: crecimiento de ingresos y EPS
    rev = _rank_metric(inputs, lambda i: _f(i, "rev_growth_yoy"), True, sv)
    eps = _rank_metric(inputs, lambda i: _f(i, "eps_growth_yoy"), True, sv)
    # MOMENTUM y LOW_RISK: siempre relativos al mercado completo
    m6 = _percentile_rank(_collect(inputs, lambda i: _t(i, "mom_6m")), higher_is_better=True)
    m12 = _percentile_rank(_collect(inputs, lambda i: _t(i, "mom_12m")), higher_is_better=True)
    vol = _percentile_rank(_collect(inputs, lambda i: _t(i, "vol_1y")), higher_is_better=False)

    results: List[FactorScore] = []
    for i in inputs:
        t = i.ticker
        value = _safe_mean([pe[t], ev[t], fcf[t]])
        quality = _safe_mean([roic[t], roe[t], margin[t], de[t]])
        growth = _safe_mean([rev[t], eps[t]])
        mom = _safe_mean([m6[t], m12[t]])
        low_risk = vol[t]
        value, quality, growth, mom, low_risk = (
            _neutral(value), _neutral(quality), _neutral(growth),
            _neutral(mom), _neutral(low_risk),
        )
        composite = (
            w["value"] * value + w["quality"] * quality + w["growth"] * growth
            + w["momentum"] * mom + w["low_risk"] * low_risk
        )
        results.append(FactorScore(
            ticker=t, value=round(value, 1), quality=round(quality, 1),
            growth=round(growth, 1), momentum=round(mom, 1), low_risk=round(low_risk, 1),
            composite=round(composite, 1), is_sample=i.is_sample,
            detail={"drawdown": _t(i, "drawdown"), "rsi_14": _t(i, "rsi_14")},
        ))
    return results


def _nan(x: float) -> float:
    return x if (x is not None and np.isfinite(x)) else float("nan")


def classify_opportunity(fs: FactorScore) -> List[str]:
    """Etiqueta tipos de oportunidad según qué factores dominan. Varias etiquetas posibles."""
    tags = []
    if fs.value >= 70:
        tags.append("value")
    if fs.growth >= 70:
        tags.append("growth")
    if fs.quality >= 70:
        tags.append("quality")
    if fs.momentum >= 70:
        tags.append("momentum")
    # oversold: RSI bajo y en drawdown, pero calidad decente (no una trampa de valor)
    rsi = fs.detail.get("rsi_14")
    dd = fs.detail.get("drawdown")
    if rsi is not None and np.isfinite(rsi) and rsi < 35 and fs.quality >= 50:
        tags.append("oversold")
    if dd is not None and np.isfinite(dd) and dd < -0.2 and fs.quality >= 60 and fs.growth >= 50:
        tags.append("turnaround")
    return tags or ["neutral"]


def rank(
    inputs: List[ScanInput],
    weights: Optional[Mapping[str, float]] = None,
    top: Optional[int] = None,
    usable_factors: Optional[List[str]] = None,
    sector_relative: bool = False,
) -> List[dict]:
    """Rankea el universo por compuesto descendente y adjunta etiquetas de oportunidad."""
    scores = score_universe(inputs, weights, usable_factors, sector_relative)
    scores.sort(key=lambda s: s.composite, reverse=True)
    rows = []
    for idx, fs in enumerate(scores, 1):
        rows.append({
            "rank": idx,
            "ticker": fs.ticker,
            "composite": fs.composite,
            "factors": {
                "value": fs.value, "quality": fs.quality, "growth": fs.growth,
                "momentum": fs.momentum, "low_risk": fs.low_risk,
            },
            "tags": classify_opportunity(fs),
            "is_sample": fs.is_sample,
        })
    return rows[:top] if top else rows
