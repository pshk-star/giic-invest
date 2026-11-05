"""Conector Stooq (stooq.com) — precios EOD GRATIS, sin clave ni tarjeta.

Entrega cierres diarios ajustados y volumen para acciones/ETF de EE. UU. e índices.
No entrega fundamentales ni holdings (eso lo cubre EDGAR). Uso personal; no se
redistribuyen los datos (ver FREE_TIER_LIMITS.md).

El parser `parse_stooq_csv` es puro y se prueba con fixtures; la descarga por red
ocurre en el job de GitHub Actions (este sandbox no sale a Stooq).
"""
from __future__ import annotations

from datetime import date, datetime
from io import StringIO
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE = "https://stooq.com/q/d/l/"


def to_stooq_symbol(ticker: str) -> str:
    """Convierte un ticker a la convención de Stooq (acciones US => sufijo '.us')."""
    t = ticker.strip().lower()
    if t.startswith("^") or "." in t:      # índices (^spx) o ya calificado
        return t
    return f"{t}.us"


def parse_stooq_csv(text: str, ticker: str) -> pd.Series:
    """CSV 'Date,Open,High,Low,Close,Volume' -> Serie de cierres por fecha (asc)."""
    text = (text or "").strip()
    if not text or text.lower().startswith("<") or "no data" in text.lower():
        return pd.Series(dtype=float)
    df = pd.read_csv(StringIO(text))
    if "Date" not in df.columns or "Close" not in df.columns:
        return pd.Series(dtype=float)
    df = df.dropna(subset=["Date", "Close"])
    idx = pd.to_datetime(df["Date"])
    return pd.Series(df["Close"].astype(float).values, index=idx, name=ticker).sort_index()


def parse_stooq_volume(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    df = pd.read_csv(StringIO(text))
    if "Volume" not in df.columns or df.empty:
        return None
    v = df["Volume"].dropna()
    return float(v.iloc[-1]) if len(v) else None


class StooqProvider(MarketDataProvider):
    name = "stooq"
    is_sample = False

    def __init__(self, timeout: float = 15.0, retries: int = 2):
        import httpx
        self._httpx = httpx
        self.retries = retries
        self._client = httpx.Client(timeout=timeout,
                                    headers={"User-Agent": "GIIC/0.3 (personal research)"})

    def _download(self, symbol: str, start=None, end=None) -> str:
        params = {"s": symbol, "i": "d"}
        if start:
            params["d1"] = start.strftime("%Y%m%d")
        if end:
            params["d2"] = end.strftime("%Y%m%d")
        last = None
        for _ in range(max(1, self.retries)):
            try:
                r = self._client.get(BASE, params=params)
                r.raise_for_status()
                return r.text
            except Exception as e:  # timeout/red transitoria: reintenta una vez
                last = e
        raise last

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        return parse_stooq_csv(self._download(to_stooq_symbol(ticker), start, end), ticker)

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        for t in tickers:
            s = self.get_price_history(t)
            if len(s) == 0:
                continue
            as_of = s.index[-1].date() if hasattr(s.index[-1], "date") else date.today()
            out[t] = Quote(ticker=t, price=float(s.iloc[-1]), as_of=as_of,
                           currency="USD", is_sample=False)
        return out

    # Stooq no provee fundamentales/holdings/FX: se devuelven vacíos (sin inventar).
    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        return {}

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        return []

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Precios EOD US (acciones, ETF, índices) vía Stooq; sin fundamentales"}
