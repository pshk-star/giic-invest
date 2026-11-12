"""Corre el motor de valoración v2 sobre las 11 empresas con datos REALES reconciliados (EODHD+EDGAR).

Imprime, por empresa, todo lo necesario para reproducir el Fair Value: precio+fecha, FV, WACC, Ke,
crecimiento explícito/terminal, FCF base (FCFF y FCFE), ROIC, reinversión, peso del valor terminal,
margen de seguridad, sensibilidad, divergencia de reconciliación, controles, estado de validación y la
fuente de cada variable. Opción --write para persistir el FV gobernante a pit_snapshots.

Uso (CI): SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (+ EODHD_API_KEY opcional) en env.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from app.research.valuation_engine import evaluate
from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows

ELEVEN = ["NVDA", "META", "NFLX", "TSM", "ASML", "PFE", "AMGN", "ADBE", "LOW", "HD", "UPS"]


def _eodhd_series(ticker: str):
    if not os.getenv("EODHD_API_KEY"):
        return {"currency": None, "by_field": {}}
    try:
        from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
        conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _ad, obj = conn._resolve(ticker)
        return eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
    except Exception:
        return {"currency": None, "by_field": {}}


def run(tickers: List[str], write: bool, snapshot_date: Optional[str]) -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,asset_class,currency,adr_ratio",
                                 params={"order": "ticker"})}
    prices: Dict[str, dict] = {}
    inlist = "in.(" + ",".join(tickers) + ")"
    for r in w.select_rows("prices", select="ticker,close,currency,as_of", params={"ticker": inlist, "order": "ticker"}):
        prices[str(r["ticker"]).upper()] = r

    today = date.today().isoformat()
    snap = snapshot_date or today
    results: Dict[str, dict] = {}
    rows_to_write: List[dict] = []
    for t in tickers:
        meta = instruments.get(t, {})
        try:
            adr = int(meta.get("adr_ratio") or 1) or 1
        except (TypeError, ValueError):
            adr = 1
        pr = prices.get(t) or {}
        px = pr.get("close")
        try:
            erows = fetch_edgar_rows(w, t)
            edgar = build_series_from_rows(erows) if erows else {"currency": None, "by_field": {}}
        except Exception as e:
            edgar = {"currency": None, "by_field": {}}
        eod = _eodhd_series(t)
        out = evaluate(t, edgar, eod, price_local=px, adr=adr)
        if out.result is None:
            results[t] = {"status": out.status, "error": out.error,
                          "edgar_campos": sorted((edgar.get("by_field") or {}).keys()),
                          "eodhd_campos": sorted((eod.get("by_field") or {}).keys())}
            continue
        r = out.result
        results[t] = {
            "status": r.status, "validado": r.validated,
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
        }
        # FV gobernante: se escribe con estado de validación. Bloqueado si no está validado.
        payload = {
            "ticker": t, "ccy": r.ccy, "precio": r.price_local, "origen": "motor_v2",
            "status": r.status, "validado": r.validated,
            "fair_value_usd": r.fair_value_usd, "margen_seguridad_pct": results[t]["margen_seguridad_pct"],
            "gobernante": True,
            "accionable": bool(r.validated),   # SOLO validado es accionable
            "indicadores": {k: results[t][k] for k in ("wacc_pct", "ke_pct", "g1_pct", "gT_pct", "roic_pct",
                            "reinversion_pct", "fcff0", "fcfe0_hist", "peso_terminal_pct",
                            "divergencia_fcff_vs_fcfe_pct")},
            "sensibilidad": r.sensitivity, "controles_fallidos": results[t]["controles_fallidos"],
            "fuentes": r.inputs.get("provenance"), "params_date": r.inputs.get("params_date"),
            "nota": "Motor v2 FCFF DCF data-driven reconciliado (EODHD+EDGAR). FV gobernante con estado de validación.",
        }
        rev_periods = sorted((edgar.get("by_field", {}).get("revenue") or eod.get("by_field", {}).get("revenue") or {}).keys())
        obs_date = rev_periods[-1] if rev_periods else today
        rows_to_write.append({"kind": "fundamental_valuation", "ticker": t, "observation_date": obs_date,
                              "published_at": today, "snapshot_date": snap,
                              "captured_at": datetime.now(timezone.utc).isoformat(),
                              "source": "motor_v2", "data_version": today, "payload": payload})

    written = 0; write_err = None
    if write and rows_to_write:
        try:
            written = w.insert_append("pit_snapshots", rows_to_write,
                                      on_conflict="kind,ticker,observation_date,snapshot_date")
        except Exception as e:
            write_err = f"{type(e).__name__}: {str(e)[:160]}"

    tally = {"validado": 0, "en_revision": 0, "no_valorable": 0}
    for v in results.values():
        tally[v.get("status", "no_valorable")] = tally.get(v.get("status", "no_valorable"), 0) + 1
    return {"as_of": today, "snapshot_date": snap, "params": "2026-11",
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
