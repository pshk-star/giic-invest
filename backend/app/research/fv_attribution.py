"""P1.7.4 — ATRIBUCIÓN y CONTROL del impacto del consenso sobre el Fair Value (puro, testeable).

Responde por qué el consenso mueve tanto el FV, aislando cada bloque y corrigiendo el mecanismo de
extrapolación. NO reconstruye el motor FCFF (reusa fcff_forward); NO calibra a mercado.

Hallazgo de mecanismo: el fade LINEAL desde el crecimiento del año 2 hasta gT en 8 años mantiene
crecimiento excepcional (p.ej. NVDA ~45-60%) durante los años 3-5 SIN fundamento, lo que compone
ingresos ~10-30× e infla desproporcionadamente los FCFF 4-10 y el VALOR TERMINAL. Corrección: usar
estimaciones explícitas por ejercicio donde existan y, para los años sin consenso, una transición por
REVERSIÓN A LA MEDIA (el exceso sobre gT se reduce a la mitad cada año) hacia crecimiento sostenible.
No se imponen topes al FV; se corrige el mecanismo.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .fcff_forward import Assump, Base, wacc_of, project_path, equity_bridge, FX
from .forward_forecast import reconcile_eps_to_ebit, _coherent_margin

MEANREV_HALFLIFE = 0.5   # el exceso de crecimiento sobre gT se reduce a la mitad cada año (reversión)


def giic_growths(a: Assump, gT: float) -> List[float]:
    y = a.years
    return [a.g1 + (gT - a.g1) * (i - 1) / (y - 1) for i in range(1, y + 1)]


def giic_margins(base: Base, a: Assump) -> List[float]:
    y = a.years
    return [base.ebit_margin0 + (a.margin_terminal - base.ebit_margin0) * i / y for i in range(1, y + 1)]


def transition_tail(g_last: float, gT: float, k: int, years: int, mode: str = "meanrev") -> List[float]:
    """Crecimiento para años k+1..years, desde g_last hacia gT.
    - 'meanrev': g = gT + (g_last−gT)·0.5^(t)  (reversión a la media; exceso se halva cada año).
    - 'linear' : fade lineal (mecanismo ANTIGUO; se conserva para exhibir la diferencia)."""
    out = []
    for i in range(k + 1, years + 1):
        t = i - k
        if mode == "linear":
            g = g_last + (gT - g_last) * t / (years - k)
        else:
            g = gT + (g_last - gT) * (MEANREV_HALFLIFE ** t)
        out.append(g)
    return out


def consensus_growths(explicit: List[float], a: Assump, gT: float, mode: str = "meanrev") -> List[float]:
    """Años 1..K con estimaciones explícitas; K+1..N por transición. Sin extrapolar la tasa alta."""
    k = len(explicit)
    return list(explicit) + transition_tail(explicit[-1], gT, k, a.years, mode)


def override_front(giic_g: List[float], explicit: List[float], k: int) -> List[float]:
    """Sustituye SOLO los primeros k años por consenso (resto queda GIIC). Aísla el efecto por año."""
    k = min(k, len(explicit))
    return list(explicit[:k]) + list(giic_g[k:])


def reconciled_margins(base: Base, a: Assump, explicit_eps: List[Optional[float]],
                       growths: List[float], k: int) -> Tuple[List[float], List[bool]]:
    """Márgenes EBIT para años 1..k reconciliados del EPS de consenso (acotados a banda); resto GIIC.
    Devuelve (márgenes, flags_coherencia). revenue_i = reportado·∏(1+g)."""
    gm = giic_margins(base, a)
    out = list(gm)
    flags: List[bool] = []
    rev = base.revenue
    for i in range(a.years):
        rev *= (1 + growths[i])
        if i < k and i < len(explicit_eps) and explicit_eps[i]:
            rec = reconcile_eps_to_ebit(explicit_eps[i], base.shares, rev, base.interest, base.tax_rate)
            m, ok = _coherent_margin(rec["margin"] if rec else None, base.ebit_margin0)
            out[i] = m
            flags.append(bool(ok))
    return out, flags


def pv_decomposition(base: Base, a: Assump, g: List[float], m: List[float], gT: float,
                     wacc: float) -> dict:
    """Descompone el EV en PV(FCFF años 1-3), PV(FCFF años 4-10) y PV(terminal)."""
    proj = project_path(base, a, g, m, gT, a.margin_terminal, wacc)
    pv_1_3 = sum(r["fcff"] / (1 + wacc) ** r["i"] for r in proj["rows"] if r["i"] <= 3)
    pv_4_10 = sum(r["fcff"] / (1 + wacc) ** r["i"] for r in proj["rows"] if r["i"] >= 4)
    return {"pv_1_3": pv_1_3, "pv_4_10": pv_4_10, "pv_terminal": proj["pv_tv"],
            "ev": proj["ev"], "terminal_weight": proj["terminal_weight"],
            "rows": proj["rows"], "reinvest_terminal": proj["reinvest_terminal"]}


def value(base: Base, a: Assump, g: List[float], m: List[float], gT: float) -> dict:
    w = wacc_of(a, base.ccy)["wacc"]
    dec = pv_decomposition(base, a, g, m, gT, w)
    br = equity_bridge(base, dec["ev"])
    return {"ps_usd": br["ps_usd"], "ps_local": br["ps_local"], "wacc": w, **dec}


def trajectory(dec_rows: List[dict], base: Base, a: Assump) -> List[dict]:
    """Tabla a 10 años: g, margen, reinversión, FCFF, ROIC (para años 1,3,5,7,10)."""
    out = []
    for r in dec_rows:
        if r["i"] in (1, 3, 5, 7, 10):
            out.append({"i": r["i"], "g_pct": round(r["g"] * 100, 1), "margin_pct": round(r["m"] * 100, 1),
                        "reinvest": round(r["reinvest"], 0), "fcff": round(r["fcff"], 0),
                        "roic_pct": round(r["roic"] * 100, 0) if r["roic"] else None})
    return out


def attribution(base: Base, a: Assump, gT: float, explicit_g: List[float],
                explicit_eps: List[Optional[float]], mode: str = "meanrev") -> dict:
    """Pasos A→E con FV y Δ. Aísla cada bloque. E = combinado (ramp consenso→GIIC)."""
    gi = giic_growths(a, gT)
    gm = giic_margins(base, a)
    K = len(explicit_g)

    def fv(g, m):
        return value(base, a, g, m, gT)["ps_usd"]

    fvA = fv(gi, gm)                                             # A: GIIC original
    gB = override_front(gi, explicit_g, 1)
    fvB = fv(gB, gm)                                             # B: solo año 1
    gC = override_front(gi, explicit_g, min(3, K))              # C: años 1..min(3,K)
    fvC = fv(gC, gm)
    mC, flags = reconciled_margins(base, a, explicit_eps, gC, min(3, K))
    fvD = fv(gC, mC)                                            # D: C + márgenes prospectivos
    # E: combinado = consenso con transición (reversión) mezclado con GIIC por ramp
    gcons = consensus_growths(explicit_g, a, gT, mode)
    w = [max(0.0, 0.70 - 0.175 * i) for i in range(a.years)]
    gE = [w[i] * gcons[i] + (1 - w[i]) * gi[i] for i in range(a.years)]
    mcons, _ = reconciled_margins(base, a, explicit_eps, gcons, K)
    mE = [w[i] * mcons[i] + (1 - w[i]) * gm[i] for i in range(a.years)]
    fvE = fv(gE, mE)

    def step(name, v, prev):
        return {"paso": name, "fv": round(v, 2),
                "delta_abs": round(v - prev, 2),
                "delta_pct": round((v / prev - 1) * 100, 1) if prev else None}
    return {
        "pasos": [step("A_GIIC", fvA, fvA), step("B_consenso_año1", fvB, fvA),
                  step("C_consenso_plurianual", fvC, fvB), step("D_mas_margenes", fvD, fvC),
                  step("E_combinado", fvE, fvD)],
        "K_años_explicitos": K, "margen_coherente": flags,
        "scenario_growths": {"GIIC": [round(x, 4) for x in gi],
                             "consenso_meanrev": [round(x, 4) for x in gcons],
                             "combinado": [round(x, 4) for x in gE]},
    }
