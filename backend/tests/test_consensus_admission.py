"""P1.7.3 — pruebas del gate de admisión de consenso (selección por fecha + controles)."""
from __future__ import annotations

from datetime import date

from app.research.consensus_admission import admit_consensus, select_fiscal_records, Reported

TODAY = date(2026, 11, 10)


def _rep():
    # reportado tipo NVDA FY2026 (enero): rev 216e9, m0 60%, 24.5e9 acciones
    return Reported(ccy="USD", revenue=216e9, shares=24.5e9, ni=120e9, ebit_margin0=0.60,
                    interest=0.0, tax_rate=0.15, fiscal_year_end="2026-01-31")


def _trend_good():
    # histórico con etiquetas 'period' repetidas + año fiscal vigente correcto (2027-01-31)
    return [
        {"date": "2018-01-31", "period": "0y", "revEstAvg": 9.5e9, "revGrowth": 0.37, "revAnalysts": 28, "epsEstAvg": 4.2, "epsAnalysts": 21},
        {"date": "2026-01-31", "period": "0y", "revEstAvg": 214e9, "revGrowth": 1.12, "revAnalysts": 55, "epsEstAvg": 2.95, "epsAnalysts": 48},
        {"date": "2027-01-31", "period": "0y", "revEstAvg": 412e9, "revGrowth": 0.907, "revAnalysts": 54, "epsEstAvg": 9.3, "epsAnalysts": 51},
        {"date": "2028-01-31", "period": "+1y", "revEstAvg": 692e9, "revGrowth": 0.68, "revAnalysts": 57, "epsEstAvg": 15.9, "epsAnalysts": 52},
    ]


def test_select_by_date_not_by_label():
    cy, prev, ny = select_fiscal_records(_trend_good(), TODAY)
    assert cy["date"] == "2027-01-31"   # vigente (≥ hoy), NO el 2018 pese a misma etiqueta '0y'
    assert prev["date"] == "2026-01-31" and ny["date"] == "2028-01-31"


def test_admits_good_consensus_flags_extreme():
    g = admit_consensus("NVDA", _trend_good(), _rep(), TODAY, "2026-11-10")
    assert g["admitted"] is True
    assert g["extreme"] is True and g["confidence"] == "baja"   # 91% crecimiento: admitido pero extremo
    assert g["cy"]["fiscal_end"] == "2027-01-31"
    assert all(g["checks"][k]["ok"] for k in ("scale_anchor", "scale_cy", "level_growth", "eps_margin", "coverage", "freshness"))


def test_old_record_only_is_rejected():
    # solo el registro viejo 2018 (el bug de P1.7.2): sin año vigente => no admitido
    old = [{"date": "2018-01-31", "period": "0y", "revEstAvg": 9.5e9, "revGrowth": 0.37,
            "revAnalysts": 28, "epsEstAvg": 4.2, "epsAnalysts": 21}]
    g = admit_consensus("NVDA", old, _rep(), TODAY, "2026-11-10")
    assert g["admitted"] is False and g["confidence"] == "na"


def test_scale_anchor_catches_misaligned_reported_year():
    tl = _trend_good()
    tl[1]["revEstAvg"] = 20e9   # el registro del año reportado desalineado (debería ≈216e9)
    g = admit_consensus("NVDA", tl, _rep(), TODAY, "2026-11-10")
    assert g["checks"]["scale_anchor"]["ok"] is False and g["admitted"] is False


def test_level_growth_inconsistency_rejected():
    tl = _trend_good()
    tl[2]["revGrowth"] = 0.10   # nivel implica ~92% pero declara 10% => inconsistente
    g = admit_consensus("NVDA", tl, _rep(), TODAY, "2026-11-10")
    assert g["checks"]["level_growth"]["ok"] is False and g["admitted"] is False


def test_low_coverage_rejected():
    tl = _trend_good()
    tl[2]["revAnalysts"] = 3
    g = admit_consensus("NVDA", tl, _rep(), TODAY, "2026-11-10")
    assert g["checks"]["coverage"]["ok"] is False and g["admitted"] is False


def test_stale_rejected():
    g = admit_consensus("NVDA", _trend_good(), _rep(), TODAY, "2025-01-01")  # >120 días
    assert g["checks"]["freshness"]["ok"] is False and g["admitted"] is False


def test_zero_eps_rejected():
    tl = _trend_good()
    tl[2]["epsEstAvg"] = 0.0
    g = admit_consensus("NVDA", tl, _rep(), TODAY, "2026-11-10")
    assert g["admitted"] is False   # EPS 0 => eps_margin falla y valor cero marcado
