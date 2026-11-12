"""P2.4 — Driver de valoración DATA-DRIVEN (puro). Construye los insumos del motor FCFF existente
(`value_p16`) a partir de series reportadas (EODHD) por empresa, SIN inventar: si faltan insumos o no
superan los controles financieros, NO produce Fair Value (status 'insuficiente').

Reutiliza el motor P1.6 intacto (no crea modelos nuevos). Respeta moneda/unidades/ADR. Supuestos
derivados de datos (crecimiento, márgenes, reinversión, estructura de capital) en rangos conservadores;
la incertidumbre se refleja como MENOR confianza, no como falsa precisión. Aplica la lección de P1.8.2
(reinversión neta capex−D&A+ΔWC) cuando hay serie suficiente.

Status posibles:
  - 'insuficiente'  : faltan insumos o fallan controles → sin FV (no se inventa).
  - 'experimental'  : corre pero con señales débiles (historia corta, peso terminal alto, etc.).
  - 'confiable'     : corre y supera todos los controles.
El status 'accionable' NO se decide aquí: lo decide la política de valoración (frontend), que combina
este status con tipo de instrumento, margen y confianza.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.research.fcff_forward import (Assump, Base, value_p16, value_path, p16_path,
                                       corrected_reinv_fn, RF, CRP, FX)

SUPPORTED_CCY = set(RF.keys()) & set(CRP.keys()) & set(FX.keys())   # USD/EUR/TWD

# Rangos conservadores para supuestos derivados de datos (clamp = evita extrapolaciones absurdas).
# P2.4.1: g1 y s2c ENDURECIDOS tras la validación de las 8 (evitar extrapolar CAGR histórico y la
# infra-reinversión de s2c alto en empresas intensivas en capital — sesgo P1.8.2). Dirección
# conservadora: reduce sobrevaloración, NUNCA produce compras.
G1_MIN, G1_MAX = -0.10, 0.18
MARGIN_MIN, MARGIN_MAX = -0.20, 0.70
TAX_MIN, TAX_MAX = 0.10, 0.30
S2C_MIN, S2C_MAX = 0.5, 3.0
DV_MAX = 0.60
BETA_DEFAULT, BETA_MIN, BETA_MAX = 1.10, 0.6, 2.0
ROIC_TERMINAL_DEFAULT = 0.14
TERMINAL_WEIGHT_MAX = 0.90        # control: si el valor vive casi todo en la perpetuidad, es frágil
FV_VS_PX_MAX = 1.8               # control: FV > 1.8× precio ⇒ modelo frágil (confianza baja, no apto)
MIN_YEARS_RELIABLE = 4            # años de serie para considerar 'confiable'
# Corrección de reinversión (diagnóstico PFE): reinversión CONSISTENTE con crecimiento y ROIC.
GROWTH_WINDOW = 6                 # ventana reciente (~5 años) para g1 (no CAGR de toda la historia)
DEP_RATE = 0.10                  # vida útil implícita: PP&E ≈ capex/DEP_RATE ⇒ s2c = ventas/PP&E
TERMINAL_G_CAP = 0.025           # crecimiento perpetuo defendible (≤ GDP nominal largo plazo)
ACQ_AMORT_RATIO = 1.5            # D&A ≫ capex ⇒ capital dominado por amortización de adquisiciones:
                                  # el capital invertido NO es reconstruible del capex ⇒ se bloquea


@dataclass
class DriverResult:
    status: str                    # insuficiente | experimental | confiable
    fair_value_usd: Optional[float]
    margin_pct: Optional[float]    # margen de seguridad vs precio (en %)
    confidence: str                # baja | media | alta (refleja incertidumbre, no mercado)
    base: Optional[Base]
    assump: Optional[Assump]
    reasons: List[str]
    inputs: Dict[str, Optional[float]]


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _latest(series: Dict[str, Dict[str, float]], field: str) -> Optional[float]:
    d = series.get(field) or {}
    if not d:
        return None
    k = sorted(d.keys())[-1]
    v = d.get(k)
    return float(v) if v is not None else None


def _periods(series: Dict[str, Dict[str, float]], field: str) -> List[Tuple[str, float]]:
    d = series.get(field) or {}
    return [(k, float(v)) for k, v in sorted(d.items()) if v is not None]


def _cagr(series: Dict[str, Dict[str, float]], field: str) -> Optional[float]:
    pts = _periods(series, field)
    if len(pts) < 2:
        return None
    first, last = pts[0][1], pts[-1][1]
    n = len(pts) - 1
    if first is None or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / n) - 1.0


def _reinv_rates(series: Dict[str, Dict[str, float]], revenue: float) -> Optional[Tuple[float, float, float]]:
    """Tasas capex/D&A/ΔWC sobre ingresos (P1.8.2), promedio reciente. Requiere serie suficiente."""
    capex = _periods(series, "capex"); dna = _periods(series, "dna"); wc = _periods(series, "wc_change")
    if len(capex) < 2 or not revenue:
        return None
    cxr = abs(capex[-1][1]) / revenue
    dnr = (abs(dna[-1][1]) / revenue) if dna else 0.0
    wcr = (wc[-1][1] / revenue) if wc else 0.0
    return cxr, dnr, wcr


def build(ticker: str, ccy: str, px: Optional[float], series: Dict[str, Dict[str, float]],
          adr: int = 1, beta: Optional[float] = None) -> DriverResult:
    """Construye Base+Assump desde la serie reportada y valora con value_p16. No inventa: controla y,
    si no pasa, status 'insuficiente' y sin FV. `series` = by_field de eodhd_annual_series_full."""
    reasons: List[str] = []
    ccy = (ccy or "").upper()
    revenue = _latest(series, "revenue")
    ebit = _latest(series, "operating_income")
    shares = _latest(series, "shares")
    total_debt = _latest(series, "total_debt")
    cash = _latest(series, "cash")
    tax = _latest(series, "tax")
    net_income = _latest(series, "net_income")
    inputs: Dict[str, Optional[float]] = {"revenue": revenue, "ebit": ebit, "shares": shares,
                                          "total_debt": total_debt, "cash": cash, "px": px}

    def fail(msg: str) -> DriverResult:
        reasons.append(msg)
        return DriverResult("insuficiente", None, None, "baja", None, None, reasons, inputs)

    # --- controles de insumos (sin ellos NO se inventa FV) ---
    if ccy not in SUPPORTED_CCY:
        return fail(f"moneda no soportada: {ccy or 'desconocida'}")
    if not revenue or revenue <= 0:
        return fail("sin ingresos reportados positivos")
    if not shares or shares <= 0:
        return fail("sin acciones en circulación")
    if ebit is None:
        return fail("sin EBIT/operating income reportado")
    if not px or px <= 0:
        return fail("sin precio comparable")

    ebit_margin0 = ebit / revenue
    if not (MARGIN_MIN <= ebit_margin0 <= MARGIN_MAX):
        return fail(f"margen EBIT fuera de rango plausible ({ebit_margin0*100:.0f}%)")

    net_debt = (total_debt or 0.0) - (cash or 0.0)
    pretax = net_income / (1 - 0.21) if net_income else None   # proxy si no hay pretax directo
    eff_tax = _clamp((tax / pretax) if (tax and pretax and pretax > 0) else 0.15, TAX_MIN, TAX_MAX)

    # --- supuestos derivados de datos, en rangos conservadores ---
    rev_pts = _periods(series, "revenue")
    n_years = len(rev_pts)
    rev_cagr = _cagr(series, "revenue")   # histórico completo (solo para reporte)
    # crecimiento g1 desde VENTANA RECIENTE (~5 años), no el CAGR de toda la historia (sesgo M&A/COVID)
    win = rev_pts[-GROWTH_WINDOW:]
    g_recent = ((win[-1][1] / win[0][1]) ** (1.0 / (len(win) - 1)) - 1.0) \
        if (len(win) >= 2 and win[0][1] > 0 and win[-1][1] > 0) else (rev_cagr if rev_cagr is not None else 0.05)
    g1 = _clamp(g_recent, G1_MIN, G1_MAX)
    margin_terminal = _clamp(min(ebit_margin0, 0.30), MARGIN_MIN, 0.30)   # fade conservador del margen
    mktcap = px * shares * (FX.get(ccy, 1.0)) * (adr or 1)
    dv = _clamp((net_debt / (net_debt + mktcap)) if (net_debt > 0 and mktcap > 0) else 0.0, 0.0, DV_MAX)
    b = _clamp(beta if beta is not None else BETA_DEFAULT, BETA_MIN, BETA_MAX)
    kd = RF[ccy] + 0.02
    # REINVERSIÓN CONSISTENTE con crecimiento y ROIC (corrige el "crecimiento gratis" del diagnóstico PFE):
    # capital invertido implícito del CAPEX (PP&E ≈ capex/DEP_RATE), s2c = ventas/capital. NO se usa
    # (capex−D&A): la amortización de intangibles ADQUIRIDOS no reduce la reinversión. Donde D&A ≫ capex
    # el capital no es reconstruible del capex ⇒ se marca para BLOQUEO (no se inventa capital).
    rr = _reinv_rates(series, revenue)      # (capex%, dna%, wc%)
    capex_int = rr[0] if rr else None
    dna_int = rr[1] if rr else None
    acq_amort = bool(capex_int and dna_int and capex_int > 0 and (dna_int / capex_int) > ACQ_AMORT_RATIO)
    s2c = _clamp(DEP_RATE / capex_int, S2C_MIN, S2C_MAX) if (capex_int and capex_int > 0) else 2.0
    gT = min(RF[ccy], TERMINAL_G_CAP)       # crecimiento terminal defendible (no = RF)
    roic_implied = ebit_margin0 * (1 - eff_tax) * s2c
    assump = Assump(beta=b, kd=kd, dv=dv, tax_norm=eff_tax, s2c=s2c, g1=g1,
                    margin_terminal=margin_terminal, roic_terminal=ROIC_TERMINAL_DEFAULT, g_terminal=gT, years=10)
    base = Base(ticker=ticker, ccy=ccy, revenue=revenue, ebit_margin0=ebit_margin0,
                net_debt=net_debt, shares=shares, tax_rate=eff_tax, interest=0.0, adr=adr)

    # --- valoración: SIEMPRE reinversión por s2c (ΔRev/s2c, positiva al crecer) con g terminal defendible ---
    try:
        val = value_p16(base, assump)
    except Exception as e:
        return fail(f"motor no converge: {type(e).__name__}")

    fv = val["bridge"]["ps_usd"]
    tw = val["proj"]["terminal_weight"]
    if fv is None or fv <= 0:
        return fail("FV no positivo")
    margin = (fv / px - 1) * 100.0

    # --- clasificación de confianza/status (incertidumbre → menor confianza) ---
    weak: List[str] = []
    extreme = (fv / px) > FV_VS_PX_MAX
    if extreme:
        weak.append(f"FV {fv/px:.1f}× precio: modelo frágil/sobrevalorado (no apto para asignación)")
    if n_years < MIN_YEARS_RELIABLE:
        weak.append(f"serie corta ({n_years} años)")
    if tw > TERMINAL_WEIGHT_MAX:
        weak.append(f"peso terminal alto ({tw*100:.0f}%)")
    if rev_cagr is None:
        weak.append("sin CAGR de ingresos (crecimiento por defecto)")
    if not rr:
        weak.append("sin tasas de reinversión (s2c por defecto)")
    reasons.append(f"g1={g1*100:.1f}% margenT={margin_terminal*100:.0f}% s2c={s2c:.1f} dv={dv*100:.0f}% WACC={val['wacc']['wacc']*100:.1f}%")
    if weak:
        reasons.extend(weak)
        # margen extremo ⇒ confianza baja SIEMPRE (no apto para asignación); otras señales débiles:
        # baja si hay varias, media si es una sola.
        status = "experimental"
        confidence = "baja" if (extreme or len(weak) >= 2) else "media"
    else:
        status, confidence = "confiable", "media"
    # --- BARRERA DE SEGURIDAD (diagnóstico PFE): marca inconsistencias económicas no resueltas que NO
    # deben generar compras/asignaciones. NO cambia el Fair Value; solo señaliza "en revisión". Criterio
    # económico, NO un umbral de diferencia vs consenso.
    reinv_neta = (rr[0] - rr[1]) if rr else None          # capex% − D&A% (solo diagnóstico/reporte)
    adr_fx_review = bool((adr or 1) != 1 or ccy != "USD")  # ruta ADR/divisa del driver NO validada
    review_reasons: List[str] = []
    if acq_amort:
        review_reasons.append(f"capital no reconstruible: D&A {dna_int*100:.1f}% ≫ capex {capex_int*100:.1f}% (ratio {dna_int/capex_int:.1f}×) ⇒ dominado por amortización de adquisiciones; falta capital invertido real")
    if adr_fx_review:
        review_reasons.append(f"ADR/divisa sin resolver (adr={adr}, ccy={ccy}): conversión no validada; usar FV productivo")
    review_block = acq_amort or adr_fx_review
    inputs.update({"g1": g1, "g_recent": g_recent, "rev_cagr_full": rev_cagr, "margin_terminal": margin_terminal,
                   "s2c": s2c, "dv": dv, "gT": gT, "roic_implied": roic_implied,
                   "wacc": val["wacc"]["wacc"], "terminal_weight": tw, "n_years": n_years,
                   "reinv_neta_pct": reinv_neta, "capex_int": capex_int, "dna_int": dna_int,
                   "acq_amort": acq_amort, "adr_fx_review": adr_fx_review, "review_block": review_block,
                   "review_reasons": review_reasons})
    if review_block:
        reasons.append("EN REVISIÓN (barrera): " + "; ".join(review_reasons))
    return DriverResult(status, round(fv, 2), round(margin, 1), confidence, base, assump, reasons, inputs)
