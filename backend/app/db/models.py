"""Modelos ORM. Persisten la cartera, operaciones, dividendos y ajustes del usuario."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (Date, DateTime, Float, ForeignKey, Integer, String,
                        Text, UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class InstrumentRow(Base):
    __tablename__ = "instruments"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="")
    asset_class: Mapped[str] = mapped_column(String(16), default="equity")  # equity|etf|cash
    exchange: Mapped[str] = mapped_column(String(16), default="US")
    country: Mapped[str] = mapped_column(String(8), default="US")
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")


class PositionRow(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_cost: Mapped[float] = mapped_column(Float, default=0.0)
    opened_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    instrument: Mapped[InstrumentRow] = relationship(lazy="joined")


class TransactionRow(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"), index=True)
    side: Mapped[str] = mapped_column(String(4))  # buy|sell
    quantity: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float, default=0.0)
    executed_at: Mapped[date] = mapped_column(Date)


class DividendRow(Base):
    __tablename__ = "dividends"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("instruments.ticker"), index=True)
    amount: Mapped[float] = mapped_column(Float)
    paid_at: Mapped[date] = mapped_column(Date)


class UserRow(Base):
    """Usuario de la plataforma. Autenticación obligatoria para toda la API."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PriceBarRow(Base):
    """Caché incremental de precios diarios ajustados por instrumento."""
    __tablename__ = "price_bars"
    __table_args__ = (UniqueConstraint("ticker", "bar_date", name="uix_ticker_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(32), index=True)
    bar_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Float)


class FundamentalsCacheRow(Base):
    """Caché de fundamentales (payload JSON) con marca de actualización."""
    __tablename__ = "fundamentals_cache"

    ticker: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SettingsRow(Base):
    """Fila única (id=1) con las restricciones y parámetros del inversor."""
    __tablename__ = "portfolio_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    base_currency: Mapped[str] = mapped_column(String(8), default="USD")
    capital_available: Mapped[float] = mapped_column(Float, default=0.0)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0)
    risk_tolerance: Mapped[str] = mapped_column(String(16), default="moderate")
    horizon_years: Mapped[float] = mapped_column(Float, default=15.0)
    max_weight_per_asset: Mapped[float] = mapped_column(Float, default=0.25)
    max_weight_per_sector: Mapped[float] = mapped_column(Float, default=0.40)
    min_cash: Mapped[float] = mapped_column(Float, default=0.0)
