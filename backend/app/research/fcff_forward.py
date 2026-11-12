"""P1.7.2 — Motor FCFF EXPERIMENTAL que consume sendas explícitas (año a año) de crecimiento y
margen, en lugar de la fade mecánica lineal de P1.6. Espejo exacto de la aritmética de P1.6
(`valuation.fcff.ts` / motor de referencia): con la senda mecánica reproduce P1.6 al céntimo
(ancla de paridad/benchmark). NO productivo, NO calibrado a mercado.

Aporta además la ATRIBUCIÓN de la diferencia de FV entre P1.6 y una senda nueva, bloque a bloque
(crecimiento / márgenes / reinversión / WACC) con orden documentado y residual de interacción.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Mercado fechado 2026-11-10 (idéntico a P1.6; SUPUESTO documentado).
RF = {"USD": 0.041, "EUR": 0.026, "TWD": 0.015}
# P2: crecimiento terminal DEFENDIBLE por defecto. Antes, al no fijar g_terminal, la perpetuidad crecía a
# la TASA LIBRE DE RIESGO (4,1% USD) — indefendible (crecimiento perpetuo = RF supera el GDP nominal de
# largo plazo). Se acota a ≤2,5% (mismo tope que el driver experimental y el DCF productivo frontend).
TERMINAL_G_CAP = 0.025
ERP = 0.045
CRP = {"USD": 0.0, "EUR": 0.0, "TWD": 0.0085}
FX = {"USD": 1.0, "EUR": 1.1203, "TWD": 1 / 32.80}
ADR = {"TSM": 5, "ASML": 1}


@dataclass
class Base:
    ticker: str
    ccy: str
    revenue: float
    ebit_margin0: float
    net_debt: float
    shares: float
    tax_rate: float = 0.15
    interest: float = 0.0
    adr: int = 1
    eligibility: str = "eligible"


@dataclass
class Assump:
    beta: float
    kd: float
    dv: float
    tax_norm: float
    s2c: float
    g1: float
    margin_terminal: float
    roic_terminal: float
    g_terminal: Optional[float] = None
    years: int = 10


def wacc_of(a: Assump, ccy: str, dwacc: float = 0.0) -> dict:
    rf = RF[ccy]
    ke = rf + a.beta * (ERP + CRP[ccy])
    w = (1 - a.dv) * ke + a.dv * a.kd * (1 - a.tax_norm) + dwacc
    return {"rf": rf, "ke": ke, "kd": a.kd, "dv": a.dv, "erp": ERP, "crp": CRP[ccy],
            "beta": a.beta, "wacc": w,
            "explain": f"Ke={ke*100:.2f}% = {rf*100:.1f}+{a.beta}·({ERP*100:.1f}+{CRP[ccy]*100:.2f}); "
                       f"WACC=(1-{a.dv})·Ke+{a.dv}·{a.kd*100:.1f}·(1-{a.tax_norm})={w*100:.2f}%"}


def p16_path(g1: float, gT: float, m0: float, mT: float, years: int = 10):
    """Senda MECÁNICA de P1.6: g lineal g1→gT (en años-1 pasos), margen lineal m0→mT (en years pasos).
    Reproduce exactamente P1.6 cuando se pasa al motor."""
    g = [g1 + (gT - g1) * (i - 1) / (years - 1) for i in range(1, years + 1)]
    m = [m0 + (mT - m0) * i / years for i in range(1, years + 1)]
    return g, m


def project_path(base: Base, a: Assump, g: List[float], m: List[float], gT: float,
                 margin_terminal: float, wacc: float, reinv_fn=None) -> dict:
    """FCFF con senda explícita. g[i], m[i] por año (longitud = years). Terminal CONSISTENTE:
    reinv_T = gT/ROIC_T; TV = NOPAT_{T+1}(1−reinv_T)/(WACC−gT). Idéntico a P1.6.
    `reinv_fn(rev, rev_prev)` opcional inyecta la reinversión (corregida capex/D&A); por defecto
    usa ventas/capital (s2c). Única lógica financiera; no se duplica en el frontend."""
    years = a.years
    if len(g) != years or len(m) != years:
        raise ValueError("las sendas g y m deben tener longitud = years")
    if not (wacc > gT):
        raise ValueError("WACC debe exceder gT")
    rows = []
    pv = 0.0
    rev_prev = base.revenue
    for i in range(1, years + 1):
        gi, mi = g[i - 1], m[i - 1]
        rev = rev_prev * (1 + gi)
        nopat = rev * mi * (1 - a.tax_norm)
        reinvest = reinv_fn(rev, rev_prev) if reinv_fn else (rev - rev_prev) / a.s2c
        fcff = nopat - reinvest
        roic = nopat / (rev / a.s2c) if a.s2c else None
        pv += fcff / (1 + wacc) ** i
        rows.append({"i": i, "g": gi, "rev": rev, "m": mi, "nopat": nopat,
                     "reinvest": reinvest, "fcff": fcff, "roic": roic})
        rev_prev = rev
    rev_t1 = rev_prev * (1 + gT)
    nopat_t1 = rev_t1 * margin_terminal * (1 - a.tax_norm)
    rr_t = gT / a.roic_terminal
    fcff_t1 = nopat_t1 * (1 - rr_t)
    tv = fcff_t1 / (wacc - gT)
    pv_tv = tv / (1 + wacc) ** years
    ev = pv + pv_tv
    return {"rows": rows, "pv_fcff": pv, "pv_tv": pv_tv, "ev": ev,
            "terminal_weight": pv_tv / ev, "reinvest_terminal": rr_t}


def equity_bridge(base: Base, ev: float) -> dict:
    equity = ev - base.net_debt
    ps_local = equity / base.shares
    ps_usd = ps_local * FX[base.ccy] * (base.adr or 1)
    return {"ev": ev, "net_debt": base.net_debt, "equity": equity,
            "ps_local": ps_local, "ps_usd": ps_usd}


def value_path(base: Base, a: Assump, g: List[float], m: List[float],
               gT: Optional[float] = None, dwacc: float = 0.0, reinv_fn=None) -> dict:
    gt = (gT if gT is not None else (a.g_terminal if a.g_terminal is not None else min(RF[base.ccy], TERMINAL_G_CAP)))
    w = wacc_of(a, base.ccy, dwacc)
    proj = project_path(base, a, g, m, gt, a.margin_terminal, w["wacc"], reinv_fn=reinv_fn)
    br = equity_bridge(base, proj["ev"])
    return {"wacc": w, "proj": proj, "bridge": br, "gT": gt}


def corrected_reinv_fn(capex_rate: float, dna_rate: float, wc_rate: float):
    """Reinversión neta P1.8.2: (capex−D&A) sobre el nivel de ingresos + ΔWC sobre el crecimiento.
    Conserva reinversión alta en intensivas en capital y permite valores negativos (desinversión)."""
    return lambda rev, rev_prev: (capex_rate - dna_rate) * rev + wc_rate * (rev - rev_prev)


def reverse_g1(base: Base, a: Assump, target_ps_usd: float, gT: Optional[float] = None,
               reinv_fn=None, lo: float = -0.2, hi: float = 1.5) -> Optional[float]:
    """g1 implícito que iguala el FV/acción USD al precio objetivo (fade mecánica P1.6, bisección)."""
    gt = (gT if gT is not None else (a.g_terminal if a.g_terminal is not None else min(RF[base.ccy], TERMINAL_G_CAP)))

    def fv(g1):
        g, m = p16_path(g1, gt, base.ebit_margin0, a.margin_terminal, a.years)
        return value_path(base, a, g, m, gT=gt, reinv_fn=reinv_fn)["bridge"]["ps_usd"]
    flo, fhi = fv(lo) - target_ps_usd, fv(hi) - target_ps_usd
    if flo * fhi > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        fm = fv(mid) - target_ps_usd
        if abs(fm) < 1e-6:
            return mid
        if flo * fm <= 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def value_p16(base: Base, a: Assump, dwacc: float = 0.0, dg1: float = 0.0, dm: float = 0.0,
              dgT: float = 0.0) -> dict:
    """Valoración P1.6 exacta (senda mecánica), con palancas de escenario/sensibilidad."""
    gt = (a.g_terminal if a.g_terminal is not None else min(RF[base.ccy], TERMINAL_G_CAP)) + dgT
    g, m = p16_path(a.g1 * (1 + dg1), gt, base.ebit_margin0, a.margin_terminal + dm, a.years)
    return value_path(base, a, g, m, gT=gt, dwacc=dwacc)


# ---------------------------------------------------------------------------
# Atribución: ΔFV P1.6 → senda nueva, bloque a bloque (orden documentado).
# ---------------------------------------------------------------------------
def attribute_fv(base: Base, a: Assump, g_new: List[float], m_new: List[float],
                 gT_new: Optional[float] = None, dwacc_new: float = 0.0) -> dict:
    """Puente secuencial P1.6 → nueva senda. Orden: crecimiento → márgenes → reinversión(s2c) →
    WACC/terminal. Cada paso revalúa cambiando SOLO ese bloque; el residual es interacción.
    Devuelve contribuciones en FV/acción USD."""
    gt_p16 = a.g_terminal if a.g_terminal is not None else min(RF[base.ccy], TERMINAL_G_CAP)
    g_p16, m_p16 = p16_path(a.g1, gt_p16, base.ebit_margin0, a.margin_terminal, a.years)
    gt_new = gT_new if gT_new is not None else gt_p16

    def fv(g, m, gt, dwacc, s2c):
        aa = Assump(**{**a.__dict__, "s2c": s2c})
        return value_path(base, aa, g, m, gT=gt, dwacc=dwacc)["bridge"]["ps_usd"]

    fv0 = fv(g_p16, m_p16, gt_p16, 0.0, a.s2c)              # P1.6
    fv_g = fv(g_new, m_p16, gt_p16, 0.0, a.s2c)             # + crecimiento
    fv_gm = fv(g_new, m_new, gt_p16, 0.0, a.s2c)            # + márgenes
    fv_gmr = fv_gm                                           # + reinversión (s2c no cambia entre P1.6 y senda: mismo a.s2c)
    fv_final = fv(g_new, m_new, gt_new, dwacc_new, a.s2c)   # + WACC/terminal
    return {
        "fv_p16": round(fv0, 2), "fv_new": round(fv_final, 2),
        "delta_total": round(fv_final - fv0, 2),
        "contrib_growth": round(fv_g - fv0, 2),
        "contrib_margin": round(fv_gm - fv_g, 2),
        "contrib_reinvest": round(fv_gmr - fv_gm, 2),
        "contrib_wacc_terminal": round(fv_final - fv_gmr, 2),
        "order": "growth→margin→reinvest→wacc/terminal (secuencial; residual en wacc/terminal)",
    }
