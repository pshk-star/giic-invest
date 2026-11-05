"""Prueba de extremo a extremo con DATOS REALES, sin escribir en Supabase y sin tu
cartera. Sirve para comprobar, antes de introducir tus posiciones, que las fuentes
gratuitas responden con datos reales y frescos y que el scanner produce un ranking
válido.

Uso:
    python -m app.jobs.selftest                 # proveedor 'free' (real; necesita red)
    python -m app.jobs.selftest --provider sample   # harness offline (datos de ejemplo)

Requiere EDGAR_USER_AGENT (correo de contacto) para el proveedor 'free'. Devuelve
código 0 si todo pasa; distinto de 0 si algo falla. No escribe nada ni expone secretos.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from ..providers import get_provider
from ..services.scan_engine import run_scan as run_scan_engine
from .universe import get_universe
from .validation import validate_scan_result

CHECK_TICKERS = ["MSFT", "NVDA", "SPY"]


def run_checks(provider_name: str = "free") -> dict:
    kwargs = {}
    if provider_name in ("free", "edgar"):
        ua = os.getenv("EDGAR_USER_AGENT", "")
        kwargs["edgar_user_agent"] = ua
        kwargs["user_agent"] = ua
    provider = get_provider(provider_name, **kwargs)
    today = date.today()
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    def safe(name, fn):
        """Ejecuta una verificación; un error (p.ej. timeout) la marca fallida sin
        abortar las demás."""
        try:
            fn()
        except Exception as e:
            add(name, False, {"error": type(e).__name__, "message": str(e)[:150]})

    # 1) Precios reales con fecha
    def _precios():
        quotes = provider.get_quotes(CHECK_TICKERS)
        add("precios", len(quotes) >= 2 and all(q.price > 0 for q in quotes.values()),
            {t: {"price": q.price, "as_of": q.as_of.isoformat(), "is_sample": q.is_sample}
             for t, q in quotes.items()})
    safe("precios", _precios)

    # 2) Histórico
    def _hist():
        from datetime import timedelta
        h = provider.get_price_history("MSFT", start=today - timedelta(days=550))
        add("historico", h is not None and len(h) > 20, {"puntos": int(len(h) if h is not None else 0)})
    safe("historico", _hist)

    # 3) Fundamentales
    def _fund():
        funds = provider.get_fundamentals(["MSFT"])
        f = funds.get("MSFT")
        add("fundamentales", f is not None and (f.net_margin is not None or f.rev_growth_yoy is not None),
            {"net_margin": getattr(f, "net_margin", None), "rev_growth_yoy": getattr(f, "rev_growth_yoy", None)} if f else None)
    safe("fundamentales", _fund)

    # 4) FX
    def _fx():
        rates = provider.get_fx_rates("USD", ["MXN", "EUR"])
        add("fx", "MXN" in rates and rates.get("MXN", 0) > 0, {k: rates[k] for k in rates if k in ("MXN", "EUR")})
    safe("fx", _fx)

    # 5) Scanner + validación sobre un universo reducido.
    # Con datos reales exigimos cobertura fundamental alta (0.4); el harness offline
    # (sample) usa un umbral menor porque sus fundamentales son intencionalmente ralos.
    result = {}

    def _scan():
        nonlocal result
        # Universo reducido y fijo: basta para probar el flujo real sin esperas largas.
        # Estos 6 existen tanto en datos reales (EDGAR+Stooq) como en el proveedor de ejemplo.
        wanted = {"NVDA", "MSFT", "AVGO", "META", "NFLX", "GOOGL"}
        universe = [i for i in get_universe(include_etfs=False) if i.ticker in wanted]
        min_cov = 0.2 if provider.is_sample else 0.4
        result = run_scan_engine(provider, universe, cache=None, today=today, top=10,
                                 min_coverage=min_cov, sector_relative=True)
        ok_valid, reasons = validate_scan_result(result, today, min_evaluated=3,
                                                 allow_sample=provider.is_sample)
        add("scanner_validez", ok_valid and len(result.get("ranking", [])) > 0,
            {"evaluated": result.get("evaluated"), "usable_factors": result.get("usable_factors"),
             "reasons": reasons, "fetch_errors": result.get("fetch_errors"),
             "top3": [(r["ticker"], r["composite"]) for r in result.get("ranking", [])[:3]]})
    safe("scanner_validez", _scan)

    all_ok = all(c["ok"] for c in checks)
    return {"provider": provider_name, "using_sample_data": result.get("using_sample_data"),
            "all_ok": all_ok, "checks": checks}


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC selftest E2E (datos reales)")
    p.add_argument("--provider", default="free", help="free | sample")
    args = p.parse_args(argv)
    try:
        report = run_checks(args.provider)
    except Exception as e:
        print(json.dumps({"all_ok": False, "error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["all_ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
