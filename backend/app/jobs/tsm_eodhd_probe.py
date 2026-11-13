"""Diagnóstico puntual: qué devuelve EODHD para los símbolos de TSM (2330.TW vs TSM.US).

Objetivo (sección 7): determinar si el balance (equity/deuda/caja) existe en algún símbolo para poder
valorar TSM con datos internacionales, en vez de dejarla no_valorable. Read-only, sin escritura.
"""
from __future__ import annotations

import json
import os
import sys


def run():
    from app.core.connectors.eodhd import EodhdFundamentalsConnector
    c = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
    out = {}
    for s in ("2330.TW", "TSM.US"):
        obj = c._get(s)
        fin = (obj or {}).get("Financials", {}) or {}
        bs = (fin.get("Balance_Sheet", {}) or {})
        bs_y = (bs.get("yearly", {}) or {})
        latest = sorted(bs_y.keys())[-1] if bs_y else None
        row = bs_y.get(latest, {}) if latest else {}
        inc = (fin.get("Income_Statement", {}) or {}).get("yearly", {}) or {}
        li = sorted(inc.keys())[-1] if inc else None
        out[s] = {
            "tiene_Financials": bool(fin),
            "moneda": (fin.get("Income_Statement", {}) or {}).get("currency_symbol"),
            "ultimo_balance": latest,
            "balance_keys_no_nulas": sorted(k for k, v in row.items() if v not in (None, "", "0", "0.0")) [:40],
            "equity": row.get("totalStockholderEquity") or row.get("totalEquity"),
            "cash": row.get("cashAndEquivalents") or row.get("cash") or row.get("cashAndShortTermInvestments"),
            "deuda_lt": row.get("longTermDebt"), "deuda_total": row.get("shortLongTermDebtTotal"),
            "acciones": row.get("commonStockSharesOutstanding"),
            "ultimo_income": li,
            "revenue": (inc.get(li, {}) or {}).get("totalRevenue") if li else None,
            "ebit": (inc.get(li, {}) or {}).get("operatingIncome") if li else None,
        }
    # Reproducir reconcile+normalize reales (EDGAR Supabase + EODHD) para ver el capital invertido
    try:
        from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows
        from app.research.valuation_engine import reconcile, normalize, _last
        from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full
        from app.jobs.supabase_writer import SupabaseWriter
        w = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
        erows = fetch_edgar_rows(w, "TSM")
        edgar = build_series_from_rows(erows) if erows else {"currency": None, "by_field": {}}
        conn = EodhdFundamentalsConnector(api_key=os.getenv("EODHD_API_KEY", ""))
        _s, _a, obj = conn._resolve("TSM")
        eod = eodhd_annual_series_full(obj) if obj else {"currency": None, "by_field": {}}
        rec = reconcile(edgar, eod)
        diag = {"moneda_edgar": edgar.get("currency"), "moneda_eodhd": eod.get("currency"),
                "moneda_reconciliada": rec.currency}
        for f in ("equity", "total_debt", "cash", "invested_capital"):
            diag[f] = {"reconc_last": (_last(rec.by_field.get(f, {}) or {}) or (None, None))[1],
                       "fuente": rec.provenance.get(f),
                       "edgar_last": (_last(edgar.get("by_field", {}).get(f, {}) or {}) or (None, None))[1],
                       "eodhd_last": (_last(eod.get("by_field", {}).get(f, {}) or {}) or (None, None))[1]}
        out["_reconcile_TSM"] = diag
    except Exception as e:
        out["_reconcile_TSM_error"] = str(e)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(run())
