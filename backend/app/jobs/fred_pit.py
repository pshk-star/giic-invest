"""Ingesta macroeconómica POINT-IN-TIME desde FRED/ALFRED -> macro_pit.

Usa ALFRED (realtime_start/realtime_end) para conservar VINTAGES: cada versión de una
observación es una fila (obs_date, value, release_date=realtime_start, vintage). Así, en
backtest, el valor conocido en D = el de mayor vintage con vintage<=D (nunca una revisión
futura). Series sin revisiones (p.ej. tasas diarias) tienen un solo vintage; se registra.

Secret: FRED_API_KEY (nunca se imprime). Append-only via ignore-duplicates.

Uso: python -m app.jobs.fred_pit --dry-run   |   python -m app.jobs.fred_pit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from typing import Dict, List, Optional

# Series oficiales FRED. revisable=True => esperamos múltiples vintages (datos revisados).
SERIES: List[Dict] = [
    {"id": "DFF", "label": "Fed funds effective rate", "revisable": False},
    {"id": "DGS2", "label": "Treasury 2Y", "revisable": False},
    {"id": "DGS10", "label": "Treasury 10Y", "revisable": False},
    {"id": "T10Y2Y", "label": "Pendiente curva 10Y-2Y", "revisable": False},
    {"id": "CPIAUCSL", "label": "CPI", "revisable": True},
    {"id": "CPILFESL", "label": "Core CPI", "revisable": True},
    {"id": "PCEPI", "label": "PCE", "revisable": True},
    {"id": "PCEPILFE", "label": "Core PCE", "revisable": True},
    {"id": "UNRATE", "label": "Desempleo", "revisable": True},
    {"id": "INDPRO", "label": "Producción industrial", "revisable": True},
    {"id": "NFCI", "label": "Chicago Fed Financial Conditions", "revisable": True},
    {"id": "BAMLH0A0HYM2", "label": "HY credit spread (OAS)", "revisable": False},
    {"id": "WALCL", "label": "Balance Fed (liquidez)", "revisable": False},
    {"id": "M2SL", "label": "M2 (liquidez)", "revisable": True},
]

ALFRED_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_fred_observations(payload: dict, series_id: str) -> List[dict]:
    """Convierte observaciones ALFRED (con realtime) en filas macro_pit (puro)."""
    out: List[dict] = []
    seen_by_date: Dict[str, int] = {}
    obs = (payload or {}).get("observations", []) or []
    # ordenar por fecha y realtime_start para numerar revisiones
    obs_sorted = sorted(obs, key=lambda o: (o.get("date", ""), o.get("realtime_start", "")))
    for o in obs_sorted:
        val = o.get("value")
        d = o.get("date")
        rt = o.get("realtime_start")
        if val in (None, ".", "") or not d or not rt:
            continue
        try:
            v = float(val)
        except ValueError:
            continue
        rev = seen_by_date.get(d, 0)
        seen_by_date[d] = rev + 1
        out.append({
            "provider": "alfred", "series_id": series_id, "obs_date": d,
            "value": v, "release_date": rt, "vintage": rt, "revision": rev,
        })
    return out


class FredError(Exception):
    pass


def fetch_series(client, series_id: str, api_key: str) -> List[dict]:
    params = {
        "series_id": series_id, "api_key": api_key, "file_type": "json",
        "realtime_start": "1776-07-04", "realtime_end": "9999-12-31",
    }
    r = client.get(ALFRED_URL, params=params)
    if r.status_code != 200:
        # Diagnóstico SIN filtrar la clave (FRED no la repite en el cuerpo de error).
        raise FredError(f"HTTP {r.status_code}: {r.text[:180]}")
    return parse_fred_observations(r.json(), series_id)


def execute(dry_run: bool = False) -> dict:
    api_key = os.getenv("FRED_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Falta FRED_API_KEY.")
    import httpx
    client = httpx.Client(timeout=30.0, headers={"User-Agent": "giic-macro/1.0"})

    writer = None
    if not dry_run:
        from .supabase_writer import SupabaseWriter
        writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))

    per, total, written = {}, 0, 0
    novint = []  # series sin vintages reales (una sola versión por observación)
    for s in SERIES:
        try:
            rows = fetch_series(client, s["id"], api_key)
        except Exception as e:
            per[s["id"]] = f"error: {str(e)[:200]}"
            continue
        # ¿tiene vintages? (más filas que fechas distintas => hay revisiones)
        dates = {r["obs_date"] for r in rows}
        has_vintages = len(rows) > len(dates)
        if s["revisable"] and not has_vintages:
            novint.append(s["id"])
        per[s["id"]] = {"rows": len(rows), "dates": len(dates), "has_vintages": has_vintages,
                        "first": min(dates) if dates else None, "last": max(dates) if dates else None}
        total += len(rows)
        if not dry_run and rows:
            for i in range(0, len(rows), 1000):
                written += writer.insert_append("macro_pit", rows[i:i + 1000],
                                                on_conflict="provider,series_id,obs_date,vintage")

    client.close()
    summary = {"series": len(SERIES), "rows_total": total, "coverage": per,
               "revisable_sin_vintages": novint}
    if dry_run:
        summary["written"] = False
        return summary
    writer.upsert("data_coverage", [{
        "dataset": "macro_pit:alfred", "provider": "alfred", "as_of": date.today().isoformat(),
        "is_complete": len(novint) == 0, "n_rows": written,
        "note": f"FRED/ALFRED {len(SERIES)} series; sin vintages reales: {','.join(novint) or 'ninguna'}.",
    }], on_conflict="dataset,provider")
    summary["rows_written"] = written
    summary["written"] = True
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC FRED/ALFRED macro ingestion")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    try:
        out = execute(args.dry_run)
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
