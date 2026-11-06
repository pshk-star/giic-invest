"""Inspección de SOLO LECTURA de tablas en Supabase (no modifica nada).

Comprueba existencia, columnas (desde el OpenAPI de PostgREST) y nº de filas de
fx_rates / etf_holdings / settings. Las políticas RLS no se exponen por REST: para eso se
imprime la consulta SQL exacta que Pablo puede correr en el editor SQL de Supabase.

Uso: python -m app.jobs.inspect_tables
"""
from __future__ import annotations

import json
import os
import sys

TABLES = ["fx_rates", "etf_holdings", "settings", "user_funds", "fund_navs"]

# Tickers a verificar en detalle (evidencia de datos reales llegando a la UI).
FUND_TICKERS = ["ASML", "TSM", "NVDA", "META", "NFLX"]

RLS_SQL = (
    "-- Columnas, tipos y RLS (correr en el editor SQL de Supabase):\n"
    "select table_name, column_name, data_type, is_nullable, column_default\n"
    "  from information_schema.columns\n"
    " where table_schema='public' and table_name in "
    "('fx_rates','etf_holdings','settings')\n"
    " order by table_name, ordinal_position;\n\n"
    "select schemaname, tablename, rowsecurity from pg_tables\n"
    " where schemaname='public' and tablename in ('fx_rates','etf_holdings','settings');\n\n"
    "select tablename, policyname, cmd, qual, with_check from pg_policies\n"
    " where schemaname='public' and tablename in ('fx_rates','etf_holdings','settings')\n"
    " order by tablename, policyname;"
)


def run() -> dict:
    import httpx
    base = os.getenv("SUPABASE_URL", "").rstrip("/") + "/rest/v1"
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    cli = httpx.Client(timeout=30.0, headers=headers)

    # OpenAPI expone las tablas y sus columnas (definitions/properties)
    spec = cli.get(f"{base}/").json()
    defs = spec.get("definitions", spec.get("components", {}).get("schemas", {})) or {}

    out = {}
    for t in TABLES:
        exists = t in defs
        cols = {}
        if exists:
            props = (defs[t] or {}).get("properties", {}) or {}
            cols = {c: (p.get("format") or p.get("type")) for c, p in props.items()}
        # conteo (HEAD con count=exact) — bypass RLS por service role
        n = None
        try:
            r = cli.get(f"{base}/{t}", params={"select": "*", "limit": "0"},
                        headers={"Prefer": "count=exact"})
            cr = r.headers.get("content-range", "")
            if "/" in cr:
                n = cr.split("/")[-1]
        except Exception as e:
            n = f"error: {type(e).__name__}"
        out[t] = {"exists_in_rest": exists, "columns": cols, "row_count": n}
    # volcado de fx_rates (solo lectura) para confirmar par MXN/USD utilizable
    fx = []
    try:
        fx = cli.get(f"{base}/fx_rates", params={"select": "base,currency,rate,as_of",
                                                 "order": "as_of.desc", "limit": "50"}).json()
    except Exception as e:
        fx = [{"error": f"{type(e).__name__}"}]

    # EVIDENCIA: fundamentales reales + precios por ticker objetivo (ASML/TSM/…).
    inlist = ",".join(FUND_TICKERS)
    fundamentals = []
    try:
        fundamentals = cli.get(f"{base}/fundamentals",
                               params={"select": "ticker,payload", "ticker": f"in.({inlist})"}).json()
    except Exception as e:
        fundamentals = [{"error": f"{type(e).__name__}"}]
    prices_now = []
    try:
        prices_now = cli.get(f"{base}/prices",
                             params={"select": "ticker,close,as_of,currency", "ticker": f"in.({inlist})"}).json()
    except Exception as e:
        prices_now = [{"error": f"{type(e).__name__}"}]
    # Comparación de precio para ASML (Prioridad 3): últimas filas de price_history.
    asml_hist = []
    try:
        asml_hist = cli.get(f"{base}/price_history",
                            params={"select": "ticker,close,as_of", "ticker": "eq.ASML",
                                    "order": "as_of.desc", "limit": "3"}).json()
    except Exception as e:
        asml_hist = [{"error": f"{type(e).__name__}"}]

    # Conteo de price_history por ticker (viabilidad de proyección estadística individual).
    hist_counts = {}
    for t in FUND_TICKERS + ["VOO", "QQQ", "SCHD", "GLD", "SLV"]:
        try:
            r = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "limit": "0"},
                        headers={"Prefer": "count=exact"})
            cr = r.headers.get("content-range", "")
            hist_counts[t] = int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else cr
        except Exception as e:
            hist_counts[t] = f"error: {type(e).__name__}"

    # Validación del historial: rango REAL (min/max con consultas de 1 fila), campos de
    # ajuste/proveedor, y chequeo de saltos sobre las 1000 MÁS RECIENTES (order desc).
    hist_validation = {}
    for t in ["ASML", "TSM", "NVDA"]:
        try:
            cnt = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "limit": "0"},
                          headers={"Prefer": "count=exact"})
            total = cnt.headers.get("content-range", "").split("/")[-1]
            first = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "order": "as_of.asc", "limit": "1"}).json()
            last = cli.get(f"{base}/price_history", params={"select": "as_of,close,adjusted,source", "ticker": f"eq.{t}", "order": "as_of.desc", "limit": "1"}).json()
            recent = cli.get(f"{base}/price_history", params={"select": "as_of,close", "ticker": f"eq.{t}", "order": "as_of.desc", "limit": "1000"}).json()
            recent = list(reversed(recent))
            closes = [float(r["close"]) for r in recent if r.get("close") is not None]
            rets = [abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1] > 0]
            hist_validation[t] = {
                "total_rows": total,
                "min_date": (first[0]["as_of"] if first else None),
                "max_date": (last[0]["as_of"] if last else None),
                "last_close": (last[0].get("close") if last else None),
                "adjusted_field": (last[0].get("adjusted") if last else None),
                "source_field": (last[0].get("source") if last else None),
                "recent_sample": len(closes),
                "max_abs_daily_return_recent1000": round(max(rets), 4) if rets else None,
                "days_over_40pct_recent1000": sum(1 for r in rets if r > 0.40),
            }
        except Exception as e:
            hist_validation[t] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

    return {
        "tables": out, "fx_rates_rows": fx,
        "fundamentals_target": fundamentals,
        "prices_target": prices_now,
        "asml_price_history_latest": asml_hist,
        "price_history_counts": hist_counts,
        "price_history_validation": hist_validation,
        "edgar_diagnostic": edgar_diag(["ASML", "TSM"]),
        "rls_sql_for_pablo": RLS_SQL,
    }


def edgar_diag(tickers: list) -> dict:
    """Diagnóstico EN VIVO de companyfacts de EDGAR: qué taxonomías y conceptos
    publica cada emisor (causa raíz de cobertura). Requiere EDGAR_USER_AGENT.
    Usa httpx directo (sin importar el provider, que depende de pandas)."""
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=30.0, headers={"User-Agent": ua})
    try:
        tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    except Exception as e:
        return {"error": f"company_tickers: {type(e).__name__}: {str(e)[:80]}"}
    cikmap = {row["ticker"].upper(): int(row["cik_str"]) for row in tk.values()}
    KEYS = ("revenue", "profit", "netincome", "earningspershare", "equity",
            "operatingactivities", "cashflowsfromused")
    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"cik": None, "note": "ticker no está en company_tickers.json de la SEC"}
            continue
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                out[t] = {"cik": cik, "http_status": r.status_code}
                continue
            facts = r.json()
        except Exception as e:
            out[t] = {"cik": cik, "error": f"{type(e).__name__}: {str(e)[:80]}"}
            continue
        f = (facts.get("facts", {}) or {})
        summ = {"cik": cik, "taxonomies": list(f.keys())}
        for tax in ("us-gaap", "ifrs-full"):
            node = f.get(tax)
            if not node:
                continue
            interesting = [c for c in node.keys() if any(k in c.lower() for k in KEYS)][:25]
            detail = {}
            for c in interesting[:12]:
                u = list((node[c].get("units", {}) or {}).keys())
                rows = (node[c].get("units", {}) or {}).get(u[0], []) if u else []
                last = rows[-1] if rows else {}
                detail[c] = {"units": u, "last_form": last.get("form"), "last_end": last.get("end")}
            # Todas las unidades "per share" (para detectar EPS en USD por ADR) + último valor
            # real de EPS por unidad (resuelve si el USD es por ADR o por acción ordinaria).
            per_share = {}
            eps_values = {}
            for c in node.keys():
                cl = c.lower()
                if "pershare" in cl:
                    units = (node[c].get("units", {}) or {})
                    u = list(units.keys())
                    if u:
                        per_share[c] = u
                    if "earningspershare" in cl or cl.startswith("dilutedearnings") or cl.startswith("basicearnings"):
                        for un, rows in units.items():
                            annual = [r for r in rows if str(r.get("form", "")).startswith(("10-K", "20-F", "40-F"))
                                      and r.get("start") and r.get("end")]
                            if annual:
                                last = sorted(annual, key=lambda r: r["end"])[-1]
                                eps_values[f"{c} [{un}]"] = {"val": last.get("val"), "end": last.get("end"), "form": last.get("form")}
            summ[tax] = {"n_concepts": len(node), "concepts": interesting,
                         "detail": detail, "per_share_units": per_share, "eps_latest": eps_values}
        out[t] = summ
    return out


def main(argv=None):
    try:
        out = run()
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-800:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
