"""Pruebas del resolver de identidad global (Fase 2)."""
from app.services.identity import resolve_identity


def ymeta(asset_class="equity", currency="USD", tz="America/New_York", name="X", exch="NMS"):
    return {"name": name, "asset_class": asset_class, "quote_currency": currency,
            "currency": currency, "timezone": tz, "exchange": exch, "exchange_code": exch}


def test_us_stock():
    r = resolve_identity("NVDA", ymeta(name="NVIDIA"), cik=1045810, report_currency="USD",
                         taxonomy="us-gaap", edgar_incorp="DE", today="2026-11-06")
    assert r["instrument_type"] == "stock"
    assert r["quote_currency"] == "USD" and r["report_currency"] == "USD"
    assert r["currency"] == r["quote_currency"]        # alias sin ambigüedad
    assert r["country_listing"] == "US"                # cotiza en US
    assert r["country_issuer"] == "US" and r["country_issuer_source"] == "sec_edgar"  # Delaware -> US
    assert r["identifiers"]["cik"]["value"] == "1045810" and r["identifiers"]["cik"]["status"] == "verified"
    assert r["adr_relation"]["status"] == "not_applicable"


def test_issuer_vs_listing_country():
    # ASML cotiza en US pero el emisor es neerlandés (EDGAR P7 -> NL).
    r = resolve_identity("ASML", ymeta(currency="USD"), report_currency="EUR",
                         edgar_state_country="P7", today="2026-11-06")
    assert r["country_listing"] == "US" and r["country_issuer"] == "NL"
    assert r["country_issuer_source"] == "sec_edgar"
    # TSM: EDGAR no expone país -> semilla curada verificable (Taiwán), nunca por zona horaria.
    r2 = resolve_identity("TSM", ymeta(currency="USD"), report_currency="TWD", today="2026-11-06")
    assert r2["country_listing"] == "US" and r2["country_issuer"] == "TW"
    assert r2["country_issuer_source"] == "curated" and r2["country_issuer_status"] == "seed"


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
    r = resolve_identity("XZZ", ymeta(tz="Mars/Olympus"), today="2026-11-06")
    assert r["country_listing"] is None       # no se inventa el país de cotización
    assert r["country_issuer"] is None and r["country_issuer_status"] == "unavailable"


def test_new_instrument_resolves_without_fixed_lists():
    # MELI: no está en universe.py; se resuelve igual desde la meta (cotiza USD en Nasdaq).
    r = resolve_identity("MELI", ymeta(currency="USD", name="MercadoLibre"), report_currency="USD", today="2026-11-06")
    assert r["instrument_type"] == "stock" and r["name"] == "MercadoLibre"
    assert r["quote_currency"] == "USD"
