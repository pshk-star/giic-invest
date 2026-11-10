"""P1.7.4 — Reporte reproducible de atribución del impacto del consenso sobre el Fair Value.

Por empresa: pasos A→E, descomposición del EV (años 1-3 / 4-10 / terminal) bajo fade LINEAL vs
REVERSIÓN A LA MEDIA (exhibe el mecanismo), trayectoria a 10 años (g/margen/reinversión/ROIC),
escenarios cons/base/opt, peso terminal y confianza del gate. Consenso EODHD vivo + gate P1.7.3.
NO calibra a mercado. NO toca producción.

Uso: python -m app.research.fv_attribution_report [--no-net]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import List, Optional

from .fcff_forward_report import BASE, ASSUMP, FY_END, PX, RF, _resolve, _trend_list, _reported
from .consensus_admission import admit_consensus
import app.research.fv_attribution as fa


def _scenarios(base, a, gT, explicit_g, explicit_eps, mode="meanrev"):
    """cons/base/opt sobre el escenario de consenso (transición por reversión): haircut de crecimiento
    + sensibilidad WACC/terminal (como P1.6). No se calibra a mercado."""
    def one(dg, dwacc, dgt):
        eg = [g * (1 + dg) for g in explicit_g]
        gc = fa.consensus_growths(eg, a, gT + dgt, mode)
        mc, _ = fa.reconciled_margins(base, a, explicit_eps, gc, len(eg))
        # desplazamiento de WACC vía gT efectivo no aplica; recomputamos con wacc shift directo
        from .fcff_forward import wacc_of, project_path, equity_bridge
        w = wacc_of(a, base.ccy)["wacc"] + dwacc
        proj = project_path(base, a, gc, mc, gT + dgt, a.margin_terminal, w)
        return equity_bridge(base, proj["ev"])["ps_usd"]
    return {"conservador": round(one(-0.25, +0.01, -0.005), 2),
            "base": round(one(0.0, 0.0, 0.0), 2),
            "optimista": round(one(+0.15, -0.01, +0.003), 2)}


def evaluate(t: str, use_net: bool = True, today: Optional[date] = None) -> dict:
    b, a = BASE[t], ASSUMP[t]
    gT = RF[b.ccy]
    today = today or date.today()
    out = {"ticker": t, "ccy": b.ccy, "price": PX[t], "gT": gT}
    obj = _resolve(t) if use_net else None
    if obj is None:
        out["note"] = "sin consenso (sin red/API)"; return out
    ccy = (obj.get("General", {}) or {}).get("CurrencyCode")
    if ccy and ccy != b.ccy:
        out["gate"] = {"admitted": False, "reasons": [f"moneda {ccy}≠{b.ccy}"]}; return out
    gate = admit_consensus(t, _trend_list(obj), _reported(t), today, (obj.get("General", {}) or {}).get("UpdatedAt"))
    out["confianza"] = gate["confidence"]; out["admitido"] = gate["admitted"]
    if not gate["admitted"]:
        out["gate_reasons"] = gate["reasons"]; return out
    cy, ny = gate["cy"], gate.get("ny") or {}
    eg = [cy["rev_growth"]] + ([ny["rev_growth"]] if ny.get("rev_growth") is not None else [])
    ee = [cy["eps"]] + ([ny.get("eps")] if ny else [])
    out["g_explicitos"] = [round(x, 4) for x in eg]
    out["extremo"] = gate["extreme"]
    # atribución A→E
    out["atribucion"] = fa.attribution(b, a, gT, eg, ee, mode="meanrev")["pasos"]
    # descomposición terminal: lineal vs reversión
    dec = {}
    for mode in ("linear", "meanrev"):
        gc = fa.consensus_growths(eg, a, gT, mode)
        mc, _ = fa.reconciled_margins(b, a, ee, gc, len(eg))
        val = fa.value(b, a, gc, mc, gT)
        dec[mode] = {"fv": round(val["ps_usd"], 2), "pv_1_3": round(val["pv_1_3"], 0),
                     "pv_4_10": round(val["pv_4_10"], 0), "pv_terminal": round(val["pv_terminal"], 0),
                     "terminal_weight": round(val["terminal_weight"], 3)}
        if mode == "meanrev":
            out["trayectoria"] = fa.trajectory(val["rows"], b, a)
    out["descomposicion"] = dec
    out["escenarios_consenso_meanrev"] = _scenarios(b, a, gT, eg, ee, "meanrev")
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-net", action="store_true")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    ts = [t.upper() for t in args.tickers] if args.tickers else ["NVDA", "META", "NFLX", "TSM", "ASML"]
    res = {t: evaluate(t, use_net=not args.no_net) for t in ts}
    print(json.dumps({"experimental": True, "no_calibrado_a_mercado": True,
                      "mecanismo": "fade lineal infla años 4-10 y terminal; reversión a la media lo corrige",
                      "resultados": res}, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
