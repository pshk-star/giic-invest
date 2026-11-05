"""Datos de mercado por instrumento: cotización, histórico y snapshot técnico."""
from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core import fx as fxmod
from ..core import indicators as ind
from ..providers import MarketDataProvider
from .deps import get_market_provider

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/quote/{ticker}")
def quote(ticker: str, provider: MarketDataProvider = Depends(get_market_provider)):
    q = provider.get_quotes([ticker])
    if ticker not in q:
        raise HTTPException(404, f"Sin cotización para {ticker} en el proveedor {provider.name}")
    r = q[ticker]
    today = date.today()
    return {"ticker": r.ticker, "price": r.price, "as_of": r.as_of,
            "currency": r.currency, "is_sample": r.is_sample,
            "stale": fxmod.is_stale(r.as_of, today),
            "business_days_old": fxmod.business_days_old(r.as_of, today)}


@router.get("/history/{ticker}")
def history(ticker: str,
            start: Optional[date] = Query(None),
            end: Optional[date] = Query(None),
            provider: MarketDataProvider = Depends(get_market_provider)):
    s = provider.get_price_history(ticker, start, end)
    if s is None or len(s) == 0:
        raise HTTPException(404, f"Sin histórico para {ticker}")
    return {
        "ticker": ticker,
        "is_sample": provider.is_sample,
        "points": [{"date": idx.date().isoformat(), "close": float(v)} for idx, v in s.items()],
    }


@router.get("/snapshot/{ticker}")
def snapshot(ticker: str, provider: MarketDataProvider = Depends(get_market_provider)):
    """Resumen técnico (RSI, SMAs, momentum, drawdown, vol) calculado del histórico."""
    s = provider.get_price_history(ticker)
    if s is None or len(s) == 0:
        raise HTTPException(404, f"Sin histórico para {ticker}")
    return {"ticker": ticker, "is_sample": provider.is_sample, "technical": ind.snapshot(s)}
