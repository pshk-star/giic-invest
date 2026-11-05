"""Scanner de oportunidades: motor escalable con caché incremental, lotes,
límite de tasa, validación de calidad y ranking (opcionalmente por sector)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.types import AssetClass, Instrument
from ..db.models import PositionRow
from ..db.session import get_db
from ..providers import MarketDataProvider
from ..schemas import ScanRequest
from ..services.cache import MarketCache
from ..services.rate_limiter import TokenBucket
from ..services.scan_engine import run_scan
from .deps import get_market_provider

router = APIRouter(prefix="/scanner", tags=["scanner"])


@router.post("/run")
def run(req: ScanRequest,
        db: Session = Depends(get_db),
        provider: MarketDataProvider = Depends(get_market_provider)):
    s = get_settings()
    if req.scope == "portfolio":
        rows = db.scalars(select(PositionRow)).all()
        universe = [
            Instrument(
                ticker=p.ticker, name=p.instrument.name,
                asset_class=_ac(p.instrument.asset_class), exchange=p.instrument.exchange,
                country=p.instrument.country, sector=p.instrument.sector,
                currency=p.instrument.currency)
            for p in rows
        ]
    else:
        universe = provider.list_universe(req.exchanges, limit=req.universe_limit)

    if not universe:
        return {"empty": True, "message": "Universo vacío para el alcance solicitado."}

    cache = MarketCache(db, s.history_max_gap_days, s.fundamentals_max_age_days) if req.use_cache else None
    bucket = TokenBucket(rate=s.provider_rate_per_min, per=60.0) if not provider.is_sample else None

    result = run_scan(
        provider, universe, cache,
        weights=req.weights, top=req.top, batch_size=s.scanner_batch_size,
        min_coverage=req.min_coverage, sector_relative=req.sector_relative, bucket=bucket,
    )
    result["scope"] = req.scope
    return result


def _ac(value: str) -> AssetClass:
    try:
        return AssetClass(value)
    except ValueError:
        return AssetClass.EQUITY
