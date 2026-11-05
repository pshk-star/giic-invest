"""Interfaz abstracta de proveedor de datos de mercado.

Cualquier proveedor (EODHD, FMP, Polygon, un CSV local, un dataset point-in-time
institucional en el futuro) implementa esta interfaz. El resto del sistema depende
solo de ella, de modo que cambiar de proveedor no obliga a reescribir la lógica.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote


class MarketDataProvider(ABC):
    #: nombre corto del proveedor
    name: str = "base"
    #: True si los datos son de ejemplo (no de mercado real)
    is_sample: bool = False

    @abstractmethod
    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        """Última cotización por ticker. Omite los que el proveedor no reconozca."""

    @abstractmethod
    def get_price_history(
        self, ticker: str, start: Optional[date] = None, end: Optional[date] = None
    ) -> pd.Series:
        """Serie de cierres ajustados indexada por fecha (ascendente)."""

    @abstractmethod
    def get_fundamentals(self, tickers: List[str]) -> Dict[str, Fundamentals]:
        """Fundamentales por ticker. Campos no disponibles quedan en None (nunca inventados)."""

    @abstractmethod
    def get_etf_holdings(self, etf_ticker: str) -> List[ETFHolding]:
        """Componentes de un ETF con sus pesos. Lista vacía si el proveedor no los expone."""

    @abstractmethod
    def list_universe(
        self, exchanges: Optional[List[str]] = None, limit: Optional[int] = None
    ) -> List[Instrument]:
        """Universo de instrumentos negociables para el scanner, por bolsa."""

    def get_fx_rates(self, base: str, currencies: List[str]) -> Dict[str, float]:
        """Tasas: moneda -> unidades de `base` por 1 unidad. Default {} (sin conversión).

        Los proveedores con forex lo sobreescriben. Si falta una tasa, la capa de
        análisis marca la posición como no convertida en vez de asumir 1:1.
        """
        return {}

    def health(self) -> dict:
        """Estado del conector, para mostrar cobertura y disponibilidad en la UI."""
        return {"provider": self.name, "is_sample": self.is_sample, "ok": True}
