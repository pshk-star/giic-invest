"""Pruebas de de-acumulación YTD -> trimestral y disponibilidad (filing_date)."""
from app.research.fundamentals import growth_yoy, is_quarterly, is_ytd, quarterly_values


def test_span_classification():
    assert is_quarterly("2025-03-01", "2025-05-31")          # ~3m
    assert is_ytd("2025-01-01", "2025-09-30")                # ~9m
    assert not is_quarterly("2025-01-01", "2025-09-30")


def test_native_quarterly_preferred():
    facts = [
        {"period_start": "2025-01-01", "period_end": "2025-03-31", "value": 100, "filing_date": "2025-04-20"},
        {"period_start": "2025-04-01", "period_end": "2025-06-30", "value": 110, "filing_date": "2025-07-20"},
    ]
    q = quarterly_values(facts)
    assert [r["value"] for r in q] == [100.0, 110.0]
    assert all(r["source"] == "native_q" for r in q)


def test_ytd_de_accumulation():
    # Solo hay YTD: Q1=100, H1(YTD)=250, 9M(YTD)=400 -> trimestres 100,150,150
    facts = [
        {"period_start": "2025-01-01", "period_end": "2025-03-31", "value": 100, "filing_date": "2025-04-20"},
        {"period_start": "2025-01-01", "period_end": "2025-06-30", "value": 250, "filing_date": "2025-07-20"},
        {"period_start": "2025-01-01", "period_end": "2025-09-30", "value": 400, "filing_date": "2025-10-20"},
    ]
    # el primero (3m) es nativo; los otros son YTD -> de-acumular
    q = {r["period_end"]: r["value"] for r in quarterly_values(facts)}
    assert q["2025-03-31"] == 100.0
    assert q["2025-06-30"] == 150.0     # 250-100
    assert q["2025-09-30"] == 150.0     # 400-250


def test_de_accumulation_availability_date():
    facts = [
        {"period_start": "2025-01-01", "period_end": "2025-06-30", "value": 250, "filing_date": "2025-07-20"},
        {"period_start": "2025-01-01", "period_end": "2025-09-30", "value": 400, "filing_date": "2025-10-20"},
    ]
    byd = {r["period_end"]: r for r in quarterly_values(facts)}
    # el Q3 de-acumulado usa el YTD-9m y el YTD-6m -> disponibilidad = la más tardía
    assert byd["2025-09-30"]["filing_date"] == "2025-10-20"


def test_growth_yoy():
    q = [{"period_end": f"202{y}-12-31", "value": v, "filing_date": "x"}
         for y, v in [(0, 100), (1, 110), (2, 121), (3, 133), (4, 146)]]
    g = growth_yoy(q)
    assert abs(g[0]["value"] - 0.46) < 0.001   # 146 vs 100
