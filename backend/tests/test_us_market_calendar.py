"""Calendario oficial NYSE/Nasdaq: feriados reales 2026, fines de semana y datos faltantes."""
from datetime import date
from app.research.us_market_calendar import market_holidays, missing_price_sessions, sessions


def test_real_2026_holidays_excluded():
    h = market_holidays(2026)
    expected = {
        date(2026, 1, 1),    # Año Nuevo (jueves)
        date(2026, 1, 19),   # MLK
        date(2026, 2, 16),   # Washington
        date(2026, 4, 3),    # Viernes Santo (Pascua 2026 = 5 abr)
        date(2026, 5, 25),   # Memorial
        date(2026, 6, 19),   # Juneteenth (viernes)
        date(2026, 7, 3),    # Independencia observada (4 jul = sábado)
        date(2026, 9, 7),    # Labor
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Navidad (viernes)
    }
    assert expected.issubset(h)


def test_sessions_exclude_holidays_and_weekends():
    s = set(sessions(date(2026, 1, 1), date(2026, 12, 31)))
    # feriados fuera
    for d in ["2026-01-01", "2026-01-19", "2026-04-03", "2026-07-03", "2026-11-26", "2026-12-25"]:
        assert d not in s
    # 4 de julio (sábado) no es sesión; su observado (jul 3) tampoco
    assert "2026-07-04" not in s and "2026-07-03" not in s
    # fines de semana fuera (4 y 5 de julio 2026 = sáb/dom)
    assert "2026-07-05" not in s
    # un día hábil normal SÍ es sesión
    assert "2026-03-10" in s   # martes normal


def test_independence_day_observed_friday():
    s = set(sessions(date(2026, 7, 1), date(2026, 7, 10)))
    assert "2026-07-02" in s          # jueves, sesión
    assert "2026-07-03" not in s      # feriado observado
    assert "2026-07-06" in s          # lunes siguiente, sesión


def test_missing_price_does_not_remove_session():
    s = sessions(date(2026, 3, 9), date(2026, 3, 13))   # lun-vie, todas sesiones
    price_dates = [d for d in s if d != "2026-03-11"]   # falta el precio del miércoles
    missing = missing_price_sessions(s, price_dates)
    assert missing == ["2026-03-11"]                     # se marca como hueco…
    assert "2026-03-11" in s                             # …pero sigue siendo sesión
