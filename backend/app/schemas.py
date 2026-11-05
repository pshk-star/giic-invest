"""Esquemas pydantic para entrada/salida de la API."""
from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class InstrumentIn(BaseModel):
    ticker: str
    name: str = ""
    asset_class: str = "equity"
    exchange: str = "US"
    country: str = "US"
    sector: Optional[str] = None
    currency: str = "USD"


class PositionIn(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    avg_cost: float = Field(ge=0)
    opened_at: Optional[date] = None
    # opcionales para autocrear el instrumento si no existe
    name: Optional[str] = None
    asset_class: str = "equity"
    exchange: str = "US"
    country: str = "US"
    sector: Optional[str] = None
    currency: str = "USD"


class PositionOut(BaseModel):
    id: int
    ticker: str
    name: str
    asset_class: str
    sector: Optional[str]
    country: str
    quantity: float
    avg_cost: float
    currency: str
    opened_at: Optional[date]


class SettingsIn(BaseModel):
    base_currency: Optional[str] = None
    capital_available: Optional[float] = None
    monthly_contribution: Optional[float] = None
    risk_tolerance: Optional[str] = None
    horizon_years: Optional[float] = None
    max_weight_per_asset: Optional[float] = None
    max_weight_per_sector: Optional[float] = None
    min_cash: Optional[float] = None


class ScanRequest(BaseModel):
    scope: str = "universe"          # "universe" | "portfolio"
    exchanges: Optional[list[str]] = None
    top: int = 20
    weights: Optional[dict[str, float]] = None
    universe_limit: int = 200        # tope de instrumentos a evaluar (coste de API)
    sector_relative: bool = False    # rankear value/quality/growth dentro del sector
    min_coverage: float = 0.5        # cobertura mínima por factor para incluirlo
    use_cache: bool = True           # descarga incremental vía caché en BD
