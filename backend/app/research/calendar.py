"""Calendario bursátil app-side: evaluate_on se calcula avanzando sobre SESIONES reales
(las fechas efectivamente presentes en price_history), que ya excluyen fines de semana y
feriados. La BD solo garantiza evaluate_on > as_of; la correspondencia exacta vive aquí.
"""
from __future__ import annotations

from bisect import bisect_left
from typing import List, Optional, Sequence


def session_index_on_or_after(sessions: Sequence[str], date_str: str) -> Optional[int]:
    """Índice de la primera sesión >= date_str (sessions ascendente, 'YYYY-MM-DD')."""
    i = bisect_left(sessions, date_str)
    return i if i < len(sessions) else None


def evaluate_on(sessions: Sequence[str], as_of: str, horizon_sessions: int) -> Optional[str]:
    """Fecha de evaluación = `horizon_sessions` sesiones después de la sesión de decisión.
    Devuelve None si no hay suficientes sesiones futuras (no inventa fechas)."""
    if horizon_sessions <= 0:
        return None
    start = session_index_on_or_after(sessions, as_of)
    if start is None:
        return None
    target = start + horizon_sessions
    return sessions[target] if target < len(sessions) else None


def sessions_between(sessions: Sequence[str], a: str, b: str) -> List[str]:
    lo = bisect_left(sessions, a)
    hi = bisect_left(sessions, b)
    return list(sessions[lo:hi + 1]) if hi < len(sessions) else list(sessions[lo:])
