"""Conector SEC EDGAR (data.sec.gov) — fundamentales OFICIALES y GRATIS (US).

Fuente: XBRL company facts de las propias presentaciones a la SEC. Sin clave; exige
un User-Agent con contacto (política de la SEC). Cobertura: emisores estadounidenses.
Lo que no está en las presentaciones NO se inventa: queda en None.

Campos derivados de EDGAR: net_margin, roe, rev_growth_yoy, eps_growth_yoy, fcf_yield
(si hay precio y acciones), market_cap (precio × acciones), pe_ttm (precio / EPS).
No disponibles de forma fiable y gratuita aquí: pe_forward, ev_ebitda, roic => None
(documentado). El parser `parse_companyfacts` es puro y se prueba con fixtures.

E1: la NORMALIZACIÓN (mapas de conceptos + helpers de período/TTM) vive ahora en
`core/normalize.py` y el motor de CALIDAD (plausibilidad, routing por tipo de instrumento)
en `core/quality.py`. Este conector los ORQUESTA; no reimplementa su lógica. Los helpers
públicos (ttm_flow, eps_ttm_from_quarterly_ni, detect_eps_split_mixing) se re-exportan aquí
para compatibilidad con pruebas y consumidores existentes.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from ..core.normalize import (  # noqa: F401  (re-export para pruebas/consumidores)
    ANNUAL_FORMS, US_GAAP_MAP, IFRS_MAP,
    _parse_date, _at, _concept_at, quarterly_3m_points, eps_ttm_from_quarterly_ni,
    detect_eps_split_mixing, _q3m, _sum_last4_3m, _duration_rows, ttm_flow, _ttm_best,
    _latest_dur, _annual_points, _instant_points, _concept, _first_concept,
    _best_annual, _best_instant, _currency_for,
)
from ..core.quality import assess_plausibility, classify_instrument
from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _has_annual_core(facts: dict) -> bool:
    """¿El companyfacts contiene al menos una CIFRA anual de ingresos o beneficio neto?

    Discrimina al emisor REAL de una entidad homónima vacía: no basta que exista la CLAVE del
    concepto (una shell puede declarar NetIncomeLoss sin valores anuales); debe haber un valor
    en formulario anual (10-K/20-F/40-F) o con ventana ~365 días. Universal, sin lógica por ticker."""
    f = facts.get("facts", {}) or {}
    for taxo, cmap, keys in (("us-gaap", US_GAAP_MAP, ("rev", "ni")),
                             ("ifrs-full", IFRS_MAP, ("rev", "ni"))):
        node = f.get(taxo, {})
        for key in keys:
            for concept in cmap.get(key, []):
                units = (node.get(concept) or {}).get("units") or {}
                for vals in units.values():
                    for v in vals:
                        if str(v.get("form", "")).startswith(ANNUAL_FORMS):
                            return True
                        st, en = v.get("start"), v.get("end")
                        if st and en:
                            try:
                                d = (date.fromisoformat(en) - date.fromisoformat(st)).days
                                if 350 <= d <= 380:
                                    return True
                            except Exception:
                                pass
    return False

# ADR: 1 ADR = N acciones ordinarias (hechos verificables, no estimaciones).
ADR_RATIO = {"TSM": 5.0, "ASML": 1.0}

# Centinela: distingue "el caller NO aportó señal de clasificación" (comportamiento legado:
# empresa operativa) de "aportó la señal y es None" (clasificar, y None → indeterminado).
_UNSET = object()


def parse_companyfacts(facts: dict, ticker: str,
                       price: Optional[float] = None,
                       shares: Optional[float] = None,
                       fx_map: Optional[Dict[str, float]] = None,
                       adr_ratio: Optional[float] = None,
                       fallback: Optional[dict] = None,
                       instrument_type=_UNSET,
                       sic=_UNSET,
                       sic_desc=_UNSET) -> Fundamentals:
    """Construye Fundamentals desde company facts de EDGAR. Campos ausentes => None.

    Cubre us-gaap (USD) e ifrs-full (emisores 20-F; divisa detectada, p. ej. EUR/TWD).
    - Ratios adimensionales (margen, ROE, crecimientos) son correctos en cualquier divisa.
    - pe_ttm / fcf_yield / market_cap mezclan precio en USD con cifras en divisa de reporte:
      se convierten con `fx_map` (USD por 1 unidad de divisa) y el `adr_ratio` (acciones
      ordinarias por ADR). Sin FX disponible para una divisa != USD => quedan en None
      (no se fabrican).

    Routing por tipo de instrumento (E1): `instrument_type` de la capa de identidad es la señal
    PRIMARIA; `sic`/`sic_desc` son COMPLEMENTO. Si el caller aporta alguna señal, se clasifica con
    `classify_instrument`: vehículos (ETF/trust) → registro `no_aplica` sin métricas corporativas;
    señal ausente o contradictoria → registro `indeterminado` (NO se asume empresa operativa). Si el
    caller NO aporta señal alguna (ambos sin especificar), el comportamiento es IDÉNTICO al anterior
    (empresa operativa), para no romper llamadas/fixtures existentes.
    """
    # --- Routing por tipo de instrumento (identidad primaria, SIC complementario) ---
    if not (instrument_type is _UNSET and sic is _UNSET):
        it = None if instrument_type is _UNSET else instrument_type
        s = None if sic is _UNSET else sic
        sd = None if sic_desc is _UNSET else sic_desc
        instrument_class, class_note = classify_instrument(it, s, sd)
        if instrument_class == "etf_o_trust":
            return Fundamentals(
                ticker=ticker, currency=None, taxonomy=None,
                data_quality="no_aplica",
                quality_reason=("instrumento no operativo (ETF/trust/fondo): las métricas "
                                "corporativas (EPS, ROE, márgenes, deuda neta) no tienen "
                                "significado económico; analizar como vehículo + subyacente. "
                                + (class_note or "")),
                instrument_class="etf_o_trust", is_sample=False,
            )
        if instrument_class == "indeterminado":
            return Fundamentals(
                ticker=ticker, currency=None, taxonomy=None,
                data_quality="indeterminado",
                quality_reason=("tipo de instrumento no determinado con certeza; no se habilitan "
                                "métricas corporativas sin clasificación. " + (class_note or "")),
                instrument_class="indeterminado", is_sample=False,
            )
    else:
        instrument_class = "empresa_operativa"

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
    wdil = _best_annual(facts, tax, M.get("wdil", []), "shares")   # acciones promedio diluidas
    # Acciones VIGENTES (para market cap): portada dei; si está obsoleta, se marca abajo.
    entity_sh_pts = _best_instant(facts, "dei", ["EntityCommonStockSharesOutstanding"], "shares") or \
        _best_instant(facts, tax, ["CommonStockSharesOutstanding"], "shares")

    def yoy(points):
        if len(points) < 2 or points[-2][1] in (0, None):
            return None
        prev = points[-2][1]
        if prev == 0:
            return None
        return points[-1][1] / prev - 1.0

    # PERÍODO DE REFERENCIA: ancla en el EPS diluido reciente (el dato mejor etiquetado).
    # Todos los flujos se toman EN ESE período (evita mezclar p. ej. NI 2013 con EPS 2025).
    ref = (eps[-1][0] if eps else (eps_usd_series[-1][0] if eps_usd_series
           else (ni[-1][0] if ni else (rev[-1][0] if rev else None))))
    eps_l = _at(eps, ref)
    rev_l = _at(rev, ref)
    eq_l = _at(equity, ref)
    ocf_l = _at(ocf, ref)
    capex_l = _at(capex, ref)
    wdil_l = _at(wdil, ref)

    # Utilidad neta REPORTADA en el período de referencia, con su CONCEPTO fuente (independiente
    # del EPS). Se busca el concepto correcto (no sólo NetIncomeLoss). Si NINGÚN concepto directo
    # existe en ese período (p. ej. MA dejó de etiquetarlo), se RECONSTRUYE = EPS×acciones diluidas
    # — pero ESO NO es una validación independiente y se marca como tal.
    ni_direct, ni_source_concept = _concept_at(facts, tax, M["ni"], ccy, ref)
    ni_reconstructed = False
    ni_l = ni_direct
    ni_period = ref.isoformat() if (ni_direct is not None and ref) else None
    if ni_l is None and eps_l is not None and wdil_l:
        ni_l = eps_l * wdil_l
        ni_reconstructed = True
        ni_source_concept = "reconstruido: EPS_diluido × acciones_ponderadas_diluidas"
        ni_period = ref.isoformat() if ref else None
    as_of = ref.isoformat() if ref else None

    # Consistencia INDEPENDIENTE: SÓLO cuando la utilidad neta es REPORTADA (no reconstruida) y hay
    # acciones ponderadas diluidas → se comparan DOS hechos EDGAR independientes (NI reportado vs
    # EPS×acciones). Si el NI es reconstruido, NO se declara consistencia (sería circular).
    eps_consistent = None
    eps_check_ratio = None
    consistency_independent = False
    if (not ni_reconstructed) and eps_l is not None and wdil_l and ni_direct not in (None, 0):
        eps_check_ratio = (eps_l * wdil_l) / ni_direct
        eps_consistent = abs(eps_check_ratio - 1.0) <= 0.15
        consistency_independent = True

    # Adimensionales (válidos en cualquier divisa) SOLO si numerador/denominador son del mismo período.
    net_margin = (ni_l / rev_l) if (ni_l is not None and rev_l) else None
    roe = (ni_l / eq_l) if (ni_l is not None and eq_l) else None

    # GUARD DE PLAUSIBILIDAD (motor de calidad, core/quality.py): detecta magnitudes imposibles
    # (p. ej. MU FY2026 con NI mayor que ingresos) y saltos interanuales implausibles. Marca el
    # dato para que no se use a ciegas en valoración.
    eg_raw = yoy(eps)
    rg_raw = yoy(rev)
    data_quality, quality_reason = assess_plausibility(ni_l, rev_l, eg_raw, rg_raw)

    # Acciones vigentes para market cap: portada si es reciente; si es obsoleta (>400d que la
    # referencia) se usa el promedio diluido reciente como proxy (marcado); si no, lo que haya.
    shares_source = None
    if shares is None:
        entity_last_end = entity_sh_pts[-1][0] if entity_sh_pts else None
        entity_val = entity_sh_pts[-1][1] if entity_sh_pts else None
        stale_entity = (entity_last_end is not None and ref is not None
                        and (ref - entity_last_end).days > 400)
        if entity_val is not None and not stale_entity:
            shares, shares_source = entity_val, "dei_entity_coverpage"
        elif wdil_l:
            shares, shares_source = wdil_l, "weighted_diluted_proxy(portada_obsoleta)"
        elif entity_val is not None:
            shares, shares_source = entity_val, "dei_entity_coverpage(obsoleta)"
    else:
        shares_source = "provided"

    adr = adr_ratio if adr_ratio else 1.0
    fx = 1.0 if ccy == "USD" else fx_map.get(ccy)      # USD por 1 unidad de la divisa
    # EPS por ADR en USD: preferir la cifra oficial en USD/shares (conv=1); si no, convertir
    # la local con FX. En ambos casos × adr una sola vez (acción ordinaria -> ADR).
    # EPS ANUAL (EDGAR) en USD por ADR.
    if eps_usd_series:
        eps_for_pe, eps_conv = _at(eps_usd_series, ref) or eps_usd_series[-1][1], 1.0
    else:
        eps_for_pe, eps_conv = eps_l, fx
    eps_annual_usd = (eps_for_pe * adr * eps_conv) if (eps_for_pe is not None and eps_conv) else None

    # EPS TTM — Control C (rigor). La identidad rodante (YTD + anual − YTD previo) se aplica a una
    # MAGNITUD ACUMULATIVA: la UTILIDAD NETA. El EPS por acción NO es aditivo si cambia la base de
    # acciones, así que se divide NI_TTM entre acciones ponderadas diluidas RECIENTES (denominador
    # consistente, no "último trimestre a secas") y se CONTRASTA con la identidad por-acción.
    eps_ttm_usd = eps_ttm_method = eps_ttm_window = None
    eps_ttm_denominator = eps_ttm_pershare_check = None
    ni_ttm = _ttm_best(facts, tax, M["ni"], ccy)
    wdil_den = _latest_dur(facts, tax, M.get("wdil", []), "shares")
    if ni_ttm is not None and "YTD" in ni_ttm["window"] and wdil_den and wdil_den[1] > 0:
        conv = 1.0 if ccy == "USD" else (fx or 0)
        if conv:
            eps_ttm_usd = (ni_ttm["ttm"] / wdil_den[1]) * adr * conv or None
            eps_ttm_method = "utilidad_neta_TTM / acciones_diluidas"
            eps_ttm_window = ni_ttm["window"]
            eps_ttm_denominator = wdil_den[1]
            # Contraste con la identidad POR ACCIÓN (sólo informativo): ≈1 si la base de acciones
            # fue comparable; divergencia → cambio de base (recompras/emisión) → prevalece NI/acciones.
            ps = (_ttm_best(facts, tax, M["eps"], "USD/shares") if ccy != "USD" else None) \
                or _ttm_best(facts, tax, M["eps"], f"{ccy}/shares")
            if eps_ttm_usd and ps and "YTD" in ps["window"]:
                ps_is_usd = (ccy == "USD") or bool(_ttm_best(facts, tax, M["eps"], "USD/shares"))
                ps_usd = ps["ttm"] * adr * (1.0 if ps_is_usd else (fx or 1))
                if ps_usd:
                    eps_ttm_pershare_check = round(eps_ttm_usd / ps_usd, 4)
    # E3.1 — TTM = ejercicio cuando el período COMPLETO más reciente es el anual (aún no hay 10-Q
    # posterior al cierre): el TTM coincide POR DEFINICIÓN con el EPS anual diluido reportado. Se usa
    # la cifra OFICIAL reportada (no se re-deriva por NI/acciones) y se marca window="anual" para
    # trazabilidad. Universal: sólo se activa si la identidad rodante (YTD) no produjo un TTM.
    if (eps_ttm_usd is None and eps_annual_usd is not None and ni_ttm is not None
            and ni_ttm["window"].startswith("anual")):
        eps_ttm_usd = eps_annual_usd
        eps_ttm_method = "EPS anual diluido reportado = TTM (sin trimestre posterior al cierre)"
        eps_ttm_window = "anual"
        eps_ttm_denominator = wdil_l
    ttm_vs_annual_ratio = (eps_ttm_usd / eps_annual_usd) if (eps_ttm_usd and eps_annual_usd) else None

    # EPS primario: TTM si está disponible (más actual); si no, el anual. El fallback (abajo) sólo
    # actúa si no hay ninguno de EDGAR.
    if eps_ttm_usd is not None:
        eps_usd, eps_source, eps_basis = eps_ttm_usd, "edgar", "ttm"
    elif eps_annual_usd is not None:
        eps_usd, eps_source, eps_basis = eps_annual_usd, "edgar", "reported_annual"
    else:
        eps_usd = eps_source = eps_basis = None

    # --- FALLBACK MULTIFUENTE CONTROLADO (p. ej. Yahoo) ---
    # SÓLO cuando EDGAR no da el dato; NUNCA sobrescribe un dato oficial; exige coherencia de
    # moneda (USD, el ADR/acción cotiza en USD) y precio; registra fuente/fecha/base; no inventa
    # si el fallback tampoco tiene cobertura. El EPS de Yahoo (trailingEps) es TTM por ADR/acción.
    def _fin(x):
        return isinstance(x, (int, float)) and x == x and x not in (float("inf"), float("-inf"))
    fb = fallback or {}
    fallback_sources: List[str] = []
    if eps_usd is None and price:
        fe, fc = fb.get("eps_ttm"), (fb.get("currency") or "").upper()
        if _fin(fe) and fe > 0 and fc in ("", "USD"):
            eps_usd, eps_source, eps_basis = float(fe), (fb.get("source") or "fallback"), "ttm"
            fallback_sources.append(f"eps_ttm<-{eps_source}@{fb.get('as_of')}")
    if (shares is None or (shares_source and "obsoleta" in shares_source)) and _fin(fb.get("shares")) and fb["shares"] > 0:
        shares = float(fb["shares"])
        shares_source = (fb.get("source") or "fallback") + ":shares"
        fallback_sources.append(f"shares<-{fb.get('source')}@{fb.get('as_of')}")

    adr_count = (shares / adr) if shares else None
    market_cap = (price * adr_count) if (price and adr_count) else None

    # FCF anual y TTM (Control D). FCF = flujo operativo − CAPEX (verificado por etiqueta).
    capex_l = capex_l if capex_l is not None else _at(_best_annual(facts, tax, M.get("capex_alt", []), ccy), ref)
    fcf_annual_ccy = (ocf_l - capex_l) if (ocf_l is not None and capex_l is not None) else None
    ocf_ttm = _ttm_best(facts, tax, M["ocf"], ccy)
    capex_ttm = _ttm_best(facts, tax, M["capex"], ccy) or _ttm_best(facts, tax, M.get("capex_alt", []), ccy)
    # TTM sólo si AMBOS son TTM reales (misma identidad rodante), para no mezclar anual con TTM.
    fcf_ttm_ccy = (ocf_ttm["ttm"] - capex_ttm["ttm"]) if (
        ocf_ttm and capex_ttm and "YTD" in ocf_ttm["window"] and "YTD" in capex_ttm["window"]) else None
    fcf_annual = (fcf_annual_ccy * fx) if (fcf_annual_ccy is not None and fx) else None   # USD
    fcf_ttm = (fcf_ttm_ccy * fx) if (fcf_ttm_ccy is not None and fx) else None             # USD
    # E3.1 — FCF TTM = FCF anual cuando el período COMPLETO más reciente de OCF/CAPEX es el anual
    # (sin trimestre posterior): coincide por definición con el ejercicio. Mismo criterio que EPS.
    if (fcf_ttm is None and fcf_annual is not None and ocf_ttm is not None
            and ocf_ttm["window"].startswith("anual")
            and (capex_ttm is None or capex_ttm["window"].startswith("anual"))):
        fcf_ttm = fcf_annual
    fcf_for_yield = fcf_ttm if fcf_ttm is not None else fcf_annual
    fcf_yield = (fcf_for_yield / market_cap) if (fcf_for_yield is not None and market_cap) else None
    pe_ttm = (price / eps_usd) if (price and eps_usd and eps_usd > 0) else None

    # Deuda (Control D): bruta = corto + largo plazo; neta = bruta − efectivo. En divisa de reporte
    # (ver `currency`); se distingue explícitamente bruta/efectivo/neta y se omite si falta.
    debt_lt = _at(_best_instant(facts, tax, M.get("debt_lt", []), ccy), ref)
    debt_cur = _at(_best_instant(facts, tax, M.get("debt_cur", []), ccy), ref)
    debt_combined = _at(_best_instant(facts, tax, M.get("debt_combined", []), ccy), ref)
    if debt_lt is not None or debt_cur is not None:
        gross_debt = (debt_lt or 0.0) + (debt_cur or 0.0)
    elif debt_combined is not None:
        gross_debt = debt_combined
    else:
        gross_debt = None
    cash_and_sti = _at(_best_instant(facts, tax, M.get("cash", []), ccy), ref)   # efectivo y equivalentes (o combinado)
    net_debt = (gross_debt - cash_and_sti) if (gross_debt is not None and cash_and_sti is not None) else None

    # Márgenes adicionales (mismo período de referencia).
    gp = _at(_best_annual(facts, tax, M.get("gross_profit", []), ccy), ref)
    opi = _at(_best_annual(facts, tax, M.get("op_income", []), ccy), ref)
    gross_margin = (gp / rev_l) if (gp is not None and rev_l) else None
    operating_margin = (opi / rev_l) if (opi is not None and rev_l) else None
    diluted_shares = wdil_l

    return Fundamentals(
        ticker=ticker,
        pe_ttm=pe_ttm,
        eps=eps_usd,                # EPS (USD por ADR): EDGAR anual o fallback TTM (ver eps_source)
        eps_basis=eps_basis,        # reported_annual (EDGAR) | ttm (fallback) | None
        eps_source=eps_source,      # edgar | yahoo:quote | ... (procedencia del EPS)
        fallback_sources=(", ".join(fallback_sources) or None),
        eps_consistent=eps_consistent,
        eps_check_ratio=(round(eps_check_ratio, 4) if eps_check_ratio is not None else None),
        consistency_independent=consistency_independent,
        ni_reconstructed=ni_reconstructed,
        ni_source_concept=ni_source_concept,
        ni_period=ni_period,
        shares_source=shares_source,
        eps_annual=eps_annual_usd,
        eps_ttm=eps_ttm_usd,
        eps_ttm_method=eps_ttm_method,
        eps_ttm_window=eps_ttm_window,
        ttm_vs_annual_ratio=(round(ttm_vs_annual_ratio, 4) if ttm_vs_annual_ratio is not None else None),
        fcf_annual=fcf_annual,
        fcf_ttm=fcf_ttm,
        diluted_shares=diluted_shares,
        gross_debt=gross_debt,
        cash_and_sti=cash_and_sti,
        net_debt=net_debt,
        gross_margin=gross_margin,
        operating_margin=operating_margin,
        eps_ttm_denominator=eps_ttm_denominator,
        eps_ttm_pershare_check=eps_ttm_pershare_check,
        data_quality=data_quality,
        quality_reason=quality_reason,
        instrument_class=instrument_class,
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
        self._cik: Dict[str, int] = {}           # ticker → CIK resuelta (datos reales)
        self._cik_cands: Dict[str, list] = {}    # ticker → candidatas (una sigla puede colisionar)

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
        if self._cik_cands:
            return
        r = self._fetch(TICKERS_URL)
        r.raise_for_status()
        for row in r.json().values():
            self._cik_cands.setdefault(row["ticker"].upper(), []).append(int(row["cik_str"]))
        for k, v in self._cik_cands.items():
            c = sorted(set(v))
            self._cik_cands[k] = c
            if len(c) == 1:                 # sin colisión: resolución inmediata y barata
                self._cik[k] = c[0]

    def _facts_for(self, cik: int) -> Optional[dict]:
        r = self._fetch(FACTS_URL.format(cik=cik))
        if r.status_code != 200:
            return None
        j = r.json()
        f = j.get("facts", {}) or {}
        if not (f.get("us-gaap") or f.get("ifrs-full")):
            return None
        return j

    def _facts(self, ticker: str) -> Optional[dict]:
        """Resuelve ticker→CIK y devuelve companyfacts. Una sigla puede mapear a varias
        entidades en company_tickers.json (p. ej. XOM → Exxon 34088 y una CIK reciente sin
        datos); en ese caso se elige la candidata con series oficiales anuales reales, con
        fallback a la primera con hechos us-gaap/ifrs. La CIK elegida queda cacheada para
        que `_sic` y los consumidores de `self._cik` usen la entidad correcta."""
        self._load_ciks()
        key = ticker.upper()
        if key in self._cik:                 # ya resuelta (sin colisión o colisión previa)
            return self._facts_for(self._cik[key])
        cands = self._cik_cands.get(key)
        if not cands:
            return None
        chosen = chosen_facts = fb = fb_facts = None
        for c in cands:
            j = self._facts_for(c)
            if j is None:
                continue
            if fb is None:
                fb, fb_facts = c, j
            if _has_annual_core(j):          # criterio material: existe dato oficial anual
                chosen, chosen_facts = c, j
                break
        if chosen is None:
            chosen, chosen_facts = fb, fb_facts
        if chosen is None:
            return None
        self._cik[key] = chosen
        return chosen_facts

    def _sic(self, ticker: str):
        """(sic, sicDescription) del emisor desde submissions; (None, None) si no disponible.
        Señal UNIVERSAL para el routing por tipo de instrumento (no por ticker)."""
        self._load_ciks()
        cik = self._cik.get(ticker.upper())
        if cik is None:
            return None, None
        try:
            r = self._fetch(SUBMISSIONS_URL.format(cik=cik))
            if r.status_code != 200:
                return None, None
            j = r.json()
            sic = j.get("sic")
            return (int(sic) if sic not in (None, "") else None), j.get("sicDescription")
        except Exception:
            return None, None

    def get_fundamentals(self, tickers: List[str], prices: Optional[Dict[str, float]] = None,
                         fx_map: Optional[Dict[str, float]] = None,
                         fallback_stats: Optional[Dict[str, dict]] = None,
                         instrument_types: Optional[Dict[str, str]] = None) -> Dict[str, Fundamentals]:
        """`instrument_types` (ticker→tipo de la capa de identidad) es la señal PRIMARIA de routing;
        el SIC de submissions es el COMPLEMENTO. Si el orquestador no aporta identidad, se clasifica
        con el SIC; sólo si faltan ambos se marca `indeterminado` (no se asume operativa)."""
        prices = prices or {}
        fx_map = fx_map or {}
        fallback_stats = fallback_stats or {}
        instrument_types = instrument_types or {}
        out = {}
        for t in tickers:
            facts = self._facts(t)
            if facts is None:
                continue
            sic, sic_desc = self._sic(t)
            it = instrument_types.get(t.upper()) or instrument_types.get(t)
            out[t] = parse_companyfacts(facts, t, price=prices.get(t), fx_map=fx_map,
                                        adr_ratio=ADR_RATIO.get(t.upper(), 1.0),
                                        fallback=fallback_stats.get(t.upper()) or fallback_stats.get(t),
                                        instrument_type=it, sic=sic, sic_desc=sic_desc)
        return out

    # EDGAR no da precios/FX/holdings
    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        return {}

    def get_price_history(self, ticker, start=None, end=None):
        import pandas as pd        # perezoso: el parser puro (parse_companyfacts) no requiere pandas
        return pd.Series(dtype=float)

    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        return []

    def list_universe(self, exchanges=None, limit=None) -> List[Instrument]:
        return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Fundamentales oficiales US (SEC EDGAR); sin pe_forward/ev_ebitda/roic"}
