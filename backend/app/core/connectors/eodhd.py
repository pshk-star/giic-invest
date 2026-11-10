"""Conector EODHD de fundamentales (E3.4) — registrado en el ConnectorRegistry E2.

Aporta ANUAL e INTERINO como observaciones DISTINTAS, con moneda, unidad, cierre fiscal, fecha de
publicación y procedencia. Respeta las reglas acordadas:
  1. revenue/net_income/ocf/cash: se integran (anual e interino).
  2. EPS: se distingue reportado vs ajustado/core, básico vs diluido, ADR vs ordinaria; se marca
     NO-USAR-PARA-VALORACIÓN si la base es ambigua (método), y nunca pisa el EPS reportado de EDGAR.
  3. CAPEX: se marca 'definición amplia' (verificar vs PP&E oficial); queda `parcial` hasta conciliar.
  4. Total debt: composición (corriente/no corriente/leases) desconocida → `parcial`.
  5. Acciones diluidas ponderadas: NO se emiten (vienen de EDGAR u otra fuente oficial). Nunca se
     sustituyen por outstanding shares.
  6. FCF: OCF−CAPEX sólo si ambos son del mismo período/moneda; si falta alguno, NO se fabrica.
  7. Selección: la emite como `aggregator` (calidad parcial); la conciliación contra fuente oficial
     (EDGAR u otra) la sube a `verificado` o la marca `inconsistente`. Un interino fresco que EDGAR
     no tiene queda `parcial` (usable, pendiente de confirmación con IR/regulador), no bloqueado.

Seguridad/operación: clave sólo por `EODHD_API_KEY` (env); cost_tier COMMERCIAL (gate); caché por TTL
en el registro; manejo de errores que nunca filtra la clave (URLs redactadas).
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from .registry import ProvenancedField
from .spec import ConnectorSpec, ConnectorStatus, Coverage, CostTier, QualityTier

EODHD_BASE = "https://eodhd.com/api"

# Semillas verificables (hecho, no estimación): símbolo EODHD por emisor y factor ADR (acciones
# ordinarias por ADR). Un emisor universal las tomaría de la capa de identidad; aquí basta el seed.
EODHD_SYMBOLS = {
    "ASML": (["ASML.AS", "ASML.US"], 1), "TSM": (["2330.TW", "TSM.US"], 5),
    "SAP": (["SAP.XETRA", "SAP.US"], 1), "NVO": (["NOVO-B.CO", "NVO.US"], 1),
    "AZN": (["AZN.LSE", "AZN.US"], 2), "BABA": (["9988.HK", "BABA.US"], 8),
    "TM": (["7203.TSE", "TM.US"], 1), "SHEL": (["SHEL.LSE", "SHEL.US"], 2),
    "BP": (["BP.LSE", "BP.US"], 6), "SONY": (["6758.TSE", "SONY.US"], 1),
    "UL": (["ULVR.LSE", "UL.US"], 1), "RIO": (["RIO.LSE", "RIO.US"], 2),
    "SE": (["SE.US"], 1), "NVS": (["NVS.US", "NOVN.SW"], 1), "HSBC": (["HSBA.LSE", "HSBC.US"], 5),
}
# Campos que EODHD aporta (acciones diluidas ponderadas NO están aquí: vienen de EDGAR — regla 5).
EODHD_FIELDS = ("revenue", "net_income", "ocf", "cash", "eps", "capex", "total_debt", "fcf")


def _redact(s):
    return re.sub(r"(api_token=)[^&\s]+", r"\1***", s or "")


def _num(d, keys):
    for k in keys:
        v = (d or {}).get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def extract_eodhd(obj: dict) -> dict:
    """Normaliza el JSON de EODHD a observaciones por período (anual e interino) con procedencia.
    No mezcla conceptos ni bases; acciones diluidas ponderadas NO se extraen de aquí."""
    fin = (obj or {}).get("Financials", {}) or {}
    currency = ((fin.get("Income_Statement", {}) or {}).get("currency_symbol")
                or (obj.get("General", {}) or {}).get("CurrencyCode"))

    def row(irow, brow, crow):
        f = {"revenue": _num(irow, ["totalRevenue"]), "net_income": _num(irow, ["netIncome"]),
             "operating_income": _num(irow, ["operatingIncome"]),
             "ocf": _num(crow, ["totalCashFromOperatingActivities"]),
             "capex": _num(crow, ["capitalExpenditures"]),
             "cash": _num(brow, ["cashAndEquivalents", "cash", "cashAndShortTermInvestments"])}
        td = _num(brow, ["shortLongTermDebtTotal"])
        if td is None:
            lt = _num(brow, ["longTermDebt"]); st = _num(brow, ["shortTermDebt", "shortLongTermDebt"])
            td = (lt or 0) + (st or 0) if (lt is not None or st is not None) else None
        f["total_debt"] = td
        # FCF: sólo si ambos del mismo período; nunca se fabrica con uno faltante (regla 6).
        fcf = _num(crow, ["freeCashFlow"])
        if fcf is None and f["ocf"] is not None and f["capex"] is not None:
            fcf = f["ocf"] - abs(f["capex"])
        f["fcf"] = fcf
        return f

    def latest(sect_i, sect_b, sect_c):
        keys = sorted((sect_i or {}).keys())
        if not keys:
            return None
        k = keys[-1]
        irow = (sect_i or {}).get(k, {})
        end = irow.get("date") or k
        return {"period_end": end, "filing_date": irow.get("filing_date"),
                "fields": row(irow, (sect_b or {}).get(k, {}) or (sect_b or {}).get(end, {}),
                              (sect_c or {}).get(k, {}) or (sect_c or {}).get(end, {}))}

    inc = fin.get("Income_Statement", {}) or {}
    bal = fin.get("Balance_Sheet", {}) or {}
    cf = fin.get("Cash_Flow", {}) or {}
    annual = latest(inc.get("yearly"), bal.get("yearly"), cf.get("yearly"))
    interim = latest(inc.get("quarterly"), bal.get("quarterly"), cf.get("quarterly"))
    # EPS por base (no se mezclan): anual reportado, trimestral, TTM.
    earn = obj.get("Earnings", {}) or {}
    eps_annual_map = {(v.get("date") or k): _num(v, ["epsActual"])
                      for k, v in (earn.get("Annual", {}) or {}).items() if isinstance(v, dict)}
    eps_annual = None
    if annual and eps_annual_map:
        eps_annual = eps_annual_map.get(annual["period_end"]) or (sorted(eps_annual_map.items())[-1][1] if eps_annual_map else None)
    eps_ttm = _num(obj.get("Highlights", {}), ["DilutedEpsTTM"])
    return {"currency": currency, "annual": annual, "interim": interim,
            "eps_annual_reported": eps_annual, "eps_ttm": eps_ttm,
            "eps_basis_ambigua": True}   # EODHD no garantiza reportado-diluido; se marca ambiguo


def eodhd_annual_series_full(obj: dict) -> dict:
    """Serie anual COMPLETA por campo desde el JSON crudo de EODHD (TODOS los años, no sólo el último).
    Aditivo para P1.5.1; no altera extract_eodhd/fetch. Devuelve {'currency': ccy, 'by_field':
    {campo: {period_iso: valor}}}. Signos crudos de EODHD (capex suele venir negativo; el consumidor
    decide abs()). No fabrica: campo ausente → no se emite ese período."""
    fin = (obj or {}).get("Financials", {}) or {}
    inc = (fin.get("Income_Statement", {}) or {}).get("yearly", {}) or {}
    bal = (fin.get("Balance_Sheet", {}) or {}).get("yearly", {}) or {}
    cf = (fin.get("Cash_Flow", {}) or {}).get("yearly", {}) or {}
    ccy = ((fin.get("Income_Statement", {}) or {}).get("currency_symbol")
           or (obj.get("General", {}) or {}).get("CurrencyCode"))
    by: Dict[str, dict] = {}

    def put(field, period, val):
        if val is not None:
            by.setdefault(field, {})[period] = val

    for k, irow in inc.items():
        if not isinstance(irow, dict):
            continue
        period = irow.get("date") or k
        brow = bal.get(k) or bal.get(period) or {}
        crow = cf.get(k) or cf.get(period) or {}
        put("revenue", period, _num(irow, ["totalRevenue"]))
        put("net_income", period, _num(irow, ["netIncome"]))
        put("operating_income", period, _num(irow, ["operatingIncome", "ebit"]))
        put("pretax", period, _num(irow, ["incomeBeforeTax"]))
        put("tax", period, _num(irow, ["incomeTaxExpense"]))
        put("interest", period, _num(irow, ["interestExpense"]))
        put("ocf", period, _num(crow, ["totalCashFromOperatingActivities"]))
        put("capex", period, _num(crow, ["capitalExpenditures"]))
        put("dna", period, _num(crow, ["depreciation", "depreciationAndAmortization"]))
        put("wc_change", period, _num(crow, ["changeInWorkingCapital"]))
        put("sbc", period, _num(crow, ["stockBasedCompensation"]))
        put("cash", period, _num(brow, ["cashAndEquivalents", "cash", "cashAndShortTermInvestments"]))
        td = _num(brow, ["shortLongTermDebtTotal"])
        if td is None:
            lt = _num(brow, ["longTermDebt"]); st = _num(brow, ["shortTermDebt", "shortLongTermDebt"])
            td = (lt or 0) + (st or 0) if (lt is not None or st is not None) else None
        put("total_debt", period, td)
        put("shares", period, _num(brow, ["commonStockSharesOutstanding"]))
    return {"currency": ccy, "by_field": by}


class EodhdFundamentalsConnector:
    """Conector EODHD (COMMERCIAL, gate de costo). Emite anual e interino con procedencia; calidad
    `parcial` (la conciliación oficial la sube o la marca). No emite acciones diluidas ponderadas."""
    spec = ConnectorSpec(
        id="eodhd_fundamentals", kind="fundamentals", provenance="EODHD Fundamentals Data Feed",
        quality=QualityTier.AGGREGATOR, priority=40, cost_tier=CostTier.COMMERCIAL,
        coverage=Coverage(fields=EODHD_FIELDS),
        cache_ttl_s=12 * 3600, rate_limit_per_s=1.0, frequency="trimestral/anual",
        limitations=("EPS puede ser core/ajustado (base ambigua)", "no provee acciones diluidas ponderadas",
                     "total_debt/capex con definición a conciliar"),
        status=ConnectorStatus.OPERATIONAL,
    )

    def __init__(self, api_key: Optional[str] = None, timeout: float = 40.0):
        self._key = api_key or os.getenv("EODHD_API_KEY", "")
        self._timeout = timeout
        self._client = None
        self._cache: Dict[str, dict] = {}

    def available(self) -> bool:
        return bool(self._key)

    def _get(self, symbol):
        import httpx
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout, headers={"User-Agent": "giic-eodhd"})
        url = f"{EODHD_BASE}/fundamentals/{symbol}?api_token={self._key}&fmt=json"
        try:
            r = self._client.get(url)
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:
            return None

    def _resolve(self, ticker):
        syms, adr = EODHD_SYMBOLS.get(ticker.upper(), ([f"{ticker.upper()}.US"], 1))
        for s in syms:
            if s in self._cache:
                obj = self._cache[s]
            else:
                obj = self._get(s)
                self._cache[s] = obj
            if obj and isinstance(obj, dict) and obj.get("Financials"):
                return s, adr, obj
        return None, adr, None

    def annual_series(self, ticker: str) -> dict:
        """Serie anual COMPLETA por campo (P1.5.1). Reutiliza el objeto cacheado de _resolve
        (sin fetch extra si ya se consultó). {} si no hay datos."""
        try:
            _sym, _adr, obj = self._resolve(ticker)
        except Exception:
            obj = None
        if obj is None:
            return {}
        return eodhd_annual_series_full(obj)

    def fetch(self, tickers: List[str], fields: Optional[List[str]] = None,
              context: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, ProvenancedField]]:
        if not self._key:
            return {}
        out: Dict[str, Dict[str, ProvenancedField]] = {}
        for t in tickers:
            sym, adr, obj = self._resolve(t)
            if obj is None:
                continue
            e = extract_eodhd(obj)
            ccy = e["currency"]
            prov = f"EODHD ({sym})"
            fm: Dict[str, ProvenancedField] = {}

            def emit(name, value, period_end, filing, window, method=None, quality="parcial"):
                if value is None:
                    return
                fm[name] = ProvenancedField(value=value, quality=quality, connector_id=self.spec.id,
                                            provenance=prov, as_of=filing, method=method,
                                            period=period_end, currency=ccy, adjusted=None)

            # Interino (observación más fresca) y anual (observación distinta) para los 4 núcleo.
            for label, obs in (("interim", e["interim"]), ("annual", e["annual"])):
                if not obs:
                    continue
                pe, fil = obs["period_end"], obs["filing_date"]
                vals = obs["fields"]
                suffix = "" if label == "interim" else "_annual"
                for core in ("revenue", "net_income", "ocf", "cash"):
                    emit(f"{core}{suffix}", vals.get(core), pe, fil, label,
                         method=f"EODHD {label}; conciliar vs oficial")
                # CAPEX: definición amplia → parcial, método explícito (no confundir con PP&E).
                emit(f"capex{suffix}", vals.get("capex"), pe, fil, label,
                     method="EODHD capitalExpenditures (definición amplia; verificar vs PP&E oficial)")
                # total_debt: composición desconocida → parcial.
                emit(f"total_debt{suffix}", vals.get("total_debt"), pe, fil, label,
                     method="EODHD total debt (composición corriente/no corriente/leases desconocida)")
                # FCF: ya calculado sólo si OCF y CAPEX presentes (regla 6).
                emit(f"fcf{suffix}", vals.get("fcf"), pe, fil, label,
                     method="EODHD FCF = OCF−CAPEX (mismo período); verificar definiciones")
            # EPS: base ambigua (reportado vs core) → NO para valoración; nunca pisa EDGAR.
            if e["annual"]:
                emit("eps_annual", e["eps_annual_reported"], e["annual"]["period_end"],
                     e["annual"]["filing_date"], "annual",
                     method="EODHD EPS anual (base ambigua reportado/core; NO usar para valoración sin confirmar)")
            if e["eps_ttm"] is not None:
                emit("eps_ttm", e["eps_ttm"], (e["interim"] or {}).get("period_end") if e["interim"] else None,
                     (e["interim"] or {}).get("filing_date") if e["interim"] else None, "ttm",
                     method="EODHD DilutedEpsTTM (TTM; base ambigua; NO usar para valoración sin confirmar)")
            if fm:
                out[t] = fm
        return out


def reconcile_quality(eodhd_fields: Dict[str, ProvenancedField], edgar_series: dict,
                      same_currency: bool, tol: float = 0.02) -> Dict[str, ProvenancedField]:
    """Control E3 de consistencia: sube a `verificado` un campo de EODHD que coincide con la fuente
    oficial (EDGAR) en MISMO período y MISMA moneda; lo marca `inconsistente` si difiere de forma
    material. Si la fuente oficial NO tiene ese período (interino fresco), queda `parcial` (usable,
    pendiente de confirmación con IR/regulador) — EDGAR no es el único validador. No convierte
    monedas ni mezcla períodos. Devuelve un NUEVO dict (no muta)."""
    from datetime import datetime

    def pd(s):
        try:
            return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None

    # Campos conciliables (núcleo). EPS/capex/total_debt se dejan parciales por definición/base.
    RECONCILABLE = {"revenue_annual": "revenue", "net_income_annual": "net_income",
                    "ocf_annual": "ocf", "cash_annual": "cash"}
    out = dict(eodhd_fields)
    for fname, pf in eodhd_fields.items():
        edg_key = RECONCILABLE.get(fname)
        if not edg_key:
            continue
        series = (edgar_series or {}).get(edg_key) or {}
        pe = pd(pf.period)
        match = None
        for k, v in series.items():
            d = pd(k)
            if d and pe and abs((d - pe).days) <= 20:
                match = v
                break
        if match is None:
            continue   # EDGAR no tiene ese período → se mantiene parcial (interino fresco)
        if not same_currency or match == 0:
            continue
        diff = abs(pf.value - match) / abs(match)
        # tolera factor de escala de unidades
        scaled = any(abs(pf.value / s - match) / abs(match) <= tol for s in (1000, 1e6))
        if diff <= tol:
            out[fname] = ProvenancedField(pf.value, "verificado", pf.connector_id,
                                          pf.provenance + " ✓EDGAR", pf.as_of, pf.method, pf.period, pf.currency, pf.adjusted)
        elif scaled or diff > 0.05:
            out[fname] = ProvenancedField(pf.value, "inconsistente", pf.connector_id,
                                          pf.provenance + f" ✗EDGAR(dif {diff*100:.0f}%)", pf.as_of, pf.method, pf.period, pf.currency, pf.adjusted)
    return out
