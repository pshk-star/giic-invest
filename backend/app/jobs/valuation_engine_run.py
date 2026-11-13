"""Corre el motor de valoración v2 sobre las 11 empresas con datos REALES reconciliados (EODHD+EDGAR).

Imprime, por empresa, todo lo necesario para reproducir el Fair Value: precio+fecha, FV, WACC, Ke,
crecimiento explícito/terminal, FCF base (FCFF y FCFE), ROIC, reinversión, peso del valor terminal,
margen de seguridad, sensibilidad, divergencia de reconciliación, controles, estado de validación y la
fuente de cada variable. Opción --write para publicar el FV gobernante en valuation_snapshots.

Uso (CI): SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (+ EODHD_API_KEY opcional) en env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from typing import Dict, List, Optional
from uuid import uuid4

from app.research.valuation_engine import evaluate_ttm, METHODOLOGY_VALIDATED, EngineOutput
from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows

ELEVEN = ["NVDA", "META", "NFLX", "TSM", "ASML", "PFE", "AMGN", "ADBE", "LOW", "HD", "UPS"]


def _eodhd_obj(ticker: str):
    """Devuelve (serie_anual, obj_crudo) de EODHD; obj crudo necesario para los trimestres (TTM)."""
    if not os.getenv("EODHD_API_KEY"):
        return {"currency": None, "by_field": {}}, {}
    try:
        from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
        conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _ad, obj = conn._resolve(ticker)
        series = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
        # A fallback US ADR may carry ADR counts, not ordinary shares: never guess.
        series["shares_basis"] = "unverified_adr" if _ad != 1 and (_s or "").endswith(".US") else "ordinary"
        series["provider_symbol"] = _s
        return series, (obj or {})
    except Exception:
        return {"currency": None, "by_field": {}}, {}


def run(tickers: List[str], write: bool, snapshot_date: Optional[str]) -> dict:
    tickers = list(dict.fromkeys(t.upper() for t in tickers))
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    # Árbitro de datos: estados oficiales SEC (companyfacts) vía EDGARProvider, para el TTM autoritativo.
    # Se crea SIEMPRE (UA genérico de respaldo si no hay secret; sin correo personal).
    prov = None
    try:
        from app.providers.edgar import EDGARProvider
        prov = EDGARProvider(user_agent=os.getenv("EDGAR_USER_AGENT") or "GIIC research noreply@giic.example")
        prov._load_ciks()
    except Exception:
        prov = None
    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,asset_class,currency,adr_ratio",
                                 params={"order": "ticker"})}
    prices: Dict[str, dict] = {}
    inlist = "in.(" + ",".join(tickers) + ")"
    for r in w.select_rows("prices", select="ticker,close,currency,as_of", params={"ticker": inlist, "order": "ticker"}):
        prices[str(r["ticker"]).upper()] = r

    today = date.today().isoformat()
    snap = snapshot_date or today
    run_id = str(uuid4())
    results: Dict[str, dict] = {}
    rows_to_write: List[dict] = []
    for t in tickers:
        meta = instruments.get(t, {})
        try:
            adr = float(meta["adr_ratio"]) if meta.get("adr_ratio") is not None else 1.0
        except (TypeError, ValueError):
            adr = float("nan")
        pr = prices.get(t) or {}
        px = pr.get("close")
        eod, eod_obj = _eodhd_obj(t)
        try:
            erows = fetch_edgar_rows(w, t)
            edgar = build_series_from_rows(erows, reporting_currency=eod.get("currency")) if erows else {"currency": None, "by_field": {}}
        except Exception as e:
            erows = []; edgar = {"currency": None, "by_field": {}}
        official = None; official_err = None
        if prov is not None:
            try:
                from app.jobs.official_reconcile import authoritative_ttm
                official = authoritative_ttm(prov, t, eod_obj)
                if not (official and official.get("ttm")):
                    official_err = f"ttm vacío (companyfacts? {bool(prov._facts(t))}, cik {prov._cik.get(t.upper())})"
            except Exception as e:
                official = None; official_err = f"{type(e).__name__}: {str(e)[:140]}"
        else:
            official_err = "prov=None"
        try:
            out, ttm_info = evaluate_ttm(t, edgar, eod, erows, eod_obj, price_local=px, adr=adr,
                                         official_ttm=official, price_currency=pr.get("currency"),
                                         shares_basis=eod.get("shares_basis", "ordinary"))
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
            out = EngineOutput(t, "no_valorable", None, error=f"input inválido: {type(exc).__name__}")
            ttm_info = {}

        if out.result is None:
            results[t] = {"status": out.status, "error": out.error,
                          "edgar_campos": sorted((edgar.get("by_field") or {}).keys()),
                          "eodhd_campos": sorted((eod.get("by_field") or {}).keys())}
            rows_to_write.append({"ticker": t, "payload": {
                "ticker": t, "ccy": eod.get("currency") or edgar.get("currency"), "precio": px,
                "origen": "motor_v2", "gobernante": True, "status": "no_valorable",
                "engine_version": "financial_integrity_p0", "error": out.error,
                "modelos": [{"modelo": "motor_v2", "disponible": False, "status": "no_valorable",
                             "fair_value_usd": None, "accionable": False, "review_block": True,
                             "metodologia_validada": False, "review_reasons": [out.error]}]}})
            continue
        r = out.result
        results[t] = {
            "status": r.status, "consistente_aritmeticamente": r.validated,
            "precio": r.price_local, "precio_fecha": pr.get("as_of"),
            "fair_value_usd": r.fair_value_usd, "fair_value_local": r.fair_value_local,
            "margen_seguridad_pct": round(r.margin_of_safety * 100, 1) if r.margin_of_safety is not None else None,
            "wacc_pct": round(r.wacc * 100, 2), "ke_pct": round(r.ke * 100, 2),
            "g1_pct": round(r.g1 * 100, 1), "gT_pct": round(r.gT * 100, 2), "roic_pct": round(r.roic * 100, 1),
            "reinversion_pct": round(r.reinvest_rate * 100, 1),
            "fcff0": r.fcff0, "fcfe0_hist": r.fcfe0, "peso_terminal_pct": round(r.terminal_weight * 100, 1),
            "ev": r.ev, "equity": r.equity_value,
            "divergencia_fcff_vs_fcfe_pct": round(r.reconc_divergence * 100, 1) if r.reconc_divergence is not None else None,
            "sensibilidad": r.sensitivity,
            "controles_fallidos": [c[0] for c in r.controls if not c[1]],
            "fuentes": r.inputs.get("provenance"),
            "ccy": r.ccy, "adr": r.inputs.get("adr"),
            "ttm": {"campos_usados": ttm_info.get("campos_ttm_usados"), "fin_ttm": ttm_info.get("fin_ttm"),
                    "tiene_ttm_real": ttm_info.get("tiene_ttm_real"), "valores": ttm_info.get("ttm"),
                    "controles_ttm": ttm_info.get("controles_ttm"), "official_err": official_err},
            "_diag": {"revenue0": r.inputs.get("revenue0"), "shares": r.inputs.get("shares"),
                      "nopat0": r.inputs.get("nopat0"), "invested_capital": r.inputs.get("invested_capital"),
                      "op_margin": r.inputs.get("op_margin"), "mktcap_implied": (r.price_local or 0) * (r.inputs.get("shares") or 0)},
        }
        # FV gobernante: payload con forma CompanyValuation (el frontend lee el snapshot más reciente por
        # ticker). UN solo modelo gobernante "motor_v2" con estado de validación. No mezcla modelos viejos.
        conf = "media" if r.validated else "baja"
        model_block = {
            "modelo": "motor_v2", "disponible": True,
            "fair_value_usd": r.fair_value_usd, "precio": r.price_local,
            "margen_seguridad_pct": results[t]["margen_seguridad_pct"], "confianza": conf,
            "status": r.status, "consistente_aritmeticamente": r.validated,
            # ACCIONABLE sólo si pasa aritmética Y la metodología está validada (backtest). Hoy la metodología
            # NO está validada ⇒ accionable=False para TODAS (FV visible e informativo, no recomendación).
            "accionable": bool(r.validated and METHODOLOGY_VALIDATED),
            "metodologia_validada": METHODOLOGY_VALIDATED,
            # BARRERA: no accionable ⇒ bloqueado para compra/asignación (FV visible, no accionable)
            "review_block": not (r.validated and METHODOLOGY_VALIDATED),
            "review_reasons": (results[t]["controles_fallidos"] or ([r.status] if not r.validated else []))
                              + ([] if METHODOLOGY_VALIDATED else ["metodologia_no_validada_backtest_pendiente"]),
            "wacc_pct": results[t]["wacc_pct"], "ke_pct": results[t]["ke_pct"],
            "g_terminal_pct": results[t]["gT_pct"], "peso_terminal_pct": results[t]["peso_terminal_pct"],
            "roic_pct": results[t]["roic_pct"], "reinversion": f"{results[t]['reinversion_pct']}%",
            "crecimiento_g1_pct": results[t]["g1_pct"], "fcff0": r.fcff0, "fcfe0_hist": r.fcfe0,
            "divergencia_fcff_vs_fcfe_pct": results[t]["divergencia_fcff_vs_fcfe_pct"],
            "escenarios": r.scenarios,
            "metodo": r.method, "metodo_razon": r.method_reason,
            "procedencia": {"fuente": "Motor v2 FCFF DCF reconciliado (EODHD+EDGAR)",
                            "fuentes_por_campo": r.inputs.get("provenance"), "fecha": today,
                            "params": r.inputs.get("params_date")},
            "nota": "Motor v2: FCFF DCF data-driven reconciliado. FV único gobernante con estado de validación.",
        }
        if r.status == "no_valorable":
            model_block.update(disponible=False, fair_value_usd=None, margen_seguridad_pct=None,
                               escenarios=None, accionable=False, review_block=True)
        payload = {
            "ticker": t, "ccy": r.ccy, "precio": r.price_local, "gT_pct": results[t]["gT_pct"],
            "origen": "motor_v2", "gobernante": True, "status": r.status, "consistente_aritmeticamente": r.validated,
            "modelos": [model_block],
            "indicadores": {k: results[t][k] for k in ("wacc_pct", "ke_pct", "g1_pct", "gT_pct", "roic_pct",
                            "reinversion_pct", "fcff0", "fcfe0_hist", "peso_terminal_pct",
                            "divergencia_fcff_vs_fcfe_pct")},
            "ttm": results[t]["ttm"], "base_periodo": "TTM" if ttm_info.get("campos_ttm_usados") else "FY",
            "sensibilidad": r.sensitivity,
            "no_calibrado_a_mercado": True,
            "engine_version": "financial_integrity_p0", "code_revision": os.getenv("GITHUB_SHA", "unknown"),
            "audit_inputs": {**r.inputs, "provider_symbol": eod.get("provider_symbol"), "price_date": pr.get("as_of")},
        }
        rows_to_write.append({"ticker": t, "payload": payload})

    written = 0; write_err = None
    if write and rows_to_write:
        try:
            written = w.publish_valuations(run_id, rows_to_write)
        except Exception as e:
            write_err = f"{type(e).__name__}: {str(e)[:160]}"

    tally = {"consistente": 0, "en_revision": 0, "no_valorable": 0}
    for v in results.values():
        tally[v.get("status", "no_valorable")] = tally.get(v.get("status", "no_valorable"), 0) + 1
    return {"run_id": run_id, "as_of": today, "snapshot_date": snap, "params": "2026-11",
            "tally": tally, "escritura": {"intentada": write, "insertadas": written, "error": write_err},
            "resultados": results}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--write", action="store_true")
    p.add_argument("--snapshot-date", default=None)
    p.add_argument("--tickers", nargs="*", default=None)
    args = p.parse_args(argv)
    out = run(args.tickers or ELEVEN, write=args.write, snapshot_date=args.snapshot_date)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 1 if out["escritura"]["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
