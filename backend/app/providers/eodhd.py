"""Conector EODHD (eodhd.com) — proveedor REAL. Requiere EODHD_API_KEY.

Elegido como proveedor inicial por su cobertura global (US, Europa, Japón, Taiwán,
Corea, Hong Kong, México, Chile, Brasil), que es exactamente el universo del scanner.
Se prueba contra respuestas de ejemplo en tests/ (no se llama a la red en pruebas).

Mapeo de datos faltantes: si EODHD no entrega un campo, queda en None. Nunca se
sustituye por una cifra inventada. Si la API falla, se propaga el error (la UI lo
muestra como fuente no disponible; no se rellena con datos ficticios).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import AssetClass, ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE = "https://eodhd.com/api"


def _num(d: dict, *keys):
    """Primer valor numérico finito entre varias claves candidatas; None si ninguna."""
    for k in keys:
        v = d.get(k)
        if v in (None, "", "NA"):
            continue
        try:
            f = float(v)
            if f == f:  # no NaN
                return f
        except (TypeError, ValueError):
            continue
    return None


class EODHDProvider(MarketDataProvider):
    name = "eodhd"
    is_sample = False

    def __init__(self, api_key: str = "", default_exchange: str = "US", timeout: float = 20.0):
        if not api_key:
            raise ValueError("EODHDProvider requiere api_key (configura EODHD_API_KEY).")
        import httpx  # import diferido: solo necesario para proveedores reales
        self._httpx = httpx
        self.api_key = api_key
        self.default_exchange = default_exchange
        self._client = httpx.Client(timeout=timeout)

    # ---- helpers -------------------------------------------------------------
    def _sym(self, ticker: str) -> str:
        return ticker if "." in ticker else f"{ticker}.{self.default_exchange}"

    def _get(self, path: str, **params) -> object:
        params["api_token"] = self.api_key
        params.setdefault("fmt", "json")
        r = self._client.get(f"{BASE}/{path}", params=params)
        r.raise_for_status()
        return r.json()

    # ---- interfaz ------------------------------------------------------------
    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        for t in tickers:
            try:
                data = self._get(f"real-time/{self._sym(t)}")
            except Exception:
                continue
            price = _num(data or {}, "close", "previousClose")
            if price is None:
                continue
            out[t] = Quote(ticker=t, price=price, as_of=date.today(),
                           currency="USD", is_sample=False)
        return out

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        params = {}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        data = self._get(f"eod/{self._sym(ticker)}", **params)
        if not isinstance(data, list) or not data:
            return pd.Series(dtype=float)
        idx, vals = [], []
        for row in data:
            px = _num(row, "adjusted_close", "close")
            if px is None:
                continue
            idx.append(pd.Timestamp(row["date"]))
            vals.append(px)
        return pd.Series(vals, index=idx, name=ticker).sort_index()

    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        out: Dict[str, Fundamentals] = {}
        for t in tickers:
            try:
                d = self._get(f"fundamentals/{self._sym(t)}")
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            hi = d.get("Highlights", {}) or {}
            val = d.get("Valuation", {}) or {}
            fin = (d.get("Financials", {}) or {})
            mcap = _num(hi, "MarketCapitalization")
            fcf_yield = None
            # FCF yield si hay free cash flow TTM y market cap
            try:
                cf = (fin.get("Cash_Flow", {}) or {}).get("yearly", {}) or {}
                latest = next(iter(sorted(cf.keys(), reverse=True)), None)
                fcf = _num(cf.get(latest, {}) if latest else {}, "freeCashFlow")
                if fcf and mcap:
                    fcf_yield = fcf / mcap
            except Exception:
                fcf_yield = None
            out[t] = Fundamentals(
                ticker=t,
                pe_ttm=_num(hi, "PERatio"),
                pe_forward=_num(hi, "ForwardPE"),
                ev_ebitda=_num(val, "EnterpriseValueEbitda"),
                fcf_yield=fcf_yield,
                roe=_num(hi, "ReturnOnEquityTTM"),
                roic=None,  # EODHD no lo da directo; se deja None (no se inventa)
                rev_growth_yoy=_num(hi, "QuarterlyRevenueGrowthYOY"),
                eps_growth_yoy=_num(hi, "QuarterlyEarningsGrowthYOY"),
                net_margin=_num(hi, "ProfitMargin"),
                debt_to_equity=None,
                market_cap=mcap,
                is_sample=False,
            )
        return out

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        try:
            d = self._get(f"fundamentals/{self._sym(etf_ticker)}")
        except Exception:
            return []
        holdings = (((d or {}).get("ETF_Data", {}) or {}).get("Holdings", {}) or {})
        out: List[ETFHolding] = []
        for code, h in holdings.items():
            w = _num(h, "Assets_%", "Assets%")
            if w is None:
                continue
            out.append(ETFHolding(
                ticker=code.split(".")[0], weight=w / 100.0,
                name=h.get("Name"), sector=h.get("Sector")))
        return out

    def get_fx_rates(self, base: str, currencies: List[str]) -> Dict[str, float]:
        """Tasas C->base vía pares FOREX de EODHD (p.ej. 'MXNUSD.FOREX' = USD por 1 MXN)."""
        base = (base or "USD").upper()
        out: Dict[str, float] = {}
        for c in currencies:
            c = c.upper()
            if c == base:
                out[c] = 1.0
                continue
            try:
                data = self._get(f"real-time/{c}{base}.FOREX")
                rate = _num(data or {}, "close", "previousClose")
                if rate:
                    out[c] = rate
            except Exception:
                continue  # sin tasa => la capa de análisis lo marca (no se asume 1:1)
        return out

    def list_universe(self, exchanges: Optional[List[str]] = None, limit: Optional[int] = None) -> List[Instrument]:
        exchanges = exchanges or [self.default_exchange]
        out: List[Instrument] = []
        for ex in exchanges:
            try:
                rows = self._get(f"exchange-symbol-list/{ex}")
            except Exception:
                continue
            for row in rows or []:
                typ = (row.get("Type") or "").lower()
                ac = AssetClass.ETF if "etf" in typ else AssetClass.EQUITY
                if ac not in (AssetClass.EQUITY, AssetClass.ETF):
                    continue
                out.append(Instrument(
                    ticker=row.get("Code"), name=row.get("Name") or row.get("Code"),
                    asset_class=ac, exchange=ex, country=row.get("Country") or "",
                    sector=None, currency=row.get("Currency") or "USD"))
                if limit and len(out) >= limit:
                    return out
        return out

    def health(self) -> dict:
        try:
            ok = bool(self.get_quotes(["AAPL"]))
        except Exception as e:
            return {"provider": self.name, "is_sample": False, "ok": False, "error": str(e)}
        return {"provider": self.name, "is_sample": False, "ok": ok,
                "coverage": "global (US, EU, JP, TW, KR, HK, MX, CL, BR vía EODHD)"}
