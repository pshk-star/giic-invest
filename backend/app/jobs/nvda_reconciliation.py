"""Reconciliación cuantitativa NVDA: motor v2 ($81,64) vs escenario ilustrativo (~$252).

Identifica TODA la diferencia matemáticamente, variable por variable, distinguiendo datos de supuestos.
NO ajusta el modelo para llegar a $252. Read-only (no escribe).

Entrega (items 1-4 del encargo):
 1. NVDA año por año: ingresos, EBIT, NOPAT, reinversión, FCFF, FCF real, deuda neta, acciones.
 2. Reproduce el escenario ilustrativo y verifica el ~$252.
 3. Puente cuantitativo ilustrativo -> motor, una variable a la vez (datos vs supuestos).
 4. Construcción del WACC 12,34% (RF, beta, ERP, Kd, pesos, fuentes).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict, List

from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows
from app.research.valuation_engine import (reconcile, normalize, RF, ERP, BETA, FX_TO_USD, YEARS)


def _eodhd(t):
    if not os.getenv("EODHD_API_KEY"):
        return {"currency": None, "by_field": {}}
    try:
        from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
        c = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _a, obj = c._resolve(t)
        return eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
    except Exception:
        return {"currency": None, "by_field": {}}


def dcf_grow_base(base, growths: List[float], disc, gT, net_adj, shares):
    """DCF genérico: crece una caja base por la senda dada, descuenta, terminal Gordon, + ajuste neto."""
    fcf = base; pv = 0.0
    for t, g in enumerate(growths, 1):
        fcf *= (1 + g)
        pv += fcf / (1 + disc) ** t
    tv = fcf * (1 + gT) / (disc - gT)
    pv_tv = tv / (1 + disc) ** len(growths)
    ev = pv + pv_tv
    equity = ev + net_adj
    return {"ev": ev, "pv_exp": pv, "pv_tv": pv_tv, "equity": equity, "ps": equity / shares,
            "term_w": pv_tv / ev}


def run():
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    px = None
    for r in w.select_rows("prices", select="ticker,close,as_of", params={"ticker": "eq.NVDA", "order": "ticker"}):
        px = r.get("close")
    edgar = build_series_from_rows(fetch_edgar_rows(w, "NVDA"))
    eod = _eodhd("NVDA")
    rec = reconcile(edgar, eod)
    n = normalize("NVDA", rec, px, adr=1)
    by = rec.by_field

    # 1) AÑO POR AÑO (datos reconciliados)
    rows = []
    for p in sorted(by.get("revenue", {})):
        rev = by["revenue"][p]; ebit = by.get("operating_income", {}).get(p)
        tax = by.get("tax", {}).get(p); ocf = by.get("ocf", {}).get(p); capex = by.get("capex", {}).get(p)
        dna = by.get("dna", {}).get(p); eq = by.get("equity", {}).get(p); debt = by.get("total_debt", {}).get(p)
        cash = by.get("cash", {}).get(p); sh = by.get("shares", {}).get(p)
        nopat = ebit * (1 - (abs(tax) / ebit if (tax and ebit) else 0.13)) if ebit else None
        fcf = (ocf - abs(capex)) if (ocf is not None and capex is not None) else None
        rows.append({"periodo": p, "revenue": rev, "ebit": ebit, "nopat": nopat, "capex": capex,
                     "dna": dna, "fcf_real": fcf, "equity": eq, "deuda": debt, "cash": cash, "shares": sh,
                     "fcf_margin": (fcf / rev if (fcf and rev) else None)})

    shares = n.shares if n.ok else 24.51e9
    # FCF real reciente (mediana y último) — ancla de datos
    fcfs = [r["fcf_real"] for r in rows[-5:] if r["fcf_real"] is not None]
    fcf_last = fcfs[-1] if fcfs else None
    from statistics import median
    fcf_med = median(fcfs) if fcfs else None

    # 2) ESCENARIO ILUSTRATIVO
    illus = dcf_grow_base(140e9, [0.22]*5 + [0.10]*5, 0.095, 0.03, 30e9, shares)

    # MOTOR (reproducción con las cifras del normalize)
    out = {"precio": px, "shares": shares}
    if n.ok:
        nopat0 = n.nopat0; roic = n.roic; g1 = n.g1; gT = n.gT
        wacc = n.w_equity * (RF[n.ccy] + n.beta * ERP[n.ccy]) + n.w_debt * n.kd_after_tax
        # senda del motor (lineal g1->gT) y FCFF = NOPAT*(1-g/ROIC)
        growths = [g1 + (gT - g1) * (t - 1) / max(1, YEARS - 1) for t in range(1, YEARS + 1)]
        nopat = nopat0; pv = 0.0; proj = []
        for t, g in enumerate(growths, 1):
            nopat *= (1 + g); reinv = g / roic; fcff = nopat * (1 - reinv)
            pv += fcff / (1 + wacc) ** t
            proj.append({"t": t, "g": round(g, 4), "reinv": round(reinv, 4), "nopat": round(nopat, 0), "fcff": round(fcff, 0)})
        roic_term = max(wacc + 0.01, min(roic, 0.60))
        fcff_term = nopat * (1 + gT) * (1 - gT / roic_term)
        tv = fcff_term / (wacc - gT); pv_tv = tv / (1 + wacc) ** YEARS
        ev = pv + pv_tv; equity = ev - n.net_debt
        fcff0 = nopat0 * (1 - g1 / roic)
        out.update({"nopat0": nopat0, "roic": roic, "g1": g1, "gT": gT, "wacc": wacc,
                    "fcff0": fcff0, "net_debt": n.net_debt, "ev": ev, "pv_exp": pv, "pv_tv": pv_tv,
                    "equity": equity, "fv": equity / shares, "term_w": pv_tv / ev, "proj": proj,
                    "beta": n.beta, "ke": RF[n.ccy] + n.beta * ERP[n.ccy], "w_eq": n.w_equity, "w_debt": n.w_debt,
                    "kd_after_tax": n.kd_after_tax, "op_margin": n.op_margin})

        # 3) PUENTE: ilustrativo -> motor, una variable a la vez (acumulativo)
        bridge = []
        base_fv = illus["ps"]; bridge.append({"paso": "0) ilustrativo", "fv": round(base_fv, 2)})
        # 3a) base de caja 140 -> FCF real reciente de NVDA (DATO)
        s1 = dcf_grow_base(fcf_last or 72e9, [0.22]*5 + [0.10]*5, 0.095, 0.03, 30e9, shares)
        bridge.append({"paso": f"1) base caja 140B -> FCF real NVDA {(fcf_last or 72e9)/1e9:.0f}B [DATO]", "fv": round(s1["ps"], 2)})
        # 3b) FCF real -> FCFF del motor (NOPAT*(1-reinv g/ROIC)) = aplica reinversión g/ROIC (SUPUESTO)
        s2 = dcf_grow_base(fcff0, [0.22]*5 + [0.10]*5, 0.095, 0.03, 30e9, shares)
        bridge.append({"paso": f"2) FCF real -> FCFF motor {fcff0/1e9:.0f}B (reinversion g/ROIC) [SUPUESTO]", "fv": round(s2["ps"], 2)})
        # 3c) senda crecimiento 22/10 -> lineal g1->gT (SUPUESTO)
        s3 = dcf_grow_base(fcff0, growths, 0.095, 0.03, 30e9, shares)
        bridge.append({"paso": "3) crecimiento 22/10 -> lineal 25->2.5% [SUPUESTO]", "fv": round(s3["ps"], 2)})
        # 3d) descuento 9.5% -> WACC motor (SUPUESTO/DATO beta)
        s4 = dcf_grow_base(fcff0, growths, wacc, 0.03, 30e9, shares)
        bridge.append({"paso": f"4) descuento 9.5% -> WACC {wacc*100:.2f}% (beta {n.beta}) [SUPUESTO]", "fv": round(s4["ps"], 2)})
        # 3e) terminal 3% -> 2.5% (SUPUESTO)
        s5 = dcf_grow_base(fcff0, growths, wacc, gT, 30e9, shares)
        bridge.append({"paso": "5) terminal 3% -> 2.5% [SUPUESTO]", "fv": round(s5["ps"], 2)})
        # 3f) ajuste neto +30B -> deuda neta real del motor
        s6 = dcf_grow_base(fcff0, growths, wacc, gT, -n.net_debt, shares)
        bridge.append({"paso": f"6) ajuste +30B -> caja/deuda neta real {-n.net_debt/1e9:.0f}B [DATO]", "fv": round(s6["ps"], 2)})
        bridge.append({"paso": "= motor (chequeo)", "fv": round(equity / shares, 2)})
        out["bridge"] = bridge
    out["fcf_real_reciente"] = {"ultimo": fcf_last, "mediana_5a": fcf_med, "serie": fcfs}
    out["ilustrativo"] = {k: round(v, 2) if k == "ps" else round(v / 1e9, 1) for k, v in illus.items() if k != "term_w"}
    out["ilustrativo"]["term_w"] = round(illus["term_w"], 3)
    return {"anio_por_anio": rows, "resumen": out, "fuentes": rec.provenance,
            "discrepancias": rec.discrepancies, "notas": rec.notes}


def main(argv=None):
    print(json.dumps(run(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
