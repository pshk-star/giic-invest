"""Pruebas de los parsers de las fuentes GRATUITAS (Stooq, EDGAR, Frankfurter).

Se prueba la LÓGICA DE PARSEO con fixtures embebidos (no hay red en este entorno;
la descarga real ocurre en GitHub Actions). Valida formas, cálculos derivados y el
tratamiento honesto de datos ausentes (None, nunca inventado).
"""
import pandas as pd

from app.providers.stooq import parse_stooq_csv, parse_stooq_volume, to_stooq_symbol
from app.providers.frankfurter import parse_frankfurter
from app.providers.edgar import parse_companyfacts


# ---------------- Stooq ----------------
STOOQ_CSV = """Date,Open,High,Low,Close,Volume
2026-11-01,180.0,185.0,179.0,183.0,1000000
2026-11-02,183.0,188.0,182.0,186.5,1200000
2026-11-03,186.5,190.0,185.0,189.0,900000
"""


def test_stooq_symbol_mapping():
    assert to_stooq_symbol("NVDA") == "nvda.us"
    assert to_stooq_symbol("^spx") == "^spx"


def test_parse_stooq_csv_series():
    s = parse_stooq_csv(STOOQ_CSV, "NVDA")
    assert len(s) == 3
    assert s.iloc[-1] == 189.0
    assert list(s.index) == sorted(s.index)


def test_parse_stooq_empty_and_nodata():
    assert len(parse_stooq_csv("", "X")) == 0
    assert len(parse_stooq_csv("No data", "X")) == 0


def test_parse_stooq_volume_last():
    assert parse_stooq_volume(STOOQ_CSV) == 900000.0


# ---------------- Frankfurter ----------------
def test_parse_frankfurter_inverts_to_base_per_cur():
    payload = {"base": "USD", "date": "2026-11-05", "rates": {"MXN": 18.5, "EUR": 0.92}}
    rates = parse_frankfurter(payload, "USD")
    assert rates["USD"] == 1.0
    assert abs(rates["MXN"] - 1 / 18.5) < 1e-9     # USD por 1 MXN
    assert abs(rates["EUR"] - 1 / 0.92) < 1e-9


def test_parse_frankfurter_empty():
    assert parse_frankfurter({}, "USD") == {"USD": 1.0}


# ---------------- EDGAR company facts ----------------
def _facts_fixture():
    """companyfacts mínimo con dos años fiscales para probar YoY y derivados."""
    def dur(start, end, val, form="10-K"):
        return {"start": start, "end": end, "val": val, "form": form, "fy": 2025, "fp": "FY"}

    def inst(end, val, form="10-K"):
        return {"end": end, "val": val, "form": form, "fy": 2025, "fp": "FY"}

    return {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": [
                    dur("2024-01-01", "2024-12-31", 1000.0),
                    dur("2025-01-01", "2025-12-31", 1200.0),
                ]}},
                "NetIncomeLoss": {"units": {"USD": [
                    dur("2024-01-01", "2024-12-31", 200.0),
                    dur("2025-01-01", "2025-12-31", 300.0),
                ]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [
                    dur("2024-01-01", "2024-12-31", 2.0),
                    dur("2025-01-01", "2025-12-31", 3.0),
                ]}},
                "StockholdersEquity": {"units": {"USD": [
                    inst("2024-12-31", 1500.0), inst("2025-12-31", 2000.0)]}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [
                    dur("2025-01-01", "2025-12-31", 350.0)]}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                    dur("2025-01-01", "2025-12-31", 50.0)]}},
            },
            "dei": {
                "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                    inst("2025-12-31", 100.0)]}},
            },
        }
    }


def test_edgar_derived_fundamentals():
    f = parse_companyfacts(_facts_fixture(), "ACME", price=60.0)
    # net margin = 300/1200 = 0.25 ; roe = 300/2000 = 0.15
    assert abs(f.net_margin - 0.25) < 1e-9
    assert abs(f.roe - 0.15) < 1e-9
    # crecimiento: ingresos 1200/1000-1=0.2 ; eps 3/2-1=0.5
    assert abs(f.rev_growth_yoy - 0.2) < 1e-9
    assert abs(f.eps_growth_yoy - 0.5) < 1e-9
    # market cap = 60 * 100 = 6000 ; fcf = 350-50=300 ; fcf_yield = 300/6000 = 0.05
    assert abs(f.market_cap - 6000.0) < 1e-6
    assert abs(f.fcf_yield - 0.05) < 1e-9
    # pe_ttm = 60 / 3 = 20
    assert abs(f.pe_ttm - 20.0) < 1e-9


def test_edgar_missing_fields_are_none_not_invented():
    f = parse_companyfacts(_facts_fixture(), "ACME", price=60.0)
    assert f.pe_forward is None       # EDGAR no lo da
    assert f.ev_ebitda is None
    assert f.roic is None
    assert f.debt_to_equity is None


def test_edgar_no_price_no_marketcap():
    f = parse_companyfacts(_facts_fixture(), "ACME", price=None)
    assert f.market_cap is None and f.pe_ttm is None and f.fcf_yield is None
    # pero los ratios que no dependen de precio sí están
    assert f.net_margin is not None and f.rev_growth_yoy is not None
