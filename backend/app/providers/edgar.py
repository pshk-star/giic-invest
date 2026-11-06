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


# Formularios anuales: 10-K (US), 20-F / 40-F (emisores extranjeros). Más enmiendas (/A).
ANNUAL_FORMS = ("10-K", "20-F", "40-F")

# Conceptos por taxonomía. us-gaap (emisores domésticos) e ifrs-full (20-F).
US_GAAP_MAP = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "ni": ["NetIncomeLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "equity": ["StockholdersEquity"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}
IFRS_MAP = {
    "rev": ["RevenueFromContractsWithCustomers", "Revenue"],
    "ni": ["ProfitLoss"],
    "eps": ["DilutedEarningsLossPerShare", "BasicEarningsLossPerShare",
            "DilutedEarningsPerShare", "BasicEarningsPerShare"],
    "equity": ["Equity"],
    "ocf": ["CashFlowsFromUsedInOperatingActivities"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
}
# ADR: 1 ADR = N acciones ordinarias (hechos verificables, no estimaciones).
ADR_RATIO = {"TSM": 5.0, "ASML": 1.0}


def _annual_points(unit_rows: list, forms: Tuple[str, ...] = ANNUAL_FORMS) -> List[Tuple[date, float]]:
    """Valores anuales (duración ~365d, formulario anual) ordenados por fecha fin."""
    out = {}
    for r in unit_rows or []:
        start, end, val, form = r.get("start"), r.get("end"), r.get("val"), str(r.get("form", ""))
        if val is None or not start or not end or not any(form.startswith(p) for p in forms):
            continue
        d0, d1 = _parse_date(start), _parse_date(end)
        if not d0 or not d1:
            continue
        span = (d1 - d0).days
        if 330 <= span <= 400:                 # ~1 año fiscal
            out[d1] = float(val)                # dedupe por fecha fin (gana la última)
    return sorted(out.items())


def _instant_points(unit_rows: list, forms: Tuple[str, ...] = ANNUAL_FORMS) -> List[Tuple[date, float]]:
    """Valores de balance (instantáneos) de formularios anuales, por fecha."""
    out = {}
    for r in unit_rows or []:
        end, val, form = r.get("end"), r.get("val"), str(r.get("form", ""))
        if val is None or not end or not any(form.startswith(p) for p in forms):
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


def _best_annual(facts, taxonomy, names, unit) -> List[Tuple[date, float]]:
    """Entre variantes de concepto, usa la que tenga datos ANUALES más RECIENTES.

    Evita series obsoletas cuando el emisor migró de etiqueta (p. ej. META:
    'Revenues' hasta 2017 vs 'RevenueFromContractWithCustomerExcludingAssessedTax').
    """
    best: List[Tuple[date, float]] = []
    for n in names:
        pts = _annual_points(_concept(facts, taxonomy, n, unit))
        if pts and (not best or pts[-1][0] > best[-1][0]):
            best = pts
    return best


def _best_instant(facts, taxonomy, names, unit) -> List[Tuple[date, float]]:
    best: List[Tuple[date, float]] = []
    for n in names:
        pts = _instant_points(_concept(facts, taxonomy, n, unit))
        if pts and (not best or pts[-1][0] > best[-1][0]):
            best = pts
    return best


def _currency_for(facts, taxonomy, names) -> Optional[str]:
    """Divisa de reporte: primera unidad monetaria (3 letras, sin '/') con datos."""
    try:
        node = facts["facts"][taxonomy]
    except (KeyError, TypeError):
        return None
    for n in names:
        units = (node.get(n, {}) or {}).get("units", {}) or {}
        for u in units:
            if "/" not in u and len(u) == 3 and u.isalpha():
                return u.upper()
    return None


def parse_companyfacts(facts: dict, ticker: str,
                       price: Optional[float] = None,
                       shares: Optional[float] = None,
                       fx_map: Optional[Dict[str, float]] = None,
                       adr_ratio: Optional[float] = None) -> Fundamentals:
    """Construye Fundamentals desde company facts de EDGAR. Campos ausentes => None.

    Cubre us-gaap (USD) e ifrs-full (emisores 20-F; divisa detectada, p. ej. EUR/TWD).
    - Ratios adimensionales (margen, ROE, crecimientos) son correctos en cualquier divisa.
    - pe_ttm / fcf_yield / market_cap mezclan precio en USD con cifras en divisa de reporte:
      se convierten con `fx_map` (USD por 1 unidad de divisa) y el `adr_ratio` (acciones
      ordinarias por ADR). Sin FX disponible para una divisa != USD => quedan en None
      (no se fabrican).
    """
    fx_map = fx_map or {}

    # Taxonomía + DIVISA DE REPORTE, data-driven. Muchos emisores extranjeros usan
    # etiquetas us-gaap pero en su divisa (ASML: us-gaap en EUR, formulario 20-F);
    # otros usan ifrs-full (TSM: TWD). Se detecta la divisa DENTRO de cada taxonomía
    # (no se asume USD) y se elige la que produzca datos anuales reales.
    def _pick(tax_name, cmap):
        c = _currency_for(facts, tax_name, cmap["rev"] + cmap["ni"] + cmap["equity"])
        if not c:
            return None
        r = _best_annual(facts, tax_name, cmap["rev"], c)
        n = _best_annual(facts, tax_name, cmap["ni"], c)
        if not (r or n):
            return None
        return (tax_name, c, cmap, r, n)

    picked = _pick("us-gaap", US_GAAP_MAP) or _pick("ifrs-full", IFRS_MAP)
    if picked:
        tax, ccy, M, rev, ni = picked
    else:
        tax, ccy, M, rev, ni = "us-gaap", "USD", US_GAAP_MAP, [], []

    eps = _best_annual(facts, tax, M["eps"], f"{ccy}/shares")
    # EPS oficial en USD por acción (p. ej. TSM publica DilutedEarningsLossPerShare en
    # USD/shares además de TWD): se prefiere para el P/E y se evita convertir desde la
    # divisa local. Es por ACCIÓN ORDINARIA; el factor ADR se aplica una sola vez abajo.
    eps_usd_series = _best_annual(facts, tax, M["eps"], "USD/shares") if ccy != "USD" else []
    equity = _best_instant(facts, tax, M["equity"], ccy)
    ocf = _best_annual(facts, tax, M["ocf"], ccy)
    capex = _best_annual(facts, tax, M["capex"], ccy)
    if shares is None:
        sh = _best_instant(facts, "dei", ["EntityCommonStockSharesOutstanding"], "shares") or \
            _best_instant(facts, tax, ["CommonStockSharesOutstanding"], "shares")
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
    as_of = (rev[-1][0].isoformat() if rev else (ni[-1][0].isoformat() if ni else None))

    # Adimensionales: válidos en cualquier divisa.
    net_margin = (ni_l / rev_l) if (ni_l is not None and rev_l) else None
    roe = (ni_l / eq_l) if (ni_l is not None and eq_l) else None

    # Dependientes de divisa/ADR.
    adr = adr_ratio if adr_ratio else 1.0
    fx = 1.0 if ccy == "USD" else fx_map.get(ccy)      # USD por 1 unidad de la divisa
    # EPS por ADR en USD: preferir la cifra oficial en USD/shares (conv=1); si no, convertir
    # la local con FX. En ambos casos × adr una sola vez (acción ordinaria -> ADR).
    if eps_usd_series:
        eps_for_pe, eps_conv = eps_usd_series[-1][1], 1.0
    else:
        eps_for_pe, eps_conv = eps_l, fx
    eps_usd = (eps_for_pe * adr * eps_conv) if (eps_for_pe is not None and eps_conv) else None
    adr_count = (shares / adr) if shares else None
    market_cap = (price * adr_count) if (price and adr_count) else None
    fcf = (ocf_l - capex_l) if (ocf_l is not None and capex_l is not None) else None
    fcf_usd = (fcf * fx) if (fcf is not None and fx) else None
    fcf_yield = (fcf_usd / market_cap) if (fcf_usd is not None and market_cap) else None
    pe_ttm = (price / eps_usd) if (price and eps_usd and eps_usd > 0) else None

    # Consistencia: identidad EPS × acciones ≈ utilidad neta (ambos en divisa de reporte).
    # Valida coherencia de EPS con moneda/acciones antes de usarlo; ADR se refleja aparte.
    eps_consistent = None
    eps_check_ratio = None
    if eps_l is not None and shares and ni_l not in (None, 0):
        eps_check_ratio = (eps_l * shares) / ni_l
        eps_consistent = abs(eps_check_ratio - 1.0) <= 0.15   # tolera básico/diluido y timing de acciones

    return Fundamentals(
        ticker=ticker,
        pe_ttm=pe_ttm,
        eps=eps_usd,                # EPS reportado (USD por ADR) → rendimiento de beneficios NO circular
        eps_basis="reported_annual",  # único disponible hoy; TTM/normalizado/forward pendientes de proveedor
        eps_consistent=eps_consistent,
        eps_check_ratio=(round(eps_check_ratio, 4) if eps_check_ratio is not None else None),
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
        currency=ccy,
        as_of=as_of,
        taxonomy=tax,
        is_sample=False,
    )


class EDGARProvider(MarketDataProvider):
    name = "edgar"
    is_sample = False

    def __init__(self, user_agent: str, timeout: float = 15.0, retries: int = 2):
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

    def get_fundamentals(self, tickers: List[str], prices: Optional[Dict[str, float]] = None,
                         fx_map: Optional[Dict[str, float]] = None) -> Dict[str, Fundamentals]:
        prices = prices or {}
        fx_map = fx_map or {}
        out = {}
        for t in tickers:
            facts = self._facts(t)
            if facts is None:
                continue
            out[t] = parse_companyfacts(facts, t, price=prices.get(t), fx_map=fx_map,
                                        adr_ratio=ADR_RATIO.get(t.upper(), 1.0))
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
