"""Conectores de datos de mercado, intercambiables tras una interfaz común.

Importa los submódulos de forma perezosa para que `SampleProvider` funcione sin
`httpx` (los proveedores reales lo requieren). Usa `get_provider(name)`.
"""
from __future__ import annotations

from .base import MarketDataProvider  # noqa: F401


def get_provider(name: str, **kwargs) -> "MarketDataProvider":
    name = (name or "sample").lower()
    if name == "sample":
        from .sample import SampleProvider
        return SampleProvider(**kwargs)
    if name == "eodhd":
        from .eodhd import EODHDProvider
        return EODHDProvider(**kwargs)
    if name == "fmp":
        from .fmp import FMPProvider
        return FMPProvider(**kwargs)
    if name == "stooq":
        from .stooq import StooqProvider
        return StooqProvider(**kwargs)
    if name == "edgar":
        from .edgar import EDGARProvider
        return EDGARProvider(**kwargs)
    if name == "frankfurter":
        from .frankfurter import FrankfurterProvider
        return FrankfurterProvider(**kwargs)
    if name == "yahoo":
        from .yahoo import YahooProvider
        return YahooProvider(**kwargs)
    if name == "free":
        # Arquitectura $0: precios Yahoo (respaldo Stooq) + EDGAR (fundamentales)
        # + Frankfurter (FX). Yahoo es primario porque Stooq suele bloquear IPs de
        # datacenter (GitHub Actions).
        from .composite import CompositeProvider, FallbackPrices
        from .yahoo import YahooProvider
        from .stooq import StooqProvider
        from .edgar import EDGARProvider
        from .frankfurter import FrankfurterProvider
        ua = kwargs.get("edgar_user_agent") or kwargs.get("user_agent")
        prices = FallbackPrices([YahooProvider(), StooqProvider()])
        return CompositeProvider(prices, EDGARProvider(user_agent=ua), FrankfurterProvider())
    raise ValueError(f"Proveedor desconocido: {name!r}. "
                     "Usa 'sample', 'eodhd', 'fmp', 'stooq', 'edgar', 'frankfurter' o 'free'.")
