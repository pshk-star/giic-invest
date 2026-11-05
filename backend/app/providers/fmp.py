"""Conector Financial Modeling Prep (FMP) — proveedor REAL alternativo.

Requiere FMP_API_KEY. Buena fuente de fundamentales y screener; cobertura
internacional razonable aunque menor que EODHD. Incluido para demostrar que la
arquitectura permite cambiar de proveedor sin tocar la lógica (mismo contrato).
Datos faltantes -> None; nunca se inventan.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import AssetClass, ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE = "https://financialmodelingprep.com/api/v3"


def _num(d: dict, *keys):
    for k in keys:
        v = d.get(k)
        if v in (None, "", "NA"):
            continue
        try:
            f = float(v)
            if f == f:
                return f
        except (TypeError, ValueError):
            continue
    return None


class FMPProvider(MarketDataProvider):
    name = "fmp"
    is_sample = False

    def __init__(self, api_key: str = "", timeout: float = 20.0):
        if not api_key:
            raise ValueError("FMPProvider requiere api_key (configura FMP_API_KEY).")
        import httpx
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout)

    def _get(self, path: str, **params):
        params["apikey"] = self.api_key
        r = self._client.get(f"{BASE}/{path}", params=params)
        r.raise_for_status()
        return r.json()

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        if not tickers:
            return {}
        try:
            data = self._get(f"quote/{','.join(tickers)}")
        except Exception:
            return {}
        out = {}
        for row in data or []:
            price = _num(row, "price")
            if price is None:
                continue
            out[row["symbol"]] = Quote(ticker=row["symbol"], price=price,
                                       as_of=date.today(), currency="USD", is_sample=False)
        return out

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        params = {"serietype": "line"}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        data = self._get(f"historical-price-full/{ticker}", **params)
        rows = (data or {}).get("historical", []) if isinstance(data, dict) else []
        idx, vals = [], []
        for row in rows:
            px = _num(row, "adjClose", "close")
            if px is None:
                continue
            idx.append(pd.Timestamp(row["date"]))
            vals.append(px)
        return pd.Series(vals, index=idx, name=ticker).sort_index()

    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        out: Dict[str, Fundamentals] = {}
        for t in tickers:
            try:
                ratios = (self._get(f"ratios-ttm/{t}") or [{}])[0]
                metrics = (self._get(f"key-metrics-ttm/{t}") or [{}])[0]
                profile = (self._get(f"profile/{t}") or [{}])[0]
            except Exception:
                continue
            out[t] = Fundamentals(
                ticker=t,
                pe_ttm=_num(ratios, "peRatioTTM"),
                pe_forward=None,  # FMP no lo da en ratios-ttm; se deja None
                ev_ebitda=_num(metrics, "enterpriseValueOverEBITDATTM"),
                fcf_yield=_num(metrics, "freeCashFlowYieldTTM"),
                roic=_num(metrics, "roicTTM"),
                roe=_num(ratios, "returnOnEquityTTM"),
                rev_growth_yoy=None,
                eps_growth_yoy=None,
                net_margin=_num(ratios, "netProfitMarginTTM"),
                debt_to_equity=_num(ratios, "debtEquityRatioTTM"),
                market_cap=_num(profile, "mktCap"),
                is_sample=False,
            )
        return out

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        try:
            data = self._get(f"etf-holder/{etf_ticker}")
        except Exception:
            return []
        out = []
        for row in data or []:
            w = _num(row, "weightPercentage")
            if w is None:
                continue
            out.append(ETFHolding(ticker=row.get("asset"), weight=w / 100.0, name=row.get("name")))
        return out

    def list_universe(self, exchanges: Optional[List[str]] = None, limit: Optional[int] = None) -> List[Instrument]:
        try:
            data = self._get("stock-screener", limit=limit or 1000,
                             exchange=",".join(exchanges) if exchanges else "NASDAQ,NYSE")
        except Exception:
            return []
        out = []
        for row in data or []:
            ac = AssetClass.ETF if row.get("isEtf") else AssetClass.EQUITY
            out.append(Instrument(
                ticker=row.get("symbol"), name=row.get("companyName") or row.get("symbol"),
                asset_class=ac, exchange=row.get("exchangeShortName") or "",
                country=row.get("country") or "US", sector=row.get("sector"),
                currency="USD"))
            if limit and len(out) >= limit:
                break
        return out

    def health(self) -> dict:
        try:
            ok = bool(self.get_quotes(["AAPL"]))
        except Exception as e:
            return {"provider": self.name, "is_sample": False, "ok": False, "error": str(e)}
        return {"provider": self.name, "is_sample": False, "ok": ok, "coverage": "US + internacional (FMP)"}
