"""Proveedor de EJEMPLO. No usa red. TODOS sus datos son sintéticos y van marcados
con is_sample=True / is_sample en cada estructura.

Existe para dos cosas: (1) permitir que la app arranque y se pruebe sin claves ni
despliegue; (2) servir de contrato de referencia para los proveedores reales. Las
cifras son plausibles pero FICTICIAS y no deben usarse para decidir inversiones.
Los precios se generan con una caminata determinista (semilla por ticker) para que
las pruebas sean reproducibles.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..core.types import AssetClass, ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

# Universo de ejemplo (ficticio pero plausible). sector/país reales para que la
# analítica de distribución tenga sentido; las MÉTRICAS son inventadas.
_UNIVERSE: Dict[str, Instrument] = {
    "NVDA": Instrument("NVDA", "NVIDIA Corp", AssetClass.EQUITY, "US", "US", "Semiconductores", "USD"),
    "ASML": Instrument("ASML", "ASML Holding", AssetClass.EQUITY, "US", "NL", "Semiconductores", "USD"),
    "TSM": Instrument("TSM", "Taiwan Semiconductor (ADR)", AssetClass.EQUITY, "US", "TW", "Semiconductores", "USD"),
    "META": Instrument("META", "Meta Platforms", AssetClass.EQUITY, "US", "US", "Servicios de Comunicación", "USD"),
    "NFLX": Instrument("NFLX", "Netflix", AssetClass.EQUITY, "US", "US", "Servicios de Comunicación", "USD"),
    "AVGO": Instrument("AVGO", "Broadcom", AssetClass.EQUITY, "US", "US", "Semiconductores", "USD"),
    "MSFT": Instrument("MSFT", "Microsoft", AssetClass.EQUITY, "US", "US", "Tecnología", "USD"),
    "GOOGL": Instrument("GOOGL", "Alphabet", AssetClass.EQUITY, "US", "US", "Servicios de Comunicación", "USD"),
    "UNH": Instrument("UNH", "UnitedHealth", AssetClass.EQUITY, "US", "US", "Salud", "USD"),
    "KO": Instrument("KO", "Coca-Cola", AssetClass.EQUITY, "US", "US", "Consumo Básico", "USD"),
    "VOO": Instrument("VOO", "Vanguard S&P 500 ETF", AssetClass.ETF, "US", "US", "ETF", "USD"),
    "QQQ": Instrument("QQQ", "Invesco Nasdaq 100 ETF", AssetClass.ETF, "US", "US", "ETF", "USD"),
    "SMH": Instrument("SMH", "VanEck Semiconductor ETF", AssetClass.ETF, "US", "US", "ETF", "USD"),
    "SCHD": Instrument("SCHD", "Schwab US Dividend ETF", AssetClass.ETF, "US", "US", "ETF", "USD"),
    "GLD": Instrument("GLD", "SPDR Gold Shares", AssetClass.ETF, "US", "US", "Materias Primas", "USD"),
    "SLV": Instrument("SLV", "iShares Silver Trust", AssetClass.ETF, "US", "US", "Materias Primas", "USD"),
}

# Fundamentales FICTICIOS (is_sample=True). Solo para probar el scanner.
_FUNDAMENTALS: Dict[str, dict] = {
    "NVDA": dict(pe_forward=34.0, ev_ebitda=30.0, fcf_yield=0.020, roic=0.55, roe=0.90, rev_growth_yoy=0.85, eps_growth_yoy=0.80, net_margin=0.56, debt_to_equity=0.20, market_cap=3.2e12),
    "ASML": dict(pe_forward=26.0, ev_ebitda=22.0, fcf_yield=0.030, roic=0.35, roe=0.55, rev_growth_yoy=0.13, eps_growth_yoy=0.15, net_margin=0.28, debt_to_equity=0.30, market_cap=3.0e11),
    "TSM": dict(pe_forward=19.0, ev_ebitda=11.0, fcf_yield=0.035, roic=0.28, roe=0.30, rev_growth_yoy=0.35, eps_growth_yoy=0.40, net_margin=0.42, debt_to_equity=0.25, market_cap=9.0e11),
    "META": dict(pe_forward=22.0, ev_ebitda=14.0, fcf_yield=0.040, roic=0.30, roe=0.34, rev_growth_yoy=0.22, eps_growth_yoy=0.35, net_margin=0.34, debt_to_equity=0.15, market_cap=1.3e12),
    "NFLX": dict(pe_forward=28.0, ev_ebitda=20.0, fcf_yield=0.028, roic=0.25, roe=0.33, rev_growth_yoy=0.15, eps_growth_yoy=0.25, net_margin=0.23, debt_to_equity=0.70, market_cap=3.0e11),
    "AVGO": dict(pe_forward=24.0, ev_ebitda=19.0, fcf_yield=0.035, roic=0.22, roe=0.40, rev_growth_yoy=0.40, eps_growth_yoy=0.30, net_margin=0.30, debt_to_equity=0.95, market_cap=7.0e11),
    "MSFT": dict(pe_forward=30.0, ev_ebitda=22.0, fcf_yield=0.028, roic=0.30, roe=0.38, rev_growth_yoy=0.15, eps_growth_yoy=0.14, net_margin=0.36, debt_to_equity=0.35, market_cap=3.1e12),
    "GOOGL": dict(pe_forward=20.0, ev_ebitda=14.0, fcf_yield=0.045, roic=0.28, roe=0.29, rev_growth_yoy=0.14, eps_growth_yoy=0.20, net_margin=0.28, debt_to_equity=0.10, market_cap=2.1e12),
    "UNH": dict(pe_forward=16.0, ev_ebitda=11.0, fcf_yield=0.060, roic=0.18, roe=0.24, rev_growth_yoy=0.10, eps_growth_yoy=0.12, net_margin=0.06, debt_to_equity=0.75, market_cap=4.5e11),
    "KO": dict(pe_forward=21.0, ev_ebitda=18.0, fcf_yield=0.035, roic=0.16, roe=0.40, rev_growth_yoy=0.05, eps_growth_yoy=0.06, net_margin=0.23, debt_to_equity=1.60, market_cap=2.6e11),
}

# Holdings FICTICIOS de los ETF (pesos aproximados-plausibles). Cobertura parcial
# a propósito: la suma < 1 para ejercitar el manejo honesto de 'resto'.
_ETF_HOLDINGS: Dict[str, List[tuple]] = {
    "QQQ": [("NVDA", 0.085), ("MSFT", 0.080), ("AVGO", 0.050), ("META", 0.045), ("GOOGL", 0.045), ("NFLX", 0.030)],
    "SMH": [("NVDA", 0.200), ("TSM", 0.120), ("AVGO", 0.090), ("ASML", 0.050)],
    "VOO": [("NVDA", 0.070), ("MSFT", 0.065), ("META", 0.025), ("GOOGL", 0.040), ("AVGO", 0.018), ("UNH", 0.012), ("KO", 0.009)],
    "SCHD": [("KO", 0.045), ("UNH", 0.040)],
}

_SEED_PRICE = {  # precio final aproximado para la caminata sintética
    "NVDA": 183.0, "ASML": 900.0, "TSM": 210.0, "META": 600.0, "NFLX": 67.0,
    "AVGO": 230.0, "MSFT": 420.0, "GOOGL": 190.0, "UNH": 300.0, "KO": 62.0,
    "VOO": 540.0, "QQQ": 480.0, "SMH": 260.0, "SCHD": 28.0, "GLD": 375.0, "SLV": 34.0,
}


class SampleProvider(MarketDataProvider):
    name = "sample"
    is_sample = True

    def __init__(self, history_days: int = 400, as_of: Optional[date] = None):
        self.history_days = history_days
        self.as_of = as_of or date(2026, 11, 5)

    def _history(self, ticker: str) -> pd.Series:
        end = _SEED_PRICE.get(ticker, 100.0)
        n = self.history_days
        seed = abs(hash(ticker)) % (2**32)
        rng = np.random.default_rng(seed)
        mu, sigma = 0.0003, 0.018
        shocks = rng.normal(mu, sigma, n)
        path = np.exp(np.cumsum(shocks[::-1]))      # construye hacia atrás desde 1.0
        path = path / path[-1] * end                 # escala para terminar en `end`
        idx = pd.bdate_range(end=self.as_of, periods=n)
        return pd.Series(path, index=idx, name=ticker)

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out = {}
        for t in tickers:
            if t in _UNIVERSE:
                out[t] = Quote(ticker=t, price=round(float(_SEED_PRICE.get(t, 100.0)), 2),
                               as_of=self.as_of, currency="USD", is_sample=True)
        return out

    def get_price_history(self, ticker, start=None, end=None) -> pd.Series:
        if ticker not in _UNIVERSE:
            return pd.Series(dtype=float)
        s = self._history(ticker)
        if start:
            s = s[s.index >= pd.Timestamp(start)]
        if end:
            s = s[s.index <= pd.Timestamp(end)]
        return s

    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        out = {}
        for t in tickers:
            d = _FUNDAMENTALS.get(t)
            if d:
                out[t] = Fundamentals(ticker=t, is_sample=True, **d)
        return out

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        rows = _ETF_HOLDINGS.get(etf_ticker, [])
        out = []
        for tk, w in rows:
            inst = _UNIVERSE.get(tk)
            out.append(ETFHolding(ticker=tk, weight=w,
                                  name=inst.name if inst else None,
                                  sector=inst.sector if inst else None))
        return out

    # Tasas FX de EJEMPLO (a USD). Ficticias, solo para demostrar la conversión.
    _FX_TO_USD = {"USD": 1.0, "MXN": 0.054, "CLP": 0.00105, "EUR": 1.08,
                  "TWD": 0.031, "JPY": 0.0064, "BRL": 0.175, "HKD": 0.128, "GBP": 1.27}

    def get_fx_rates(self, base: str, currencies: List[str]) -> dict:
        base = (base or "USD").upper()
        base_to_usd = self._FX_TO_USD.get(base, 1.0)
        out = {}
        for c in currencies:
            c = c.upper()
            if c in self._FX_TO_USD:
                out[c] = self._FX_TO_USD[c] / base_to_usd  # unidades de base por 1 c
        return out

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        items = [i for i in _UNIVERSE.values()
                 if i.asset_class == AssetClass.EQUITY
                 and (not exchanges or i.exchange in exchanges)]
        return items[:limit] if limit else items

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": True, "ok": True,
                "coverage": f"{len(_UNIVERSE)} instrumentos de EJEMPLO (no reales)"}
