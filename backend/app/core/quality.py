"""Calidad de datos: validación de múltiplos, cobertura por factor y suficiencia.

Objetivo: que el ranking no se contamine con cifras imposibles (como un P/E forward
de 4x por una anualización mal hecha, o un crecimiento de EPS de +900% por un dato
basura). Los valores implausibles se ANULAN con un motivo explícito; nunca se
corrigen inventando otro número.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Mapping, Optional, Tuple

import numpy as np

from .types import Fundamentals

# Rangos plausibles por métrica (fuera de rango => se anula con motivo).
BOUNDS: Dict[str, Tuple[float, float]] = {
    "pe_ttm": (0.0, 1000.0),          # P/E negativo no es "barato": se anula (ver abajo)
    "pe_forward": (0.0, 1000.0),
    "ev_ebitda": (0.0, 500.0),
    "fcf_yield": (-1.0, 1.0),         # -100%..100%
    "roic": (-5.0, 5.0),              # -500%..500%
    "roe": (-5.0, 5.0),
    "rev_growth_yoy": (-1.0, 10.0),   # -100%..+1000%
    "eps_growth_yoy": (-1.0, 10.0),
    "net_margin": (-10.0, 1.0),       # margen > 100% es imposible
    "debt_to_equity": (-50.0, 100.0),
    "market_cap": (0.0, 1e14),
}

# Factores del scanner y las métricas que los alimentan (para medir cobertura).
FACTOR_METRICS: Dict[str, List[str]] = {
    "value": ["pe_forward", "ev_ebitda", "fcf_yield"],
    "quality": ["roic", "roe", "net_margin", "debt_to_equity"],
    "growth": ["rev_growth_yoy", "eps_growth_yoy"],
}


def validate_fundamentals(f: Optional[Fundamentals]) -> Tuple[Optional[Fundamentals], List[dict]]:
    """Devuelve (fundamentales saneados, lista de incidencias).

    Cada incidencia: {field, value, reason}. El campo problemático queda en None.
    """
    if f is None:
        return None, []
    issues: List[dict] = []
    updates: Dict[str, Optional[float]] = {}
    for field, (lo, hi) in BOUNDS.items():
        v = getattr(f, field, None)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            updates[field] = None
            issues.append({"field": field, "value": v, "reason": "no numérico"})
            continue
        if not np.isfinite(x):
            updates[field] = None
            issues.append({"field": field, "value": v, "reason": "no finito"})
        elif x < lo or x > hi:
            updates[field] = None
            issues.append({"field": field, "value": x,
                           "reason": f"fuera de rango plausible [{lo}, {hi}]"})
    if updates:
        f = replace(f, **updates)
    return f, issues


def coverage_report(fundamentals_by_ticker: Mapping[str, Optional[Fundamentals]]) -> Dict[str, float]:
    """Fracción del universo con AL MENOS una métrica presente por factor (0-1)."""
    n = len(fundamentals_by_ticker) or 1
    out: Dict[str, float] = {}
    for factor, metrics in FACTOR_METRICS.items():
        present = 0
        for f in fundamentals_by_ticker.values():
            if f is None:
                continue
            if any(getattr(f, m, None) is not None for m in metrics):
                present += 1
        out[factor] = present / n
    return out


def usable_factors(coverage: Mapping[str, float], min_coverage: float) -> List[str]:
    """Factores cuya cobertura alcanza el mínimo; el resto se excluye del compuesto."""
    return [f for f, c in coverage.items() if c >= min_coverage]


def count_present_metrics(f: Optional[Fundamentals]) -> int:
    if f is None:
        return 0
    allm = [m for ms in FACTOR_METRICS.values() for m in ms]
    return sum(1 for m in allm if getattr(f, m, None) is not None)


def is_sufficient(f: Optional[Fundamentals], min_metrics: int = 3) -> bool:
    """¿Hay datos fundamentales suficientes para rankear con confianza?"""
    return count_present_metrics(f) >= min_metrics
