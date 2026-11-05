"""Caché incremental de datos de mercado respaldada en la BD.

Precios: se guardan por (ticker, fecha). La descarga es INCREMENTAL: solo se piden
al proveedor las fechas posteriores a la última en caché. Fundamentales: se refrescan
solo si superan una antigüedad máxima. Esto permite escanear miles de instrumentos
sin volver a descargar todo cada día ni agotar los límites de la API.

`needs_refresh` y `missing_from` son funciones PURAS (probadas sin BD); el repositorio
`MarketCache` usa SQLAlchemy y se ejecuta en el despliegue.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Optional

import pandas as pd

from ..core.types import Fundamentals


# ---------------- lógica pura (testeable sin BD) ----------------
def needs_refresh(updated_at: Optional[datetime], now: datetime, max_age_days: int) -> bool:
    """True si un dato cacheado falta o supera la antigüedad máxima."""
    if updated_at is None:
        return True
    return (now - updated_at) > timedelta(days=max_age_days)


def missing_from(last_cached: Optional[date], today: date) -> Optional[date]:
    """Primera fecha a solicitar al proveedor para completar de forma incremental.

    None en caché => descargar todo (se devuelve None para indicar 'sin límite from').
    Si ya hay historia hasta `last_cached`, pedir desde el día siguiente.
    """
    if last_cached is None:
        return None
    return last_cached + timedelta(days=1)


def is_fresh_enough(last_cached: Optional[date], today: date, max_gap_days: int = 4) -> bool:
    """True si la última fecha en caché está suficientemente cerca de hoy."""
    if last_cached is None:
        return False
    return (today - last_cached).days <= max_gap_days


# ---------------- repositorio con BD (se ejecuta en despliegue) ----------------
class MarketCache:
    def __init__(self, db, history_max_gap_days: int = 4, fundamentals_max_age_days: int = 7):
        self.db = db
        self.history_max_gap_days = history_max_gap_days
        self.fundamentals_max_age_days = fundamentals_max_age_days

    # --- precios ---
    def last_price_date(self, ticker: str) -> Optional[date]:
        from ..db.models import PriceBarRow
        from sqlalchemy import select, func as f
        return self.db.scalar(select(f.max(PriceBarRow.bar_date)).where(PriceBarRow.ticker == ticker))

    def get_history(self, ticker: str) -> pd.Series:
        from ..db.models import PriceBarRow
        from sqlalchemy import select
        rows = self.db.scalars(
            select(PriceBarRow).where(PriceBarRow.ticker == ticker).order_by(PriceBarRow.bar_date)
        ).all()
        if not rows:
            return pd.Series(dtype=float)
        return pd.Series([r.close for r in rows],
                         index=[pd.Timestamp(r.bar_date) for r in rows], name=ticker)

    def upsert_history(self, ticker: str, series: pd.Series) -> int:
        """Inserta barras nuevas (ignora fechas ya presentes). Devuelve cuántas agregó."""
        from ..db.models import PriceBarRow
        from sqlalchemy import select
        if series is None or len(series) == 0:
            return 0
        existing = set(self.db.scalars(
            select(PriceBarRow.bar_date).where(PriceBarRow.ticker == ticker)).all())
        added = 0
        for idx, val in series.items():
            d = idx.date() if hasattr(idx, "date") else idx
            if d in existing:
                continue
            self.db.add(PriceBarRow(ticker=ticker, bar_date=d, close=float(val)))
            added += 1
        self.db.commit()
        return added

    def refresh_history(self, provider, ticker: str, today: date) -> pd.Series:
        """Devuelve la historia del ticker, descargando solo lo que falte (incremental)."""
        last = self.last_price_date(ticker)
        if not is_fresh_enough(last, today, self.history_max_gap_days):
            start = missing_from(last, today)
            fresh = provider.get_price_history(ticker, start=start)
            self.upsert_history(ticker, fresh)
        return self.get_history(ticker)

    # --- fundamentales ---
    def get_fundamentals(self, ticker: str) -> Optional[Fundamentals]:
        from ..db.models import FundamentalsCacheRow
        row = self.db.get(FundamentalsCacheRow, ticker)
        if row is None:
            return None
        data = json.loads(row.payload_json)
        return Fundamentals(**data)

    def fundamentals_age_ok(self, ticker: str, now: datetime) -> bool:
        from ..db.models import FundamentalsCacheRow
        row = self.db.get(FundamentalsCacheRow, ticker)
        return not needs_refresh(row.updated_at if row else None, now, self.fundamentals_max_age_days)

    def upsert_fundamentals(self, ticker: str, f: Fundamentals) -> None:
        from ..db.models import FundamentalsCacheRow
        row = self.db.get(FundamentalsCacheRow, ticker)
        payload = json.dumps(asdict(f))
        if row is None:
            self.db.add(FundamentalsCacheRow(ticker=ticker, payload_json=payload, updated_at=datetime.utcnow()))
        else:
            row.payload_json = payload
            row.updated_at = datetime.utcnow()
        self.db.commit()

    def refresh_fundamentals(self, provider, tickers: List[str], now: datetime) -> Dict[str, Fundamentals]:
        """Devuelve fundamentales, pidiendo al proveedor solo los obsoletos/faltantes."""
        stale = [t for t in tickers if not self.fundamentals_age_ok(t, now)]
        if stale:
            fetched = provider.get_fundamentals(stale)
            for t, f in fetched.items():
                self.upsert_fundamentals(t, f)
        out: Dict[str, Fundamentals] = {}
        for t in tickers:
            f = self.get_fundamentals(t)
            if f is not None:
                out[t] = f
        return out
