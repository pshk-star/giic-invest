"""Pruebas de la capa de actualidad (vigencia por cadencia + reportes posteriores)."""
from datetime import date

from app.core.recency import reporting_cadence_days, typical_filing_lag_days, assess_recency


def test_cadencia_trimestral_y_anual():
    q = [date(2025, 3, 31), date(2025, 6, 30), date(2025, 9, 30), date(2025, 12, 31)]
    assert 89 <= reporting_cadence_days(q) <= 92
    a = [date(2023, 12, 31), date(2024, 12, 31), date(2025, 12, 31)]
    assert 364 <= reporting_cadence_days(a) <= 366
    assert reporting_cadence_days([date(2025, 1, 1)]) is None


def test_retardo_de_publicacion():
    pairs = [(date(2024, 12, 31), date(2025, 2, 10)), (date(2025, 12, 31), date(2026, 2, 12))]
    lag = typical_filing_lag_days(pairs)
    assert 40 <= lag <= 44


def test_anual_recien_cerrado_es_vigente():
    # AAPL: FY cerró hace ~42 días; cadencia trimestral → vigente (aún sin 10-Q posterior).
    r = assess_recency(date(2026, 9, 26), date(2026, 11, 7), cadence_days=91, lag_days=30,
                       later_report_exists=False, window="anual")
    assert r["estado"] == "vigente"


def test_anual_con_reporte_posterior_es_desactualizado():
    # ASML/TSM: EDGAR sólo tiene FY2025 pero ya hay un 6-K con período 2026 → desactualizado.
    r = assess_recency(date(2025, 12, 31), date(2026, 11, 7), cadence_days=365, lag_days=60,
                       later_report_exists=True, window="anual")
    assert r["estado"] == "desactualizado" and "posterior" in r["razon"]


def test_anual_vencido_por_cadencia_es_desactualizado():
    # Sin reporte posterior detectado, pero la antigüedad supera cadencia+retardo → desactualizado.
    r = assess_recency(date(2024, 12, 31), date(2026, 11, 7), cadence_days=365, lag_days=60,
                       later_report_exists=False, window="anual")
    assert r["estado"] == "desactualizado"


def test_sin_cadencia_es_desconocida():
    r = assess_recency(date(2025, 12, 31), date(2026, 11, 7), cadence_days=None)
    assert r["estado"] == "desconocida"


def test_sin_cierre_es_desconocida():
    assert assess_recency(None, date(2026, 11, 7))["estado"] == "desconocida"
