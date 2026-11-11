"""P2.3 — Diagnóstico de COBERTURA REAL del Opportunity Scanner (datos de Supabase, solo lectura).

Mide el universo que el scanner evalúa de verdad (v_latest_scan ∪ transacciones ∪ valoraciones P1.9
∪ ETF de cartera), clasifica cada instrumento y explica TODAS las exclusiones. NO modifica reglas de
valoración ni genera recomendaciones: es el diagnóstico cuantitativo que alimentará P2.4.

Distingue: no_evaluable (sin datos) / evaluable_no_atractivo / atractivo_no_accionable / accionable,
y cuenta cuántas oportunidades quedan bloqueadas EXCLUSIVAMENTE por exigir FV productivo (DCF antiguo),
sin tocar todavía esa regla. Mide tiempo de la pasada completa (eficiencia, sin tope artificial).

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY en env; python -m app.jobs.scanner_coverage_report
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Dict, List, Optional

MIN_MARGIN = 0.10          # mismo umbral que minMarginToBuy del scanner/Advisor 3.0
MIN_BARS_RISK = 60         # barras mínimas para riesgo marginal fiable
ETF_CLASSES = {"etf", "fund", "etn", "mutualfund"}
EQUITY_CLASSES = {"equity", "stock", "adr", "common"}


def kind_of(asset_class: Optional[str], sector: Optional[str]) -> str:
    ac = (asset_class or "").lower()
    if ac in ETF_CLASSES:
        return "etf"
    if sector and re.search(r"financ|bank|banco|insurance|seguro", sector, re.I):
        return "banco"
    if ac and ac not in EQUITY_CLASSES:
        return "otro"
    return "empresa"


def _model(payload: dict, name: str) -> Optional[dict]:
    for m in (payload or {}).get("modelos", []):
        if m.get("modelo") == name:
            return m
    return None


def _margin(payload: dict, name: str) -> Optional[float]:
    m = _model(payload, name)
    if not m or m.get("disponible") is False or m.get("margen_seguridad_pct") is None:
        return None
    return m["margen_seguridad_pct"] / 100.0


def _count(w, table: str, params: dict) -> int:
    p = {"select": "ticker", "limit": "1"}
    p.update(params)
    r = w._client.get(f"{w.base}/{table}", params=p, headers={"Prefer": "count=exact"})
    r.raise_for_status()
    cr = r.headers.get("content-range", "")
    try:
        return int(cr.split("/")[-1])
    except Exception:
        return len(r.json())


def diagnose() -> dict:
    url = os.getenv("SUPABASE_URL", "")
    srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk:
        return {"error": "faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    t0 = time.time()

    # --- universo real (mismas fuentes que el frontend) ---
    scan = w.select_rows("v_latest_scan", select="ticker,sector,composite,rank", params={"order": "rank"})
    scan_tk = [str(r["ticker"]).upper() for r in scan if r.get("ticker")]
    port_tk = w.get_transaction_tickers()
    fv_rows = w.select_rows("pit_snapshots", select="ticker,snapshot_date,payload",
                            params={"kind": "eq.fundamental_valuation", "order": "snapshot_date.desc"})
    fv: Dict[str, dict] = {}
    for r in fv_rows:
        t = str(r["ticker"]).upper()
        if t not in fv:
            fv[t] = r.get("payload") or {}
    universe = sorted(set(scan_tk) | set(port_tk) | set(fv.keys()))

    # --- metadatos + fundamentales ---
    instruments = {str(r["ticker"]).upper(): r for r in
                   w.select_rows("instruments", select="ticker,name,asset_class,sector,status,currency",
                                 params={"order": "ticker"})}
    fund_rows = w.select_rows("fundamentals", select="ticker,payload", params={"order": "ticker"})
    fundamentals = {str(r["ticker"]).upper(): (r.get("payload") or {}) for r in fund_rows}

    by_kind: Dict[str, int] = {}
    with_prod = with_fcff = with_any_val = with_fund = with_hist = with_hist_risk = 0
    eligible_companies = 0
    excluded: List[dict] = []
    classification = {"no_evaluable": 0, "evaluable_no_atractivo": 0, "atractivo_no_accionable": 0, "accionable": 0}
    attractive_prod_l: List[str] = []
    attractive_fcff_only_l: List[str] = []
    blocked_by_productive_l: List[str] = []
    held = set(port_tk)
    details: List[dict] = []

    for t in universe:
        inst = instruments.get(t, {})
        sector = inst.get("sector") or next((s.get("sector") for s in scan if str(s.get("ticker", "")).upper() == t), None)
        kind = kind_of(inst.get("asset_class"), sector)
        by_kind[kind] = by_kind.get(kind, 0) + 1
        pay = fv.get(t, {})
        pm = _margin(pay, "DCF_productivo")
        fm = _margin(pay, "FCFF_GIIC")
        has_prod = pm is not None
        has_fcff = fm is not None
        has_val = has_prod or has_fcff
        has_fund = t in fundamentals and bool(fundamentals[t])
        n_bars = _count(w, "price_history", {"ticker": f"eq.{t}"})
        has_hist = n_bars >= 2
        has_hist_risk_t = n_bars >= MIN_BARS_RISK
        with_prod += has_prod
        with_fcff += has_fcff
        with_any_val += has_val
        with_fund += has_fund
        with_hist += has_hist
        with_hist_risk += has_hist_risk_t
        is_company = kind in ("empresa", "banco")
        if is_company:
            eligible_companies += 1

        # --- clasificación 4 vías + exclusiones explicadas ---
        reasons: List[str] = []
        if not inst:
            reasons.append("sin metadata en instruments")
        if kind in ("etf", "otro"):
            reasons.append("tipo no valorable por DCF/FCFF (se evalúa por rol en cartera)")
        if not has_val and not has_hist:
            reasons.append("sin valoración ni historial de precios")
        if has_val and not has_hist:
            reasons.append("sin historial de precios (riesgo marginal n/d)")
        if is_company and not has_prod:
            reasons.append("sin FV productivo")
        if is_company and not has_fund:
            reasons.append("sin fundamentales (ROIC/crecimiento/margen)")

        attractive_prod_t = is_company and has_prod and pm is not None and pm >= MIN_MARGIN
        attractive_fcff_t = is_company and has_fcff and fm is not None and fm >= MIN_MARGIN
        usable_prod = has_prod and pm is not None
        # bloqueado SOLO por DCF productivo: FCFF lo haría atractivo, pero el productivo lo impide
        blocked = is_company and attractive_fcff_t and (not usable_prod or (pm is not None and pm < MIN_MARGIN))

        if is_company:
            if not has_val and not has_hist:
                classification["no_evaluable"] += 1
                excluded.append({"ticker": t, "kind": kind, "reasons": reasons})
            elif attractive_prod_t:
                classification["accionable"] += 1       # accionable por VALOR (FV productivo + margen)
                attractive_prod_l.append(t)
            elif blocked:
                classification["atractivo_no_accionable"] += 1
                attractive_fcff_only_l.append(t)
                blocked_by_productive_l.append(t)
            else:
                classification["evaluable_no_atractivo"] += 1
        else:
            # ETF/otro: no clasifican por DCF; si no hay historial, no evaluable para riesgo
            if not has_hist:
                classification["no_evaluable"] += 1
                excluded.append({"ticker": t, "kind": kind, "reasons": reasons})
            else:
                classification["evaluable_no_atractivo"] += 1

        details.append({"ticker": t, "kind": kind, "prod_margin": pm, "fcff_margin": fm,
                        "n_bars": n_bars, "has_fund": has_fund, "reasons": reasons})

    elapsed = round(time.time() - t0, 1)
    return {
        "as_of_run": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "universe": {
            "total": len(universe),
            "from_scan": len(scan_tk), "from_portfolio": len(port_tk), "from_valuations": len(fv),
            "by_kind": by_kind, "eligible_companies": eligible_companies,
        },
        "coverage": {
            "with_any_valuation": with_any_val, "with_productive_fv": with_prod, "with_fcff": with_fcff,
            "with_fundamentals": with_fund, "with_price_history>=2": with_hist,
            f"with_history>={MIN_BARS_RISK}": with_hist_risk,
        },
        "classification": classification,
        "blocked_solely_by_productive_dcf": {
            "count": len(blocked_by_productive_l), "tickers": sorted(blocked_by_productive_l),
            "note": "FCFF los haría atractivos (margen>=10%) pero el FV productivo falta o no es atractivo. "
                    "NO se modifica la regla en P2.3; es el insumo de P2.4.",
        },
        "attractive_by_productive": {"count": len(attractive_prod_l), "tickers": sorted(attractive_prod_l)},
        "excluded_no_evaluable": {"count": len(excluded), "items": excluded[:50]},
        "timing_seconds": elapsed,
        "note": "Diagnóstico de cobertura (solo lectura). No cambia valoración ni recomendaciones.",
    }


def main() -> int:
    out = diagnose()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
