"""Proveedor compuesto: combina fuentes gratuitas especializadas tras la interfaz
única `MarketDataProvider`. Precios de uno, fundamentales de otro, FX de otro.

Esto permite la arquitectura $0: Stooq (precios) + EDGAR (fundamentales) +
Frankfurter (FX), sin que el resto del sistema (scan_engine, analítica) note la
diferencia respecto a un proveedor único de pago.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider


class CompositeProvider(MarketDataProvider):
    name = "composite(free)"
    is_sample = False

    def __init__(self, prices: MarketDataProvider, fundamentals: MarketDataProvider,
                 fx: Optional[MarketDataProvider] = None):
        self.prices = prices
        self.fundamentals = fundamentals
        self.fx = fx

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        return self.prices.get_quotes(tickers)

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        return self.prices.get_price_history(ticker, start, end)

    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        # El proveedor de fundamentales puede necesitar precios (market cap, P/E).
        quotes = self.prices.get_quotes(tickers)
        prices = {t: q.price for t, q in quotes.items()}
        try:
            return self.fundamentals.get_fundamentals(tickers, prices=prices)  # EDGAR acepta prices
        except TypeError:
            return self.fundamentals.get_fundamentals(tickers)

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        return self.fundamentals.get_etf_holdings(etf_ticker)

    def get_fx_rates(self, base: str, currencies: List[str]) -> Dict[str, float]:
        if self.fx is not None:
            return self.fx.get_fx_rates(base, currencies)
        return {}

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        return []  # el universo lo define jobs/universe.py de forma sistemática

    def health(self) -> dict:
        return {
            "provider": self.name, "is_sample": False, "ok": True,
            "sources": {
                "prices": self.prices.health(),
                "fundamentals": self.fundamentals.health(),
                "fx": self.fx.health() if self.fx else None,
            },
        }
