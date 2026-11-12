"""E-0 — Auditoría READ-ONLY de datos y factibilidad histórica. NO escribe, NO toca motores, NO cambia
Fair Values ni decisiones. Cuantifica cobertura PIT real, disponibilidad de variables por modelo,
reconciliación/moneda/ADR/precios, sesgo de supervivencia, observaciones elegibles para retornos forward,
auditoría EODHD /api/user y naturaleza (PIT vs foto) del consenso. Entrega una tabla de factibilidad.

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (+ EODHD_API_KEY) en env.
     python -m app.jobs.e0_data_audit
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime
from typing import Dict, List, Optional

# Conceptos US-GAAP que EDGAR ingiere hoy (ver edgar_pit.CONCEPTS) → disponibles gratis.
EDGAR_US = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "ebit": ["OperatingIncomeLoss"], "net_income": ["NetIncomeLoss"], "gross_profit": ["GrossProfit"],
    "eps_diluted": ["EarningsPerShareDiluted"], "eps_basic": ["EarningsPerShareBasic"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "equity": ["StockholdersEquity"], "assets": ["Assets"], "liabilities": ["Liabilities"],
    "lt_debt": ["LongTermDebtNoncurrent"],
}
# Variables que EDGAR NO ingiere hoy (faltan para los modelos): D&A, caja, ΔWC, deuda corto, dividendos.
EDGAR_MISSING = ["dna", "cash", "wc_change", "short_debt", "dividends", "ebitda", "shares_outstanding"]

# Variables requeridas por modelo (para medir disponibilidad real).
MODEL_VARS = {
    "FCFF":        ["revenue", "ebit", "dna", "capex", "wc_change", "lt_debt", "cash", "shares_outstanding"],
    "FCFE":        ["net_income", "ocf", "capex", "lt_debt", "short_debt", "shares_outstanding"],
    "IngresoResidual": ["net_income", "equity", "shares_outstanding"],
    "MultiplosNorm":   ["ebit", "net_income", "equity", "assets", "liabilities", "shares_outstanding", "eps_diluted"],
}


def _count(w, table: str, params: Optional[dict] = None) -> int:
    p = {"select": "id"}; p.update(params or {})
    r = w._client.get(f"{w.base}/{table}", params={**p, "limit": "1"}, headers={"Prefer": "count=exact", "Range": "0-0"})
    cr = r.headers.get("content-range", "")
    try:
        return int(cr.split("/")[-1])
    except (ValueError, IndexError):
        return -1


def _minmax(w, table: str, col: str, params: dict):
    lo = w._client.get(f"{w.base}/{table}", params={**params, "select": col, "order": f"{col}.asc", "limit": "1"}).json()
    hi = w._client.get(f"{w.base}/{table}", params={**params, "select": col, "order": f"{col}.desc", "limit": "1"}).json()
    return (lo[0][col] if lo else None), (hi[0][col] if hi else None)


def _yr(d: Optional[str]) -> Optional[int]:
    try:
        return int(str(d)[:4])
    except (ValueError, TypeError):
        return None


def _add_months(iso: str, months: int) -> str:
    dt = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    y, m = dt.year + (dt.month - 1 + months) // 12, (dt.month - 1 + months) % 12 + 1
    return date(y, m, min(dt.day, 28)).isoformat()


def run() -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk:
        return {"error": "faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    out: Dict = {"as_of": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())}

    # instruments (sector/currency/status + adr si existe)
    try:
        instr_rows = w.select_rows("instruments", select="ticker,sector,currency,status,asset_class,adr_ratio")
    except Exception:
        instr_rows = w.select_rows("instruments", select="ticker,sector,currency,status,asset_class")
    instr = {str(r["ticker"]).upper(): r for r in instr_rows}
    sector_of = {t: (r.get("sector") or "—") for t, r in instr.items()}

    # ---------- 1) fundamentals_pit: cobertura por proveedor/año/sector/empresa ----------
    fp_total = _count(w, "fundamentals_pit")
    fp = w.select_rows("fundamentals_pit", select="ticker,provider,concept,period_end,fiscal_period,filing_date,unit,amended")
    by_provider = defaultdict(int); tickers_by_provider = defaultdict(set)
    year_hist = defaultdict(int); concepts_by_ticker = defaultdict(set); lags = []
    annual_filings = defaultdict(set)   # ticker -> {(fiscal_period, filing_date)} FY
    by_sector_rows = defaultdict(int)
    for r in fp:
        t = str(r["ticker"]).upper(); prov = r.get("provider") or "?"
        by_provider[prov] += 1; tickers_by_provider[prov].add(t)
        y = _yr(r.get("period_end"));
        if y: year_hist[y] += 1
        concepts_by_ticker[t].add(r.get("concept"))
        by_sector_rows[sector_of.get(t, "—")] += 1
        pe, fd = r.get("period_end"), r.get("filing_date")
        if pe and fd:
            try: lags.append((datetime.strptime(fd[:10], "%Y-%m-%d") - datetime.strptime(pe[:10], "%Y-%m-%d")).days)
            except Exception: pass
        if str(r.get("fiscal_period") or "").upper().startswith("FY") and fd:
            annual_filings[t].add((r.get("fiscal_period"), fd))
    lags.sort()
    out["1_cobertura_fundamentals_pit"] = {
        "filas_total": fp_total, "por_proveedor": dict(by_provider),
        "tickers_por_proveedor": {k: len(v) for k, v in tickers_by_provider.items()},
        "rango_anios_fiscales": [min(year_hist) if year_hist else None, max(year_hist) if year_hist else None],
        "filas_por_anio_fiscal": dict(sorted(year_hist.items())),
        "filas_por_sector": dict(sorted(by_sector_rows.items(), key=lambda x: -x[1])),
        "lag_publicacion_vs_fiscal_dias": {"mediana": lags[len(lags)//2] if lags else None, "n": len(lags)},
        "nota_fechas": "fiscal=period_end, publicación=filing_date, captura=retrieved_at (3 fechas distintas, PIT real)",
    }

    # ---------- 2) disponibilidad de variables por modelo ----------
    # presencia de cada concepto EDGAR por (ticker con algún FY) sobre el universo con fundamentals
    universe_fp = sorted(concepts_by_ticker.keys())
    def pct_present(concept_keys: List[str]) -> float:
        if not universe_fp: return 0.0
        tags = set();
        for k in concept_keys: tags.update(EDGAR_US.get(k, []))
        hit = sum(1 for t in universe_fp if concepts_by_ticker[t] & tags)
        return round(100.0 * hit / len(universe_fp), 1)
    var_avail = {}
    for var in set(sum(MODEL_VARS.values(), [])):
        if var in EDGAR_US:
            var_avail[var] = {"fuente": "EDGAR (gratis)", "disponibilidad_%": pct_present([var])}
        else:
            var_avail[var] = {"fuente": "NO en EDGAR (hoy)", "disponibilidad_%": 0.0,
                              "nota": "proviene de EODHD (serie) o no se ingiere; falta para PIT solo-EDGAR"}
    model_feasible = {}
    for model, vars_ in MODEL_VARS.items():
        missing = [v for v in vars_ if v not in EDGAR_US]
        model_feasible[model] = {"variables": vars_, "faltantes_en_edgar": missing,
                                 "cobertura_edgar_%": round(100.0 * (len(vars_) - len(missing)) / len(vars_), 0)}
    out["2_variables_por_modelo"] = {"disponibilidad_variable": var_avail, "por_modelo": model_feasible,
        "edgar_ingiere": sorted(EDGAR_US.keys()), "edgar_NO_ingiere": EDGAR_MISSING}

    # ---------- 3) reconciliación anual/TTM/Q, monedas, ADR, precios ----------
    fp_period_kinds = defaultdict(int)
    for r in fp:
        fpd = str(r.get("fiscal_period") or "").upper()
        fp_period_kinds["FY" if fpd.startswith("FY") else ("Q" if fpd.startswith("Q") else "otro")] += 1
    units = defaultdict(int)
    for r in fp: units[r.get("unit") or "?"] += 1
    ccy_hist = defaultdict(int)
    for t, r in instr.items(): ccy_hist[(r.get("currency") or "?")] += 1
    adr_present = any("adr_ratio" in r for r in instr.values())
    adr_nontrivial = [t for t, r in instr.items() if r.get("adr_ratio") and str(r.get("adr_ratio")) not in ("1", "1.0")]
    ph_total = _count(w, "price_history")
    ph_adj = _count(w, "price_history", {"adjusted": "eq.true"})
    ph_recon = _count(w, "price_history", {"reconstructed": "eq.true"})
    out["3_reconciliacion_moneda_adr_precios"] = {
        "fundamentals_por_tipo_periodo": dict(fp_period_kinds),
        "hay_trimestral": fp_period_kinds.get("Q", 0) > 0,
        "reconciliacion_anual_TTM_Q": "posible solo si hay FY y Q; TTM se construye de Q (ver conteos)",
        "unidades": dict(units), "monedas_instrumentos": dict(ccy_hist),
        "adr_columna_presente": adr_present, "adr_no_triviales": adr_nontrivial,
        "price_history": {"filas": ph_total, "ajustadas": ph_adj, "reconstruidas(yahoo)": ph_recon,
                          "nota": "reconstructed=true ⇒ precios reconstruidos (no vendor oficial): calidad a verificar"},
    }

    # ---------- 4) deslistadas / sesgo de supervivencia ----------
    status_hist = defaultdict(int)
    for t, r in instr.items(): status_hist[r.get("status") or "?"] += 1
    port = set(w.get_transaction_tickers())
    try:
        scan = {str(s["ticker"]).upper() for s in w.select_rows("v_latest_scan", select="ticker", params={"order": "rank"}) if s.get("ticker")}
    except Exception:
        scan = set()
    universe_now = port | scan
    delisted_like = [t for t, r in instr.items() if (r.get("status") or "").lower() in ("delisted", "inactive", "dead")]
    out["4_deslistadas_supervivencia"] = {
        "instruments_por_status": dict(status_hist),
        "deslistadas_marcadas": len(delisted_like), "tickers_deslistados": delisted_like[:20],
        "universo_actual(port∪scan)": len(universe_now),
        "diagnostico": ("No hay deslistadas en el universo: el sesgo de supervivencia NO es corregible con los datos actuales."
                        if not delisted_like else "Hay deslistadas marcadas; corrección parcial posible."),
    }

    # ---------- 5) observaciones elegibles para retornos forward 1/3/5a ----------
    tickers_fp = sorted(annual_filings.keys())
    elig = {"1a": 0, "3a": 0, "5a": 0}; per_ticker_elig = {}
    ph_span = {}
    for t in tickers_fp:
        pmin, pmax = _minmax(w, "price_history", "as_of", {"ticker": f"eq.{t}"})
        ph_span[t] = [pmin, pmax]
        c = {"1a": 0, "3a": 0, "5a": 0}
        for (_fp, fd) in annual_filings[t]:
            if not (pmin and pmax and fd): continue
            if fd < pmin: continue           # no hay precio en la fecha de valoración
            for h, mo in (("1a", 12), ("3a", 36), ("5a", 60)):
                if _add_months(fd, mo) <= pmax: c[h] += 1
        for h in elig: elig[h] += c[h]
        per_ticker_elig[t] = c
    out["5_observaciones_forward_elegibles"] = {
        "total_por_horizonte": elig, "n_tickers_con_fundamentals_anuales": len(tickers_fp),
        "nota": "obs = (ticker, filing anual) con precio en la fecha y a +h; limitado por profundidad de price_history",
    }

    # ---------- 6) auditoría EODHD /api/user ----------
    eodhd = {"consultado": False}
    if os.getenv("EODHD_API_KEY"):
        try:
            import httpx
            u = httpx.get(f"https://eodhd.com/api/user?api_token={os.getenv('EODHD_API_KEY')}&fmt=json", timeout=20).json()
            eodhd = {"consultado": True, "name": u.get("name"), "subscriptionType": u.get("subscriptionType"),
                     "apiRequests": u.get("apiRequests"), "apiRequestsDate": u.get("apiRequestsDate"),
                     "dailyRateLimit": u.get("dailyRateLimit"), "extraLimit": u.get("extraLimit"),
                     "inviteToken": "(omitido)"}
        except Exception as e:
            eodhd = {"consultado": True, "error": f"{type(e).__name__}: {e}"}
    out["6_auditoria_eodhd"] = {"plan_y_uso": eodhd,
        "endpoints_en_codigo": ["/fundamentals/{symbol} (estados + consenso/targets/múltiplos forward)",
                                "/eod (precios ajustados)", "/api/user (plan/uso)", "/api/xbrl"],
        "justifica_usd60": "lo exclusivo = consenso/estimaciones + cobertura internacional; los fundamentales US son gratis en EDGAR"}

    # ---------- 7) consenso: ¿PIT histórico o foto actual? ----------
    est_total = _count(w, "pit_snapshots", {"kind": "like.estimate:*"})
    est = w.select_rows("pit_snapshots", select="ticker,kind,observation_date,published_at,snapshot_date",
                        params={"kind": "like.estimate:*"}) if est_total and est_total > 0 else []
    snap_dates = defaultdict(int); per_tk_snaps = defaultdict(set); obs_dates = set()
    for r in est:
        snap_dates[r.get("snapshot_date")] += 1
        per_tk_snaps[str(r.get("ticker")).upper()].add(r.get("snapshot_date"))
        obs_dates.add(r.get("observation_date"))
    distinct_snaps = sorted([d for d in snap_dates.keys() if d])
    multi = sum(1 for t, s in per_tk_snaps.items() if len(s) >= 2)
    out["7_consenso_pit_vs_foto"] = {
        "filas_estimate": est_total, "fechas_captura_distintas": len(distinct_snaps),
        "rango_captura": [distinct_snaps[0], distinct_snaps[-1]] if distinct_snaps else None,
        "tickers_con_≥2_capturas": multi, "tickers_con_estimate": len(per_tk_snaps),
        "veredicto": ("FOTO ACTUAL (no PIT histórico): ≤1 fecha de captura o sin re-capturas por ticker"
                      if len(distinct_snaps) <= 1 or multi == 0 else
                      "PIT incipiente: hay varias capturas en el tiempo para algunos tickers"),
    }

    # ---------- 8) recomendación + tabla de factibilidad ----------
    def feas(model: str) -> str:
        mf = model_feasible[model]["faltantes_en_edgar"]
        if not mf: return "VIABLE AHORA (solo EDGAR)"
        # si faltan solo variables que EODHD provee (dna/cash/wc) => viable con datos adicionales
        return "VIABLE CON DATOS ADICIONALES (faltan en EDGAR: " + ", ".join(mf) + ")"
    out["8_recomendacion_factibilidad"] = {
        "tabla_factibilidad_modelos": {m: feas(m) for m in MODEL_VARS},
        "consenso_como_benchmark": "NO usable como PIT histórico si §7 = foto actual: solo contraste puntual",
        "periodos_evaluables": "los que tengan FY en fundamentals_pit Y price_history a +h (ver §1 y §5)",
        "resumen": "EDGAR habilita RI y múltiplos (equity/EBIT/NI) sin datos extra; FCFF/FCFE requieren "
                   "D&A, caja y ΔWC (hoy solo vía EODHD, no PIT) ⇒ su backtest PIT riguroso no es viable aún.",
    }
    return out


def main(argv=None) -> int:
    out = run()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
