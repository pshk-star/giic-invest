"""Persistencia automática de la IDENTIDAD de instrumentos (Fase 2).

Resuelve identidad (Yahoo chart.meta + SEC EDGAR companyfacts/submissions + OpenFIGI)
para los tickers de la cartera y la escribe en public.instruments (columnas de 0012).
SEGURO: si la migración 0012 no está aplicada (faltan columnas), aborta sin escribir y
lo reporta; no toca el pipeline de identify ni las predicciones A/B/C.

Uso:
    python -m app.jobs.resolve_identity --dry-run
    python -m app.jobs.resolve_identity --tickers NVDA TSM ASML VOO MELI
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from ..services.identity import resolve_identity
from .supabase_writer import SupabaseWriter


def _client(ua: str):
    import httpx
    return httpx.Client(timeout=30.0, headers={"User-Agent": ua})


def _cik_map(cli):
    try:
        return {r["ticker"].upper(): int(r["cik_str"]) for r in cli.get("https://www.sec.gov/files/company_tickers.json").json().values()}
    except Exception:
        return {}


def _yahoo_meta(cli, t):
    try:
        p = cli.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}", params={"range": "5d", "interval": "1d"}).json()
        m = (((p or {}).get("chart", {}) or {}).get("result") or [{}])[0].get("meta", {}) or {}
        it = (m.get("instrumentType") or "").upper()
        return {"name": m.get("longName") or m.get("shortName"),
                "asset_class": "equity" if it == "EQUITY" else "etf" if it == "ETF" else "unknown",
                "quote_currency": m.get("currency"), "currency": m.get("currency"),
                "exchange": m.get("fullExchangeName") or m.get("exchangeName"),
                "exchange_code": m.get("exchangeName"), "timezone": m.get("exchangeTimezoneName")}
    except Exception:
        return {}


def _edgar(cli, cik):
    """(report_currency, taxonomy, stateOfIncorporation, business_stateOrCountry)."""
    if not cik:
        return (None, None, None, None)
    rc, tax, incorp, bsc = None, None, None, None
    try:
        facts = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json().get("facts", {})
        for t, names in (("us-gaap", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss"]),
                         ("ifrs-full", ["RevenueFromContractsWithCustomers", "Revenue", "ProfitLoss"])):
            node = facts.get(t, {})
            for n in names:
                for u in ((node.get(n, {}) or {}).get("units", {}) or {}):
                    if "/" not in u and len(u) == 3 and u.isalpha():
                        rc, tax = u.upper(), t
                        break
                if rc:
                    break
            if rc:
                break
    except Exception:
        pass
    try:
        s = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
        incorp = s.get("stateOfIncorporation") or None
        bsc = ((s.get("addresses", {}) or {}).get("business", {}) or {}).get("stateOrCountry")
    except Exception:
        pass
    return (rc, tax, incorp, bsc)


def _figi(cli, t):
    try:
        r = cli.post("https://api.openfigi.com/v3/mapping", json=[{"idType": "TICKER", "idValue": t, "exchCode": "US"}])
        d = ((r.json() or [{}])[0].get("data")) or []
        return d[0].get("figi") if d else None
    except Exception:
        return None


def _row(identity: dict) -> dict:
    ids = identity.get("identifiers", {})
    return {
        "ticker": identity["ticker"],
        "country_listing": identity.get("country_listing"),
        "country_issuer": identity.get("country_issuer"),
        "quote_currency": identity.get("quote_currency"),
        "report_currency": identity.get("report_currency"),
        "instrument_type": identity.get("instrument_type"),
        "adr_ratio": identity.get("adr_ratio"),
        "cik": (ids.get("cik") or {}).get("value"),
        "figi": (ids.get("figi") or {}).get("value"),
        "isin": (ids.get("isin") or {}).get("value"),
        "lei": (ids.get("lei") or {}).get("value"),
        "identity": {**ids, "adr_relation": identity.get("adr_relation"),
                     "country_issuer": {"value": identity.get("country_issuer"),
                                        "source": identity.get("country_issuer_source"),
                                        "status": identity.get("country_issuer_status")}},
        "identity_as_of": identity.get("identity_as_of"),
    }


def execute(tickers=None, dry_run: bool = False) -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "") or "GIIC research admin@giic.app"
    url, key = os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    writer = SupabaseWriter(url, key) if (url and key) else None
    if not tickers:
        tickers = writer.get_transaction_tickers() if writer else []
    today = date.today().isoformat()
    cli = _client(ua)
    cikmap = _cik_map(cli)

    resolved = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        rc, tax, incorp, bsc = _edgar(cli, cik)
        ident = resolve_identity(t, ymeta=_yahoo_meta(cli, t), cik=cik, report_currency=rc, taxonomy=tax,
                                 figi=_figi(cli, t), edgar_incorp=incorp, edgar_state_country=bsc, today=today)
        resolved[t] = _row(ident)

    if dry_run or writer is None:
        return {"dry_run": True, "resolved": resolved}

    # Guarda: ¿existen las columnas de 0012? GET directo a la columna (sin order=id,
    # que instruments no tiene). 200 => aplicada; 400 => faltan columnas.
    try:
        hdr = {"apikey": key, "Authorization": f"Bearer {key}"}
        probe = cli.get(f"{url.rstrip('/')}/rest/v1/instruments",
                        params={"select": "country_issuer", "limit": "1"}, headers=hdr)
        applied = probe.status_code == 200
    except Exception:
        applied = False
    if not applied:
        return {"written": False, "reason": "migración 0012 no aplicada (faltan columnas de identidad)",
                "resolved_sample": {k: resolved[k] for k in list(resolved)[:2]}}

    n = writer.upsert("instruments", list(resolved.values()), on_conflict="ticker")
    return {"written": True, "rows": n, "tickers": list(resolved.keys())}


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC — persistencia de identidad de instrumentos")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    try:
        out = execute([t.upper() for t in a.tickers] if a.tickers else None, a.dry_run)
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
