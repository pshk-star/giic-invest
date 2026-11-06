"""Conector Yahoo Finance (precios EOD) — GRATIS, sin clave.

Usa la API pública de gráficos (chart). A diferencia de Stooq, suele responder desde
IPs de datacenter (GitHub Actions), por eso es la fuente de precios primaria en la
arquitectura $0. Parser puro `parse_yahoo_chart`; la descarga ocurre en el job.

Nota: es una API no documentada formalmente; puede limitar por volumen. Uso personal
y moderado (EOD de decenas de instrumentos al día).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import pandas as pd

from ..core.types import ETFHolding, Fundamentals, Instrument, Quote
from .base import MarketDataProvider

BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def parse_yahoo_chart(payload: dict, ticker: str) -> pd.Series:
    """Convierte la respuesta chart de Yahoo en Serie de cierres ajustados por fecha."""
    try:
        res = (payload or {}).get("chart", {}).get("result")
        if not res:
            return pd.Series(dtype=float)
        r0 = res[0]
        ts = r0.get("timestamp") or []
        ind = r0.get("indicators", {}) or {}
        adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
        close = (ind.get("quote") or [{}])[0].get("close")
        vals = adj if adj else close
        if not ts or not vals:
            return pd.Series(dtype=float)
        idx, data = [], []
        for t, v in zip(ts, vals):
            if v is None:
                continue
            idx.append(pd.Timestamp(datetime.fromtimestamp(t, tz=timezone.utc).date()))
            data.append(float(v))
        return pd.Series(data, index=idx, name=ticker).sort_index()
    except (KeyError, IndexError, TypeError, ValueError):
        return pd.Series(dtype=float)


def parse_yahoo_meta(payload: dict) -> dict:
    """Extrae metadatos de identificación del instrumento desde chart.meta."""
    try:
        res = (payload or {}).get("chart", {}).get("result")
        if not res:
            return {}
        m = res[0].get("meta", {}) or {}
        it = (m.get("instrumentType") or "").upper()
        asset_class = "equity" if it == "EQUITY" else "etf" if it == "ETF" else "unknown"
        return {
            "name": m.get("longName") or m.get("shortName"),
            "asset_class": asset_class,
            "instrument_type_raw": m.get("instrumentType"),
            "exchange": m.get("fullExchangeName") or m.get("exchangeName"),
            "exchange_code": m.get("exchangeName"),
            "quote_currency": m.get("currency") or None,
            "currency": m.get("currency") or "USD",
            "timezone": m.get("exchangeTimezoneName") or m.get("timezone"),
            "symbol": m.get("symbol"),
        }
    except (KeyError, IndexError, TypeError):
        return {}


def parse_yahoo_history_bars(payload: dict) -> List[dict]:
    """Barras diarias {as_of, close, volume, adjusted} desde la respuesta chart.

    `adjusted` indica si el cierre proviene de adjclose (ajustado por splits y
    dividendos). Si Yahoo no entrega adjclose y se usa el cierre crudo, adjusted=False
    (control: NO marcar ajustado por defecto)."""
    res = (payload or {}).get("chart", {}).get("result")
    if not res:
        return []
    r0 = res[0] or {}
    ts = r0.get("timestamp") or []
    ind = r0.get("indicators", {}) or {}
    adj = (ind.get("adjclose") or [{}])[0].get("adjclose")
    close = (ind.get("quote") or [{}])[0].get("close")
    vol = (ind.get("quote") or [{}])[0].get("volume")
    use_adj = bool(adj)
    series = adj if use_adj else close
    if not ts or not series:
        return []
    out: List[dict] = []
    for i, t in enumerate(ts):
        c = series[i] if i < len(series) else None
        if c is None:
            continue
        v = vol[i] if (vol and i < len(vol)) else None
        out.append({
            "as_of": datetime.fromtimestamp(float(t), tz=timezone.utc).date().isoformat(),
            "close": float(c),
            "volume": float(v) if v is not None else None,
            "adjusted": use_adj,
        })
    return out


def parse_yahoo_splits(payload: dict) -> List[dict]:
    """Extrae splits de chart.result[0].events.splits (fuente verificable de Yahoo).

    Cada evento: {date epoch, numerator, denominator, splitRatio "10:1"}.
    ratio = numerator/denominator (forward 10-for-1 => 10; reverse 1-for-10 => 0.1).
    """
    res = (payload or {}).get("chart", {}).get("result")
    if not res:
        return []
    events = (res[0] or {}).get("events", {}) or {}
    splits = events.get("splits", {}) or {}
    out: List[dict] = []
    for ev in splits.values():
        try:
            num = int(ev.get("numerator"))
            den = int(ev.get("denominator"))
            if num <= 0 or den <= 0:
                continue
            ex_date = datetime.fromtimestamp(float(ev["date"]), tz=timezone.utc).date().isoformat()
            ratio = num / den
            out.append({
                "ex_date": ex_date,
                "ratio": ratio,
                "numerator": num,
                "denominator": den,
                "action_type": "split" if ratio >= 1 else "reverse_split",
                "split_ratio": ev.get("splitRatio"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    out.sort(key=lambda x: x["ex_date"])
    return out


def _market_state(meta: dict, now_epoch: float) -> Optional[str]:
    """Deriva el estado del mercado desde currentTradingPeriod (si existe)."""
    ctp = meta.get("currentTradingPeriod") or {}
    reg = ctp.get("regular") or {}
    pre = ctp.get("pre") or {}
    post = ctp.get("post") or {}
    try:
        if reg.get("start") is not None and reg.get("end") is not None:
            if reg["start"] <= now_epoch <= reg["end"]:
                return "REGULAR"
            if pre.get("start") is not None and pre["start"] <= now_epoch < reg["start"]:
                return "PRE"
            if post.get("end") is not None and reg["end"] < now_epoch <= post["end"]:
                return "POST"
            return "CLOSED"
    except (TypeError, KeyError):
        return None
    return None


def parse_quote_snapshot(payload: dict, ticker: str, now_epoch: Optional[float] = None) -> Optional[dict]:
    """Extrae un snapshot de cotización de la respuesta chart (range=1d, interval=2m).

    Devuelve None si no hay datos. NO inventa valores: los campos ausentes quedan None.
    """
    import time
    now_epoch = time.time() if now_epoch is None else now_epoch
    res = (payload or {}).get("chart", {}).get("result")
    if not res:
        return None
    r0 = res[0] or {}
    meta = r0.get("meta", {}) or {}

    ts = r0.get("timestamp") or []
    q = ((r0.get("indicators", {}) or {}).get("quote") or [{}])[0] or {}
    highs = [x for x in (q.get("high") or []) if x is not None]
    lows = [x for x in (q.get("low") or []) if x is not None]
    closes = [x for x in (q.get("close") or []) if x is not None]
    vols = [x for x in (q.get("volume") or []) if x is not None]

    price = meta.get("regularMarketPrice")
    if price is None and closes:
        price = closes[-1]
    if price is None:
        return None

    prev = meta.get("chartPreviousClose")
    if prev is None:
        prev = meta.get("previousClose")

    qt = meta.get("regularMarketTime")
    if qt is None and ts:
        qt = ts[-1]
    quote_time = (datetime.fromtimestamp(float(qt), tz=timezone.utc).isoformat()
                  if qt is not None else datetime.now(timezone.utc).isoformat())

    change = (float(price) - float(prev)) if prev else None
    change_pct = (change / float(prev)) if (change is not None and prev) else None

    return {
        "ticker": ticker.upper(),
        "price": float(price),
        "previous_close": float(prev) if prev is not None else None,
        "change": change,
        "change_pct": change_pct,
        "day_high": float(max(highs)) if highs else meta.get("regularMarketDayHigh"),
        "day_low": float(min(lows)) if lows else meta.get("regularMarketDayLow"),
        "volume": float(sum(vols)) if vols else meta.get("regularMarketVolume"),
        "currency": meta.get("currency") or "USD",
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "market_state": _market_state(meta, now_epoch),
        "quote_time": quote_time,
        "source": "yahoo",
        "delayed": True,   # fuente gratuita: se asume retrasada; nunca 'tiempo real'
    }


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    is_sample = False

    def __init__(self, timeout: float = 15.0, retries: int = 2):
        import httpx
        self.retries = retries
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": _UA})

    def _chart(self, ticker: str, rng: str = "2y", interval: str = "1d",
               events: Optional[str] = None) -> dict:
        last = None
        params = {"range": rng, "interval": interval}
        if events:
            params["events"] = events   # p.ej. "div,splits" (necesario para eventos)
        for _ in range(max(1, self.retries)):
            try:
                r = self._client.get(f"{BASE}{ticker}", params=params)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last = e
        raise last

    def get_quote_snapshots(self, tickers: List[str]) -> Dict[str, dict]:
        """Snapshot de cotización (último precio, cierre previo, rango, volumen, estado).
        Best-effort por ticker; omite los que fallan (nunca inventa precio)."""
        out: Dict[str, dict] = {}
        for t in tickers:
            try:
                snap = parse_quote_snapshot(self._chart(t, rng="1d", interval="2m"), t)
            except Exception:
                snap = None
            if snap and snap.get("price") is not None:
                out[t] = snap
        return out

    def get_price_history(self, ticker, start: Optional[date] = None, end: Optional[date] = None) -> pd.Series:
        s = parse_yahoo_chart(self._chart(ticker), ticker)
        if start is not None and len(s):
            s = s[s.index >= pd.Timestamp(start)]
        if end is not None and len(s):
            s = s[s.index <= pd.Timestamp(end)]
        return s

    def get_quotes(self, tickers: List[str]) -> Dict[str, Quote]:
        out: Dict[str, Quote] = {}
        for t in tickers:
            try:
                s = self.get_price_history(t)
            except Exception:
                continue
            if len(s) == 0:
                continue
            as_of = s.index[-1].date() if hasattr(s.index[-1], "date") else date.today()
            out[t] = Quote(ticker=t, price=float(s.iloc[-1]), as_of=as_of,
                           currency="USD", is_sample=False)
        return out

    def get_history_bars(self, ticker: str, rng: str = "5y") -> List[dict]:
        """Serie diaria ajustada (close+volume) para backfill histórico."""
        try:
            return parse_yahoo_history_bars(self._chart(ticker, rng=rng, interval="1d"))
        except Exception:
            return []

    def get_splits(self, tickers: List[str]) -> Dict[str, List[dict]]:
        """Splits por ticker desde Yahoo (range=max). Best-effort; omite los que fallan."""
        out: Dict[str, List[dict]] = {}
        for t in tickers:
            try:
                sp = parse_yahoo_splits(self._chart(t, rng="max", interval="1d", events="div,splits"))
            except Exception:
                sp = []
            if sp:
                out[t] = sp
        return out

    def get_instrument_meta(self, ticker: str) -> dict:
        """Identifica el instrumento: nombre, tipo, bolsa, moneda. {} si no se puede."""
        try:
            return parse_yahoo_meta(self._chart(ticker, rng="5d"))
        except Exception:
            return {}

    def get_stats(self, tickers: List[str]) -> Dict[str, dict]:
        """Estadísticas complementarias (FALLBACK) desde el endpoint v7/quote de Yahoo:
        EPS TTM (trailing), acciones en circulación y moneda, con fecha de consulta. Best-effort;
        NO oficial — se usa sólo cuando EDGAR no cubre, con su procedencia. {} si falla."""
        import datetime as _dt
        out: Dict[str, dict] = {}
        try:
            url = "https://query1.finance.yahoo.com/v7/finance/quote"
            r = self._client.get(url, params={"symbols": ",".join(tickers)})
            if r.status_code != 200:
                return {}
            today = _dt.date.today().isoformat()
            for q in (((r.json() or {}).get("quoteResponse", {}) or {}).get("result", []) or []):
                sym = (q.get("symbol") or "").upper()
                if not sym:
                    continue
                out[sym] = {
                    "eps_ttm": q.get("epsTrailingTwelveMonths"),
                    "shares": q.get("sharesOutstanding"),
                    "currency": q.get("currency"),
                    "as_of": today,
                    "source": "yahoo:quote",
                }
        except Exception:
            return {}
        return out

    def get_fundamentals(self, tickers): return {}
    def get_etf_holdings(self, etf_ticker): return []
    def list_universe(self, exchanges=None, limit=None): return []

    def health(self) -> dict:
        return {"provider": self.name, "is_sample": False, "ok": True,
                "coverage": "Precios EOD US (Yahoo Finance chart API), sin clave"}
