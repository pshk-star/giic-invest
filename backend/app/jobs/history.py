"""Job de HISTÓRICO de precios: serie diaria ajustada para Research y forecasting.

Dos modos:
  - backfill (por defecto): trae la serie histórica (adjclose+volumen) de Yahoo para
    cartera + universo y la escribe con reconstructed=true (histórico reconstruido hoy,
    NO una captura point-in-time de su día).
  - --daily: añade el último cierre del día con reconstructed=false (captura real EOD).

Idempotente: upsert por (ticker, as_of). No requiere la computadora del usuario.

Uso:
    python -m app.jobs.history --backfill --range 5y
    python -m app.jobs.history --daily
    python -m app.jobs.history --backfill --dry-run --tickers NFLX NVDA
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


def _targets(writer, explicit) -> list[str]:
    if explicit:
        return [t.upper() for t in explicit]
    uni = {i.ticker.upper() for i in get_universe(include_etfs=True)}
    port = set()
    if writer is not None:
        try:
            port = {t.upper() for t in writer.get_transaction_tickers()}
        except Exception:
            port = set()
    return sorted(uni | port)


def execute(backfill: bool, daily: bool, rng: str, dry_run: bool, tickers=None) -> dict:
    url = os.getenv("SUPABASE_URL", ""); key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    writer = None
    if not dry_run:
        writer = SupabaseWriter(url, key)
    elif url and key:
        try: writer = SupabaseWriter(url, key)
        except Exception: writer = None

    yahoo = get_provider("yahoo")
    tk = _targets(writer, tickers)
    use_range = "5d" if (daily and not backfill) else rng
    reconstructed = not (daily and not backfill)

    rows, per_ticker = [], {}
    now = datetime.utcnow().isoformat()
    for t in tk:
        bars = yahoo.get_history_bars(t, rng=use_range)
        if daily and not backfill:
            bars = bars[-1:]  # solo el último cierre
        for b in bars:
            rows.append({
                "ticker": t, "as_of": b["as_of"], "close": b["close"], "volume": b["volume"],
                "adjusted": True, "reconstructed": reconstructed, "source": "yahoo", "updated_at": now,
            })
        per_ticker[t] = len(bars)

    summary = {
        "ts": now, "mode": "daily" if (daily and not backfill) else "backfill",
        "range": use_range, "tickers": len(tk), "rows": len(rows),
        "empty": sorted([t for t, n in per_ticker.items() if n == 0])[:20],
        "sample": {t: per_ticker[t] for t in tk[:5]},
    }
    if dry_run:
        summary["written"] = False
        return summary
    if writer is None:
        raise RuntimeError("Faltan credenciales de Supabase.")
    written = 0
    for i in range(0, len(rows), 1000):
        chunk = rows[i:i + 1000]
        writer.upsert("price_history", chunk, on_conflict="ticker,as_of")
        written += len(chunk)
    summary["written"] = True
    summary["rows_written"] = written
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC price history job")
    p.add_argument("--backfill", action="store_true", help="serie histórica completa (reconstruida)")
    p.add_argument("--daily", action="store_true", help="solo el último cierre (captura EOD)")
    p.add_argument("--range", default="5y", help="rango para backfill: 1y|2y|5y|10y|max")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    backfill = args.backfill or not args.daily  # por defecto backfill
    try:
        summary = execute(backfill, args.daily, args.range, args.dry_run, args.tickers)
    except Exception as e:
        print(json.dumps({"written": False, "error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
