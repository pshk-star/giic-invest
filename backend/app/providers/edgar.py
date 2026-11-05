"""Conector SEC EDGAR (data.sec.gov) — fundamentales OFICIALES y GRATIS (US).

Fuente: XBRL company facts de las propias presentaciones a la SEC. Sin clave; exige
un User-Agent con contacto (política de la SEC). Cobertura: emisores estadounidenses.
Lo que no está en las presentaciones NO se inventa: queda en None.

Campos derivados de EDGAR: net_margin, roe, rev_growth_yoy, eps_growth_yoy, fcf_yield
(si hay precio y acciones), market_cap (precio × acciones), pe_ttm (precio / EPS).
No disponibles de forma fiable y gratuita aquí: pe_forward, ev_ebitda, roic => None
(documentado). El parser `parse_companyfacts` es puro y se prueba con fixtures.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _parse_date(s: str) -> Optional[date]:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _annual_points(unit_rows: list) -> List[Tuple[date, float]]:
    """Valores anuales (duración ~365d, formulario 10-K) ordenados por fecha fin."""
    out = {}
    for r in unit_rows or []:
        start, end, val, form = r.get("start"), r.get("end"), r.get("val"), r.get("form", "")
        if val is None or not start or not end or not str(form).startswith("10-K"):
            continue
        d0, d1 = _parse_date(start), _parse_date(end)
        if not d0 or not d1:
            continue
        span = (d1 - d0).days
        if 330 <= span <= 400:                 # ~1 año fiscal
            out[d1] = float(val)                # dedupe por fecha fin (gana la última)
    return sorted(out.items())


def _instant_points(unit_rows: list) -> List[Tuple[date, float]]:
    """Valores de balance (instantáneos) de formularios 10-K, por fecha."""
    out = {}
    for r in unit_rows or []:
        end, val, form = r.get("end"), r.get("val"), r.get("form", "")
        if val is None or not end or not str(form).startswith("10-K"):
            continue
        d = _parse_date(end)
        if d:
            out[d] = float(val)
    return sorted(out.items())


def _concept(facts: dict, taxonomy: str, name: str, unit: str) -> list:
    try:
        return facts["facts"][taxonomy][name]["units"][unit]
    except (KeyError, TypeError):
        return []


def _first_concept(facts, taxonomy, names, unit):
    for n in names:
        rows = _concept(facts, taxonomy, n, unit)
        if rows:
            return rows
    return []


def parse_companyfacts(facts: dict, ticker: str,
                       price: Optional[float] = None,
                       shares: Optional[float] = None) -> Fundamentals:
    """Construye Fundamentals desde company facts de EDGAR. Campos ausentes => None."""
    rev = _annual_points(_first_concept(
        facts, "us-gaap",
        ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"], "USD"))
    ni = _annual_points(_concept(facts, "us-gaap", "NetIncomeLoss", "USD"))
    eps = _annual_points(_first_concept(
        facts, "us-gaap", ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares"))
    equity = _instant_points(_concept(facts, "us-gaap", "StockholdersEquity", "USD"))
    ocf = _annual_points(_concept(
        facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"))
    capex = _annual_points(_first_concept(
        facts, "us-gaap", ["PaymentsToAcquirePropertyPlantAndEquipment",
                           "PaymentsToAcquireProductiveAssets"], "USD"))
    if shares is None:
        sh = _instant_points(_first_concept(
            facts, "dei", ["EntityCommonStockSharesOutstanding"], "shares")) or \
            _instant_points(_concept(facts, "us-gaap", "CommonStockSharesOutstanding", "shares"))
        shares = sh[-1][1] if sh else None

    def latest(points):
        return points[-1][1] if points else None

    def yoy(points):
        if len(points) < 2 or points[-2][1] in (0, None):
            return None
        prev = points[-2][1]
        if prev == 0:
            return None
        return points[-1][1] / prev - 1.0

    rev_l, ni_l, eps_l = latest(rev), latest(ni), latest(eps)
    eq_l, ocf_l, capex_l = latest(equity), latest(ocf), latest(capex)

    net_margin = (ni_l / rev_l) if (ni_l is not None and rev_l) else None
    roe = (ni_l / eq_l) if (ni_l is not None and eq_l) else None
    fcf = (ocf_l - capex_l) if (ocf_l is not None and capex_l is not None) else None
    market_cap = (price * shares) if (price and shares) else None
    fcf_yield = (fcf / market_cap) if (fcf is not None and market_cap) else None
    pe_ttm = (price / eps_l) if (price and eps_l and eps_l > 0) else None

    return Fundamentals(
        ticker=ticker,
        pe_ttm=pe_ttm,
        pe_forward=None,            # no disponible gratis en EDGAR
        ev_ebitda=None,             # requiere deuda/caja + EBITDA fiables
        fcf_yield=fcf_yield,
        roic=None,                  # no derivado aquí
        roe=roe,
        rev_growth_yoy=yoy(rev),
        eps_growth_yoy=yoy(eps),
        net_margin=net_margin,
        debt_to_equity=None,
        market_cap=market_cap,
        is_sample=False,
    )


class EDGARProvider(MarketDataProvider):
    name = "edgar"
    is_sample = False

    def __init__(self, user_agent: str, timeout: float = 30.0, retries: int = 2):
        if not user_agent or "@" not in user_agent:
            raise ValueError("EDGAR exige User-Agent con email de contacto (política SEC).")
        import httpx
        self.retries = retries
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": user_agent})
        self._cik: Dict[str, int] = {}

    def _fetch(self, url: str):
        """GET con un reintento ante timeout/red transitoria."""
        last = None
        for _ in range(max(1, self.retries)):
            try:
                return self._client.get(url)
            except Exception as e:
                last = e
        raise last

    def _load_ciks(self):
        if self._cik:
            return
        r = self._fetch(TICKERS_URL)
        r.raise_for_status()
        for row in r.json().values():
            self._cik[row["ticker"].upper()] = int(row["cik_str"])

    def _facts(self, ticker: str) -> Optional[dict]:
        self._load_ciks()
        cik = self._cik.get(ticker.upper())
        if cik is None:
            return None
        r = self._fetch(FACTS_URL.format(cik=cik))
        if r.status_code != 200:
            return None
        return r.json()

    def get_fundamentals(self, tickers: List[str], prices: Optional[Dict[str, float]] = None) -> Dict[str, Fundamentals]:
        prices = prices or {}
        out = {}
        for t in tickers:
            facts = self._facts(t)
            if facts is None:
                continue
            out[t] = parse_companyfacts(facts, t, price=prices.get(t))
        return out

    # EDGAR no da precios/FX/holdings
    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        return {}

    def get_price_history(self, ticker, start=None, end=None) -> pd.Series:
        return pd.Series(dtype=float)

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        return []

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Fundamentales oficiales US (SEC EDGAR); sin pe_forward/ev_ebitda/roic"}
