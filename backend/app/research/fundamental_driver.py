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
    rev_cagr = _cagr(series, "revenue")
    n_years = len(_periods(series, "revenue"))
    g1 = _clamp(rev_cagr if rev_cagr is not None else 0.05, G1_MIN, G1_MAX)
    margin_terminal = _clamp(min(ebit_margin0, 0.30), MARGIN_MIN, 0.30)   # fade conservador del margen
    mktcap = px * shares * (FX.get(ccy, 1.0)) * (adr or 1)
    dv = _clamp((net_debt / (net_debt + mktcap)) if (net_debt > 0 and mktcap > 0) else 0.0, 0.0, DV_MAX)
    b = _clamp(beta if beta is not None else BETA_DEFAULT, BETA_MIN, BETA_MAX)
    kd = RF[ccy] + 0.02
    # sales-to-capital desde reinversión histórica: s2c ≈ ΔRev / reinversión; si no hay, default 2.0
    rr = _reinv_rates(series, revenue)
    if rr and (rr[0] - rr[1]) > 0:
        s2c = _clamp(1.0 / (rr[0] - rr[1]), S2C_MIN, S2C_MAX)   # 1/(capex%−D&A%)
    else:
        s2c = 2.0
    assump = Assump(beta=b, kd=kd, dv=dv, tax_norm=eff_tax, s2c=s2c, g1=g1,
                    margin_terminal=margin_terminal, roic_terminal=ROIC_TERMINAL_DEFAULT, years=10)
    base = Base(ticker=ticker, ccy=ccy, revenue=revenue, ebit_margin0=ebit_margin0,
                net_debt=net_debt, shares=shares, tax_rate=eff_tax, interest=0.0, adr=adr)

    # --- valoración con el motor existente (reinversión neta corregida si hay serie) ---
    try:
        reinv_fn = corrected_reinv_fn(*rr) if rr else None
        if reinv_fn:
            g, m = p16_path(g1, RF[ccy], ebit_margin0, margin_terminal, assump.years)
            val = value_path(base, assump, g, m, gT=RF[ccy], reinv_fn=reinv_fn)
        else:
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
    inputs.update({"g1": g1, "margin_terminal": margin_terminal, "s2c": s2c, "dv": dv,
                   "wacc": val["wacc"]["wacc"], "terminal_weight": tw, "n_years": n_years})
    return DriverResult(status, round(fv, 2), round(margin, 1), confidence, base, assump, reasons, inputs)
