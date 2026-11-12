"""Sonda READ-ONLY del plan EODHD: cuántos años de precios ajustados, splits y dividendos entrega HOY
el plan para una muestra (US + internacional/ADR). NO escribe, NO toca motores. Responde puntos 3 y 6
de la auditoría de costo: ¿qué histórico y cobertura internacional podemos obtener ya, sin otro servicio?

Uso: EODHD_API_KEY en env.  DIAG_TICKERS="NVDA,ASML,TSM,PFE,AAPL,META,KO,EOG" python -m app.jobs.eodhd_usage_probe
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List

BASE = "https://eodhd.com/api"
DEFAULT = ["NVDA", "ASML", "TSM", "PFE", "AAPL", "META", "KO", "EOG"]


def _get(client, path: str, **params):
    params["api_token"] = os.getenv("EODHD_API_KEY", ""); params.setdefault("fmt", "json")
    r = client.get(f"{BASE}/{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def probe(client, sym: str) -> dict:
    out: Dict = {"symbol": sym}
    # precios EOD ajustados (histórico completo)
    try:
        eod = _get(client, f"eod/{sym}", **{"from": "1980-01-01"})
        if isinstance(eod, list) and eod:
            dates = [r["date"] for r in eod if r.get("date")]
            has_adj = any(r.get("adjusted_close") not in (None, "") for r in eod[:5])
            out["precios"] = {"n": len(eod), "desde": min(dates), "hasta": max(dates),
                              "anios": round((int(max(dates)[:4]) - int(min(dates)[:4])), 0),
                              "adjusted_close": has_adj}
        else:
            out["precios"] = {"n": 0, "nota": "sin datos"}
    except Exception as e:
        out["precios"] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
    # splits
    try:
        sp = _get(client, f"splits/{sym}", **{"from": "1980-01-01"})
        out["splits"] = {"n": len(sp) if isinstance(sp, list) else 0,
                         "primero": (sp[0].get("date") if isinstance(sp, list) and sp else None)}
    except Exception as e:
        out["splits"] = {"error": f"{type(e).__name__}"}
    # dividendos
    try:
        dv = _get(client, f"div/{sym}", **{"from": "1980-01-01"})
        out["dividendos"] = {"n": len(dv) if isinstance(dv, list) else 0,
                             "primero": (dv[0].get("date") if isinstance(dv, list) and dv else None)}
    except Exception as e:
        out["dividendos"] = {"error": f"{type(e).__name__}"}
    return out


def run() -> dict:
    if not os.getenv("EODHD_API_KEY"):
        return {"error": "falta EODHD_API_KEY"}
    import httpx
    client = httpx.Client()
    tickers = [t.strip().upper() for t in (os.getenv("DIAG_TICKERS") or ",".join(DEFAULT)).split(",") if t.strip()]
    user = {}
    try:
        user = _get(client, "user")
        user = {"name": user.get("name"), "subscriptionType": user.get("subscriptionType"),
                "dailyRateLimit": user.get("dailyRateLimit"), "apiRequests": user.get("apiRequests")}
    except Exception as e:
        user = {"error": str(e)}
    results = [probe(client, f"{t}.US") for t in tickers]   # .US: ASML/TSM cotizan como ADR/listing en EE.UU.
    return {"as_of": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()), "plan": user, "muestra": results}


def main(argv=None) -> int:
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
