"""E2 — adaptadores que registran los proveedores EXISTENTES como conectores, SIN cambiar su
lógica interna. Cada adaptador sólo declara su spec y traduce la salida del proveedor a
{campo: ProvenancedField}. El proveedor subyacente se construye de forma PEREZOSA (en el primer
fetch), para que el catálogo/health del registro sea legible sin red ni User-Agent.

Incorporar un proveedor nuevo = añadir un adaptador análogo + registrarlo. No se toca el registro
ni la lógica consumidora. Aquí NO hay conectores específicos por empresa (p. ej. Visa): el routing
y la cobertura son por metadatos.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..types import Fundamentals
from .registry import ConnectorRegistry, ProvenancedField
from .spec import ConnectorSpec, ConnectorStatus, Coverage, CostTier, QualityTier

# Campos fundamentales normalizados que expone el conector EDGAR.
FUND_FIELDS = ("eps", "eps_annual", "eps_ttm", "net_margin", "roe", "gross_margin",
               "operating_margin", "fcf_annual", "fcf_ttm", "net_debt", "gross_debt",
               "diluted_shares")
_EPS_FIELDS = {"eps", "eps_annual", "eps_ttm"}
_RATIO_FIELDS = {"net_margin", "roe", "gross_margin", "operating_margin"}


def fundamentals_to_fields(f: Fundamentals, connector_id: str, provenance: str
                           ) -> Dict[str, ProvenancedField]:
    """Traduce un Fundamentals a campos con calidad+procedencia. Los veredictos de calidad del
    motor (no_aplica/indeterminado/bloqueado) se propagan como TERMINALES autoritativos para que
    un fallback no los sobrescriba."""
    dq = f.data_quality
    out: Dict[str, ProvenancedField] = {}
    values = {k: getattr(f, k, None) for k in FUND_FIELDS}
    ccy = f.currency
    period = f.as_of
    if dq in ("no_aplica", "indeterminado"):
        for k in FUND_FIELDS:
            out[k] = ProvenancedField(None, dq, connector_id, provenance, f.as_of,
                                      method=f.instrument_class)
        return out
    for k, v in values.items():
        if v is None:
            q = "faltante"
        elif dq == "bloqueado":
            q = "bloqueado"
        elif k in _EPS_FIELDS:
            if f.consistency_independent and not f.ni_reconstructed:
                q = "verificado"
            elif f.ni_reconstructed:
                q = "derivado"
            else:
                q = "derivado"
        elif k in _RATIO_FIELDS:
            q = "derivado"
        else:
            q = "parcial"
        if dq == "sospechoso" and q in ("verificado", "derivado"):
            q = "parcial"       # dato marcado: usable pero sin verificación independiente
        method = f.eps_source if k in _EPS_FIELDS else None
        # EPS/acciones: EDGAR usa comparativos reexpresados (filed más reciente) → ajustado por split.
        adjusted = True if k in _EPS_FIELDS or k == "diluted_shares" else None
        out[k] = ProvenancedField(v, q, connector_id, provenance, as_of=f.as_of, method=method,
                                  period=period, currency=ccy, adjusted=adjusted)
    return out


class EdgarFundamentalsConnector:
    """Conector OFICIAL de fundamentales (SEC EDGAR companyfacts + submissions para SIC)."""
    spec = ConnectorSpec(
        id="edgar_companyfacts", kind="fundamentals", provenance="SEC EDGAR (companyfacts)",
        quality=QualityTier.OFFICIAL, priority=10, cost_tier=CostTier.FREE,
        # Cubre CUALQUIER tipo de instrumento: el conector es consciente del routing y, ante un
        # vehículo (ETF/trust), emite el veredicto `no_aplica` explícito (restricción semántica),
        # en vez de quedar fuera de cobertura y dejar el campo sin marcar.
        coverage=Coverage(instrument_types=(), fields=FUND_FIELDS, jurisdictions=()),
        cache_ttl_s=6 * 3600, rate_limit_per_s=8.0, frequency="trimestral/anual (10-Q/10-K/20-F)",
        limitations=("sólo emisores con presentaciones XBRL en EDGAR",
                     "no expone XBRL dimensional (p. ej. EPS por clase accionaria)"),
        status=ConnectorStatus.OPERATIONAL,
    )

    def __init__(self, user_agent: Optional[str] = None):
        self._ua = user_agent
        self._prov = None

    def _provider(self):
        if self._prov is None:
            from ...providers.edgar import EDGARProvider
            self._prov = EDGARProvider(user_agent=self._ua)
        return self._prov

    def fetch(self, tickers: List[str], fields: Optional[List[str]] = None,
              context: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, ProvenancedField]]:
        context = context or {}
        itypes = {t: (context.get(t) or {}).get("instrument_type") for t in tickers}
        itypes = {k: v for k, v in itypes.items() if v}
        funds = self._provider().get_fundamentals(tickers, instrument_types=itypes or None)
        out: Dict[str, Dict[str, ProvenancedField]] = {}
        for t, f in funds.items():
            out[t] = fundamentals_to_fields(f, self.spec.id, self.spec.provenance)
        return out


class YahooStatsConnector:
    """Fallback de estadísticas (EPS TTM / acciones) vía Yahoo. Declarado DOWN: el endpoint público
    v7/quote responde 401 sin autenticación (registrado como límite, no como dato)."""
    spec = ConnectorSpec(
        id="yahoo_stats", kind="fundamentals", provenance="Yahoo Finance (quote)",
        quality=QualityTier.FALLBACK, priority=60, cost_tier=CostTier.FREE,
        coverage=Coverage(fields=("eps_ttm", "diluted_shares")),
        cache_ttl_s=3600, frequency="diaria",
        limitations=("endpoint público v7/quote devuelve 401 sin sesión",),
        status=ConnectorStatus.DOWN,
    )

    def __init__(self):
        self._prov = None

    def _provider(self):
        if self._prov is None:
            from ...providers.yahoo import YahooProvider
            self._prov = YahooProvider()
        return self._prov

    def fetch(self, tickers, fields=None, context=None):
        out: Dict[str, Dict[str, ProvenancedField]] = {}
        try:
            stats = self._provider().get_stats(tickers) or {}
        except Exception:
            return out
        for t, s in stats.items():
            if (s.get("currency") or "USD").upper() != "USD":
                continue
            fm = {}
            if isinstance(s.get("eps_ttm"), (int, float)):
                fm["eps_ttm"] = ProvenancedField(float(s["eps_ttm"]), "parcial", self.spec.id,
                                                 self.spec.provenance, as_of=s.get("as_of"),
                                                 method="trailingEps", currency="USD")
            if isinstance(s.get("shares"), (int, float)):
                fm["diluted_shares"] = ProvenancedField(float(s["shares"]), "parcial", self.spec.id,
                                                        self.spec.provenance, as_of=s.get("as_of"),
                                                        currency="USD")
            if fm:
                out[t] = fm
        return out


class FrankfurterFxConnector:
    """FX oficial (BCE vía Frankfurter). kind='fx'."""
    spec = ConnectorSpec(
        id="frankfurter_fx", kind="fx", provenance="Frankfurter / BCE",
        quality=QualityTier.REGULATORY, priority=10, cost_tier=CostTier.FREE,
        cache_ttl_s=12 * 3600, frequency="diaria (días hábiles BCE)",
        limitations=("sin intradía", "sólo divisas publicadas por el BCE"),
        status=ConnectorStatus.OPERATIONAL,
    )

    def __init__(self):
        self._prov = None

    def _provider(self):
        if self._prov is None:
            from ...providers.frankfurter import FrankfurterProvider
            self._prov = FrankfurterProvider()
        return self._prov

    def fetch(self, tickers, fields=None, context=None):
        # Para FX, `tickers` son códigos de divisa; se consulta USD por 1 unidad.
        try:
            rates = self._provider().get_fx_rates("USD", list(tickers)) or {}
        except Exception:
            rates = {}
        return {c: {"fx_usd_per_unit": ProvenancedField(r, "verificado", self.spec.id,
                                                         self.spec.provenance)}
                for c, r in rates.items()}


class PricesConnector:
    """Precios/cotizaciones (Yahoo primario, respaldo Stooq). kind='prices'."""
    spec = ConnectorSpec(
        id="prices_yahoo_stooq", kind="prices", provenance="Yahoo Finance / Stooq",
        quality=QualityTier.AGGREGATOR, priority=20, cost_tier=CostTier.FREE,
        cache_ttl_s=900, frequency="diaria/intradía",
        limitations=("Stooq bloquea IPs de datacenter", "ajustes por dividendos según fuente"),
        status=ConnectorStatus.OPERATIONAL,
    )

    def __init__(self):
        self._prov = None

    def _provider(self):
        if self._prov is None:
            from ...providers.composite import FallbackPrices
            from ...providers.yahoo import YahooProvider
            from ...providers.stooq import StooqProvider
            self._prov = FallbackPrices([YahooProvider(), StooqProvider()])
        return self._prov

    def fetch(self, tickers, fields=None, context=None):
        out: Dict[str, Dict[str, ProvenancedField]] = {}
        try:
            quotes = self._provider().get_quotes(list(tickers)) or {}
        except Exception:
            return out
        for t, q in quotes.items():
            px = getattr(q, "price", None)
            if px is not None:
                out[t] = {"price": ProvenancedField(px, "parcial", self.spec.id, self.spec.provenance,
                                                    getattr(q, "as_of", None))}
        return out


class EdgarDimensionalConnector:
    """E3.2 — EPS/acciones diluidas POR CLASE desde el XBRL dimensional del último 10-K (fuente
    oficial). On-demand (descarga el 10-K sólo cuando se piden sus campos). NO combina clases ni
    fabrica un EPS consolidado: devuelve un mapa {clase: {value, period_end, unit}} con procedencia
    (accession/URL). Universal: sin lógica por ticker."""
    CONCEPTS = ("EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding")
    spec = ConnectorSpec(
        id="edgar_xbrl_dimensional", kind="fundamentals", provenance="SEC EDGAR 10-K (XBRL dimensional)",
        quality=QualityTier.OFFICIAL, priority=15, cost_tier=CostTier.FREE,
        coverage=Coverage(fields=("eps_diluted_by_class", "diluted_shares_by_class")),
        cache_ttl_s=24 * 3600, rate_limit_per_s=8.0, frequency="anual (10-K)",
        limitations=("requiere XBRL inline en el 10-K", "sólo conceptos con desglose dimensional"),
        status=ConnectorStatus.OPERATIONAL, on_demand=True,
    )
    _FIELD_CONCEPT = {"eps_diluted_by_class": "EarningsPerShareDiluted",
                      "diluted_shares_by_class": "WeightedAverageNumberOfDilutedSharesOutstanding"}

    def __init__(self, user_agent: Optional[str] = None):
        self._ua = user_agent
        self._cik = None

    def _client(self):
        import httpx
        return httpx.Client(timeout=40.0, headers={"User-Agent": self._ua or ""}, follow_redirects=True)

    def _cikmap(self, cli):
        if self._cik is None:
            tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
            self._cik = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}
        return self._cik

    def _latest_10k(self, cli, cik):
        j = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        recent = j.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        for i, fm in enumerate(forms):
            if fm == "10-K":
                acc = recent["accessionNumber"][i].replace("-", "")
                doc = recent["primaryDocument"][i]
                rpt = recent.get("reportDate", [None] * len(forms))[i]
                return (f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}", rpt)
        return (None, None)

    def fetch(self, tickers: List[str], fields: Optional[List[str]] = None,
              context: Optional[Dict[str, dict]] = None) -> Dict[str, Dict[str, ProvenancedField]]:
        from ..xbrl_dimensional import extract_dimensional_facts, latest_annual_by_class
        want = set(fields or self._FIELD_CONCEPT.keys())
        out: Dict[str, Dict[str, ProvenancedField]] = {}
        try:
            cli = self._client()
            cikmap = self._cikmap(cli)
        except Exception:
            return out
        for t in tickers:
            cik = cikmap.get(t.upper())
            if not cik:
                continue
            try:
                url, rpt = self._latest_10k(cli, cik)
                if not url:
                    continue
                html = cli.get(url).text
                facts = extract_dimensional_facts(html, list(self.CONCEPTS))
            except Exception:
                continue
            fm: Dict[str, ProvenancedField] = {}
            for field_name in want:
                concept = self._FIELD_CONCEPT.get(field_name)
                if not concept:
                    continue
                by_class = latest_annual_by_class(facts, concept)
                # SÓLO exponer si hay desglose dimensional (clase); si no, no es trabajo de este conector.
                dim = {k: v for k, v in by_class.items() if k != "__sin_clase__"}
                if not dim:
                    continue
                value = {cls: {"value": f.value, "period_end": f.period_end.isoformat() if f.period_end else None,
                               "unit": f.unit} for cls, f in dim.items()}
                any_end = max((f.period_end for f in dim.values() if f.period_end), default=None)
                unit0 = next(iter(dim.values())).unit
                ccy = unit0.split("/")[0] if unit0 and "/" in unit0 else None
                fm[field_name] = ProvenancedField(
                    value=value, quality="verificado", connector_id=self.spec.id,
                    provenance=f"SEC EDGAR 10-K XBRL dimensional ({url})",
                    as_of=rpt, period=any_end.isoformat() if any_end else None,
                    method="dimensional:StatementClassOfStockAxis (por clase, sin combinar)",
                    currency=ccy)
            if fm:
                out[t] = fm
        return out


def build_default_registry(edgar_user_agent: Optional[str] = None,
                           max_cost: CostTier = CostTier.FREE) -> ConnectorRegistry:
    """Registro por defecto de la arquitectura $0. Los conectores se construyen perezosamente;
    el catálogo/health es legible sin red. `max_cost` por defecto FREE (USD 0); subirlo a TRIAL/
    COMMERCIAL habilita conectores de pago (requiere autorización explícita del operador)."""
    reg = ConnectorRegistry(max_cost=max_cost)
    reg.register(EdgarFundamentalsConnector(user_agent=edgar_user_agent))
    reg.register(EdgarDimensionalConnector(user_agent=edgar_user_agent))
    reg.register(YahooStatsConnector())
    reg.register(FrankfurterFxConnector())
    reg.register(PricesConnector())
    return reg
