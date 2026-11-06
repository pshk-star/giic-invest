"""Pruebas del resolver de identidad global (Fase 2)."""
from app.services.identity import resolve_identity


def ymeta(asset_class="equity", currency="USD", tz="America/New_York", name="X", exch="NMS"):
    return {"name": name, "asset_class": asset_class, "quote_currency": currency,
            "currency": currency, "timezone": tz, "exchange": exch, "exchange_code": exch}


def test_us_stock():
    r = resolve_identity("NVDA", ymeta(name="NVIDIA"), cik=1045810, report_currency="USD",
                         taxonomy="us-gaap", today="2026-11-06")
    assert r["instrument_type"] == "stock"
    assert r["quote_currency"] == "USD" and r["report_currency"] == "USD"
    assert r["currency"] == r["quote_currency"]        # alias sin ambigüedad
    assert r["country"] == "US"
    assert r["identifiers"]["cik"]["value"] == "1045810" and r["identifiers"]["cik"]["status"] == "verified"
    assert r["adr_relation"]["status"] == "not_applicable"


def test_adr_foreign_report_currency_differs():
    # TSM: cotiza USD, reporta TWD -> ADR; ratio semilla 5; país por zona horaria.
    r = resolve_identity("TSM", ymeta(currency="USD", tz="America/New_York", name="TSMC"),
                         cik=1046179, report_currency="TWD", taxonomy="ifrs-full", today="2026-11-06")
    assert r["instrument_type"] == "adr"
    assert r["adr_ratio"] == 5.0 and r["adr_relation"]["source"] == "curated"
    assert r["quote_currency"] == "USD" and r["report_currency"] == "TWD"


def test_asml_adr_ratio_1():
    r = resolve_identity("ASML", ymeta(currency="USD", name="ASML"), report_currency="EUR", today="2026-11-06")
    assert r["instrument_type"] == "adr" and r["adr_ratio"] == 1.0


def test_etf_and_commodity():
    assert resolve_identity("VOO", ymeta(asset_class="etf"), today="2026-11-06")["instrument_type"] == "etf"
    assert resolve_identity("GLD", ymeta(asset_class="etf"), today="2026-11-06")["instrument_type"] == "commodity_etf"


def test_identifiers_without_backing_are_unavailable():
    r = resolve_identity("NEWCO", ymeta(), today="2026-11-06")
    assert r["identifiers"]["isin"]["status"] == "unavailable" and r["identifiers"]["isin"]["value"] is None
    assert r["identifiers"]["figi"]["status"] == "unavailable"   # no se pasó figi
    assert r["identifiers"]["lei"]["status"] == "unavailable"


def test_country_none_when_tz_unknown_not_invented():
    r = resolve_identity("X", ymeta(tz="Mars/Olympus"), today="2026-11-06")
    assert r["country"] is None   # no se inventa el país


def test_new_instrument_resolves_without_fixed_lists():
    # MELI: no está en universe.py; se resuelve igual desde la meta (cotiza USD en Nasdaq).
    r = resolve_identity("MELI", ymeta(currency="USD", name="MercadoLibre"), report_currency="USD", today="2026-11-06")
    assert r["instrument_type"] == "stock" and r["name"] == "MercadoLibre"
    assert r["quote_currency"] == "USD"
