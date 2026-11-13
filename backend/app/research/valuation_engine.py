"""Motor de valoración GIIC v2 — FCFF DCF profesional, data-driven y reproducible.

Reemplaza los modelos fragmentados anteriores (PRODUCTIVE_DCF congelado, FCFF_GIIC calibrado, driver
experimental) por UN motor coherente. Principios:

- DATOS REALES reconciliados de EODHD + SEC EDGAR (sin preferencia dogmática: la fuente más completa por
  campo; discrepancias registradas). Proveniencia por variable.
- FCFF DCF multietapa con doble ancla RECONCILIADA:
    (A) FCFF/WACC:  NOPAT − reinversión(g, ROIC);  descontado al WACC.
    (B) FCFE/Ke:    FCF real (OCF − capex) proyectado;  descontado al coste de equity.
  Reconciliar A vs B es el control central ("FCF histórico vs proyectado"): si divergen, se señala y se
  toma la postura conservadora; nunca se calibra al consenso.
- CONTROLES automáticos antes de publicar; estado de validación explícito.
- Sin tasas arbitrarias: todos los parámetros de mercado están centralizados, fechados y documentados.
- Reproducible: cada resultado trae sus insumos y la fuente de cada variable.

NO confunde D&A, amortización de adquisiciones, capex, OCF y FCF (ver reconcile + normalize).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
import math
from typing import Dict, List, Optional, Tuple

# ----------------------------------------------------------------------------------------------------
# Parámetros de mercado — CENTRALIZADOS, FECHADOS Y DOCUMENTADOS (sin supuestos ocultos).
# Fecha de referencia: 2026-11 (mercado). Fuentes: bonos soberanos 10A, ERP de mercado + riesgo país.
# ----------------------------------------------------------------------------------------------------
PARAMS_DATE = "2026-11"
RF = {"USD": 0.042, "EUR": 0.026, "TWD": 0.015}            # bono soberano 10A por moneda
ERP = {"USD": 0.048, "EUR": 0.055, "TWD": 0.070}           # prima de riesgo de equity (incl. riesgo país)
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "TWD": 0.031}        # spot a USD (fechado 2026-11)
GDP_NOMINAL_LT = {"USD": 0.025, "EUR": 0.022, "TWD": 0.030}  # techo de crecimiento terminal (economía LP)
# Beta apalancada por ticker (betas de mercado publicadas; documentadas, no arbitrarias). Acotadas.
BETA = {"NVDA": 1.70, "META": 1.20, "NFLX": 1.30, "TSM": 1.05, "ASML": 1.30, "PFE": 0.62,
        "AMGN": 0.60, "ADBE": 1.30, "LOW": 1.02, "HD": 1.00, "UPS": 1.00}
BETA_DEFAULT = 1.10
# Horizonte explícito del DCF (años) antes del valor terminal.
YEARS = 10
# Límites de cordura (no calibración; evitan resultados imposibles).
G1_MIN, G1_MAX = 0.0, 0.25           # crecimiento explícito inicial acotado
MARGIN_MIN, MARGIN_MAX = 0.01, 0.75  # margen operativo plausible
TAX_MIN, TAX_MAX = 0.08, 0.35        # tasa efectiva normalizada
ROIC_FLOOR, ROIC_CAP = 0.06, 0.60    # ROIC plausible para economía de reinversión
KD_SPREAD_MAX = 0.05                 # spread máximo de coste de deuda sobre RF
RECONCILE_TOL = 0.35                 # tolerancia de divergencia FCFF vs FCFE (control central)
TERMINAL_WEIGHT_WARN = 0.80          # peso del valor terminal que dispara advertencia
MARGIN_EXTREME = 0.60                # |margen de seguridad| extremo ⇒ señal de REVISIÓN (no objetivo)
MIN_SHARES = 1e5                     # escala de acciones plausible

# BARRERA DE METODOLOGÍA (item 7): "consistente" = pasa controles ARITMÉTICOS; NO es validación económica
# ni predictiva. Esta requiere backtest/track record contra retornos realizados (pendiente). Mientras sea
# False, NINGÚN Fair Value es accionable aunque sea aritméticamente consistente: el FV y los indicadores
# son INFORMATIVOS, no recomendaciones. No se pone True por pasar pruebas aritméticas.
METHODOLOGY_VALIDATED = False


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _last(d: Dict[str, float]) -> Optional[Tuple[str, float]]:
    if not d:
        return None
    k = sorted(d)[-1]
    return k, d[k]


def _recent(d: Dict[str, float], n: int) -> List[Tuple[str, float]]:
    return [(k, d[k]) for k in sorted(d)][-n:]


# ----------------------------------------------------------------------------------------------------
# 1) RECONCILIACIÓN de fuentes (EODHD + EDGAR) por campo, periodo, con proveniencia y discrepancias.
# ----------------------------------------------------------------------------------------------------
# Campos canónicos y su regla de preferencia. 'complete' = la fuente con serie más larga/reciente gana;
# se registra la otra y la discrepancia relativa si ambas existen para el último periodo común.
CANON_FIELDS = ("revenue", "operating_income", "net_income", "tax", "ocf", "capex", "dna",
                "wc_change", "cash", "total_debt", "equity", "invested_capital", "shares",
                "goodwill", "intangibles")


@dataclass
class Reconciled:
    by_field: Dict[str, Dict[str, float]]
    provenance: Dict[str, str]              # campo -> fuente elegida
    discrepancies: Dict[str, float]         # campo -> |EODHD-EDGAR|/|EDGAR| en último periodo común
    currency: Optional[str]
    notes: List[str] = field(default_factory=list)


def reconcile(edgar: dict, eodhd: dict) -> Reconciled:
    """Combina EODHD + EDGAR por campo. Sin preferencia dogmática: gana la fuente con más periodos
    (más completa); si ambas tienen el último periodo común y difieren >10%, se registra la discrepancia."""
    e_by = (edgar or {}).get("by_field", {}) or {}
    o_by = (eodhd or {}).get("by_field", {}) or {}
    out: Dict[str, Dict[str, float]] = {}
    prov: Dict[str, str] = {}
    disc: Dict[str, float] = {}
    notes: List[str] = []
    for f in CANON_FIELDS:
        es, os_ = e_by.get(f, {}) or {}, o_by.get(f, {}) or {}
        if es and os_:
            # discrepancia en el último periodo común
            common = sorted(set(es) & set(os_))
            if common:
                p = common[-1]
                a, b = es.get(p), os_.get(p)
                if a and b and abs(a) > 1:
                    disc[f] = abs(b - a) / abs(a)
            # elegir la más completa (más periodos); empate -> EDGAR (auditada, point-in-time)
            if len(es) >= len(os_):
                out[f] = es; prov[f] = "EDGAR"
            else:
                out[f] = os_; prov[f] = "EODHD"
        elif es:
            out[f] = es; prov[f] = "EDGAR"
        elif os_:
            out[f] = os_; prov[f] = "EODHD"
    # moneda: coincidencia de fuentes; si difieren, se nota
    ce = (edgar or {}).get("currency"); co = (eodhd or {}).get("currency")
    ccy = ce or co
    if ce and co and ce.upper() != co.upper():
        return Reconciled({}, {}, {}, None, ["monedas de fuentes incompatibles"])
    if ce and co and ce != co:
        notes.append(f"discrepancia de moneda EDGAR={ce} EODHD={co}; se usa {ccy}")
    for f, d in disc.items():
        if d > 0.10:
            notes.append(f"discrepancia {f}: {d*100:.0f}% entre fuentes (último periodo común)")
    return Reconciled(by_field=out, provenance=prov, discrepancies=disc, currency=ccy, notes=notes)


# ----------------------------------------------------------------------------------------------------
# 2) NORMALIZACIÓN de insumos (márgenes, tasa, crecimiento, capital, ROIC) — con proveniencia.
# ----------------------------------------------------------------------------------------------------
@dataclass
class NormInputs:
    ticker: str
    ccy: str
    revenue0: float
    op_margin: float             # margen operativo normalizado (mediana reciente)
    tax_eff: float               # tasa efectiva normalizada
    g1: float                    # crecimiento explícito inicial
    gT: float                    # crecimiento terminal (economía)
    invested_capital: float      # capital invertido total (equity + deuda − caja)
    roic: float                  # NOPAT0 / capital invertido
    net_debt: float
    shares: float
    hist_fcf_margin: Optional[float]   # mediana (OCF−capex)/ingresos  (ancla de reconciliación)
    beta: float
    kd_after_tax: float
    w_equity: float
    w_debt: float
    nopat0: float
    prov: Dict[str, str] = field(default_factory=dict)
    discrepancies: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    fcf_real_recent: Optional[float] = None
    roiic_observed: Optional[Dict[str, float]] = None   # {roiic_3y, roiic_all, stable} de balances oficiales
    split_flag: bool = False
    balance_incompleto: bool = False   # caja o deuda ausentes (no se asumieron 0 en silencio)
    ok: bool = True
    fail: Optional[str] = None


def normalize(ticker: str, rec: Reconciled, price_local: Optional[float], adr: float = 1,
              *, price_currency: str = "USD", shares_basis: str = "ordinary",
              base_financials: Optional[dict] = None) -> NormInputs:
    by = rec.by_field
    ccy = (rec.currency or "USD").upper()
    nz = lambda *a, **k: None  # placeholder to satisfy linters

    def fail(msg: str) -> NormInputs:
        return NormInputs(ticker, ccy, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, BETA.get(ticker, BETA_DEFAULT),
                          0, 1, 0, 0, prov=rec.provenance, reasons=[msg], ok=False, fail=msg)

    if not rec.currency or any("incompatibles" in x for x in rec.notes):
        return fail("moneda de reporte ausente/incompatible")
    if price_currency != "USD" or shares_basis != "ordinary":
        return fail("contrato precio/acciones: exige precio USD y acciones ordinarias")
    if not isinstance(adr, (float, int)) or not math.isfinite(adr) or adr <= 0:
        return fail("ratio ADR inválido")
    if price_local is not None and (not math.isfinite(price_local) or price_local <= 0):
        return fail("precio no finito/positivo")
    if any(not math.isfinite(v) for values in by.values() for v in values.values()):
        return fail("dato financiero no finito")
    if ccy not in RF:
        return fail(f"moneda {ccy} sin parámetros de mercado (RF/ERP/FX)")
    rev = by.get("revenue", {})
    lastrev = _last(rev)
    if not lastrev:
        return fail("sin ingresos")
    revenue0 = base_financials["revenue"] if base_financials else lastrev[1]
    if revenue0 <= 0:
        return fail("ingresos no positivos")

    # margen operativo normalizado (mediana de margen EBIT reciente)
    ebit = by.get("operating_income", {})
    margins = [ebit[p] / rev[p] for p in sorted(rev) if p in ebit and rev[p] > 0]
    if not margins and not base_financials:
        return fail("sin margen operativo (EBIT) en ninguna fuente")
    med_margin = base_financials["op_margin"] if base_financials else median(margins[-5:])
    # Pérdida operativa (margen mediano ≤ 0): NO se trunca a +1% (eso convertiría una pérdida en rentabilidad
    # positiva y FV positivo). FCFF DCF requiere NOPAT positivo normalizado ⇒ no valorable por este método.
    if med_margin <= 0:
        return fail(f"margen operativo mediano no positivo ({med_margin*100:.1f}%): pérdida ⇒ no valorable por FCFF")
    if not MARGIN_MIN <= med_margin <= MARGIN_MAX:
        return fail("margen fuera de límites; exige normalización explícita")
    op_margin = med_margin

    # tasa efectiva normalizada (impuesto/pretax si hay; si no, 21% US por defecto documentado)
    tax = by.get("tax", {}); ni = by.get("net_income", {})
    tax_rates = []
    for p in sorted(rev):
        if p in tax and p in ebit and ebit[p] > 0:
            tr = abs(tax[p]) / ebit[p]
            if 0 < tr < 0.6:
                tax_rates.append(tr)
    tax_eff = base_financials["tax_eff"] if base_financials else _clamp(median(tax_rates[-5:]) if tax_rates else 0.21, TAX_MIN, TAX_MAX)

    # crecimiento: CAGR de ingresos ventana reciente (≤6 años), acotado; terminal = economía
    rr = _recent(rev, 6)
    if len(rr) >= 2 and rr[0][1] > 0:
        cagr = (rr[-1][1] / rr[0][1]) ** (1 / (len(rr) - 1)) - 1
    else:
        cagr = 0.03
    g1 = _clamp(cagr, G1_MIN, G1_MAX)
    gT = min(RF[ccy], GDP_NOMINAL_LT[ccy])

    # capital invertido = equity + deuda − caja. Preferir el campo precomputado SOLO si es positivo; si es
    # nulo o no positivo, recalcular equity+deuda−caja. (El origen del IC negativo de TSM era una MEZCLA de
    # monedas en el selector EDGAR —equity USD con caja TWD—, corregida aguas arriba con el filtro de unidad
    # en _pick_pit; esta guarda queda como defensa secundaria, no como explicación del fenómeno.)
    eq = (_last(by.get("equity", {})) or (None, None))[1]
    debt = (_last(by.get("total_debt", {})) or (None, None))[1]
    cash = (_last(by.get("cash", {})) or (None, None))[1]
    ic_field = (_last(by.get("invested_capital", {})) or (None, None))[1]
    if debt is None or cash is None:
        return fail("balance incompleto: caja/deuda ausentes; no se sustituyen por cero")
    ic_calc = (eq + debt - cash) if eq is not None else None
    ic = ic_field if (ic_field is not None and ic_field > 0) else ic_calc
    # Admission above rejects missing cash/debt; observed zero remains a valid value.
    balance_incompleto = (debt is None) or (cash is None)
    net_debt = debt - cash

    # NOPAT y ROIC
    nopat0 = revenue0 * op_margin * (1 - tax_eff)
    roic = _clamp(nopat0 / ic, ROIC_FLOOR, ROIC_CAP) if (ic and ic > 0) else None
    if roic is None:
        return fail("capital invertido no reconstruible (equity/deuda/caja ausentes) ⇒ no valorable")

    # acciones diluidas
    sh = (_last(by.get("shares", {})) or (None, None))[1]
    if not sh or sh < MIN_SHARES:
        return fail(f"acciones no fiables ({sh}) ⇒ escala/unidad inconsistente")

    # ancla de reconciliación: margen FCF histórico (OCF − capex)/ingresos + NIVEL de FCF real reciente.
    # El FCF real reciente es la prueba de realidad del FCFF proyectado (control item 6): si el motor
    # proyecta un FCFF base muy por debajo del FCF que la empresa YA genera, el supuesto de reinversión
    # (g/ROIC con ROIC medio) es económicamente falso para esa empresa (caso NVDA: capex ligero).
    ocf = by.get("ocf", {}); capex = by.get("capex", {})
    fcf_levels = [(p, ocf[p] - abs(capex[p])) for p in sorted(rev) if p in ocf and p in capex and rev[p] > 0]
    fcf_margins = [lvl / rev[p] for (p, lvl) in fcf_levels]
    hist_fcf_margin = median(fcf_margins[-5:]) if fcf_margins else None
    # FCF real reciente: promedio de los 2 últimos años (nivel), ancla de la prueba de realidad.
    fcf_real_recent = (sum(l for _, l in fcf_levels[-2:]) / len(fcf_levels[-2:])) if fcf_levels else None

    # detección de split no ajustado: salto YoY de acciones > 3x (señal de datos precio/acciones dudosos)
    sh_series = [by["shares"][p] for p in sorted(by.get("shares", {})) if by["shares"][p]]
    split_flag = any(b > 0 and (max(a, b) / min(a, b)) > 3.0 for a, b in zip(sh_series, sh_series[1:]))

    # WACC: Ke = RF + β·ERP ; Kd = (interés/deuda)·(1−t) acotado ; pesos por valor de mercado
    beta = _clamp(BETA.get(ticker, BETA_DEFAULT), 0.5, 2.2)
    kd_pre = RF[ccy] + 0.01
    kd_after_tax = _clamp(kd_pre, RF[ccy], RF[ccy] + KD_SPREAD_MAX) * (1 - tax_eff)
    # Capitalización en MONEDA LOCAL, homogénea con la deuda (Codex P0 #2). Para ADRs, price_local es el
    # precio del ADR en USD y `sh` son acciones ORDINARIAS locales: mktcap_local = precio_ADR × (ordinarias/
    # ratio_ADR) ÷ FX(local→USD). Para US (adr=1, ccy USD, fx=1) queda precio×acciones, sin cambio.
    fx_local = FX_TO_USD.get(ccy, 1.0)
    mktcap = (price_local * (sh / adr) / fx_local) if (price_local and sh and fx_local) else None
    if mktcap and mktcap > 0 and debt is not None:
        tot = mktcap + max(debt, 0)
        w_equity = mktcap / tot; w_debt = max(debt, 0) / tot
    else:
        w_equity, w_debt = 0.9, 0.1

    prov = dict(rec.provenance)
    reasons = list(rec.notes)
    n = NormInputs(ticker, ccy, revenue0, op_margin, tax_eff, g1, gT, ic, roic, net_debt, sh,
                   hist_fcf_margin, beta, kd_after_tax, w_equity, w_debt, nopat0, prov=prov,
                   discrepancies=dict(rec.discrepancies), reasons=reasons)
    n.fcf_real_recent = fcf_real_recent
    n.split_flag = split_flag
    n.balance_incompleto = balance_incompleto
    return n


# ----------------------------------------------------------------------------------------------------
# 3) FCFF DCF (doble ancla) + 4) CONTROLES + validación.
# ----------------------------------------------------------------------------------------------------
@dataclass
class DcfResult:
    ticker: str
    ccy: str
    fair_value_local: Optional[float]
    fair_value_usd: Optional[float]
    price_local: Optional[float]
    margin_of_safety: Optional[float]
    wacc: float
    ke: float
    g1: float
    gT: float
    roic: float
    reinvest_rate: float
    fcff0: float
    fcfe0: Optional[float]
    terminal_weight: float
    ev: float
    equity_value: float
    reconc_divergence: Optional[float]
    sensitivity: Dict[str, float]
    scenarios: Dict[str, object]
    method: str
    method_reason: str
    controls: List[Tuple[str, bool, str]]
    validated: bool
    status: str
    reasons: List[str]
    inputs: dict


def _ke(n: NormInputs) -> float:
    return RF[n.ccy] + n.beta * ERP[n.ccy]


def _wacc(n: NormInputs) -> float:
    ke = _ke(n)
    return n.w_equity * ke + n.w_debt * n.kd_after_tax


ROIIC_CEIL = 0.60          # techo conservador sobre el ROIIC inicial (retornos extraordinarios se erosionan)
ROIIC_DEFAULT = 0.15       # supuesto conservador documentado cuando el ROIIC observado no es medible/estable


def _roiic_assumed(n: NormInputs) -> Tuple[float, str]:
    """ROIIC para la economía de reinversión (NO circular; NO fuerza FCFF=FCF).

    Preferido: ROIIC OBSERVADO = ΔNOPAT/ΔCapital invertido (balances oficiales, ventanas plurianuales),
    usado SOLO si es estable (ventanas 3a y plurianual positivas, consistentes), acotado a ≤60%. Si es
    inestable o no medible, se usa un SUPUESTO CONSERVADOR documentado (15%). No se fabrica un ROIIC para
    cerrar una identidad contable."""
    obs = n.roiic_observed or {}
    r3, rall, stable = obs.get("roiic_3y"), obs.get("roiic_all"), obs.get("stable")
    if stable and r3 and rall and r3 > 0 and rall > 0:
        return _clamp((r3 + rall) / 2, 0.08, ROIIC_CEIL), f"observado 3a={r3*100:.0f}% plurianual={rall*100:.0f}% (capado)"
    return ROIIC_DEFAULT, "conservador por defecto (ROIIC observado inestable/no medible)"


def _project_fcff(n: NormInputs, wacc: float, gT: Optional[float] = None,
                  g1: Optional[float] = None, roiic0: Optional[float] = None) -> Tuple[float, float, float, float]:
    """FCFF = NOPAT·(1 − g/ROIIC). Reinversión económica con ROIIC observado (si estable) o supuesto
    conservador, que SE ERONA hacia un ROIIC terminal ≈ 2×WACC (competencia). Devuelve
    (PV explícito, PV terminal, FCFF0, reinvest_rate0). No reconcilia por construcción con el FCF real;
    la comparación FCFF vs FCF real queda como DIAGNÓSTICO (no como validación). g1/roiic0 permiten
    overrides para escenarios (conservador/optimista); por defecto usan los supuestos base."""
    gt = n.gT if gT is None else gT
    g_1 = n.g1 if g1 is None else g1
    r0 = _roiic_assumed(n)[0] if roiic0 is None else roiic0
    roiic_term = _clamp(2 * wacc, 0.10, 0.18)            # ROIIC sostenible terminal (≈2×WACC)
    nopat = n.nopat0
    pv = 0.0
    fcff0 = nopat * (1 - g_1 / r0)
    reinv0 = g_1 / r0
    for t in range(1, YEARS + 1):
        g = g_1 + (gt - g_1) * (t - 1) / max(1, YEARS - 1)
        roiic_t = r0 + (roiic_term - r0) * (t - 1) / max(1, YEARS - 1)   # erosión lineal del ROIIC
        nopat *= (1 + g)
        reinv = g / roiic_t
        fcff = nopat * (1 - reinv)
        pv += fcff / (1 + wacc) ** t
    nopat_term = nopat * (1 + gt)
    fcff_term = nopat_term * (1 - gt / roiic_term)
    tv = fcff_term / (wacc - gt) if wacc > gt else 0.0
    pv_tv = tv / (1 + wacc) ** YEARS
    return pv, pv_tv, fcff0, reinv0


# ── Selección de método de valoración por tipo de negocio (sección 3 del mandato) ───────────────────
#   No se aplica una única fórmula DCF a todo. Se elige el método según la economía del negocio y se
#   DOCUMENTA la razón. Bancos/aseguradoras (RIM/exceso de capital) y REITs (FFO/NAV) requieren modelos
#   dedicados aún NO implementados ⇒ se marcan y se bloquean en vez de forzar un FCFF inapropiado.
SECTOR_METHOD = {
    "banks": ("RIM", False), "insurance": ("RIM", False), "reit": ("FFO/NAV", False),
    "real_estate": ("FFO/NAV", False), "utilities": ("FCFF", True), "energy": ("FCFF", True),
}
# Mapa explícito de tickers del universo a su clase económica (para enrutar el método).
TICKER_SECTOR = {
    "AMT": "reit", "PLD": "reit", "NEE": "utilities", "DUK": "utilities",
    "JPM": "banks", "BAC": "banks", "WFC": "banks", "C": "banks", "GS": "banks", "MS": "banks",
    "BRK.B": "insurance", "AIG": "insurance", "MET": "insurance", "PRU": "insurance",
    "COP": "energy", "EOG": "energy", "FCX": "energy", "XOM": "energy", "CVX": "energy",
}


def _select_method(ticker: str) -> Tuple[str, bool, str]:
    """Devuelve (metodo, apto_para_FCFF, razon). apto=False ⇒ requiere modelo dedicado no implementado."""
    sec = TICKER_SECTOR.get(ticker.upper())
    if sec and sec in SECTOR_METHOD:
        method, fcff_ok = SECTOR_METHOD[sec]
        if not fcff_ok:
            return method, False, f"negocio '{sec}': requiere modelo {method} (no FCFF); dedicado pendiente ⇒ bloqueado"
        return "FCFF", True, f"negocio '{sec}': flujos operativos descontables ⇒ FCFF DCF"
    return "FCFF", True, "empresa operativa (opex/capex/NWC estándar) ⇒ FCFF DCF multi-etapa"


def _project_fcfe(n: NormInputs, ke: float) -> Optional[float]:
    """Ancla de reconciliación: FCF real (margen histórico·ingresos) crecido y descontado a Ke → equity."""
    if n.hist_fcf_margin is None:
        return None
    fcf0 = n.hist_fcf_margin * n.revenue0
    if fcf0 <= 0:
        return None
    pv = 0.0; fcf = fcf0
    for t in range(1, YEARS + 1):
        g = n.g1 + (n.gT - n.g1) * (t - 1) / max(1, YEARS - 1)
        fcf *= (1 + g)
        pv += fcf / (1 + ke) ** t
    tv = fcf * (1 + n.gT) / (ke - n.gT) if ke > n.gT else 0.0
    pv_tv = tv / (1 + ke) ** YEARS
    return pv + pv_tv  # valor de equity (FCFE descontado a Ke)


def value_from_norm(n: NormInputs, price_local: Optional[float], adr: int = 1) -> DcfResult:
    ke = _ke(n); wacc = _wacc(n)
    roiic_asm, roiic_basis = _roiic_assumed(n)
    pv_exp, pv_tv, fcff0, reinv0 = _project_fcff(n, wacc)
    ev = pv_exp + pv_tv
    equity_value = ev - n.net_debt
    terminal_weight = pv_tv / ev if ev > 0 else 1.0
    fcfe_equity = _project_fcfe(n, ke)

    fv_local = equity_value / n.shares if n.shares > 0 else None
    # ADR: FV por acción local × ratio ADR, convertido a USD
    fx = FX_TO_USD.get(n.ccy, 1.0)
    fv_usd = (fv_local * adr * fx) if (fv_local is not None) else None
    px_usd = None
    if price_local is not None:
        # price_local ya viene en USD para ADRs (precio de cotización); el margen se calcula en USD
        px_usd = price_local
    mos = (fv_usd / px_usd - 1) if (fv_usd and px_usd) else None

    # reconciliación FCFF(equity) vs FCFE(equity)
    reconc = None
    if fcfe_equity and equity_value:
        reconc = abs(equity_value - fcfe_equity) / abs(fcfe_equity)

    # sensibilidad: WACC ±1pp, gT ±0.5pp → FV/acción USD
    sens: Dict[str, float] = {}
    for dw, label_w in ((-0.01, "wacc-1"), (0.01, "wacc+1")):
        pe, pt, _, _ = _project_fcff(n, _clamp(wacc + dw, n.gT + 0.01, 0.25))
        evv = pe + pt; eqv = evv - n.net_debt
        if n.shares > 0:
            sens[label_w] = round((eqv / n.shares) * adr * fx, 2)
    for dg, label_g in ((-0.005, "gT-0.5"), (0.005, "gT+0.5")):
        gt2 = _clamp(n.gT + dg, 0.0, wacc - 0.01)
        pe, pt, _, _ = _project_fcff(n, wacc, gT=gt2)
        evv = pe + pt; eqv = evv - n.net_debt
        if n.shares > 0:
            sens[label_g] = round((eqv / n.shares) * adr * fx, 2)

    # ESCENARIOS (sección 5): conservador / base / optimista con paquetes de supuestos DOCUMENTADOS y
    # defendibles (NO se calibran al precio). Base = supuestos fundamentados actuales. El rango y el margen
    # de seguridad se derivan de los tres. Deltas: conservador (WACC +1,5pp, g1 ×0,70, ROIIC ×0,80,
    # gT −0,5pp); optimista (WACC −1,0pp, g1 ×1,15, ROIIC ×1,15 cap 60%, gT +0,3pp).
    def _fv_scn(dw: float, gmul: float, rmul: float, dgt: float) -> Optional[float]:
        w = _clamp(wacc + dw, n.gT + 0.01, 0.30)
        g1s = _clamp(n.g1 * gmul, 0.0, 0.40)
        r0s = _clamp(roiic_asm * rmul, 0.08, ROIIC_CEIL)
        gts = _clamp(n.gT + dgt, 0.0, w - 0.01)
        pe, pt, _, _ = _project_fcff(n, w, gT=gts, g1=g1s, roiic0=r0s)
        eqv = (pe + pt) - n.net_debt
        return round((eqv / n.shares) * adr * fx, 2) if n.shares > 0 else None
    fv_cons = _fv_scn(+0.015, 0.70, 0.80, -0.005)
    fv_opt = _fv_scn(-0.010, 1.15, 1.15, +0.003)
    def _mos(v): return round(v / px_usd - 1, 4) if (v and px_usd) else None
    scenarios = {
        "conservador": {"fv_usd": fv_cons, "margen": _mos(fv_cons),
                        "supuestos": "WACC+1,5pp, g1×0,70, ROIIC×0,80, gT−0,5pp"},
        "base": {"fv_usd": round(fv_usd, 2) if fv_usd else None, "margen": round(mos, 4) if mos is not None else None,
                 "supuestos": f"WACC {wacc*100:.1f}%, g1 {n.g1*100:.1f}%, ROIIC {roiic_asm*100:.0f}%, gT {n.gT*100:.1f}%"},
        "optimista": {"fv_usd": fv_opt, "margen": _mos(fv_opt),
                      "supuestos": "WACC−1,0pp, g1×1,15, ROIIC×1,15 (cap 60%), gT+0,3pp"},
        "rango_usd": [v for v in sorted(x for x in (fv_cons, fv_usd, fv_opt) if x is not None)][:1]
                     + ([round(max(x for x in (fv_cons, fv_usd, fv_opt) if x is not None), 2)] if any(x is not None for x in (fv_cons, fv_usd, fv_opt)) else []),
    }
    method, method_fcff_ok, method_reason = _select_method(n.ticker)

    # CONTROLES
    controls: List[Tuple[str, bool, str]] = []
    controls.append(("metodo_apropiado", method_fcff_ok, f"{method}: {method_reason}"))
    controls.append(("WACC>gT", wacc > n.gT, f"WACC={wacc*100:.1f}% gT={n.gT*100:.1f}%"))
    controls.append(("peso_terminal", terminal_weight <= TERMINAL_WEIGHT_WARN,
                     f"{terminal_weight*100:.0f}% del EV"))
    controls.append(("reinversion_vs_ROIC", n.g1 < n.roic,
                     f"g1={n.g1*100:.1f}% < ROIC={n.roic*100:.1f}% (reinv {reinv0*100:.0f}%)"))
    controls.append(("margen_operativo_plausible", MARGIN_MIN <= n.op_margin <= MARGIN_MAX,
                     f"{n.op_margin*100:.1f}%"))
    controls.append(("acciones_escala", n.shares >= MIN_SHARES, f"{n.shares:.3g}"))
    if reconc is not None:
        controls.append(("FCFF_vs_FCFE", reconc <= RECONCILE_TOL,
                         f"divergencia {reconc*100:.0f}% (tol {RECONCILE_TOL*100:.0f}%)"))
    if mos is not None:
        controls.append(("margen_no_extremo", abs(mos) <= MARGIN_EXTREME,
                         f"margen seguridad {mos*100:.0f}% (|{MARGIN_EXTREME*100:.0f}%| ⇒ revisión)"))
    # CONTROL de reconciliación de fuentes: una divergencia grande entre EODHD y EDGAR en acciones,
    # ingresos o capital indica un problema de datos (p. ej. NFLX con acciones/precio mal escalados) ⇒
    # no se publica como validado; se manda a revisión y se investiga la causa (no se calibra).
    # Nota: 'shares' se excluye del control por ser ruidoso (splits, clases de acciones, promedio
    # ponderado vs fin de periodo producen divergencias legítimas). Se usan ingresos/equity/capital.
    disc = n.discrepancies or {}
    bad_disc = {k: v for k, v in disc.items() if k in ("revenue", "equity", "invested_capital")
                and v is not None and v > 0.25}
    controls.append(("fuentes_consistentes", not bad_disc,
                     ("ok" if not bad_disc else "; ".join(f"{k} difiere {v*100:.0f}%" for k, v in bad_disc.items()))))
    # DIAGNÓSTICO (NO validación): el FCFF proyectado (NOPAT − reinversión por ROIIC asumido) NO se fuerza a
    # igualar el FCF histórico (OCF − CAPEX): son magnitudes distintas (FCFF excluye intereses/no-operativo
    # e incluye ΔNWC). Se reporta la divergencia como señal informativa; solo una brecha EXTREMA (>3×, que
    # sugeriría un error de datos, no economía) manda a revisión. No se usa la coincidencia como prueba.
    if n.fcf_real_recent and n.fcf_real_recent > 0:
        div_fcf = abs(fcff0 - n.fcf_real_recent) / n.fcf_real_recent
        controls.append(("FCFF_proy_vs_FCF_real_diag", div_fcf <= 2.0,
                         f"FCFF proy {fcff0/1e9:.0f}B vs FCF real {n.fcf_real_recent/1e9:.0f}B "
                         f"(dif {div_fcf*100:.0f}%; diagnóstico, no se fuerza igualdad)"))
    # DATOS DUDOSOS (item 5): split de acciones no ajustado en la serie ⇒ precio/acciones en verificación.
    controls.append(("datos_precio_acciones", not n.split_flag,
                     "ok" if not n.split_flag else "posible split no ajustado (precio/acciones en verificación)"))
    # Defense for callers that construct NormInputs directly (entry points reject missing balances).
    controls.append(("balance_completo", not getattr(n, "balance_incompleto", False),
                     "ok" if not getattr(n, "balance_incompleto", False) else "caja o deuda ausente (net_debt asumió 0)"))

    hard_fail = [c for c in controls if not c[1] and c[0] in
                 ("metodo_apropiado", "WACC>gT", "reinversion_vs_ROIC", "margen_operativo_plausible", "acciones_escala")]
    review = [c for c in controls if not c[1] and c[0] in
              ("peso_terminal", "FCFF_vs_FCFE", "margen_no_extremo", "fuentes_consistentes",
               "FCFF_proy_vs_FCF_real_diag", "datos_precio_acciones", "balance_completo")]
    # "consistente" = pasa los controles ARITMÉTICOS (no es validación económica ni predictiva: eso exige
    # backtest/track record, pendiente). Solo lo consistente es accionable; el resto queda bloqueado.
    validated = not hard_fail and not review
    if hard_fail:
        status = "no_valorable"
    elif review:
        status = "en_revision"
    else:
        status = "consistente"
    reasons = list(n.reasons) + [f"{c[0]}: {c[2]}" for c in controls if not c[1]]

    return DcfResult(
        ticker=n.ticker, ccy=n.ccy, fair_value_local=round(fv_local, 2) if fv_local else None,
        fair_value_usd=round(fv_usd, 2) if fv_usd else None, price_local=price_local,
        margin_of_safety=round(mos, 4) if mos is not None else None,
        wacc=round(wacc, 4), ke=round(ke, 4), g1=round(n.g1, 4), gT=round(n.gT, 4), roic=round(n.roic, 4),
        reinvest_rate=round(reinv0, 4), fcff0=round(fcff0, 0),
        fcfe0=round(n.hist_fcf_margin * n.revenue0, 0) if n.hist_fcf_margin else None,
        terminal_weight=round(terminal_weight, 4), ev=round(ev, 0), equity_value=round(equity_value, 0),
        reconc_divergence=round(reconc, 4) if reconc is not None else None, sensitivity=sens,
        scenarios=scenarios, method=method, method_reason=method_reason,
        controls=controls, validated=validated, status=status, reasons=reasons,
        inputs={"revenue0": n.revenue0, "op_margin": n.op_margin, "tax_eff": n.tax_eff,
                "invested_capital": n.invested_capital, "net_debt": n.net_debt, "shares": n.shares,
                "beta": n.beta, "hist_fcf_margin": n.hist_fcf_margin, "w_equity": round(n.w_equity, 3),
                "w_debt": round(n.w_debt, 3), "nopat0": round(n.nopat0, 0), "adr": adr,
                "roic_medio": round(n.roic, 4), "roiic_asumido": round(roiic_asm, 4),
                "roiic_base": roiic_basis, "roiic_observado": n.roiic_observed,
                "fcf_real_recent": n.fcf_real_recent,
                "market_cap_local": price_local * n.shares / (adr * fx) if price_local else None,
                "price_currency": "USD", "shares_basis": "ordinary",
                "w_equity_exact": n.w_equity, "w_debt_exact": n.w_debt,
                "kd_after_tax": n.kd_after_tax, "wacc_exact": wacc,
                "g1_exact": n.g1, "gT_exact": n.gT,
                "fx_to_usd": FX_TO_USD.get(n.ccy, 1.0), "provenance": n.prov, "params_date": PARAMS_DATE})


@dataclass
class EngineOutput:
    ticker: str
    status: str
    result: Optional[DcfResult]
    error: Optional[str] = None


def evaluate(ticker: str, edgar_series: dict, eodhd_series: dict, price_local: Optional[float],
             adr: float = 1, *, price_currency: str = "USD", shares_basis: str = "ordinary") -> EngineOutput:
    """Orquesta: reconciliar → normalizar → valorar+controles. Devuelve resultado reproducible."""
    rec = reconcile(edgar_series, eodhd_series)
    n = normalize(ticker, rec, price_local, adr=adr, price_currency=price_currency, shares_basis=shares_basis)
    if not n.ok:
        return EngineOutput(ticker, "no_valorable", None, error=n.fail)
    r = value_from_norm(n, price_local, adr=adr)
    return EngineOutput(ticker, r.status, r)


def evaluate_ttm(ticker: str, edgar_series: dict, eodhd_series: dict, edgar_rows: list,
                 eodhd_obj: dict, price_local: Optional[float], adr: float = 1,
                 official_ttm: dict = None, *, price_currency: str = "USD",
                 shares_basis: str = "ordinary"):
    """One admitted TTM window for every fallback; normalize only after choosing the base.

    FY-only histories remain available through evaluate(), explicitly labelled FY by callers.
    Missing/invalid TTM at this live entry point invalidates the preceding valuation.
    """
    from app.research.ttm import reconstruct_ttm, valid_quarter_window
    rec = reconcile(edgar_series, eodhd_series)
    ttm_res = official_ttm if official_ttm and official_ttm.get("ttm") else reconstruct_ttm(edgar_rows or [], eodhd_obj or {}, currency=rec.currency)
    if official_ttm and not official_ttm.get("ttm"):
        ttm_res["controles"] = list(ttm_res.get("controles", [])) + list(official_ttm.get("controles", []))
    T = ttm_res.get("ttm", {})
    window = ttm_res.get("ventana", [])
    required = ("revenue", "operating_income", "tax", "pretax", "ocf", "capex")
    missing = [f for f in required if (T.get(f) or {}).get("ttm") is None]
    def reject(msg):
        return EngineOutput(ticker, "no_valorable", None, error=msg), {"fin_ttm": ttm_res.get("fin_ttm"), "controles_ttm": [msg]}
    if not valid_quarter_window(window) or missing:
        return reject("TTM incompleto/no contiguo: " + ",".join(missing))
    if ttm_res.get("currency") not in (None, rec.currency):
        return reject("moneda TTM incompatible")
    vals = {f: T[f]["ttm"] for f in required}
    if any(not math.isfinite(v) for v in vals.values()):
        return reject("TTM no finito")
    if vals["revenue"] <= 0 or vals["operating_income"] <= 0 or vals["pretax"] <= 0:
        return reject("base TTM no positiva; requiere método de recuperación dedicado")
    margin = vals["operating_income"] / vals["revenue"]
    tax = vals["tax"] / vals["pretax"]
    if not MARGIN_MIN <= margin <= MARGIN_MAX or not 0 <= tax <= TAX_MAX:
        return reject("margen/tasa TTM fuera de límites; sin ajustes silenciosos")
    # Annual observations supply only g1/balance. Never rewrite reported history
    # to inject the TTM margin; pass the admitted base as an explicit override.
    n = normalize(ticker, rec, price_local, adr=adr, price_currency=price_currency,
                  shares_basis=shares_basis, base_financials={"revenue": vals["revenue"],
                                                            "op_margin": margin, "tax_eff": tax})
    if not n.ok:
        return reject(n.fail)
    n.revenue0 = vals["revenue"]; n.op_margin = margin; n.tax_eff = tax
    n.kd_after_tax = (RF[n.ccy] + .01) * (1 - tax)  # existing estimate; never labelled observed
    n.nopat0 = n.revenue0 * margin * (1 - tax)
    n.roic = _clamp(n.nopat0 / n.invested_capital, ROIC_FLOOR, ROIC_CAP)
    n.fcf_real_recent = vals["ocf"] - abs(vals["capex"])
    n.hist_fcf_margin = n.fcf_real_recent / n.revenue0
    n.roiic_observed = ttm_res.get("roiic_observed")
    for f, blk in T.items():
        n.prov[f + "_ttm"] = blk.get("fuente")
    r = value_from_norm(n, price_local, adr=adr)
    failed = [c for c in ttm_res.get("controles", []) if not c[1]]
    r.controls.extend(failed)
    if failed:
        r.validated = False
        if r.status != "no_valorable": r.status = "en_revision"
        r.reasons.extend(f"{c[0]}: {c[2]}" for c in failed)
    r.inputs["ttm_window"] = window
    r.inputs["observed_ttm"] = T
    r.inputs["annual_observed"] = rec.by_field
    r.inputs["balance_dates"] = {f: (_last(rec.by_field.get(f, {})) or (None,))[0]
                                  for f in ("cash", "total_debt", "equity", "invested_capital", "shares")}
    r.inputs["shares_measure"] = "ordinary_outstanding" if n.prov.get("shares") == "EODHD" else "diluted_or_outstanding_SEC"
    r.inputs["assumptions"] = {"market_parameters": "estimated/manual", "roiic": r.inputs["roiic_base"],
                               "tax": "observed_TTM", "kd": "estimated_rf_plus_1pp"}
    info = {"campos_ttm_usados": list(required) + ["fcf"], "fin_ttm": window[-1],
            "tiene_ttm_real": True, "ttm": T, "controles_ttm": [c[0] for c in failed]}
    return EngineOutput(ticker, r.status, r), info
