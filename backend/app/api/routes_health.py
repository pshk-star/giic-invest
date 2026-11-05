"""Salud del sistema y estado del proveedor de datos (incluye si es EJEMPLO)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..config import get_settings
from ..providers import MarketDataProvider
from .deps import get_market_provider

router = APIRouter(tags=["health"])


@router.get("/health")
def health(provider: MarketDataProvider = Depends(get_market_provider)):
    s = get_settings()
    return {
        "status": "ok",
        "environment": s.environment,
        "configured_provider": s.data_provider,
        "provider": provider.health(),
        "using_sample_data": provider.is_sample,
    }
