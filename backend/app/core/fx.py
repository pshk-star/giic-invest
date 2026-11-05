"""Conversión de divisas a moneda base y detección de datos obsoletos (stale).

Las tasas FX las provee la capa de datos (p.ej. EODHD forex) y se pasan aquí como
un mapa simple. Nada se convierte con una tasa inventada: si falta la tasa para una
moneda, la conversión se reporta como None y el instrumento se marca, nunca se
asume 1:1 salvo que la moneda ya sea la base.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Mapping, Optional


@dataclass
class FXResult:
    amount_base: Optional[float]
    rate: Optional[float]
    ok: bool
    reason: Optional[str] = None


def convert(amount: float, currency: str, base: str, rates: Mapping[str, float]) -> FXResult:
    """Convierte `amount` de `currency` a `base`.

    `rates`: moneda -> unidades de BASE por 1 unidad de esa moneda
    (p.ej. {'MXN': 0.054} significa 1 MXN = 0.054 USD si base=USD).
    """
    cur = (currency or "").upper()
    base = (base or "").upper()
    if not cur:
        return FXResult(None, None, False, "moneda del instrumento desconocida")
    if cur == base:
        return FXResult(amount, 1.0, True)
    rate = rates.get(cur)
    if rate is None or rate <= 0:
        return FXResult(None, None, False, f"sin tasa FX {cur}->{base}")
    return FXResult(amount * rate, rate, True)


def build_rate_map(base: str, pairs: Mapping[str, float]) -> Dict[str, float]:
    """Normaliza un mapa de tasas asegurando que la base valga 1.0."""
    out = {k.upper(): float(v) for k, v in pairs.items() if v and v > 0}
    out[base.upper()] = 1.0
    return out


def is_stale(as_of: Optional[date], today: date, max_business_days: int = 4) -> bool:
    """True si la cotización es demasiado vieja (posible dato desactualizado).

    Cuenta días hábiles aproximados (excluye sábados y domingos) entre `as_of` y
    `today`. Útil para detectar un ticker que dejó de actualizarse o un feriado
    prolongado de una bolsa internacional.
    """
    if as_of is None:
        return True
    if as_of > today:
        return False
    days = 0
    d = as_of
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:  # 0-4 = lunes a viernes
            days += 1
    return days > max_business_days


def business_days_old(as_of: Optional[date], today: date) -> Optional[int]:
    if as_of is None or as_of > today:
        return None
    days, d = 0, as_of
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days
