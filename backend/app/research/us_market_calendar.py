"""Calendario OFICIAL de sesiones NYSE/Nasdaq (no depende de price_history).

Genera los feriados del mercado por reglas (incluida la regla de observancia en fin de
semana) y produce la lista de SESIONES entre dos fechas. Los medios días (cierre
temprano) SIGUEN siendo sesiones. Permite cierres ad-hoc (suspensiones). La disponibilidad
de PRECIO en una sesión es un asunto aparte (missing_price_sessions): un hueco de datos NO
elimina la sesión del calendario.

Sin dependencias externas; determinístico y testeable.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Sequence, Set

# Cierres ad-hoc conocidos (suspensiones no recurrentes): fecha -> motivo.
AD_HOC_CLOSURES: Dict[date, str] = {
    date(2025, 1, 9): "Duelo nacional (J. Carter)",
    # (2026 no tiene cierres ad-hoc conocidos al momento del diseño.)
}


def _easter(year: int) -> date:
    # Algoritmo de Gauss/Anónimo Gregoriano.
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year, month, 31)
    while d.month != month:
        d -= timedelta(days=1)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d


def _observed(d: date) -> date:
    """Regla NYSE: feriado en sábado -> viernes previo; en domingo -> lunes siguiente."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def market_holidays(year: int) -> Set[date]:
    MON, THU = 0, 3
    hols = {
        _observed(date(year, 1, 1)),                 # Año Nuevo
        _nth_weekday(year, 1, MON, 3),               # MLK (3er lunes ene)
        _nth_weekday(year, 2, MON, 3),               # Washington (3er lunes feb)
        _easter(year) - timedelta(days=2),           # Viernes Santo
        _last_weekday(year, 5, MON),                 # Memorial (último lunes may)
        _observed(date(year, 6, 19)),                # Juneteenth
        _observed(date(year, 7, 4)),                 # Independencia
        _nth_weekday(year, 9, MON, 1),               # Labor (1er lunes sep)
        _nth_weekday(year, 11, THU, 4),              # Thanksgiving (4º jueves nov)
        _observed(date(year, 12, 25)),               # Navidad
    }
    for d in AD_HOC_CLOSURES:
        if d.year == year:
            hols.add(d)
    return hols


def sessions(start: date, end: date) -> List[str]:
    """Sesiones (ISO 'YYYY-MM-DD') entre start y end inclusive: días hábiles menos feriados."""
    hols: Set[date] = set()
    for y in range(start.year, end.year + 1):
        hols |= market_holidays(y)
    out: List[str] = []
    d = start
    while d <= end:
        if d.weekday() < 5 and d not in hols:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def missing_price_sessions(session_list: Sequence[str], price_dates: Sequence[str]) -> List[str]:
    """Sesiones oficiales SIN precio disponible (hueco de datos). No altera el calendario."""
    have = set(price_dates)
    return [s for s in session_list if s not in have]
