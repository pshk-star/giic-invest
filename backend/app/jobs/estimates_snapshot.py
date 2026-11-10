"""P1.7 Fase 1 — CAPTURA PROSPECTIVA INMUTABLE de expectativas (estimaciones, revisiones,
targets, ratings y múltiplos forward) de EODHD /fundamentals que YA pagamos.

Reutiliza infraestructura existente:
  - tabla `pit_snapshots` (migración 0006/0007): append-only, trigger de inmutabilidad y
    UNIQUE (kind, ticker, observation_date, snapshot_date) => dedupe nativo. Nunca sobrescribe.
  - `SupabaseWriter.insert_append` con resolution=ignore-duplicates => reintentar la misma
    captura del día es idempotente (no actualiza filas previas: el historial se conserva).
  - `EodhdFundamentalsConnector._resolve` (objeto cacheado; una sola llamada por ticker).

Tres fechas DISTINTAS (exigidas): `captured_at` (cuándo lo registramos), `published_at`
(fecha efectiva del dato = fecha del trend de EODHD), `observation_date` (fin del período
FISCAL al que se refiere la estimación). El período fiscal textual va además en payload.

Controles: duplicados (UNIQUE + DO NOTHING), costo de API (1 fetch/ticker, contado), y
fallos parciales (try/except por ticker; un ticker caído no aborta el resto). Incluye un
GUARD de escala/período (P1.7 #5): marca estimaciones con escala implausible vs. lo reportado
para que NUNCA se usen a ciegas para actualizar el FCFF.

Uso:
  python -m app.jobs.estimates_snapshot --dry-run            # imprime filas + cobertura, no escribe
  python -m app.jobs.estimates_snapshot --tickers NVDA META  # escribe (requiere SUPABASE_*)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from app.core.connectors.eodhd import EodhdFundamentalsConnector, eodhd_annual_series_full

# MVP científicamente defendible: las 5 (P1.7). Ampliable sin tocar el esquema.
DEFAULT_TICKERS = ["NVDA", "META", "NFLX", "TSM", "ASML"]

# Guard de escala para estimaciones de INGRESOS vs. último ingreso anual reportado (misma
# moneda). Rango ancho a propósito: hasta 6x admite estimaciones a +2 años de alto crecimiento
# (p.ej. TSM FY2027 ~2x FY2025); por debajo de 0.3x o por encima de 6x => revisar unidades/escala.
REV_SCALE_LO, REV_SCALE_HI = 0.30, 6.0


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(x) -> Optional[float]:
    try:
        if x is None or x == "" or (isinstance(x, str) and x.lower() in ("na", "null", "none")):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _parse_period_end(key: str, datum: dict) -> Optional[str]:
    """Fin de período fiscal al que se refiere la estimación. EODHD Earnings.Trend usa como
    clave la fecha de fin de período (YYYY-MM-DD). Devuelve esa fecha o None si no parseable."""
    for cand in (key, (datum or {}).get("date")):
        if isinstance(cand, str) and len(cand) == 10 and cand[4] == "-" and cand[7] == "-":
            try:
                date.fromisoformat(cand)
                return cand
            except ValueError:
                continue
    return None


def _dispersion(avg: Optional[float], lo: Optional[float], hi: Optional[float]) -> Optional[float]:
    """Coeficiente de dispersión = (high-low)/|avg|. None si falta algo o avg~0."""
    if avg is None or lo is None or hi is None or abs(avg) < 1e-9:
        return None
    return round((hi - lo) / abs(avg), 4)


def revenue_scale_check(value: Optional[float], reported_revenue: Optional[float]) -> dict:
    """GUARD P1.7 #5. Compara una estimación de ingresos con el último ingreso anual reportado
    (MISMA moneda, MISMA escala de campo crudo). No corrige: marca para revisión humana.
    - ratio en [0.3, 6.0]  => 'ok'
    - fuera de rango        => 'revisar_escala' con el ratio y una hipótesis de orden de magnitud.
    """
    if value is None or reported_revenue is None or reported_revenue <= 0:
        return {"status": "sin_referencia"}
    ratio = value / reported_revenue
    out = {"status": "ok" if REV_SCALE_LO <= ratio <= REV_SCALE_HI else "revisar_escala",
           "ratio_vs_reported": round(ratio, 4)}
    if out["status"] == "revisar_escala":
        # hipótesis de unidad: ¿difieren por ~10^3 (miles) o ~10^6 (millones)?
        import math
        mag = round(math.log10(abs(ratio))) if ratio > 0 else None
        out["magnitude_hint"] = mag
        out["note"] = ("posible desajuste de unidades/escala; revisar antes de usar en FCFF"
                       if mag not in (None, 0) else "escala inconsistente con lo reportado")
    return out


def _row(kind: str, ticker: str, observation_date: str, snapshot_date: str, captured_at: str,
         source: str, data_version: Optional[str], payload: dict) -> dict:
    return {"kind": kind, "ticker": ticker, "observation_date": observation_date,
            "published_at": payload.get("effective_date"), "snapshot_date": snapshot_date,
            "captured_at": captured_at, "source": source, "data_version": data_version,
            "payload": payload}


def build_estimate_rows(ticker: str, obj: dict, snapshot_date: str, captured_at: str,
                        reported_revenue: Optional[float] = None) -> List[dict]:
    """PURO y testeable: objeto /fundamentals crudo -> filas pit_snapshots. Sin red.

    `reported_revenue`: último ingreso anual reportado (misma moneda) para el guard de escala.
    """
    obj = obj or {}
    gen = obj.get("General", {}) or {}
    ccy = gen.get("CurrencyCode")
    data_version = gen.get("UpdatedAt")
    earn = (obj.get("Earnings", {}) or {})
    trend = earn.get("Trend", {}) or {}
    ar = obj.get("AnalystRatings", {}) or {}
    hi = obj.get("Highlights", {}) or {}
    val = obj.get("Valuation", {}) or {}
    rows: List[dict] = []

    # 1) Estimaciones forward + dispersión + #analistas + revisiones + trend (por período fiscal).
    for key in sorted(trend.keys()):
        d = trend.get(key) or {}
        pe = _parse_period_end(key, d)
        obs = pe or snapshot_date  # si no hay fecha de período, ancla al día de captura
        eff = d.get("date")
        period_label = d.get("period")
        base = {"fiscal_period_end": pe, "fiscal_period_label": period_label,
                "effective_date": eff, "currency": ccy}

        # 1a) Ingresos
        rev_avg = _num(d.get("revenueEstimateAvg"))
        if rev_avg is not None:
            payload = {**base, "metric": "revenue", "unit": "raw_currency", "value": rev_avg,
                       "low": _num(d.get("revenueEstimateLow")), "high": _num(d.get("revenueEstimateHigh")),
                       "n_analysts": _num(d.get("revenueEstimateNumberOfAnalysts")),
                       "growth": _num(d.get("revenueEstimateGrowth"))}
            payload["dispersion"] = _dispersion(rev_avg, payload["low"], payload["high"])
            payload["scale_check"] = revenue_scale_check(rev_avg, reported_revenue)
            rows.append(_row("estimate:revenue", ticker, obs, snapshot_date, captured_at,
                             "EODHD:Earnings.Trend", data_version, payload))

        # 1b) EPS + revisiones + trend temporal (revisiones = señal prospectiva clave)
        eps_avg = _num(d.get("earningsEstimateAvg"))
        if eps_avg is not None:
            payload = {**base, "metric": "eps", "unit": "per_share", "value": eps_avg,
                       "low": _num(d.get("earningsEstimateLow")), "high": _num(d.get("earningsEstimateHigh")),
                       "n_analysts": _num(d.get("earningsEstimateNumberOfAnalysts")),
                       "growth": _num(d.get("earningsEstimateGrowth")),
                       "trend": {k: _num(d.get(v)) for k, v in
                                 (("current", "epsTrendCurrent"), ("d7", "epsTrend7daysAgo"),
                                  ("d30", "epsTrend30daysAgo"), ("d60", "epsTrend60daysAgo"),
                                  ("d90", "epsTrend90daysAgo"))},
                       "revisions": {k: _num(d.get(v)) for k, v in
                                     (("up7", "epsRevisionsUpLast7days"), ("up30", "epsRevisionsUpLast30days"),
                                      ("down7", "epsRevisionsDownLast7days"), ("down30", "epsRevisionsDownLast30days"))}}
            payload["dispersion"] = _dispersion(eps_avg, payload["low"], payload["high"])
            rows.append(_row("estimate:eps", ticker, obs, snapshot_date, captured_at,
                             "EODHD:Earnings.Trend", data_version, payload))

    # 2) Targets y ratings de analistas (snapshot; se ancla al día de captura).
    if ar:
        payload = {"effective_date": snapshot_date, "currency_note": "TargetPrice en moneda de cotización",
                   "target_price": _num(ar.get("TargetPrice")), "rating": _num(ar.get("Rating")),
                   "counts": {k: _num(ar.get(k)) for k in ("StrongBuy", "Buy", "Hold", "Sell", "StrongSell")}}
        if payload["target_price"] is not None or payload["rating"] is not None:
            rows.append(_row("analyst_target_rating", ticker, snapshot_date, snapshot_date, captured_at,
                             "EODHD:AnalystRatings", data_version, payload))

    # 3) Múltiplos forward (snapshot). ForwardPE/PEG + EPS estimados agregados de Highlights.
    fwd = {"forward_pe": _num(val.get("ForwardPE")) or _num(hi.get("ForwardPE")),
           "peg": _num(hi.get("PEGRatio")), "ps_ttm": _num(val.get("PriceSalesTTM")),
           "ev_ebitda": _num(val.get("EnterpriseValueEbitda")),
           "eps_cy": _num(hi.get("EPSEstimateCurrentYear")), "eps_ny": _num(hi.get("EPSEstimateNextYear")),
           "eps_cq": _num(hi.get("EPSEstimateCurrentQuarter")), "eps_nq": _num(hi.get("EPSEstimateNextQuarter"))}
    if any(v is not None for v in fwd.values()):
        rows.append(_row("forward_multiple", ticker, snapshot_date, snapshot_date, captured_at,
                         "EODHD:Highlights+Valuation", data_version,
                         {"effective_date": snapshot_date, "currency": ccy, **fwd}))
    return rows


def _latest_annual_revenue(obj: dict) -> Optional[float]:
    """Último ingreso anual reportado (misma moneda cruda) para el guard de escala."""
    try:
        ser = eodhd_annual_series_full(obj) or {}
        rev = ser.get("revenue") or {}
        vals = [(_num(v.get("value")) if isinstance(v, dict) else _num(v)) for k, v in sorted(rev.items())]
        vals = [v for v in vals if v is not None]
        return vals[-1] if vals else None
    except Exception:
        return None


def capture(tickers: List[str], dry_run: bool = True) -> dict:
    key = os.getenv("EODHD_API_KEY", "")
    snapshot_date = date.today().isoformat()
    captured_at = _utcnow()
    summary = {"snapshot_date": snapshot_date, "dry_run": dry_run, "api_fetches": 0,
               "tickers": {}, "coverage": {}, "scale_flags": [], "total_rows": 0, "errors": {}}
    if not key:
        summary["error"] = "sin EODHD_API_KEY"
        return summary
    conn = EodhdFundamentalsConnector(api_key=key)
    all_rows: List[dict] = []
    for t in tickers:
        try:
            sym, _adr, obj = conn._resolve(t)   # 1 fetch/ticker (cacheado)
            summary["api_fetches"] += 1
            if not obj:
                summary["errors"][t] = "sin objeto"
                continue
            rep_rev = _latest_annual_revenue(obj)
            rows = build_estimate_rows(t, obj, snapshot_date, captured_at, reported_revenue=rep_rev)
            all_rows.extend(rows)
            kinds: Dict[str, int] = {}
            for r in rows:
                kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
                sc = (r["payload"] or {}).get("scale_check") or {}
                if sc.get("status") == "revisar_escala":
                    summary["scale_flags"].append({"ticker": t, "period": r["observation_date"],
                                                    "value": r["payload"].get("value"), **sc})
            summary["tickers"][t] = {"symbol": sym, "rows": len(rows), "by_kind": kinds,
                                     "reported_revenue_ref": rep_rev}
        except Exception as e:  # fallo parcial: no aborta el resto
            summary["errors"][t] = f"{type(e).__name__}: {str(e)[:120]}"
    # cobertura agregada por kind
    cov: Dict[str, int] = {}
    for r in all_rows:
        cov[r["kind"]] = cov.get(r["kind"], 0) + 1
    summary["coverage"] = cov
    summary["total_rows"] = len(all_rows)
    if dry_run:
        summary["sample_rows"] = all_rows[:6]
        return summary
    # Escritura inmutable: dedupe nativo por UNIQUE; DO NOTHING conserva snapshots previos.
    from app.jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    blob = json.dumps(all_rows, default=str)
    sk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if sk and sk in blob:
        raise RuntimeError("ABORT: secret leak detected in snapshot rows")
    writer.insert_append("pit_snapshots", all_rows,
                         on_conflict="kind,ticker,observation_date,snapshot_date")
    # confirmación: releer lo persistido para hoy
    stored = writer.select_rows("pit_snapshots", select="kind,ticker,observation_date",
                                params={"snapshot_date": f"eq.{snapshot_date}",
                                        "kind": "like.estimate:*"})
    summary["stored_confirm"] = len(stored)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tickers", nargs="*")
    args = p.parse_args(argv)
    tickers = [t.upper() for t in args.tickers] if args.tickers else DEFAULT_TICKERS
    out = capture(tickers, dry_run=args.dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
