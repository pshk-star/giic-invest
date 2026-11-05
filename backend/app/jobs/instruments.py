"""Identificación de instrumentos para la tabla `instruments` (Fase A).

El universo curado (universe.py) ya trae nombre/tipo/sector verificados → se escriben
como 'resolved'. Los tickers extra que el usuario agregue (presentes en transactions)
se resuelven vía Yahoo (tipo/moneda/bolsa) y EDGAR (nombre); si no se logra
identificar el tipo, quedan 'pending' (nunca se marca verificado un ticker
desconocido).
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .universe import get_universe


def build_universe_instrument_rows() -> List[dict]:
    """Filas de instruments para el universo curado (identificación verificada)."""
    now = datetime.utcnow().isoformat()
    rows = []
    for i in get_universe(include_etfs=True):
        rows.append({
            "ticker": i.ticker,
            "name": i.name,
            "asset_class": i.asset_class.value,
            "exchange": i.exchange,
            "currency": i.currency,
            "sector": i.sector,
            "status": "resolved",
            "source": "universe",
            "updated_at": now,
        })
    return rows


def resolve_instrument(ticker: str, meta: Optional[dict],
                       edgar_name: Optional[str] = None) -> dict:
    """Construye una fila de instrument a partir de metadatos de Yahoo (+ nombre EDGAR).

    `meta`: salida de YahooProvider.get_instrument_meta (puede ser {} o None).
    status='resolved' solo si se identificó el tipo; si no, 'pending'.
    """
    meta = meta or {}
    asset_class = meta.get("asset_class") or "unknown"
    name = meta.get("name") or edgar_name
    status = "resolved" if asset_class in ("equity", "etf") else "pending"
    return {
        "ticker": ticker.upper(),
        "name": name,
        "asset_class": asset_class,
        "exchange": meta.get("exchange"),
        "currency": meta.get("currency") or "USD",
        "sector": None,
        "status": status,
        "source": "yahoo" if meta else ("edgar" if edgar_name else "unresolved"),
        "updated_at": datetime.utcnow().isoformat(),
    }


def resolve_extra_tickers(tickers: List[str], yahoo, edgar_names: Dict[str, str]) -> List[dict]:
    """Resuelve tickers fuera del universo. Tolerante a fallos por ticker."""
    rows = []
    for t in tickers:
        try:
            meta = yahoo.get_instrument_meta(t)
        except Exception:
            meta = {}
        rows.append(resolve_instrument(t, meta, edgar_names.get(t.upper())))
    return rows
