"""Motor del scanner: orquesta descarga incremental, lotes, límites de API,
validación de calidad y scoring, de forma que escale a miles de instrumentos.

Flujo por lote:
  1. refresca precios (incremental vía caché) y fundamentales (si obsoletos),
     respetando el token bucket del proveedor;
  2. valida y sanea los múltiplos (quality.validate_fundamentals);
  3. calcula snapshot técnico;
Luego, sobre todo el universo:
  4. mide cobertura por factor y descarta del compuesto los factores sin cobertura;
  5. rankea (opcionalmente comparando por sector).
Devuelve ranking + informe de calidad de datos.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import List, Mapping, Optional

# Ventana de histórico a solicitar cuando no hay caché. Suficiente para momentum
# 12m y volatilidad 1y con margen; limita el tamaño de descarga (p.ej. CSV de Stooq)
# para reducir timeouts de las fuentes gratuitas.
HISTORY_LOOKBACK_DAYS = 550

from ..core import indicators as ind
from ..core import quality as q
from ..core import scanner as sc
from ..core.fx import business_days_old
from .cache import MarketCache
from .rate_limiter import TokenBucket, batched, throttle


def _parse_iso(s: str) -> Optional[date]:
    try:
        y, m, d = (int(x) for x in s.split("-"))
        return date(y, m, d)
    except (ValueError, TypeError, AttributeError):
        return None


def run_scan(
    provider,
    universe,                       # List[Instrument]
    cache: Optional[MarketCache] = None,
    *,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    weights: Optional[Mapping[str, float]] = None,
    top: Optional[int] = 20,
    batch_size: int = 50,
    min_coverage: float = 0.5,
    min_metrics: int = 3,
    sector_relative: bool = False,
    bucket: Optional[TokenBucket] = None,
    max_stale_business_days: int = 5,
) -> dict:
    today = today or date.today()
    now = now or datetime.utcnow()
    tickers = [i.ticker for i in universe]
    meta = {i.ticker: i for i in universe}

    fundamentals_raw = {}
    technical = {}
    quality_issues = {}
    price_meta = {}   # ticker -> {"close": float, "as_of": "YYYY-MM-DD"} con la fecha REAL del dato
    fetch_errors = {} # ticker/batch -> motivo; un fallo de fuente NO aborta la corrida
    hist_start = today - timedelta(days=HISTORY_LOOKBACK_DAYS)

    for batch in batched(tickers, batch_size):
        # fundamentales del lote (incremental si hay caché). Un error de fuente no aborta.
        if bucket:
            throttle(bucket, len(batch))
        try:
            if cache is not None:
                funds = cache.refresh_fundamentals(provider, batch, now)
            else:
                funds = provider.get_fundamentals(batch)
        except Exception as e:
            funds = {}
            fetch_errors["fundamentals_batch"] = f"{type(e).__name__}: {str(e)[:120]}"
        # precios + técnico por instrumento (tolerante a timeouts individuales)
        for t in batch:
            if bucket:
                throttle(bucket, 1)
            try:
                hist = (cache.refresh_history(provider, t, today) if cache is not None
                        else provider.get_price_history(t, start=hist_start))
            except Exception as e:
                hist = None
                fetch_errors[t] = f"{type(e).__name__}: {str(e)[:120]}"
            if hist is not None and len(hist):
                technical[t] = ind.snapshot(hist)
                last_idx = hist.index[-1]
                as_of_dt = last_idx.date() if hasattr(last_idx, "date") else last_idx
                price_meta[t] = {"close": float(hist.iloc[-1]), "as_of": as_of_dt.isoformat()}
            else:
                technical[t] = {}
            clean, issues = q.validate_fundamentals(funds.get(t))
            fundamentals_raw[t] = clean
            if issues:
                quality_issues[t] = issues

    coverage = q.coverage_report(fundamentals_raw)
    usable = q.usable_factors(coverage, min_coverage)
    # momentum y low_risk dependen de técnico, no de fundamentales: siempre usables
    usable = sorted(set(usable) | {"momentum", "low_risk"})

    # Frescura: un instrumento con precio OBSOLETO no debe contaminar el ranking.
    stale_excluded: List[str] = []
    fresh_count = 0
    for t, m in price_meta.items():
        d = _parse_iso(m.get("as_of"))
        age = business_days_old(d, today) if d else None
        if age is None or age > max_stale_business_days:
            stale_excluded.append(t)
        else:
            fresh_count += 1
    stale_set = set(stale_excluded)
    priced_count = len(price_meta)
    fresh_fraction = (fresh_count / priced_count) if priced_count else 0.0

    inputs: List[sc.ScanInput] = []
    insufficient = []
    for t in tickers:
        inst = meta[t]
        f = fundamentals_raw.get(t)
        if t in stale_set:
            continue  # excluido por precio obsoleto
        if not q.is_sufficient(f, min_metrics) and not technical.get(t):
            insufficient.append(t)
            continue
        inputs.append(sc.ScanInput(
            ticker=t, fundamentals=f, technical=technical.get(t),
            is_sample=provider.is_sample, sector=inst.sector))

    ranking = sc.rank(inputs, weights=weights, top=top,
                      usable_factors=usable, sector_relative=sector_relative)
    for r in ranking:
        inst = meta.get(r["ticker"])
        if inst is not None:
            r["name"] = inst.name
            r["sector"] = inst.sector
            r["country"] = inst.country
            r["exchange"] = inst.exchange

    # Datos crudos ya obtenidos (para persistir sin volver a descargar).
    # market_prices lleva la fecha REAL del dato del proveedor (no la fecha de corrida).
    market_prices = price_meta
    fundamentals_payload = {t: asdict(f) for t, f in fundamentals_raw.items() if f is not None}

    return {
        "using_sample_data": provider.is_sample,
        "evaluated": len(inputs),
        "excluded_insufficient_data": insufficient,
        "stale_excluded": stale_excluded,
        "priced_count": priced_count,
        "fresh_fraction": fresh_fraction,
        "coverage": coverage,
        "usable_factors": usable,
        "sector_relative": sector_relative,
        "quality_issues": quality_issues,
        "fetch_errors": fetch_errors,
        "weights": dict(weights) if weights else sc.DEFAULT_WEIGHTS,
        "market_prices": market_prices,
        "fundamentals_payload": fundamentals_payload,
        "ranking": ranking,
        "disclaimer": "Puntaje multifactor de atractivo relativo; no es una probabilidad. "
                      "Factores sin cobertura mínima se excluyen del compuesto.",
    }
