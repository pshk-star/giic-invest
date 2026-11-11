"""P2.4 — Ampliación de cobertura de valoración sobre el universo elegible (datos reales).

Corre el driver data-driven (reutiliza value_p16, sin modelos nuevos) sobre las empresas elegibles que
HOY no tienen valoración, construyendo insumos desde la serie reportada de EODHD. Escribe las
valoraciones que superan los controles a pit_snapshots (kind='fundamental_valuation', origen P2.4,
confianza/estatus explícitos) y mide la cobertura ANTES/DESPUÉS. No toca los 5 ya valorados (sus
payloads ricos de P1.9 quedan intactos). No modifica valuation.ts ni Advisor 2.2. Nada es recomendación.

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (+ EODHD_API_KEY) en env.
     python -m app.jobs.valuation_coverage_expand            # escribe
     python -m app.jobs.valuation_coverage_expand --dry-run  # solo diagnostica, no escribe
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from app.research.fundamental_driver import build, SUPPORTED_CCY

ETF_CLASSES = {"etf", "fund", "etn", "mutualfund"}
EQUITY_CLASSES = {"equity", "stock", "adr", "common"}
MIN_MARGIN = 0.10


def kind_of(asset_class: Optional[str], sector: Optional[str]) -> str:
    ac = (asset_class or "").lower()
    if ac in ETF_CLASSES:
        return "etf"
    if sector and re.search(r"financ|bank|banco|insurance|seguro", sector, re.I):
        return "banco"
    if ac and ac not in EQUITY_CLASSES:
        return "otro"
    return "empresa"


def run(write: bool) -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk:
        return {"error": "faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    t0 = time.time()

    scan = w.select_rows("v_latest_scan", select="ticker,sector", params={"order": "rank"})
    scan_tk = [str(r["ticker"]).upper() for r in scan if r.get("ticker")]
    port_tk = w.get_transaction_tickers()
    existing_rows = w.select_rows("pit_snapshots", select="ticker",
                                  params={"kind": "eq.fundamental_valuation", "order": "ticker"})
    already = sorted({str(r["ticker"]).upper() for r in existing_rows})
    universe = sorted(set(scan_tk) | set(port_tk) | set(already))

    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,asset_class,sector,currency,adr_ratio",
                                 params={"order": "ticker"})}
    # precios (una query)
    prices: Dict[str, dict] = {}
    if universe:
        inlist = "in.(" + ",".join(universe) + ")"
        for r in w.select_rows("prices", select="ticker,close,currency,as_of", params={"ticker": inlist, "order": "ticker"}):
            prices[str(r["ticker"]).upper()] = r

    sector_of = {s["ticker"].upper(): s.get("sector") for s in scan if s.get("ticker")}
    eligible = [t for t in universe
                if kind_of(instruments.get(t, {}).get("asset_class"), instruments.get(t, {}).get("sector") or sector_of.get(t)) == "empresa"]
    todo = [t for t in eligible if t not in set(already)]

    # conector EODHD (serie reportada)
    conn = None
    if os.getenv("EODHD_API_KEY"):
        try:
            from app.core.connectors.eodhd import EodhdFundamentalsConnector
            conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        except Exception as e:
            return {"error": f"conector EODHD no disponible: {type(e).__name__}: {e}"}
    if conn is None:
        return {"error": "falta EODHD_API_KEY para series reportadas"}
    from app.core.connectors.eodhd import eodhd_annual_series_full

    status_tally = {"confiable": 0, "experimental": 0, "insuficiente": 0, "error_fuente": 0}
    insuff_reasons: Dict[str, int] = {}
    per_ticker: List[dict] = []
    rows_to_write: List[dict] = []
    attractive: List[str] = []
    today = date.today().isoformat()

    for t in todo:
        px = None; ccy = None; adr = 1
        pr = prices.get(t)
        if pr:
            px = pr.get("close"); ccy = (pr.get("currency") or "").upper()
        meta = instruments.get(t, {})
        try:
            adr = int(meta.get("adr_ratio") or 1) or 1
        except (TypeError, ValueError):
            adr = 1
        try:
            _s, _ad, obj = conn._resolve(t)
            full = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
            series = full.get("by_field", {})
            ccy = ccy or (full.get("currency") or "").upper()
        except Exception as e:
            status_tally["error_fuente"] += 1
            per_ticker.append({"ticker": t, "status": "error_fuente", "detalle": f"{type(e).__name__}"})
            continue

        # observation_date = fecha fiscal REAL del dato (no el día de captura). Da una clave única
        # distinta por versión de dato y permite re-insertar valores corregidos (append-only).
        rev_periods = sorted((series.get("revenue") or {}).keys())
        obs_date = rev_periods[-1] if rev_periods else today
        r = build(t, ccy or "", px, series, adr=adr)
        status_tally[r.status] = status_tally.get(r.status, 0) + 1
        rec = {"ticker": t, "status": r.status, "fv_usd": r.fair_value_usd, "margen_pct": r.margin_pct,
               "confianza": r.confidence, "motivos": r.reasons[:4]}
        per_ticker.append(rec)
        if r.status == "insuficiente":
            key = (r.reasons[0] if r.reasons else "desconocido").split(" (")[0]
            insuff_reasons[key] = insuff_reasons.get(key, 0) + 1
            continue
        if r.margin_pct is not None and r.margin_pct >= MIN_MARGIN * 100:
            attractive.append(t)
        payload = {
            "ticker": t, "ccy": r.base.ccy, "precio": px, "origen": "P2.4_data_driven", "status": r.status,
            "modelos": [{
                "modelo": "FCFF_GIIC", "fair_value_usd": r.fair_value_usd, "precio": px,
                "margen_seguridad_pct": r.margin_pct, "confianza": r.confidence, "status": r.status,
                "limitaciones": r.reasons,
                "procedencia": {"fuente": "driver data-driven P2.4 (serie reportada EODHD)", "fecha": today},
                "nota": "experimental: FCFF con supuestos derivados de datos; no es FV productivo",
            }],
            "no_calibrado_a_mercado": True,
        }
        rows_to_write.append({"kind": "fundamental_valuation", "ticker": t, "observation_date": obs_date,
                              "published_at": today, "snapshot_date": today,
                              "captured_at": datetime.now(timezone.utc).isoformat(),
                              "source": "P2.4", "data_version": today, "payload": payload})

    written = 0; write_err = None
    if write and rows_to_write:
        try:
            written = w.insert_append("pit_snapshots", rows_to_write,
                                      on_conflict="kind,ticker,observation_date,snapshot_date")
        except Exception as e:
            write_err = f"{type(e).__name__}: {str(e)[:160]}"

    valued = status_tally["confiable"] + status_tally["experimental"]
    return {
        "as_of_run": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "cobertura_antes": {"empresas_elegibles": len(eligible), "ya_valoradas": len(already),
                            "ya_valoradas_tickers": already},
        "procesadas": len(todo),
        "status_tally": status_tally,
        "insuficientes_por_motivo": insuff_reasons,
        "valoradas_nuevas": valued,
        "atractivas_margen>=10pct": {"count": len(attractive), "tickers": sorted(attractive)},
        "cobertura_despues": {"empresas_elegibles": len(eligible),
                              "valoradas_total": len(already) + (written if write else valued),
                              "cobertura_pct": round(100.0 * (len(already) + (written if write else valued)) / max(1, len(eligible)), 1)},
        "escritura": {"intentada": write, "insertadas": written, "error": write_err},
        "timing_seconds": round(time.time() - t0, 1),
        "detalle": per_ticker,
        "note": "Valoraciones experimentales data-driven; no productivas, no recomendaciones. "
                "La política de valoración (frontend) decide accionabilidad bajo feature flag reversible.",
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="no escribe; solo diagnostica")
    args = p.parse_args(argv)
    out = run(write=not args.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
