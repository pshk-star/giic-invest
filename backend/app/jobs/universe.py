"""Universo del scanner: selección SISTEMÁTICA y DOCUMENTADA de instrumentos US.

Criterio de inclusión (v0.3): acciones estadounidenses grandes y líquidas (perfil
S&P 100 ampliado) más los ETF y proxies de índice de referencia. Es un punto de
partida verificable y sostenible con fuentes gratuitas (Stooq + EDGAR), no una
lista arbitraria ni exhaustiva. La cobertura real se reporta en cada corrida; el
universo es ampliable editando esta lista o, más adelante, construyéndolo
dinámicamente desde un índice público.

Los sectores son clasificaciones estables (nivel sector GICS aproximado), no datos
de mercado; permiten el ranking comparable por sector.
"""
from __future__ import annotations

from typing import List

from ..core.types import AssetClass, Instrument

# (ticker, nombre, sector). Acciones US líquidas.
_EQUITIES = [
    ("AAPL", "Apple", "Tecnología"),
    ("MSFT", "Microsoft", "Tecnología"),
    ("NVDA", "NVIDIA", "Semiconductores"),
    ("AVGO", "Broadcom", "Semiconductores"),
    ("AMD", "Advanced Micro Devices", "Semiconductores"),
    ("INTC", "Intel", "Semiconductores"),
    ("QCOM", "Qualcomm", "Semiconductores"),
    ("TXN", "Texas Instruments", "Semiconductores"),
    ("MU", "Micron", "Semiconductores"),
    ("AMAT", "Applied Materials", "Semiconductores"),
    ("GOOGL", "Alphabet", "Servicios de Comunicación"),
    ("META", "Meta Platforms", "Servicios de Comunicación"),
    ("NFLX", "Netflix", "Servicios de Comunicación"),
    ("DIS", "Walt Disney", "Servicios de Comunicación"),
    ("TMUS", "T-Mobile US", "Servicios de Comunicación"),
    ("AMZN", "Amazon", "Consumo Discrecional"),
    ("TSLA", "Tesla", "Consumo Discrecional"),
    ("HD", "Home Depot", "Consumo Discrecional"),
    ("MCD", "McDonald's", "Consumo Discrecional"),
    ("NKE", "Nike", "Consumo Discrecional"),
    ("SBUX", "Starbucks", "Consumo Discrecional"),
    ("LOW", "Lowe's", "Consumo Discrecional"),
    ("KO", "Coca-Cola", "Consumo Básico"),
    ("PEP", "PepsiCo", "Consumo Básico"),
    ("PG", "Procter & Gamble", "Consumo Básico"),
    ("COST", "Costco", "Consumo Básico"),
    ("WMT", "Walmart", "Consumo Básico"),
    ("MDLZ", "Mondelez", "Consumo Básico"),
    ("CL", "Colgate-Palmolive", "Consumo Básico"),
    ("JPM", "JPMorgan Chase", "Financiero"),
    ("BAC", "Bank of America", "Financiero"),
    ("WFC", "Wells Fargo", "Financiero"),
    ("GS", "Goldman Sachs", "Financiero"),
    ("MS", "Morgan Stanley", "Financiero"),
    ("V", "Visa", "Financiero"),
    ("MA", "Mastercard", "Financiero"),
    ("AXP", "American Express", "Financiero"),
    ("BLK", "BlackRock", "Financiero"),
    ("SPGI", "S&P Global", "Financiero"),
    ("UNH", "UnitedHealth", "Salud"),
    ("JNJ", "Johnson & Johnson", "Salud"),
    ("LLY", "Eli Lilly", "Salud"),
    ("PFE", "Pfizer", "Salud"),
    ("MRK", "Merck", "Salud"),
    ("ABBV", "AbbVie", "Salud"),
    ("TMO", "Thermo Fisher", "Salud"),
    ("ABT", "Abbott", "Salud"),
    ("DHR", "Danaher", "Salud"),
    ("AMGN", "Amgen", "Salud"),
    ("XOM", "Exxon Mobil", "Energía"),
    ("CVX", "Chevron", "Energía"),
    ("COP", "ConocoPhillips", "Energía"),
    ("SLB", "Schlumberger", "Energía"),
    ("EOG", "EOG Resources", "Energía"),
    ("BA", "Boeing", "Industrial"),
    ("CAT", "Caterpillar", "Industrial"),
    ("HON", "Honeywell", "Industrial"),
    ("GE", "GE Aerospace", "Industrial"),
    ("UPS", "United Parcel Service", "Industrial"),
    ("RTX", "RTX", "Industrial"),
    ("DE", "Deere", "Industrial"),
    ("LMT", "Lockheed Martin", "Industrial"),
    ("CRM", "Salesforce", "Tecnología"),
    ("ORCL", "Oracle", "Tecnología"),
    ("ADBE", "Adobe", "Tecnología"),
    ("CSCO", "Cisco", "Tecnología"),
    ("ACN", "Accenture", "Tecnología"),
    ("IBM", "IBM", "Tecnología"),
    ("NOW", "ServiceNow", "Tecnología"),
    ("INTU", "Intuit", "Tecnología"),
    ("LIN", "Linde", "Materiales"),
    ("SHW", "Sherwin-Williams", "Materiales"),
    ("FCX", "Freeport-McMoRan", "Materiales"),
    ("NEE", "NextEra Energy", "Servicios Públicos"),
    ("DUK", "Duke Energy", "Servicios Públicos"),
    ("SO", "Southern Company", "Servicios Públicos"),
    ("AMT", "American Tower", "Inmobiliario"),
    ("PLD", "Prologis", "Inmobiliario"),
]

# ETF y proxies de índice (sin fundamentales de empresa; aportan contexto de mercado).
_ETFS = [
    ("SPY", "SPDR S&P 500 ETF", "ETF"),
    ("QQQ", "Invesco Nasdaq 100 ETF", "ETF"),
    ("DIA", "SPDR Dow Jones ETF", "ETF"),
    ("IWM", "iShares Russell 2000 ETF", "ETF"),
    ("VOO", "Vanguard S&P 500 ETF", "ETF"),
    ("SMH", "VanEck Semiconductor ETF", "ETF"),
    ("SCHD", "Schwab US Dividend ETF", "ETF"),
    ("GLD", "SPDR Gold Shares", "ETF"),
    ("SLV", "iShares Silver Trust", "ETF"),
    ("XLK", "Technology Select Sector SPDR", "ETF"),
    ("XLF", "Financial Select Sector SPDR", "ETF"),
    ("XLE", "Energy Select Sector SPDR", "ETF"),
    ("XLV", "Health Care Select Sector SPDR", "ETF"),
]

UNIVERSE_VERSION = "us-core-v1"


def get_universe(include_etfs: bool = True) -> List[Instrument]:
    out = [Instrument(ticker=t, name=n, asset_class=AssetClass.EQUITY,
                      exchange="US", country="US", sector=s, currency="USD")
           for t, n, s in _EQUITIES]
    if include_etfs:
        out += [Instrument(ticker=t, name=n, asset_class=AssetClass.ETF,
                           exchange="US", country="US", sector=s, currency="USD")
                for t, n, s in _ETFS]
    return out


def equity_tickers() -> List[str]:
    return [t for t, _, _ in _EQUITIES]
