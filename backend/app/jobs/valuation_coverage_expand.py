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
    existing_rows = w.select_rows("pit_snapshots", select="ticker,payload",
                                  params={"kind": "eq.fundamental_valuation", "order": "ticker"})
    # 'already' = solo valoraciones PRODUCTIVAS/P1.9 (origen != P2.4): esas NO se re-escriben (payloads
    # ricos intactos). Las de origen P2.4 SÍ se re-valoran para incorporar correcciones del driver.
    already = sorted({str(r["ticker"]).upper() for r in existing_rows
                      if (r.get("payload") or {}).get("origen") != "P2.4_data_driven"})
    valued_p24 = sorted({str(r["ticker"]).upper() for r in existing_rows
                         if (r.get("payload") or {}).get("origen") == "P2.4_data_driven"})
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

    # FUENTE DE SERIES (P4): EDGAR es la fuente PRIMARIA (gratis, point-in-time, con capital invertido real).
    # EODHD queda SOLO como respaldo cuando EDGAR no tiene datos del ticker. El sistema DEBE funcionar con
    # EODHD deshabilitado (sin EODHD_API_KEY): entonces se usa EDGAR y los tickers sin EDGAR quedan
    # 'insuficiente' (no se inventa). Se mide la dependencia residual de EODHD por ticker.
    from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows
    conn = None
    eodhd_disabled = not os.getenv("EODHD_API_KEY")
    if not eodhd_disabled:
        try:
            from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
            conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        except Exception:
            conn = None  # respaldo no disponible: se continúa solo con EDGAR

    status_tally = {"confiable": 0, "experimental": 0, "insuficiente": 0, "error_fuente": 0}
    source_tally = {"EDGAR": 0, "EODHD": 0, "sin_fuente": 0}
    insuff_reasons: Dict[str, int] = {}
    per_ticker: List[dict] = []
    rows_to_write: List[dict] = []
    attractive: List[str] = []
    today = date.today().isoformat()
    # snapshot_date de la captura. Override explícito (SNAPSHOT_DATE) para registrar una captura
    # CORREGIDA el mismo día: la tabla es append-only inmutable con UNIQUE (…,snapshot_date), así que
    # una recaptura con la misma fecha se DEDUPLICA (no actualiza). El override permite que la versión
    # corregida entre como una captura nueva sin borrar el histórico (que queda intacto).
    snap_date = os.getenv("SNAPSHOT_DATE") or today

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
        # EDGAR primero (fuente primaria). Respaldo EODHD solo si EDGAR no trae ingresos.
        series: Dict[str, dict] = {}; src = None; edgar_ccy = None
        try:
            erows = fetch_edgar_rows(w, t)
            efull = build_series_from_rows(erows) if erows else {"currency": None, "by_field": {}}
            if efull.get("by_field", {}).get("revenue"):
                series = efull["by_field"]; edgar_ccy = (efull.get("currency") or "").upper(); src = "EDGAR"
        except Exception as e:
            per_ticker.append({"ticker": t, "status": "edgar_error", "detalle": f"{type(e).__name__}: {str(e)[:80]}"})
        if src is None and conn is not None:
            try:
                _s, _ad, obj = conn._resolve(t)
                full = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
                if full.get("by_field", {}).get("revenue"):
                    series = full["by_field"]; edgar_ccy = (full.get("currency") or "").upper(); src = "EODHD"
            except Exception as e:
                status_tally["error_fuente"] += 1
                source_tally["sin_fuente"] += 1
                per_ticker.append({"ticker": t, "status": "error_fuente", "detalle": f"{type(e).__name__}"})
                continue
        if src is None:
            status_tally["insuficiente"] += 1
            source_tally["sin_fuente"] += 1
            insuff_reasons["sin fuente de datos (EDGAR/EODHD)"] = insuff_reasons.get("sin fuente de datos (EDGAR/EODHD)", 0) + 1
            per_ticker.append({"ticker": t, "status": "insuficiente", "motivos": ["sin fuente de datos (EDGAR/EODHD)"]})
            continue
        source_tally[src] += 1
        ccy = ccy or edgar_ccy

        # observation_date = fecha fiscal REAL del dato (no el día de captura). Da una clave única
        # distinta por versión de dato y permite re-insertar valores corregidos (append-only).
        rev_periods = sorted((series.get("revenue") or {}).keys())
        obs_date = rev_periods[-1] if rev_periods else today
        r = build(t, ccy or "", px, series, adr=adr)
        status_tally[r.status] = status_tally.get(r.status, 0) + 1
        rec = {"ticker": t, "status": r.status, "fv_usd": r.fair_value_usd, "margen_pct": r.margin_pct,
               "confianza": r.confidence, "fuente": src, "capital": r.inputs.get("capital_source"),
               "roic_pct": round((r.inputs.get("roic_implied") or 0) * 100, 1), "motivos": r.reasons[:4]}
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
                # BARRERA (diagnóstico PFE): marca de accionabilidad bloqueada por inconsistencia económica
                # no resuelta. NO altera fair_value_usd; la política compartida la respeta.
                "review_block": bool(r.inputs.get("review_block")),
                "review_reasons": r.inputs.get("review_reasons") or [],
                # indicadores clave visibles (P3): unidades y fuente identificables
                "roic_pct": round((r.inputs.get("roic_implied") or 0) * 100, 1),
                "roic_terminal_pct": round((r.inputs.get("roic_terminal") or 0) * 100, 1),
                "wacc_pct": round((r.inputs.get("wacc") or 0) * 100, 2),
                "crecimiento_g1_pct": round((r.inputs.get("g1") or 0) * 100, 1),
                "crecimiento_terminal_pct": round((r.inputs.get("gT") or 0) * 100, 2),
                "peso_terminal_pct": round((r.inputs.get("terminal_weight") or 0) * 100, 1),
                "capital_invertido_usd": r.inputs.get("invested_capital"),
                "capital_source": r.inputs.get("capital_source"),
                "procedencia": {"fuente": f"driver data-driven ({src})", "capital": r.inputs.get("capital_source"),
                                "fecha": today},
                "nota": "experimental: FCFF con supuestos derivados de datos; no es FV productivo",
            }],
            "controles": {"review_block": bool(r.inputs.get("review_block")),
                          "reinv_neta_pct": r.inputs.get("reinv_neta_pct"),
                          "acq_amort": bool(r.inputs.get("acq_amort")),
                          "ic_negative": bool(r.inputs.get("ic_negative")),
                          "adr_fx_review": bool(r.inputs.get("adr_fx_review"))},
            "no_calibrado_a_mercado": True,
        }
        rows_to_write.append({"kind": "fundamental_valuation", "ticker": t, "observation_date": obs_date,
                              "published_at": today, "snapshot_date": snap_date,
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
        "cobertura_antes": {"empresas_elegibles": len(eligible), "ya_valoradas_productivas": len(already),
                            "ya_valoradas_productivas_tickers": already, "revaloradas_P2.4": len(valued_p24)},
        "procesadas": len(todo),
        "status_tally": status_tally,
        "fuentes_de_datos": source_tally,
        "eodhd_deshabilitado": eodhd_disabled,
        "dependencia_eodhd_residual": source_tally["EODHD"],
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
