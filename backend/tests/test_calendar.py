"""evaluate_on debe contar SESIONES bursátiles, saltando fines de semana y feriados."""
from app.research.calendar import evaluate_on, session_index_on_or_after

# Sesiones reales Nov–Dic 2025: SIN 11-27 (Thanksgiving) ni fines de semana (29,30).
SESSIONS = ["2025-11-24", "2025-11-25", "2025-11-26", "2025-11-28", "2025-12-01", "2025-12-02"]


def test_skips_holiday_and_weekend():
    # +3 sesiones desde el 24: 25, 26, 28 (salta Thanksgiving 27 y el fin de semana).
    assert evaluate_on(SESSIONS, "2025-11-24", 3) == "2025-11-28"
    # +1 sesión desde el 26 es el 28 (NO el 27, feriado) -> prueba de salto de feriado.
    assert evaluate_on(SESSIONS, "2025-11-26", 1) == "2025-11-28"
    # +2 desde el 28 salta fin de semana: 12-01, 12-02.
    assert evaluate_on(SESSIONS, "2025-11-28", 2) == "2025-12-02"


def test_as_of_not_a_session_uses_next_session():
    # 2025-11-27 (feriado, no es sesión) -> arranca en 11-28.
    assert evaluate_on(SESSIONS, "2025-11-27", 1) == "2025-12-01"


def test_no_future_sessions_returns_none():
    assert evaluate_on(SESSIONS, "2025-12-02", 5) is None   # no inventa fechas
    assert evaluate_on(SESSIONS, "2025-11-24", 0) is None   # horizonte inválido


def test_index_lookup():
    assert session_index_on_or_after(SESSIONS, "2025-11-26") == 2
    assert session_index_on_or_after(SESSIONS, "2025-11-27") == 3   # siguiente sesión
