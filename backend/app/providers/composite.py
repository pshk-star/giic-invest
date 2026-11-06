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


class FallbackPrices(MarketDataProvider):
    """Fuente de precios con respaldo: prueba varias en orden y usa la primera que
    devuelva datos. Permite que, si una (p.ej. Stooq) es bloqueada desde una IP de
    datacenter, otra (p.ej. Yahoo) cubra sin tumbar el job."""
    name = "fallback-prices"
    is_sample = False

    def __init__(self, providers: List[MarketDataProvider]):
        self.providers = providers

    def get_price_history(self, ticker, start=None, end=None) -> pd.Series:
        for p in self.providers:
            try:
                s = p.get_price_history(ticker, start, end)
            except Exception:
                s = None
            if s is not None and len(s):
                return s
        return pd.Series(dtype=float)

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        remaining = list(tickers)
        for p in self.providers:
            if not remaining:
                break
            try:
                got = p.get_quotes(remaining)
            except Exception:
                got = {}
            out.update(got)
            remaining = [t for t in remaining if t not in out]
        return out

    def get_stats(self, tickers: List[str]) -> Dict[str, dict]:
        """Estadísticas de fallback (EPS TTM / acciones): primera fuente que las ofrezca."""
        out: Dict[str, dict] = {}
        for p in self.providers:
            getter = getattr(p, "get_stats", None)
            if not callable(getter):
                continue
            try:
                got = getter([t for t in tickers if t not in out]) or {}
            except Exception:
                got = {}
            out.update(got)
        return out

    def get_fundamentals(self, tickers): return {}
    def get_etf_holdings(self, etf_ticker): return []
    def list_universe(self, exchanges=None, limit=None): return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "sources": [p.name for p in self.providers]}


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
        # El proveedor de fundamentales puede necesitar precios (market cap, P/E) y FX
        # (emisores extranjeros IFRS que reportan en EUR/TWD/… -> convertir a USD).
        quotes = self.prices.get_quotes(tickers)
        prices = {t: q.price for t, q in quotes.items()}
        fx_map: Dict[str, float] = {}
        if self.fx is not None:
            try:
                fx_map = self.fx.get_fx_rates("USD", [
                    "EUR", "TWD", "JPY", "GBP", "HKD", "CAD", "CHF", "KRW",
                    "ILS", "DKK", "SEK", "BRL", "CLP", "AUD", "SGD", "CNY",
                ])
            except Exception:
                fx_map = {}
        # Fallback multifuente: estadísticas complementarias (p. ej. Yahoo EPS TTM / acciones)
        # usadas SÓLO cuando EDGAR no cubre. Best-effort; no aborta si no está disponible.
        fallback_stats: Dict[str, dict] = {}
        getter = getattr(self.prices, "get_stats", None)
        if callable(getter):
            try:
                fallback_stats = getter(tickers) or {}
            except Exception:
                fallback_stats = {}
        try:
            return self.fundamentals.get_fundamentals(tickers, prices=prices, fx_map=fx_map,
                                                      fallback_stats=fallback_stats)
        except TypeError:
            try:
                return self.fundamentals.get_fundamentals(tickers, prices=prices, fx_map=fx_map)
            except TypeError:
                try:
                    return self.fundamentals.get_fundamentals(tickers, prices=prices)
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
