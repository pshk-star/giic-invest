"""P2.4.1 — Validación FOCALIZADA de valoraciones nuevas (solo lectura, datos reales).

Corre el driver sobre una lista de tickers e imprime los SUPUESTOS y RESULTADOS completos más chequeos
de anomalías (WACC, crecimiento, márgenes, reinversión, terminal, moneda, deuda). Clasifica cada
valoración en 'apta_para_asignacion' vs 'solo_calculada'. NO ajusta supuestos para producir compras; es
un control de calidad previo a usar las valoraciones en la asignación (P2.5).

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY + EODHD_API_KEY.
     python -m app.jobs.valuation_validate ADBE AMGN AMT EOG HD LOW PFE UPS
"""
from __future__ import annotations

import json
import os
import sys
from typing import List

from app.research.fundamental_driver import build
from app.research.fcff_forward import RF

DEFAULT = ["ADBE", "AMGN", "AMT", "EOG", "HD", "LOW", "PFE", "UPS"]


def anomalies(ccy: str, inp: dict, base, assump) -> List[dict]:
    """Devuelve lista de {flag, sev, detalle}. sev: alta (bloquea asignación) | media | info."""
    out: List[dict] = []
    g1 = inp.get("g1"); mt = inp.get("margin_terminal"); s2c = inp.get("s2c"); dv = inp.get("dv")
    wacc = inp.get("wacc"); tw = inp.get("terminal_weight"); ny = inp.get("n_years")
    gt = RF.get(ccy, 0.04)
    em0 = base.ebit_margin0 if base else None

    if wacc is not None and wacc <= gt + 0.005:
        out.append({"flag": "wacc_no_supera_gt", "sev": "alta", "detalle": f"WACC {wacc*100:.1f}% ≈ gT {gt*100:.1f}%"})
    if wacc is not None and (wacc < 0.05 or wacc > 0.20):
        out.append({"flag": "wacc_fuera_rango", "sev": "alta", "detalle": f"WACC {wacc*100:.1f}%"})
    if g1 is not None and (abs(g1 - 0.35) < 1e-9 or abs(g1 + 0.10) < 1e-9):
        out.append({"flag": "g1_en_tope", "sev": "media", "detalle": f"g1 {g1*100:.1f}% (clamp: extrapolación acotada)"})
    if g1 is not None and g1 > 0.30:
        out.append({"flag": "g1_muy_alto", "sev": "media", "detalle": f"g1 {g1*100:.1f}%"})
    if mt is not None and em0 is not None and mt > em0 + 0.02:
        out.append({"flag": "margen_terminal_expande", "sev": "media", "detalle": f"margenT {mt*100:.0f}% > actual {em0*100:.0f}%"})
    if s2c is not None and (s2c <= 0.5 + 1e-9 or s2c >= 6.0 - 1e-9):
        out.append({"flag": "s2c_en_tope", "sev": "media", "detalle": f"s2c {s2c:.2f} (reinversión por defecto/tope)"})
    if tw is not None and tw > 0.80:
        out.append({"flag": "peso_terminal_alto", "sev": "alta", "detalle": f"terminal {tw*100:.0f}% del valor"})
    elif tw is not None and tw > 0.70:
        out.append({"flag": "peso_terminal_medio", "sev": "media", "detalle": f"terminal {tw*100:.0f}%"})
    if dv is not None and dv >= 0.60 - 1e-9:
        out.append({"flag": "dv_en_tope", "sev": "media", "detalle": f"D/V {dv*100:.0f}% (tope)"})
    if base and base.net_debt is not None and base.revenue and base.net_debt > 3 * base.revenue:
        out.append({"flag": "deuda_neta_alta", "sev": "media", "detalle": f"deuda neta {base.net_debt/base.revenue:.1f}× ingresos"})
    if ccy not in ("USD", "EUR", "TWD"):
        out.append({"flag": "moneda_no_soportada", "sev": "alta", "detalle": ccy})
    if ny is not None and ny < 4:
        out.append({"flag": "serie_corta", "sev": "media", "detalle": f"{ny} años"})
    return out


def run(tickers: List[str]) -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk or not os.getenv("EODHD_API_KEY"):
        return {"error": "faltan SUPABASE_URL/SERVICE_ROLE/EODHD_API_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
    w = SupabaseWriter(url, srk)
    conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))

    inlist = "in.(" + ",".join(tickers) + ")"
    prices = {str(r["ticker"]).upper(): r for r in
              w.select_rows("prices", select="ticker,close,currency", params={"ticker": inlist, "order": "ticker"})}
    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,adr_ratio", params={"ticker": inlist, "order": "ticker"})}

    results = []
    apta = 0
    for t in tickers:
        pr = prices.get(t, {}); px = pr.get("close"); ccy = (pr.get("currency") or "").upper()
        try:
            adr = int(instruments.get(t, {}).get("adr_ratio") or 1) or 1
        except (TypeError, ValueError):
            adr = 1
        try:
            _s, _a, obj = conn._resolve(t)
            full = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
            series = full.get("by_field", {}); ccy = ccy or (full.get("currency") or "").upper()
        except Exception as e:
            results.append({"ticker": t, "error_fuente": type(e).__name__}); continue

        r = build(t, ccy or "", px, series, adr=adr)
        an = anomalies(ccy, r.inputs, r.base, r.assump) if r.base else [{"flag": "sin_valoracion", "sev": "alta", "detalle": r.reasons[:2]}]
        high = [a for a in an if a["sev"] == "alta"]
        verdict = "apta_para_asignacion" if (r.status == "confiable" and r.confidence in ("alta", "media") and not high) else "solo_calculada"
        if verdict == "apta_para_asignacion":
            apta += 1
        b = r.base
        results.append({
            "ticker": t, "status": r.status, "confianza": r.confidence,
            "fv_usd": r.fair_value_usd, "margen_pct": r.margin_pct,
            "ccy": ccy, "precio": px,
            "supuestos": {"g1_pct": _p(r.inputs.get("g1")), "margenT_pct": _p(r.inputs.get("margin_terminal")),
                          "s2c": r.inputs.get("s2c"), "dv_pct": _p(r.inputs.get("dv")),
                          "wacc_pct": _p(r.inputs.get("wacc")), "peso_terminal_pct": _p(r.inputs.get("terminal_weight")),
                          "n_años": r.inputs.get("n_years"),
                          "margen_ebit_actual_pct": _p(b.ebit_margin0) if b else None,
                          "deuda_neta": b.net_debt if b else None, "ingresos": b.revenue if b else None},
            "anomalias": an, "veredicto": verdict,
        })
    return {"tickers": tickers, "aptas_para_asignacion": apta, "solo_calculadas": len(tickers) - apta,
            "detalle": results,
            "note": "Control de calidad previo a P2.5. 'solo_calculada' NO respalda asignación significativa."}


def _p(x):
    return round(x * 100, 1) if isinstance(x, (int, float)) else None


def main(argv=None) -> int:
    tickers = [t.upper() for t in (argv or sys.argv[1:])] or DEFAULT
    out = run(tickers)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
