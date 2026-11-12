"""P1.9 — Payload de VALORACIÓN FUNDAMENTAL (única fuente de lógica financiera).

Calcula, por empresa elegible, cuatro modelos: DCF productivo (de la tubería productiva), FCFF GIIC
(P1.6), FCFF con reinversión corregida (P1.8.2) y FCFF combinado con consenso validado (P1.7.3/4),
cada uno con FV, margen de seguridad, escenarios, confianza+limitaciones, WACC/terminal/peso terminal,
proyección a 10 años, reverse-DCF y procedencia. El frontend sólo RENDERIZA este payload — no duplica
aritmética. Experimental: no sustituye el Fair Value productivo ni Advisor; nada se marca como
recomendación.

Uso: python -m app.jobs.fundamental_valuation            # EODHD para consenso/tasas (CI)
     python -m app.jobs.fundamental_valuation --no-net   # solo GIIC + productivo (sin red)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import List, Optional

from app.research.fcff_forward import (Assump, Base, value_p16, value_path, p16_path,
                                       corrected_reinv_fn, reverse_g1, wacc_of)
from app.research.fcff_forward_report import BASE, ASSUMP, PX, RF, FY_END
from app.research.forecast_models import _rate, _rate_signed
from app.research.forecast_backtest import build_series
from app.research.consensus_admission import admit_consensus, Reported
import app.research.fv_attribution as fa
from app.research.confidence_rubric import score_confidence

# Entradas de procedencia conocida (etiquetadas). DCF productivo = salida de la tubería productiva (V1).
PRODUCTIVE_DCF = {"NVDA": 90.0, "META": 559.0, "NFLX": 37.0, "TSM": 98.0, "ASML": 720.0}
OOS_MAE = {"NVDA": 0.203, "META": 0.150, "NFLX": 0.104, "TSM": 0.134, "ASML": 0.214}  # P1.8 (ingresos, A)
CONSENSUS_STATUS = {"NVDA": "por_encima_guidance", "META": "corroborado", "NFLX": "corroborado",
                    "TSM": "por_encima_guidance", "ASML": "corroborado"}
TODAY = date(2026, 11, 10)
PRICE_DATE = "2026-11-10"


def _traj(rows, n=(1, 3, 5, 7, 10)):
    return [{"año": r["i"], "g_pct": round(r["g"] * 100, 1), "margen_pct": round(r["m"] * 100, 1),
             "fcff": round(r["fcff"], 0), "roic_pct": round(r["roic"] * 100, 0) if r["roic"] else None}
            for r in rows if r["i"] in n]


def _scen(base, a, gT, reinv_fn):
    """cons/base/opt vía sensibilidad WACC×g1×gT (como P1.6). base = senda mecánica."""
    def fv(dg1, dwacc, dgt):
        g, m = p16_path(a.g1 * (1 + dg1), gT + dgt, base.ebit_margin0, a.margin_terminal, a.years)
        return value_path(base, a, g, m, gT=gT + dgt, dwacc=dwacc, reinv_fn=reinv_fn)["bridge"]["ps_usd"]
    return {"conservador": round(fv(-0.25, +0.01, -0.005), 2), "base": round(fv(0, 0, 0), 2),
            "optimista": round(fv(+0.15, -0.01, +0.003), 2)}


def _model_block(name, fv, base, a, gT, val, reinv_fn, extra_lims, confianza, reinv_mode_label, provenance):
    px = PX.get(base.ticker)
    proj = val["proj"]
    return {
        "modelo": name, "fair_value_usd": round(fv, 2), "precio": px,
        "margen_seguridad_pct": round((fv / px - 1) * 100, 1) if px else None,
        "escenarios": _scen(base, a, gT, reinv_fn),
        "confianza": confianza, "limitaciones": extra_lims,
        "wacc_pct": round(val["wacc"]["wacc"] * 100, 2), "g_terminal_pct": round(gT * 100, 2),
        "peso_terminal_pct": round(proj["terminal_weight"] * 100, 1),
        "reverse_dcf_g1_pct": (lambda r: round(r * 100, 1) if r is not None else None)(
            reverse_g1(base, a, px, gT=gT, reinv_fn=reinv_fn) if px else None),
        "reinversion": reinv_mode_label,
        "proyeccion_10a": _traj(proj["rows"]),
        "procedencia": provenance,
    }


def evaluate(t: str, use_net: bool = True) -> dict:
    base, a = BASE[t], ASSUMP[t]
    gT = RF[base.ccy]
    px = PX[t]
    prov = {"fecha": PRICE_DATE, "moneda": base.ccy, "precio_fecha": PRICE_DATE}
    out = {"ticker": t, "ccy": base.ccy, "precio": px, "gT_pct": round(gT * 100, 2), "modelos": []}

    # 1) DCF productivo (de la tubería productiva; no se recalcula aquí)
    fvp = PRODUCTIVE_DCF.get(t)
    out["modelos"].append({"modelo": "DCF_productivo", "fair_value_usd": fvp, "precio": px,
                           "margen_seguridad_pct": round((fvp / px - 1) * 100, 1) if (fvp and px) else None,
                           "confianza": "producción", "limitaciones": ["motor productivo V1 (sin cambios)"],
                           "procedencia": {**prov, "fuente": "tubería productiva GIIC (valuation.ts)"},
                           "nota": "referencia productiva; no experimental"})

    # 2) FCFF GIIC (P1.6, reinversión ventas/capital)
    vG = value_p16(base, a)
    scG = _scen(base, a, gT, None)
    spread = (scG["optimista"] - scG["conservador"]) / scG["base"] if scG["base"] else None
    confG = score_confidence("eligible", OOS_MAE[t], CONSENSUS_STATUS[t], spread,
                             vG["proj"]["terminal_weight"])["nivel"]
    out["modelos"].append(_model_block(
        "FCFF_GIIC", vG["bridge"]["ps_usd"], base, a, gT, vG, None,
        ["supuestos GIIC (P1.6); reinversión por ventas/capital puede sobreestimar (ver P1.8.2)"],
        confG, "ventas/capital (s2c)", {**prov, "fuente": "EDGAR/EODHD reportado + supuestos GIIC"}))

    # tasas de reinversión corregida (requieren serie reportada)
    rates = None
    if use_net and os.getenv("EODHD_API_KEY"):
        try:
            from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
            conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
            _s, _ad, obj = conn._resolve(t)
            ser = build_series(eodhd_annual_series_full(obj).get("by_field", {})) if obj else []
            if len(ser) >= 5:
                ti = len(ser) - 1
                rates = (_rate(ser, ti, "capex"), _rate(ser, ti, "dna"), _rate_signed(ser, ti, "wc_change"))
            cons_obj = obj
        except Exception as e:
            out["aviso"] = f"sin tasas/consenso: {type(e).__name__}"; cons_obj = None
    else:
        cons_obj = None

    # 3) FCFF corregido (reinversión capex/D&A por separado)
    if rates:
        cxr, dnr, wcr = rates
        rfn = corrected_reinv_fn(cxr, dnr, wcr)
        g, m = p16_path(a.g1, gT, base.ebit_margin0, a.margin_terminal, a.years)
        vC = value_path(base, a, g, m, gT=gT, reinv_fn=rfn)
        out["modelos"].append(_model_block(
            "FCFF_corregido", vC["bridge"]["ps_usd"], base, a, gT, vC, rfn,
            [f"reinversión neta capex({cxr*100:.1f}%)−D&A({dnr*100:.1f}%)+ΔWC; experimental P1.8.2"],
            confG, f"capex−D&A separados (neto {(cxr-dnr)*100:.1f}% ingresos)",
            {**prov, "fuente": "EODHD serie anual (tasas capex/D&A/ΔWC)"}))
    else:
        out["modelos"].append({"modelo": "FCFF_corregido", "disponible": False,
                               "motivo": "requiere serie reportada (EODHD) para tasas capex/D&A"})

    # 4) FCFF combinado con consenso VALIDADO (gate P1.7.3) + reinversión corregida
    if cons_obj and rates:
        from app.research.forecast_backtest import build_series as _bs  # noqa
        from app.research.fcff_forward_report import _trend_list, _reported
        gate = admit_consensus(t, _trend_list(cons_obj), _reported(t), TODAY,
                               (cons_obj.get("General", {}) or {}).get("UpdatedAt"))
        if gate["admitted"]:
            cy, ny = gate["cy"], gate.get("ny") or {}
            eg = [cy["rev_growth"]] + ([ny["rev_growth"]] if ny.get("rev_growth") is not None else [])
            gc = fa.consensus_growths(eg, a, gT, "meanrev")
            mm = fa.giic_margins(base, a)
            rfn = corrected_reinv_fn(*rates)
            vK = value_path(base, a, gc, mm, gT=gT, reinv_fn=rfn)
            lims = ["consenso validado + reversión a la media (P1.7.4) + reinversión corregida"]
            if gate["extreme"]:
                lims.append("crecimiento de consenso EXTREMO/por encima de guidance: confianza baja")
            out["modelos"].append(_model_block(
                "FCFF_combinado_consenso", vK["bridge"]["ps_usd"], base, a, gT, vK, rfn,
                lims, gate["confidence"], "capex−D&A separados",
                {**prov, "fuente": "EODHD consenso (gate P1.7.3) + reportado"}))
        else:
            out["modelos"].append({"modelo": "FCFF_combinado_consenso", "disponible": False,
                                   "motivo": "consenso no admitido por el gate", "razones": gate["reasons"]})
    else:
        out["modelos"].append({"modelo": "FCFF_combinado_consenso", "disponible": False,
                               "motivo": "sin consenso (sin red/API)"})

    # comparación: por qué difieren
    fvs = {m["modelo"]: m.get("fair_value_usd") for m in out["modelos"] if m.get("fair_value_usd")}
    out["comparacion"] = {
        "fair_values": fvs,
        "explicacion": ("DCF productivo (V1) es el más bajo por supuestos simples; FCFF GIIC sube por "
                        "márgenes/senda fundamentales; FCFF corregido ajusta la reinversión (capex≈D&A "
                        "⇒ reinversión neta menor ⇒ FCFF/FV algo mayores que GIIC); el combinado "
                        "incorpora el crecimiento de consenso validado con reversión a la media. "
                        "Las diferencias vienen de CRECIMIENTO (consenso vs GIIC) y REINVERSIÓN "
                        "(s2c vs capex−D&A), no de calibración a mercado.")}
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--no-net", action="store_true")
    p.add_argument("--write", action="store_true", help="upsert a Supabase fundamental_valuation")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    ts = [t.upper() for t in args.tickers] if args.tickers else ["NVDA", "META", "NFLX", "TSM", "ASML"]
    resultados = {t: evaluate(t, not args.no_net) for t in ts}
    res = {"P1.9": "valoración fundamental (experimental, no productiva)", "generado": PRICE_DATE,
           "no_calibrado_a_mercado": True, "resultados": resultados}
    if args.write:
        # Reutiliza pit_snapshots (infra existente, sin DDL): append-only, dedupe por UNIQUE,
        # legible por autenticados. kind='fundamental_valuation'; el frontend lee el snapshot más
        # reciente por ticker. Best-effort: un fallo no pierde el payload (ya impreso).
        from datetime import datetime, timezone
        try:
            from app.jobs.supabase_writer import SupabaseWriter
            w = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
            # override SNAPSHOT_DATE: la tabla es append-only inmutable con UNIQUE(...,snapshot_date). Para
            # que una versión corregida AFLORE por encima de una captura previa (p. ej. con fecha futura),
            # se permite fijar la fecha de captura. No borra el histórico.
            snap = os.getenv("SNAPSHOT_DATE") or date.today().isoformat()
            rows = [{"kind": "fundamental_valuation", "ticker": t, "observation_date": PRICE_DATE,
                     "published_at": PRICE_DATE, "snapshot_date": snap,
                     "captured_at": datetime.now(timezone.utc).isoformat(),
                     "source": "P1.9", "data_version": PRICE_DATE, "payload": v}
                    for t, v in resultados.items()]
            n = w.insert_append("pit_snapshots", rows,
                                on_conflict="kind,ticker,observation_date,snapshot_date")
            res["escritura"] = {"ok": True, "insertados": n, "tabla": "pit_snapshots",
                                "kind": "fundamental_valuation", "snapshot_date": snap}
            # Verificación de lectura (#2): releer de Supabase y comparar FVs con lo calculado.
            back = w.select_rows("pit_snapshots", select="ticker,payload",
                                 params={"kind": "eq.fundamental_valuation",
                                         "snapshot_date": f"eq.{snap}"})
            def _fvs(cv):
                return {m["modelo"]: m.get("fair_value_usd") for m in cv.get("modelos", [])
                        if m.get("fair_value_usd") is not None}
            stored = {r["ticker"]: _fvs(r["payload"]) for r in back}
            calc = {t: _fvs(v) for t, v in resultados.items()}
            match = all(stored.get(t) == calc.get(t) for t in calc)
            res["verificacion_lectura"] = {"coincide": match, "tickers_releidos": len(stored)}
        except Exception as e:
            res["escritura"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
