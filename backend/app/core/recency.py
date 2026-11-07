"""Capa de ACTUALIDAD (vigencia) del Financial Data Engine — pura, sin red ni pandas.

Cobertura, exactitud y actualidad son dimensiones DISTINTAS de la calidad. Un dato anual puede ser
contablemente correcto como "últimos doce meses" y, a la vez, NO estar vigente a la fecha de
consulta si el emisor ya publicó resultados posteriores. Este módulo evalúa la vigencia SIN umbrales
universales arbitrarios: usa la CADENCIA de reporte del propio emisor y la existencia de REPORTES
POSTERIORES.

No convierte un anual viejo en TTM vigente: conserva valor/procedencia/ventana y sólo etiqueta la
antigüedad (vigente | desactualizado | desconocida).
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional


def reporting_cadence_days(period_ends: List[date]) -> Optional[int]:
    """Cadencia de reporte del emisor = mediana de la diferencia entre cierres de período DISTINTOS
    consecutivos (p. ej. ~91 trimestral, ~182 semestral, ~365 anual). None si hay <2 cierres."""
    uniq = sorted(set(d for d in period_ends if d))
    if len(uniq) < 2:
        return None
    gaps = sorted((uniq[i] - uniq[i - 1]).days for i in range(1, len(uniq)))
    n = len(gaps)
    return gaps[n // 2] if n % 2 else (gaps[n // 2 - 1] + gaps[n // 2]) // 2


def typical_filing_lag_days(pairs: List[tuple]) -> Optional[int]:
    """Retardo típico de publicación del emisor = mediana de (fecha de presentación − cierre de
    período). pairs = [(period_end, filed), ...]. Derivado del propio emisor, no universal."""
    lags = sorted((f - e).days for e, f in pairs if e and f and f >= e)
    if not lags:
        return None
    n = len(lags)
    return lags[n // 2] if n % 2 else (lags[n // 2 - 1] + lags[n // 2]) // 2


def assess_recency(period_end: Optional[date], eval_date: date, *,
                   cadence_days: Optional[int] = None, lag_days: Optional[int] = None,
                   later_report_exists: bool = False, window: Optional[str] = None) -> dict:
    """Evalúa la vigencia de un dato a la fecha de evaluación.

    Reglas (sin umbral universal; todo derivado del emisor):
      - Si YA EXISTE un reporte periódico POSTERIOR (reportDate > period_end) que este dato no
        refleja → `desactualizado` (hay información más reciente publicada).
      - Si la antigüedad del cierre ≤ cadencia + retardo del emisor → `vigente` (todavía no debería
        existir un período más nuevo).
      - Si la antigüedad excede ese presupuesto → `desactualizado` (período más nuevo vencido).
      - Sin cierre o sin cadencia conocida → `desconocida`.

    Devuelve dict con estado, antigüedad, presupuesto de frescura y la razón, para trazabilidad.
    """
    if period_end is None:
        return {"estado": "desconocida", "edad_dias": None, "razon": "sin fecha de cierre"}
    age = (eval_date - period_end).days
    if later_report_exists:
        return {"estado": "desactualizado", "edad_dias": age, "ventana": window,
                "razon": "existe un reporte periódico posterior no incorporado"}
    if cadence_days is None:
        return {"estado": "desconocida", "edad_dias": age, "ventana": window,
                "razon": "cadencia de reporte del emisor no determinable"}
    budget = cadence_days + (lag_days or 0)
    if age <= budget:
        return {"estado": "vigente", "edad_dias": age, "ventana": window,
                "presupuesto_dias": budget,
                "razon": f"cierre a {age}d ≤ cadencia+retardo {budget}d; aún no vence un período más nuevo"}
    return {"estado": "desactualizado", "edad_dias": age, "ventana": window,
            "presupuesto_dias": budget,
            "razon": f"cierre a {age}d > cadencia+retardo {budget}d; un período más nuevo está vencido"}
