"""Gestión y analítica de la cartera: CRUD de posiciones, import CSV, ajustes,
y el análisis completo (valuación, distribución, look-through y concentración)."""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core import fx as fxmod
from ..core import portfolio as pf
from ..core.types import AssetClass, Instrument, Position
from ..db.models import InstrumentRow, PositionRow, SettingsRow
from ..db.session import get_db
from ..providers import MarketDataProvider
from ..schemas import PositionIn, PositionOut, SettingsIn
from .deps import get_market_provider

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


def _ensure_instrument(db: Session, data) -> InstrumentRow:
    inst = db.get(InstrumentRow, data.ticker)
    if inst is None:
        inst = InstrumentRow(
            ticker=data.ticker, name=data.name or data.ticker,
            asset_class=getattr(data, "asset_class", "equity"),
            exchange=getattr(data, "exchange", "US"),
            country=getattr(data, "country", "US"),
            sector=getattr(data, "sector", None),
            currency=getattr(data, "currency", "USD"))
        db.add(inst)
    return inst


def _row_to_out(p: PositionRow) -> PositionOut:
    return PositionOut(
        id=p.id, ticker=p.ticker, name=p.instrument.name,
        asset_class=p.instrument.asset_class, sector=p.instrument.sector,
        country=p.instrument.country, quantity=p.quantity, avg_cost=p.avg_cost,
        currency=p.instrument.currency, opened_at=p.opened_at)


def _to_core(rows: List[PositionRow]) -> List[Position]:
    out = []
    for p in rows:
        try:
            ac = AssetClass(p.instrument.asset_class)
        except ValueError:
            ac = AssetClass.EQUITY
        out.append(Position(
            instrument=Instrument(
                ticker=p.ticker, name=p.instrument.name, asset_class=ac,
                exchange=p.instrument.exchange, country=p.instrument.country,
                sector=p.instrument.sector, currency=p.instrument.currency),
            quantity=p.quantity, avg_cost=p.avg_cost, opened_at=p.opened_at))
    return out


@router.get("/positions", response_model=List[PositionOut])
def list_positions(db: Session = Depends(get_db)):
    rows = db.scalars(select(PositionRow)).all()
    return [_row_to_out(p) for p in rows]


@router.post("/positions", response_model=PositionOut, status_code=201)
def add_position(data: PositionIn, db: Session = Depends(get_db)):
    _ensure_instrument(db, data)
    row = PositionRow(ticker=data.ticker, quantity=data.quantity,
                      avg_cost=data.avg_cost, opened_at=data.opened_at)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_out(row)


@router.delete("/positions/{position_id}", status_code=204)
def delete_position(position_id: int, db: Session = Depends(get_db)):
    row = db.get(PositionRow, position_id)
    if row is None:
        raise HTTPException(404, "Posición no encontrada")
    db.delete(row)
    db.commit()


@router.post("/import")
def import_csv(file: UploadFile, db: Session = Depends(get_db)):
    """Importa posiciones desde CSV. Columnas: ticker,quantity,avg_cost[,opened_at,
    currency,asset_class,sector,name,country]. Devuelve filas creadas y errores."""
    raw = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    created, errors = 0, []
    for n, r in enumerate(reader, 2):  # fila 1 = encabezado
        try:
            data = PositionIn(
                ticker=r["ticker"].strip().upper(),
                quantity=float(r["quantity"]),
                avg_cost=float(r.get("avg_cost") or r.get("avg_price") or 0),
                opened_at=date.fromisoformat(r["opened_at"]) if r.get("opened_at") else None,
                currency=(r.get("currency") or "USD").strip().upper(),
                asset_class=(r.get("asset_class") or "equity").strip().lower(),
                sector=(r.get("sector") or None),
                name=(r.get("name") or None),
                country=(r.get("country") or "US").strip().upper())
            _ensure_instrument(db, data)
            db.add(PositionRow(ticker=data.ticker, quantity=data.quantity,
                               avg_cost=data.avg_cost, opened_at=data.opened_at))
            created += 1
        except Exception as e:
            errors.append({"row": n, "error": str(e)})
    db.commit()
    return {"created": created, "errors": errors}


@router.get("/settings")
def get_settings_row(db: Session = Depends(get_db)):
    s = db.get(SettingsRow, 1)
    if s is None:
        s = SettingsRow(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


@router.put("/settings")
def update_settings(data: SettingsIn, db: Session = Depends(get_db)):
    s = db.get(SettingsRow, 1) or SettingsRow(id=1)
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.get("/analysis")
def analyze(db: Session = Depends(get_db),
            provider: MarketDataProvider = Depends(get_market_provider)):
    """Análisis completo de la cartera con precios del proveedor configurado.

    Si el proveedor es de EJEMPLO, la respuesta lo indica con using_sample_data=True.
    """
    rows = db.scalars(select(PositionRow)).all()
    if not rows:
        return {"empty": True, "message": "Cartera vacía: agrega posiciones o importa un CSV."}
    core_positions = _to_core(rows)
    tickers = [p.instrument.ticker for p in core_positions]

    quotes = provider.get_quotes(tickers)
    prices = {t: q.price for t, q in quotes.items()}

    settings = db.get(SettingsRow, 1) or SettingsRow(id=1)
    base = settings.base_currency or get_settings().base_currency

    # FX: tasas del proveedor a la moneda base; posiciones sin tasa se marcan.
    currencies = sorted({p.instrument.currency for p in core_positions})
    rates = fxmod.build_rate_map(base, provider.get_fx_rates(base, currencies))
    fx = {c: rates[c] for c in currencies if c in rates}
    fx_missing = [c for c in currencies if c not in rates]

    # Obsolescencia de cotizaciones (posible dato desactualizado).
    today = date.today()
    stale = []
    for t, qt in quotes.items():
        if fxmod.is_stale(qt.as_of, today, get_settings().history_max_gap_days):
            stale.append({"ticker": t, "as_of": qt.as_of.isoformat(),
                          "business_days_old": fxmod.business_days_old(qt.as_of, today)})

    valuation = pf.portfolio_valuation(core_positions, prices, fx=fx)
    etf_holdings = {}
    for p in core_positions:
        if p.instrument.asset_class == AssetClass.ETF:
            etf_holdings[p.instrument.ticker] = provider.get_etf_holdings(p.instrument.ticker)
    look_through = pf.look_through_exposure(core_positions, prices, etf_holdings)
    concentration = pf.concentration_report(look_through, settings.max_weight_per_asset)

    return {
        "using_sample_data": provider.is_sample,
        "base_currency": base,
        "fx_rates": fx,
        "fx_missing": fx_missing,
        "stale_quotes": stale,
        "valuation": valuation,
        "distribution": {
            "sector": pf.distribution(valuation, "sector"),
            "country": pf.distribution(valuation, "country"),
            "asset_class": pf.distribution(valuation, "asset_class"),
        },
        "look_through": look_through,
        "concentration": concentration,
    }
