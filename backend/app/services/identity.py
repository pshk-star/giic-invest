"""Resolución GLOBAL de identidad de instrumentos (Fase 2).

Determinístico y puro: consume datos ya obtenidos de fuentes verificables (Yahoo
chart.meta, SEC EDGAR, OpenFIGI, GLEIF) y arma una identidad consolidada. Cada
identificador lleva FUENTE, FECHA de verificación y ESTADO de disponibilidad.
NO inventa ni infiere identificadores sin respaldo: lo que no se puede verificar
queda con status="unavailable" y value=None.

Distingue tres monedas sin ambigüedad:
  - quote_currency : moneda en la que COTIZA el instrumento (precio de mercado).
  - report_currency: moneda de los ESTADOS FINANCIEROS (fundamentales).
  - currency       : alias heredado = quote_currency (compatibilidad), para evitar
                     conversiones duplicadas (el precio ya está en quote_currency).
"""
from __future__ import annotations

from typing import Dict, Optional

# PAÍS DE COTIZACIÓN (listing) por zona horaria de la bolsa. NO es el país del EMISOR.
# Mapa verificable y acotado; lo no cubierto queda None (no se inventa).
TZ_COUNTRY = {
    "America/New_York": "US", "America/Chicago": "US", "America/Los_Angeles": "US",
    "America/Toronto": "CA", "America/Sao_Paulo": "BR", "America/Mexico_City": "MX",
    "America/Santiago": "CL", "America/Argentina/Buenos_Aires": "AR",
    "Europe/Amsterdam": "NL", "Europe/Paris": "FR", "Europe/London": "GB",
    "Europe/Madrid": "ES", "Europe/Berlin": "DE", "Europe/Frankfurt": "DE",
    "Europe/Zurich": "CH", "Europe/Milan": "IT", "Europe/Stockholm": "SE",
    "Europe/Copenhagen": "DK", "Europe/Dublin": "IE", "Europe/Oslo": "NO",
    "Asia/Taipei": "TW", "Asia/Tokyo": "JP", "Asia/Hong_Kong": "HK",
    "Asia/Shanghai": "CN", "Asia/Seoul": "KR", "Asia/Singapore": "SG",
    "Asia/Kolkata": "IN", "Australia/Sydney": "AU",
}

# Ratios ADR/GDR de PARTIDA (acciones ordinarias por ADR). Verificable manualmente;
# NO es la solución definitiva: se marca source="curated" y debe poder resolverse de
# forma dinámica (prospecto/banco depositario) a futuro. Lo no cubierto queda null.
ADR_RATIO_SEED = {"TSM": 5.0, "ASML": 1.0, "NVO": 1.0, "TM": 5.0, "BABA": 8.0, "SONY": 1.0}

# PAÍS DEL EMISOR (domicilio), distinto del país de cotización. Fuentes, en orden:
#   1) EDGAR submissions (stateOfIncorporation / business.stateOrCountry).
#   2) Semilla curada verificable para emisores extranjeros conocidos (EDGAR a veces
#      no lo expone, p. ej. TSM). Marcada source="curated"; extensible, no definitiva.
US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE",
    "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD",
    "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU", "AS", "MP",
}
# Códigos EDGAR de país extranjero (confiables) -> ISO-3166 alfa-2.
EDGAR_FOREIGN_CODE = {"P7": "NL", "F4": "TW", "X3": "AR", "D8": "DE", "L2": "CH", "M6": "GB"}
ISSUER_COUNTRY_SEED = {
    "TSM": "TW", "ASML": "NL", "NVO": "DK", "TM": "JP", "MELI": "AR", "BABA": "CN",
    "SONY": "JP", "SAP": "DE", "SHEL": "GB", "TTE": "FR", "NVS": "CH", "AZN": "GB",
}


def resolve_issuer_country(ticker, edgar_incorp=None, edgar_state_country=None):
    """País del EMISOR con procedencia. (valor, source, status)."""
    for code in (edgar_incorp, edgar_state_country):
        c = (code or "").upper()
        if c in US_STATE_CODES:
            return ("US", "sec_edgar", "verified")
        if c in EDGAR_FOREIGN_CODE:
            return (EDGAR_FOREIGN_CODE[c], "sec_edgar", "verified")
    seed = ISSUER_COUNTRY_SEED.get(ticker.upper())
    if seed:
        return (seed, "curated", "seed")
    return (None, None, "unavailable")

COMMODITY_ETFS = {"GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"}


def _ident(value, source: Optional[str], as_of: Optional[str]) -> dict:
    """Envuelve un identificador con procedencia y estado de disponibilidad."""
    if value in (None, "", []):
        return {"value": None, "source": None, "as_of": as_of, "status": "unavailable"}
    return {"value": value, "source": source, "as_of": as_of, "status": "verified"}


def resolve_identity(
    ticker: str,
    ymeta: Optional[dict] = None,
    cik: Optional[int] = None,
    report_currency: Optional[str] = None,
    taxonomy: Optional[str] = None,
    figi: Optional[str] = None,
    lei: Optional[str] = None,
    adr_ratio: Optional[float] = None,
    adr_ratio_source: Optional[str] = None,
    edgar_incorp: Optional[str] = None,
    edgar_state_country: Optional[str] = None,
    today: Optional[str] = None,
) -> dict:
    tk = ticker.upper()
    ymeta = ymeta or {}
    quote_currency = ymeta.get("quote_currency") or ymeta.get("currency")
    asset_class = ymeta.get("asset_class") or "unknown"
    tz = ymeta.get("timezone")
    country_listing = TZ_COUNTRY.get(tz) if tz else None   # país de COTIZACIÓN (bolsa)
    issuer_c, issuer_src, issuer_status = resolve_issuer_country(tk, edgar_incorp, edgar_state_country)

    # Tipo de instrumento (no aplicar valoración de empresa a lo que no corresponde).
    if tk in COMMODITY_ETFS:
        instrument_type = "commodity_etf"
    elif asset_class == "etf":
        instrument_type = "etf"
    elif asset_class == "equity":
        # ADR/GDR: cotiza en una divisa distinta a la de sus estados financieros.
        foreign = (report_currency and quote_currency and report_currency != quote_currency)
        instrument_type = "adr" if foreign else "stock"
    else:
        instrument_type = asset_class or "unknown"

    # Ratio ADR: solo si el tipo es ADR/GDR; curado (semilla) o el provisto; sin inventar.
    ratio = None
    ratio_block = {"value": None, "source": None, "as_of": today, "status": "not_applicable"}
    if instrument_type in ("adr", "gdr"):
        ratio = adr_ratio if adr_ratio is not None else ADR_RATIO_SEED.get(tk)
        if ratio is not None:
            ratio_block = {"value": ratio, "source": adr_ratio_source or "curated",
                           "as_of": today, "status": "verified" if adr_ratio_source else "seed"}
        else:
            ratio_block = {"value": None, "source": None, "as_of": today, "status": "unavailable"}

    return {
        "ticker": tk,
        "name": ymeta.get("name"),
        "asset_class": asset_class,
        "instrument_type": instrument_type,
        "exchange": ymeta.get("exchange"),
        "exchange_code": ymeta.get("exchange_code"),
        "country_listing": country_listing,   # dónde COTIZA (bolsa)
        "country_issuer": issuer_c,            # domicilio del EMISOR (EDGAR/curado)
        "country_issuer_source": issuer_src,
        "country_issuer_status": issuer_status,
        "quote_currency": quote_currency,
        "report_currency": report_currency,
        "currency": quote_currency,   # alias heredado = quote_currency
        "adr_ratio": ratio,
        "taxonomy": taxonomy,
        "identifiers": {
            "cik": _ident(str(cik) if cik is not None else None, "sec_edgar", today),
            "figi": _ident(figi, "openfigi", today),
            "lei": _ident(lei, "gleif", today),
            # ISIN: sin fuente gratuita fiable directa -> no se infiere.
            "isin": {"value": None, "source": None, "as_of": today, "status": "unavailable"},
        },
        "adr_relation": ratio_block,
        "identity_as_of": today,
        "sources": {
            "meta": "yahoo_chart_meta" if ymeta else None,
            "country_listing": "exchange_timezone" if country_listing else None,
            "country_issuer": issuer_src,
        },
    }
