"""Catálogo COMPLETO de instrumentos cotizados en EE. UU.

Problema que resuelve: el autocompletado de «Mi Cartera» solo encuentra lo que ya
está en la tabla `instruments`, que hasta ahora era el universo curado (~91) más los
tickers que el usuario ya hubiera registrado. Un ticker válido fuera de ese conjunto
(p. ej. el ADR TSM o ASML) no aparecía. En vez de agregar excepciones manuales, se
carga el DIRECTORIO OFICIAL y gratuito de Nasdaq Trader, que lista TODOS los valores
cotizados en EE. UU. (NASDAQ, NYSE, NYSE American, Arca, Cboe, IEX), incluidos ETF y
ADR. Así el catálogo es general y escalable.

Fuentes (públicas, sin clave):
    https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt
    https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt

Las filas se escriben con status='catalog' (identificado por el directorio de la bolsa).
El scan diario y la resolución vía Yahoo pueden ENRIQUECER después (status 'resolved'
con sector/moneda); por orden de ejecución, esas escrituras ganan sobre 'catalog'.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# Códigos de bolsa en otherlisted.txt
EXCHANGE_MAP = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}


def _row(ticker: str, name: Optional[str], asset_class: str, exchange: Optional[str]) -> dict:
    return {
        "ticker": ticker.upper(),
        "name": (name or "").strip() or None,
        "asset_class": asset_class,
        "exchange": exchange,
        "currency": "USD",
        "sector": None,
        "status": "catalog",
        "source": "nasdaqtrader",
        "updated_at": datetime.utcnow().isoformat(),
    }


def _valid_symbol(sym: str) -> bool:
    if not sym:
        return False
    # Descarta símbolos con espacio o caracteres de prueba; conserva clases (BRK.A) y guiones.
    if " " in sym:
        return False
    return all(c.isalnum() or c in ".-" for c in sym)


def parse_nasdaq_listed(text: str) -> List[dict]:
    """nasdaqlisted.txt: Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot|ETF|NextShares"""
    rows: List[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("Symbol|") or line.startswith("File Creation Time"):
            continue
        p = line.split("|")
        if len(p) < 7:
            continue
        sym, name, test_issue, etf = p[0].strip(), p[1], p[3].strip().upper(), p[6].strip().upper()
        if test_issue == "Y" or not _valid_symbol(sym):
            continue
        rows.append(_row(sym, name, "etf" if etf == "Y" else "equity", "NASDAQ"))
    return rows


def parse_other_listed(text: str) -> List[dict]:
    """otherlisted.txt: ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot|Test Issue|NASDAQ Symbol"""
    rows: List[dict] = []
    for line in text.splitlines():
        if not line or line.startswith("ACT Symbol|") or line.startswith("File Creation Time"):
            continue
        p = line.split("|")
        if len(p) < 7:
            continue
        sym, name, exch_code, etf, test_issue = p[0].strip(), p[1], p[2].strip().upper(), p[4].strip().upper(), p[6].strip().upper()
        if test_issue == "Y" or not _valid_symbol(sym):
            continue
        rows.append(_row(sym, name, "etf" if etf == "Y" else "equity", EXCHANGE_MAP.get(exch_code, exch_code or None)))
    return rows


def parse_catalog(nasdaq_text: str, other_text: str) -> List[dict]:
    """Combina ambos directorios y deduplica por ticker (gana la primera aparición)."""
    seen = set()
    out: List[dict] = []
    for r in parse_nasdaq_listed(nasdaq_text) + parse_other_listed(other_text):
        t = r["ticker"]
        if t in seen:
            continue
        seen.add(t)
        out.append(r)
    return out


def fetch_catalog_rows(client=None, timeout: float = 30.0) -> List[dict]:
    """Descarga ambos directorios y devuelve las filas parseadas.

    Lanza excepción si no se pueden obtener: el llamador decide si es best-effort.
    """
    own = False
    if client is None:
        import httpx
        client = httpx.Client(timeout=timeout, headers={"User-Agent": "giic-catalog/1.0"})
        own = True
    try:
        nq = client.get(NASDAQ_LISTED_URL); nq.raise_for_status()
        ot = client.get(OTHER_LISTED_URL); ot.raise_for_status()
        return parse_catalog(nq.text, ot.text)
    finally:
        if own:
            client.close()


def load_catalog(writer, batch_size: int = 1000, client=None) -> dict:
    """Descarga el catálogo y lo escribe en `instruments` por lotes (best-effort por lote)."""
    rows = fetch_catalog_rows(client=client)
    written = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i:i + batch_size]
        writer.upsert("instruments", chunk, on_conflict="ticker")
        written += len(chunk)
    return {"catalog_rows": len(rows), "catalog_written": written}
