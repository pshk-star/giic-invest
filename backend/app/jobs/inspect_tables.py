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
    return {"tables": out, "fx_rates_rows": fx, "rls_sql_for_pablo": RLS_SQL}


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
