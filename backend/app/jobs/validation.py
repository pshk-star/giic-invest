"""Validación de calidad previa a publicar un scan. PURA y probada.

Un scan solo se publica si es: (a) de datos REALES (no de ejemplo), (b) no vacío,
(c) con cobertura fundamental mínima (no solo técnicos), y (d) con precios FRESCOS
(no obsoletos). Si algo falla, el job NO escribe en Supabase: así no se sobrescriben
datos válidos anteriores con una corrida incompleta por fallo de las fuentes gratuitas.
"""
from __future__ import annotations

from datetime import date
from typing import List, Tuple

from ..core.fx import business_days_old

FUNDAMENTAL_FACTORS = {"value", "quality", "growth"}


def newest_price_asof(market_prices: dict) -> str | None:
    """Fecha de cotización más reciente (ISO) entre los precios obtenidos; None si no hay."""
    dates = [m.get("as_of") for m in market_prices.values() if m and m.get("as_of")]
    return max(dates) if dates else None


def validate_scan_result(
    result: dict,
    today: date,
    min_evaluated: int = 10,
    max_stale_business_days: int = 5,
    min_fresh_fraction: float = 0.7,
    allow_sample: bool = False,
) -> Tuple[bool, List[str]]:
    reasons: List[str] = []

    if result.get("using_sample_data") and not allow_sample:
        reasons.append("datos de EJEMPLO: no se publican en producción")

    ranking = result.get("ranking") or []
    if len(ranking) == 0:
        reasons.append("ranking vacío")

    evaluated = result.get("evaluated", 0)
    if evaluated < min_evaluated:
        reasons.append(f"instrumentos evaluados insuficientes ({evaluated} < {min_evaluated})")

    usable = set(result.get("usable_factors") or [])
    if not (usable & FUNDAMENTAL_FACTORS):
        reasons.append("sin factores fundamentales con cobertura mínima (ranking incompleto)")

    # Frescura por PROPORCIÓN: no basta la cotización más reciente; una parte
    # suficiente del universo con precio debe estar actualizada.
    priced = result.get("priced_count", 0)
    fresh_fraction = result.get("fresh_fraction")
    if priced == 0:
        reasons.append("sin precios con fecha")
    elif fresh_fraction is not None and fresh_fraction < min_fresh_fraction:
        reasons.append(
            f"frescura insuficiente: solo {fresh_fraction:.0%} del universo con precio "
            f"está actualizado (mínimo {min_fresh_fraction:.0%})")

    # Piso adicional: la cotización más reciente no debe ser muy vieja.
    newest = newest_price_asof(result.get("market_prices") or {})
    if newest is not None:
        d = _parse(newest)
        age = business_days_old(d, today) if d else None
        if age is None:
            reasons.append(f"fecha de precio inválida: {newest}")
        elif age > max_stale_business_days:
            reasons.append(f"precios obsoletos (última fecha {newest}, {age} días hábiles)")

    return (len(reasons) == 0, reasons)


def _parse(s: str):
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d)
    except (ValueError, TypeError, AttributeError):
        return None
