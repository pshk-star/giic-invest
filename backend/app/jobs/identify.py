"""Identificación + precio de instrumentos de la cartera — INDEPENDIENTE del scan.

Motivación: antes la identificación y el precio de un ticker nuevo dependían de que el
scan diario completo se ejecutara Y pasara la validación de calidad. Si el scan era
rechazado (datos obsoletos, cobertura baja, etc.), un ticker recién registrado se
quedaba sin nombre ni precio indefinidamente. Este job NO tiene ese acoplamiento:

    1. Lee los tickers presentes en `transactions` (service role, solo tickers).
    2. Resuelve metadatos (nombre/tipo/bolsa/moneda) vía Yahoo y los upsert en `instruments`.
    3. Obtiene el PRECIO de cierre más reciente vía Yahoo y lo upsert en `prices`.
    4. Opcional (--with-catalog): recarga el catálogo completo de Nasdaq Trader.

Así, tras registrar una posición, un disparo de este job (manual desde Actions o el
cron semanal) deja el instrumento reconocido y con precio, sin esperar al scan.

Uso:
    python -m app.jobs.identify                 # identifica+precio de la cartera
    python -m app.jobs.identify --with-catalog  # además recarga el catálogo US completo
    python -m app.jobs.identify --dry-run       # no escribe (requiere credenciales para leer)

Variables de entorno: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from .catalog import load_catalog
from .instruments import resolve_extra_tickers
from .supabase_writer import SupabaseWriter


def identify_portfolio(writer, yahoo, tickers) -> dict:
    """Resuelve identidad y precio de una lista de tickers. Best-effort por ticker."""
    inst_rows = resolve_extra_tickers(tickers, yahoo, {})
    quotes = {}
    try:
        quotes = yahoo.get_quotes(tickers)
    except Exception:
        quotes = {}
    price_rows = []
    for t, q in quotes.items():
        price_rows.append({
            "ticker": t.upper(),
            "close": float(q.price),
            "as_of": q.as_of.isoformat() if hasattr(q.as_of, "isoformat") else str(q.as_of),
            "currency": getattr(q, "currency", "USD") or "USD",
        })
    inst_written = writer.upsert("instruments", inst_rows, on_conflict="ticker")
    price_written = writer.upsert("prices", price_rows, on_conflict="ticker") if price_rows else 0
    resolved = [r["ticker"] for r in inst_rows if r["status"] == "resolved"]
    pending = [r["ticker"] for r in inst_rows if r["status"] != "resolved"]
    priced = [r["ticker"] for r in price_rows]
    return {
        "requested": len(tickers),
        "instruments_written": inst_written,
        "prices_written": price_written,
        "resolved": sorted(resolved),
        "pending": sorted(pending),           # identificados pero sin tipo fiable
        "priced": sorted(priced),
        "unpriced": sorted(set(t.upper() for t in tickers) - set(priced)),
    }


def execute(with_catalog: bool = False, dry_run: bool = False, extra_tickers=None) -> dict:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    writer = SupabaseWriter(url, key)

    from ..providers import get_provider
    yahoo = get_provider("yahoo")

    summary = {"ts": datetime.utcnow().isoformat(), "with_catalog": with_catalog}

    if with_catalog and not dry_run:
        try:
            summary.update(load_catalog(writer))
        except Exception as e:
            summary["catalog_error"] = f"{type(e).__name__}: {str(e)[:150]}"

    tickers = list(extra_tickers) if extra_tickers else writer.get_transaction_tickers()
    summary["portfolio_tickers"] = tickers
    if dry_run:
        summary["written"] = False
        return summary
    if tickers:
        summary.update(identify_portfolio(writer, yahoo, tickers))
    summary["written"] = True
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC identify+price job (independiente del scan)")
    p.add_argument("--with-catalog", action="store_true", help="recarga el catálogo US completo")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tickers", nargs="*", help="(prueba) lista explícita en lugar de la cartera")
    args = p.parse_args(argv)
    try:
        summary = execute(args.with_catalog, args.dry_run, args.tickers)
    except Exception as e:
        print(json.dumps({"written": False, "error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
