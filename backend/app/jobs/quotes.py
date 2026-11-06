"""Job de COTIZACIONES: toma el último precio disponible (retrasado) y lo escribe en
`quotes`. Lo dispara GitHub Actions cada ~15 min en horario de mercado US. Independiente
del scan y del EOD; no requiere la computadora del usuario.

Diseño ($0, estable, legal):
  - Fuente: Yahoo chart (range=1d, interval=2m) — la misma que ya funciona desde Actions.
  - NO es tiempo real: se marca delayed=true y se guarda la hora REAL de la cotización.
  - Si una cotización falla, NO se toca la fila previa (se conserva el último valor válido).
  - Universo acotado (cartera + universo del scanner) para no agotar cuotas ni Supabase.

Uso:
    python -m app.jobs.quotes                 # cartera + universo -> escribe en Supabase
    python -m app.jobs.quotes --dry-run       # imprime snapshots, NO escribe
    python -m app.jobs.quotes --tickers TSM ASML NVDA QQQ --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from ..providers import get_provider
from .supabase_writer import SupabaseWriter
from .universe import get_universe


def collect_tickers(writer) -> list[str]:
    uni = [i.ticker for i in get_universe(include_etfs=True)]
    port: list[str] = []
    if writer is not None:
        try:
            port = writer.get_transaction_tickers()
        except Exception:
            port = []
    # cartera primero (prioridad), luego universo; sin duplicados
    seen, out = set(), []
    for t in port + uni:
        u = t.upper()
        if u not in seen:
            seen.add(u); out.append(u)
    return out


def execute(dry_run: bool = False, tickers=None) -> dict:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    writer = None
    if not dry_run or (url and key):
        try:
            writer = SupabaseWriter(url, key)
        except Exception:
            writer = None

    tk = [t.upper() for t in tickers] if tickers else collect_tickers(writer)
    yahoo = get_provider("yahoo")
    snaps = yahoo.get_quote_snapshots(tk)

    rows = []
    now = datetime.utcnow().isoformat()
    for t, s in snaps.items():
        r = dict(s); r["updated_at"] = now
        rows.append(r)

    summary = {
        "ts": now, "requested": len(tk), "quoted": len(rows),
        "missing": sorted(set(tk) - set(snaps.keys()))[:20],
        "sample": {t: {"price": snaps[t]["price"], "change_pct": snaps[t]["change_pct"],
                       "market_state": snaps[t]["market_state"], "quote_time": snaps[t]["quote_time"]}
                   for t in list(snaps.keys())[:6]},
    }
    if dry_run:
        summary["written"] = False
        return summary
    if writer is None:
        raise RuntimeError("Faltan credenciales de Supabase para escribir cotizaciones.")
    if rows:
        # on_conflict=ticker: si una cotización falla no está en rows, por lo que su fila
        # previa se conserva intacta (nunca se sobrescribe con cero ni se borra).
        writer.upsert("quotes", rows, on_conflict="ticker")
    summary["written"] = True
    summary["quotes_written"] = len(rows)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC quotes job")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    try:
        summary = execute(args.dry_run, args.tickers)
    except Exception as e:
        print(json.dumps({"written": False, "error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
