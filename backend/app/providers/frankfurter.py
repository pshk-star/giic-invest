"""Conector Frankfurter (frankfurter.dev) — tipos de cambio GRATIS, sin clave.

Datos del BCE (cierre diario). Sin límite de consultas documentado. Parser puro
`parse_frankfurter`; descarga por red en el job.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE_URL = "https://api.frankfurter.dev/v1"


def parse_frankfurter(payload: dict, base: str) -> Dict[str, float]:
    """Convierte la respuesta a {moneda: unidades de `base` por 1 unidad de moneda}.

    Frankfurter da rates[cur] = 'cur por 1 base'; invertimos para obtener
    'base por 1 cur', que es lo que espera core.fx.convert.
    """
    base = (base or "USD").upper()
    rates = (payload or {}).get("rates", {}) or {}
    out: Dict[str, float] = {base: 1.0}
    for cur, r in rates.items():
        try:
            r = float(r)
            if r > 0:
                out[cur.upper()] = 1.0 / r
        except (TypeError, ValueError):
            continue
    return out


class FrankfurterProvider(MarketDataProvider):
    name = "frankfurter"
    is_sample = False

    def __init__(self, timeout: float = 15.0):
        import httpx
        self._client = httpx.Client(timeout=timeout,
                                    headers={"User-Agent": "GIIC/0.3 (personal research)"})

    def get_fx_rates(self, base: str, currencies: List[str]) -> Dict[str, float]:
        base = (base or "USD").upper()
        symbols = [c.upper() for c in currencies if c.upper() != base]
        if not symbols:
            return {base: 1.0}
        try:
            r = self._client.get(f"{BASE_URL}/latest",
                                 params={"base": base, "symbols": ",".join(symbols)})
            r.raise_for_status()
            return parse_frankfurter(r.json(), base)
        except Exception:
            return {base: 1.0}   # sin red/errores: solo la base (el resto se marca)

    # No aplica
    def get_quotes(self, tickers): return {}
    def get_price_history(self, ticker, start=None, end=None): return pd.Series(dtype=float)
    def get_fundamentals(self, tickers): return {}
    def get_etf_holdings(self, etf_ticker): return []
    def list_universe(self, exchanges=None, limit=None): return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "FX BCE (frankfurter.dev), sin clave"}
