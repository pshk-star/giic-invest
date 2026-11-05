"""Job principal: ejecuta el scanner sobre el universo y guarda resultados en Supabase.

Lo invoca GitHub Actions (cron diario tras el cierre de EE. UU. y manual). Reutiliza
el núcleo v0.2 y los proveedores gratuitos. No depende de la computadora del usuario.

Uso:
    python -m app.jobs.run_scan                 # free + escribe en Supabase (producción)
    python -m app.jobs.run_scan --provider sample --dry-run   # prueba sin red ni escritura

Variables de entorno (producción):
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, EDGAR_USER_AGENT (email de contacto)
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import date, datetime

from ..core.types import AssetClass, Instrument
from ..providers import get_provider
from ..services.scan_engine import run_scan as run_scan_engine
from .instruments import build_universe_instrument_rows, resolve_extra_tickers
from .supabase_writer import SupabaseWriter, build_run_row, build_snapshot_rows
from .universe import UNIVERSE_VERSION, get_universe
from .validation import validate_scan_result

ALGO_VERSION = "scanner-v1"


class ScanRejected(Exception):
    """El scan no pasó la validación de calidad; no se publica nada."""


def publish_run(writer, run_id, run_row, snapshot_rows, price_rows, fund_rows, fx_rows) -> None:
    """Publicación ATÓMICA: inserta la corrida 'pending', escribe todo y la marca
    'completed'. Si algo falla a mitad, la marca 'failed' y relanza; el frontend solo
    consulta corridas 'completed', así nunca ve datos a medias."""
    writer.insert("scan_runs", run_row)  # status='pending'
    try:
        writer.upsert("scan_snapshots", snapshot_rows, on_conflict="run_id,ticker")
        if price_rows:
            writer.upsert("prices", price_rows, on_conflict="ticker")
        if fund_rows:
            writer.upsert("fundamentals", fund_rows, on_conflict="ticker")
        if fx_rows:
            writer.upsert("fx_rates", fx_rows, on_conflict="currency")
        writer.update_run_status(run_id, "completed")
    except Exception as e:
        try:
            writer.update_run_status(run_id, "failed", error=f"{type(e).__name__}: {e}")
        except Exception:
            pass
        raise


def execute(provider_name: str = "free", top: int = 50, dry_run: bool = False,
            sector_relative: bool = True, allow_sample_write: bool = False,
            writer=None) -> dict:
    today = date.today()
    run_id = str(uuid.uuid4())

    kwargs = {}
    if provider_name in ("free", "edgar"):
        ua = os.getenv("EDGAR_USER_AGENT", "")
        kwargs["edgar_user_agent"] = ua
        kwargs["user_agent"] = ua
    provider = get_provider(provider_name, **kwargs)

    # Writer temprano (si corresponde) para leer tickers de la cartera y extender el
    # universo: así los instrumentos que el usuario tiene reciben precio e identificación.
    # Solo si hay credenciales (si no, la validación sigue su curso y puede rechazar).
    if writer is None and not dry_run and os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""),
                                os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    universe = get_universe()
    universe_tickers = {i.ticker for i in universe}
    extra_tickers: list[str] = []
    if writer is not None:
        try:
            extra_tickers = [t for t in writer.get_transaction_tickers()
                             if t not in universe_tickers]
        except Exception:
            extra_tickers = []
        for t in extra_tickers:
            universe.append(Instrument(ticker=t, name=t, asset_class=AssetClass.EQUITY,
                                       exchange="US", country="US", sector=None, currency="USD"))

    result = run_scan_engine(
        provider, universe, cache=None,
        today=today, top=top, batch_size=25,
        min_coverage=0.4, sector_relative=sector_relative,
    )

    as_of = today.isoformat()
    run_row = build_run_row(run_id, as_of, result, UNIVERSE_VERSION, ALGO_VERSION)
    snapshot_rows = build_snapshot_rows(result, run_id, as_of, UNIVERSE_VERSION, ALGO_VERSION)

    summary = {
        "run_id": run_id, "as_of": as_of, "provider": provider.health().get("provider"),
        "using_sample_data": result.get("using_sample_data"),
        "evaluated": result.get("evaluated"), "snapshots": len(snapshot_rows),
        "usable_factors": result.get("usable_factors"),
        "top3": [(r["ticker"], r["composite"]) for r in result.get("ranking", [])[:3]],
    }

    # Validación de calidad: bloquea publicar sample, vacío, incompleto u obsoleto.
    ok, reasons = validate_scan_result(result, today, allow_sample=allow_sample_write)
    summary["valid"] = ok
    summary["validation_reasons"] = reasons

    if dry_run:
        summary["written"] = False
        return summary

    if not ok:
        # No se escribe NADA: se conservan los datos válidos de la corrida anterior.
        raise ScanRejected("; ".join(reasons))

    if writer is None:
        writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""),
                                os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))

    # Datos de mercado con la FECHA REAL del dato por ticker (no la fecha de corrida).
    # (price_rows/fund_rows/fx_rows se construyen abajo y se publican con publish_run)
    price_rows = [{"ticker": t, "close": m["close"], "as_of": m["as_of"], "currency": "USD"}
                  for t, m in result.get("market_prices", {}).items() if m.get("close") is not None]
    fund_rows = [{"ticker": t, "payload": p}
                 for t, p in result.get("fundamentals_payload", {}).items()]
    base = os.getenv("BASE_CURRENCY", "USD")
    rates = provider.get_fx_rates(base, ["MXN", "EUR", "CLP", "BRL", "TWD", "JPY", "HKD", "GBP", "CAD"])
    fx_rows = [{"currency": c, "base": base, "rate": float(r), "as_of": as_of}
               for c, r in rates.items()]

    publish_run(writer, run_id, run_row, snapshot_rows, price_rows, fund_rows, fx_rows)

    # Identificación de instrumentos (Fase A): universo curado + tickers extra de la
    # cartera. Best-effort: no debe tumbar la corrida ya publicada.
    try:
        inst_rows = build_universe_instrument_rows()
        if extra_tickers:
            inst_rows += resolve_extra_tickers(extra_tickers, get_provider("yahoo"), {})
        writer.upsert("instruments", inst_rows, on_conflict="ticker")
        summary["instruments_written"] = len(inst_rows)
    except Exception as e:
        summary["instruments_error"] = f"{type(e).__name__}: {str(e)[:120]}"

    summary["written"] = True
    summary["status"] = "completed"
    summary["prices_written"] = len(price_rows)
    summary["fundamentals_written"] = len(fund_rows)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC scanner job")
    p.add_argument("--provider", default="free", help="free | sample | eodhd | fmp")
    p.add_argument("--top", type=int, default=50)
    p.add_argument("--dry-run", action="store_true", help="no escribe en Supabase")
    p.add_argument("--no-sector-relative", action="store_true")
    p.add_argument("--allow-sample-write", action="store_true",
                   help="(solo pruebas) permite publicar datos de ejemplo")
    args = p.parse_args(argv)

    import json
    try:
        summary = execute(args.provider, args.top, args.dry_run,
                          not args.no_sector_relative, args.allow_sample_write)
    except ScanRejected as e:
        # Mensaje sin secretos: solo los motivos de validación.
        print(json.dumps({"written": False, "rejected": True, "reasons": str(e)}, indent=2))
        return 2
    except Exception as e:
        # Nunca volcar el entorno; solo el tipo y un mensaje corto y seguro.
        print(json.dumps({"written": False, "error": type(e).__name__,
                          "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
