"""Conector Yahoo Finance (precios EOD) — GRATIS, sin clave.

Usa la API pública de gráficos (chart). A diferencia de Stooq, suele responder desde
IPs de datacenter (GitHub Actions), por eso es la fuente de precios primaria en la
arquitectura $0. Parser puro `parse_yahoo_chart`; la descarga ocurre en el job.

Nota: es una API no documentada formalmente; puede limitar por volumen. Uso personal
y moderado (EOD de decenas de instrumentos al día).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def parse_yahoo_chart(payload: dict, ticker: str) -> pd.Series:
    """Convierte la respuesta chart de Yahoo en Serie de cierres ajustados por fecha."""
    try:
        res = (payload or {}).get("chart", {}).get("result")
        if not res:
            return pd.Series(dtype=float)
        r0 = res[0]
        ts = r0.get("timestamp") or []
        ind = r0.get("indicators", {}) or {}
        adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
        close = (ind.get("quote") or [{}])[0].get("close")
        vals = adj if adj else close
        if not ts or not vals:
            return pd.Series(dtype=float)
        idx, data = [], []
        for t, v in zip(ts, vals):
            if v is None:
                continue
            idx.append(pd.Timestamp(datetime.fromtimestamp(t, tz=timezone.utc).date()))
            data.append(float(v))
        return pd.Series(data, index=idx, name=ticker).sort_index()
    except (KeyError, IndexError, TypeError, ValueError):
        return pd.Series(dtype=float)


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    is_sample = False

    def __init__(self, timeout: float = 15.0, retries: int = 2):
        import httpx
        self.retries = retries
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": _UA})

    def _chart(self, ticker: str, rng: str = "2y") -> dict:
        last = None
        for _ in range(max(1, self.retries)):
            try:
                r = self._client.get(f"{BASE}{ticker}",
                                     params={"range": rng, "interval": "1d"})
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
        raise last

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        s = parse_yahoo_chart(self._chart(ticker), ticker)
        if start is not None and len(s):
            s = s[s.index >= pd.Timestamp(start)]
        if end is not None and len(s):
            s = s[s.index <= pd.Timestamp(end)]
        return s

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        for t in tickers:
            try:
                s = self.get_price_history(t)
            except Exception:
                continue
            if len(s) == 0:
                continue
            as_of = s.index[-1].date() if hasattr(s.index[-1], "date") else date.today()
            out[t] = Quote(ticker=t, price=float(s.iloc[-1]), as_of=as_of,
                           currency="USD", is_sample=False)
        return out

    def get_fundamentals(self, tickers): return {}
    def get_etf_holdings(self, etf_ticker): return []
    def list_universe(self, exchanges=None, limit=None): return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Precios EOD US (Yahoo Finance chart API), sin clave"}
