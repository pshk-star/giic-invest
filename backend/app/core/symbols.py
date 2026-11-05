"""Normalización de tickers por bolsa y metadatos derivados (moneda, país).

Formato canónico interno: "TICKER.EXCHANGE" (estilo EODHD), p.ej. "NVDA.US",
"2330.TW", "WALMEX.MX". La moneda y el país que entrega el PROVEEDOR siempre
mandan; estos mapas son solo un respaldo cuando el proveedor no los da, y son
fácilmente editables. Esto evita el error de tratar un ticker local como si
cotizara en USD (p.ej. leer TSM en TWD como si fuera el ADR en USD).
"""
from __future__ import annotations

from typing import Optional, Tuple

# Sufijo de bolsa -> (moneda ISO, país ISO-2). Los códigos siguen la convención de
# EODHD. Los marcados "verificar" conviene confirmarlos contra la lista real del
# proveedor antes de operar esa bolsa; no se asumen como verdad de mercado.
EXCHANGE_META: dict[str, Tuple[str, str]] = {
    "US": ("USD", "US"),
    "TO": ("CAD", "CA"),        # Toronto
    "V": ("CAD", "CA"),         # TSX Venture
    "LSE": ("GBP", "GB"),       # London
    "PA": ("EUR", "FR"),        # Euronext Paris
    "AS": ("EUR", "NL"),        # Euronext Amsterdam
    "XETRA": ("EUR", "DE"),     # Deutsche Börse XETRA
    "F": ("EUR", "DE"),         # Frankfurt
    "MC": ("EUR", "ES"),        # Madrid
    "MI": ("EUR", "IT"),        # Milan
    "TSE": ("JPY", "JP"),       # Tokyo (verificar código EODHD)
    "TW": ("TWD", "TW"),        # Taiwan
    "TWO": ("TWD", "TW"),       # Taiwan OTC
    "KO": ("KRW", "KR"),        # Korea KOSPI (verificar)
    "KQ": ("KRW", "KR"),        # Korea KOSDAQ (verificar)
    "HK": ("HKD", "HK"),        # Hong Kong
    "MX": ("MXN", "MX"),        # México BMV
    "SN": ("CLP", "CL"),        # Santiago (verificar)
    "SA": ("BRL", "BR"),        # B3 São Paulo
}

DEFAULT_EXCHANGE = "US"


def parse_symbol(symbol: str, default_exchange: str = DEFAULT_EXCHANGE) -> Tuple[str, str]:
    """Devuelve (ticker, exchange) desde 'TICKER.EX'. Sin sufijo -> default_exchange.

    El punto se parte por la DERECHA para soportar tickers con punto (p.ej. 'BRK.B').
    """
    if not symbol:
        raise ValueError("símbolo vacío")
    s = symbol.strip().upper()
    if "." in s:
        base, ex = s.rsplit(".", 1)
        if base and ex:
            return base, ex
    return s, default_exchange.upper()


def canonical(symbol: str, default_exchange: str = DEFAULT_EXCHANGE) -> str:
    base, ex = parse_symbol(symbol, default_exchange)
    return f"{base}.{ex}"


def currency_for(symbol: str, default_exchange: str = DEFAULT_EXCHANGE) -> Optional[str]:
    _, ex = parse_symbol(symbol, default_exchange)
    meta = EXCHANGE_META.get(ex)
    return meta[0] if meta else None


def country_for(symbol: str, default_exchange: str = DEFAULT_EXCHANGE) -> Optional[str]:
    _, ex = parse_symbol(symbol, default_exchange)
    meta = EXCHANGE_META.get(ex)
    return meta[1] if meta else None


def same_instrument(a: str, b: str, default_exchange: str = DEFAULT_EXCHANGE) -> bool:
    """True si dos símbolos refieren al mismo instrumento (comparación canónica)."""
    return canonical(a, default_exchange) == canonical(b, default_exchange)
