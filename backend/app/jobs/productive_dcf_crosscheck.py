"""P2 — Cross-check del DCF PRODUCTIVO (NVDA/META/NFLX/TSM/ASML) con datos FRESCOS de EDGAR.

Replica la metodología de `frontend/src/core/valuation.ts` (fairValueDCF): FCFE descontado al COSTE DE
EQUITY (Ke=9,5%), base FCF NORMALIZADA (margen FCF medio ≤4 años × ingresos del último ejercicio),
crecimiento = CAGR de ingresos ≤6 años acotado [0,18%], senda lineal g1→gT sobre 10 años, terminal
Gordon con gT=2,5% (defendible). FCF = OCF − |capex| por año (anual, EDGAR point-in-time).

Objetivo: VALIDAR o señalar como obsoletos los FV productivos congelados (PRODUCTIVE_DCF hardcode).
NO escribe nada; no cambia el modelo productivo. Solo compara.
"""
from __future__ import annotations

import json
import os
import sys

from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows

RF, ERP, BETA = 0.04, 0.05, 1.10
DISCOUNT_BASE = RF + BETA * ERP            # 9,5% Ke (idéntico a valuation.ts)
GT_BASE = 0.025                            # crecimiento terminal defendible (idéntico a valuation.ts base)
# FV productivos CONGELADOS actuales (de fundamental_valuation.PRODUCTIVE_DCF) y precios de referencia.
FROZEN = {"NVDA": 90.0, "META": 559.0, "NFLX": 37.0, "TSM": 98.0, "ASML": 720.0}
PX = {"NVDA": 177.20, "META": 610.15, "NFLX": 63.41, "TSM": 375.44, "ASML": 1424.75}


def _run_dcf(base_fcf, shares, years, g1, gT, discount):
    if not (base_fcf > 0 and shares > 0 and discount > gT and years >= 1):
        return None
    pv, fcf = 0.0, base_fcf
    for t in range(1, years + 1):
        g = g1 + (gT - g1) * (t - 1) / max(1, years - 1)
        fcf *= (1 + g)
        pv += fcf / (1 + discount) ** t
    tv = fcf * (1 + gT) / (discount - gT)
    pv_tv = tv / (1 + discount) ** years
    equity = pv + pv_tv
    return {"equity": equity, "per_share": equity / shares, "terminal_weight": pv_tv / equity}


def _fcf_history(by):
    """FCF por año = OCF − |capex|; empareja por periodo. Devuelve lista [(periodo, rev, fcf)] ascendente."""
    ocf = by.get("ocf", {}); capex = by.get("capex", {}); rev = by.get("revenue", {})
    out = []
    for p in sorted(rev):
        o, c = ocf.get(p), capex.get(p)
        if o is not None and c is not None:
            out.append((p, rev[p], o - abs(c)))
    return out


def _normalized_base_fcf(hist):
    rows = [(p, r, f) for (p, r, f) in hist if f is not None and r and r > 0]
    if len(rows) < 3:
        return None, "insuficiente (<3 años)"
    recent = rows[-4:]
    margins = [f / r for (_, r, f) in recent]
    avg = sum(margins) / len(margins)
    last_rev = rows[-1][1]
    return last_rev * avg, f"margen FCF medio {avg*100:.1f}% × ingresos"


def _rev_cagr(hist):
    rows = [(p, r) for (p, r, _) in hist if r and r > 0][-6:]
    if len(rows) < 2:
        return 0.05
    first, last, n = rows[0][1], rows[-1][1], len(rows) - 1
    return min(0.18, max(0.0, (last / first) ** (1 / n) - 1))


def run(tickers):
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    out = {}
    for t in tickers:
        rows = fetch_edgar_rows(w, t)
        s = build_series_from_rows(rows)
        by = s["by_field"]
        hist = _fcf_history(by)
        base_fcf, method = _normalized_base_fcf(hist)
        shares = None
        sh = by.get("shares", {})
        if sh:
            shares = sh[sorted(sh)[-1]]
        net_debt = None
        td = by.get("total_debt", {}); csh = by.get("cash", {})
        if td and csh:
            lastp = sorted(td)[-1]
            net_debt = td[lastp] - (csh.get(lastp) or 0)
        if base_fcf is None or not shares or shares < 1e5:
            out[t] = {"recomputable": False, "motivo": method if base_fcf is None else f"acciones implausibles ({shares})",
                      "fv_congelado": FROZEN.get(t)}
            continue
        g1 = _rev_cagr(hist)
        run_base = _run_dcf(base_fcf, shares, 10, g1, GT_BASE, DISCOUNT_BASE)
        fv_new = round(run_base["per_share"], 2) if run_base else None
        px = PX.get(t); frozen = FROZEN.get(t)
        out[t] = {
            "recomputable": True, "moneda": s["currency"], "ultimo_periodo": hist[-1][0] if hist else None,
            "anios_fcf": len(hist), "base_fcf": round(base_fcf, 0), "metodo_base": method,
            "g1_pct": round(g1 * 100, 1), "gT_pct": GT_BASE * 100, "Ke_pct": DISCOUNT_BASE * 100,
            "shares": shares, "net_debt": net_debt,
            "fv_recomputado_fresco": fv_new, "peso_terminal": round(run_base["terminal_weight"], 3) if run_base else None,
            "fv_congelado_actual": frozen, "precio_ref": px,
            "margen_recomputado_pct": round((fv_new / px - 1) * 100, 1) if (fv_new and px) else None,
            "margen_congelado_pct": round((frozen / px - 1) * 100, 1) if (frozen and px) else None,
            "divergencia_vs_congelado_pct": round((fv_new / frozen - 1) * 100, 1) if (fv_new and frozen) else None,
        }
    return out


def main(argv=None):
    tickers = [t.upper() for t in (argv or sys.argv[1:])] or ["NVDA", "META", "NFLX", "TSM", "ASML"]
    print(json.dumps(run(tickers), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
