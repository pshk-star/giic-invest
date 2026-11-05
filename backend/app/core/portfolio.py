"""Analítica de cartera: valoración, P&L, pesos, distribución, concentración,
correlación y —lo más importante— exposición *look-through* a través de ETF.

El look-through resuelve la pregunta real del inversor: ¿cuánta exposición EFECTIVA
a una compañía (p.ej. NVDA) cargo de verdad cuando mantengo NVDA directa más QQQ,
SMH y VOO, que también la contienen? Mantener los tres a la vez concentra sin que
el peso nominal lo muestre.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Mapping, Optional

import numpy as np
import pandas as pd

from .types import AssetClass, ETFHolding, Position


def market_value(position: Position, price: float, fx_to_base: float = 1.0) -> float:
    """Valor de mercado de una posición en moneda base (fx = unidades base por unidad local)."""
    return position.quantity * price * fx_to_base


def position_pnl(position: Position, price: float, fx_to_base: float = 1.0) -> dict:
    mv = market_value(position, price, fx_to_base)
    cost = position.cost_basis() * fx_to_base
    pnl = mv - cost
    pct = (pnl / cost) if cost else float("nan")
    return {"market_value": mv, "cost_basis": cost, "pnl": pnl, "pnl_pct": pct}


def portfolio_valuation(
    positions: List[Position],
    prices: Mapping[str, float],
    fx: Optional[Mapping[str, float]] = None,
) -> dict:
    """Valuación total: por posición, pesos nominales, P&L agregado.

    `prices`: ticker -> precio actual (moneda del instrumento).
    `fx`: moneda -> factor a base (default 1.0). Si falta un precio, la posición
    se reporta con market_value None y se lista en `missing_prices` (nunca se inventa).
    """
    fx = fx or {}
    rows, missing = [], []
    total_mv = 0.0
    for p in positions:
        t = p.instrument.ticker
        price = prices.get(t)
        if price is None:
            missing.append(t)
            rows.append({"ticker": t, "market_value": None, "weight": None})
            continue
        f = fx.get(p.instrument.currency, 1.0)
        pnl = position_pnl(p, price, f)
        total_mv += pnl["market_value"]
        rows.append({
            "ticker": t,
            "name": p.instrument.name,
            "asset_class": p.instrument.asset_class.value,
            "sector": p.instrument.sector,
            "country": p.instrument.country,
            "quantity": p.quantity,
            "price": price,
            "currency": p.instrument.currency,
            **pnl,
        })
    for r in rows:
        if r.get("market_value"):
            r["weight"] = r["market_value"] / total_mv if total_mv else 0.0
    return {
        "total_market_value": total_mv,
        "positions": rows,
        "missing_prices": missing,
    }


def distribution(valuation: dict, key: str) -> Dict[str, float]:
    """Pesos agregados por una clave de la posición: 'sector', 'country' o 'asset_class'."""
    agg: Dict[str, float] = defaultdict(float)
    total = valuation["total_market_value"] or 0.0
    for r in valuation["positions"]:
        mv = r.get("market_value")
        if not mv:
            continue
        agg[r.get(key) or "desconocido"] += mv
    return {k: (v / total if total else 0.0) for k, v in sorted(agg.items(), key=lambda x: -x[1])}


def look_through_exposure(
    positions: List[Position],
    prices: Mapping[str, float],
    etf_holdings: Mapping[str, List[ETFHolding]],
    fx: Optional[Mapping[str, float]] = None,
) -> dict:
    """Exposición efectiva por compañía subyacente, expandiendo los ETF.

    - Una acción directa aporta todo su valor de mercado al ticker.
    - Un ETF aporta su valor de mercado repartido según los pesos de sus holdings.
      El residuo no cubierto por los holdings conocidos se asigna a '<ETF>:resto'
      para no sobre/infra-contar (honestidad sobre cobertura parcial de holdings).
    Devuelve exposición efectiva por ticker, en valor y en fracción del total.
    """
    fx = fx or {}
    eff: Dict[str, float] = defaultdict(float)
    total = 0.0
    coverage_warnings = []
    for p in positions:
        t = p.instrument.ticker
        price = prices.get(t)
        if price is None:
            continue
        mv = market_value(p, price, fx.get(p.instrument.currency, 1.0))
        total += mv
        if p.instrument.asset_class == AssetClass.ETF and t in etf_holdings:
            holdings = etf_holdings[t]
            covered = sum(h.weight for h in holdings)
            for h in holdings:
                eff[h.ticker] += mv * h.weight
            if covered < 0.999:
                eff[f"{t}:resto"] += mv * max(0.0, 1.0 - covered)
                coverage_warnings.append(
                    {"etf": t, "covered_weight": round(covered, 4)}
                )
        else:
            eff[t] += mv
    rows = [
        {"ticker": k, "effective_value": v, "effective_weight": (v / total if total else 0.0)}
        for k, v in sorted(eff.items(), key=lambda x: -x[1])
    ]
    return {
        "total_market_value": total,
        "effective_exposure": rows,
        "coverage_warnings": coverage_warnings,
    }


def herfindahl(weights: List[float]) -> float:
    """Índice HHI de concentración (0 = perfectamente diversificado, 1 = todo en uno)."""
    w = np.array([x for x in weights if x and np.isfinite(x)], dtype=float)
    if w.sum() <= 0:
        return float("nan")
    w = w / w.sum()
    return float((w ** 2).sum())


def effective_number_of_holdings(weights: List[float]) -> float:
    """1/HHI: número 'efectivo' de posiciones equivalentes equiponderadas."""
    h = herfindahl(weights)
    return float(1.0 / h) if h and np.isfinite(h) and h > 0 else float("nan")


def concentration_report(look_through: dict, max_weight_per_asset: float = 0.25) -> dict:
    """Marca los subyacentes que superan el límite de peso por activo."""
    rows = look_through["effective_exposure"]
    weights = [r["effective_weight"] for r in rows]
    breaches = [
        {"ticker": r["ticker"], "effective_weight": r["effective_weight"],
         "over_by": r["effective_weight"] - max_weight_per_asset}
        for r in rows if r["effective_weight"] > max_weight_per_asset
    ]
    return {
        "hhi": herfindahl(weights),
        "effective_holdings": effective_number_of_holdings(weights),
        "top_exposure": rows[0] if rows else None,
        "limit": max_weight_per_asset,
        "breaches": breaches,
    }


def correlation_matrix(price_history: Mapping[str, pd.Series]) -> pd.DataFrame:
    """Matriz de correlación de retornos diarios entre instrumentos con historia común."""
    frames = {}
    for t, s in price_history.items():
        s = pd.Series(s).astype(float).sort_index()
        frames[t] = s.pct_change()
    if not frames:
        return pd.DataFrame()
    df = pd.DataFrame(frames).dropna(how="all")
    return df.corr()


def portfolio_volatility(
    weights: Mapping[str, float],
    price_history: Mapping[str, pd.Series],
) -> float:
    """Volatilidad anualizada de la cartera usando la matriz de covarianza de retornos."""
    tickers = [t for t in weights if t in price_history]
    if len(tickers) < 1:
        return float("nan")
    rets = pd.DataFrame(
        {t: pd.Series(price_history[t]).astype(float).sort_index().pct_change() for t in tickers}
    ).dropna(how="all")
    if rets.shape[0] < 2:
        return float("nan")
    cov = rets.cov() * 252.0
    w = np.array([weights[t] for t in tickers], dtype=float)
    if w.sum() > 0:
        w = w / w.sum()
    var = float(w @ cov.values @ w)
    return float(np.sqrt(var)) if var >= 0 else float("nan")
