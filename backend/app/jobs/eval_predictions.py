"""Evaluación POSTERIOR de predicciones prospectivas ya maduradas (evaluate_on <= hoy).

Append-only: escribe en prediction_outcomes (unique prediction_id, ignore-duplicates).
NO modifica ninguna predicción emitida. Si nada ha madurado aún, reporta 0 (correcto).

Métrica alineada con el target del modelo (retorno RELATIVO al equiponderado del universo
emitido ese día). Guarda también el absoluto, el del mercado equiponderado y el de SPY.

Uso: python -m app.jobs.eval_predictions [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from ..providers import get_provider


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ret(bars_by_date: Dict[str, float], a: str, b: str) -> Optional[float]:
    pa, pb = bars_by_date.get(a), bars_by_date.get(b)
    if pa and pb and pa > 0:
        return pb / pa - 1.0
    return None


def run(provider, writer, dry_run: bool) -> dict:
    today = _today()
    preds = writer.select_rows(
        "predictions",
        select="id,model_name,model_version,ticker,as_of,evaluate_on,horizon_sessions,prediction",
        params={"origin": "eq.production", "evaluate_on": f"lte.{today}"})
    if not preds:
        return {"matured": 0, "note": "ninguna predicción ha alcanzado su evaluate_on todavía", "today": today}

    done = {r["prediction_id"] for r in writer.select_rows("prediction_outcomes", select="prediction_id")}
    pending = [p for p in preds if p["id"] not in done]
    if not pending:
        return {"matured": len(preds), "evaluated_now": 0, "note": "todas ya evaluadas", "today": today}

    tickers = sorted({p["ticker"] for p in pending} | {"SPY"})
    closes = {}
    for t in tickers:
        bars = provider.get_history_bars(t, rng="5y")
        closes[t] = {x["as_of"]: x["close"] for x in bars}

    # mercado equiponderado por fecha de emisión (universo emitido ese día)
    by_asof = defaultdict(set)
    for p in pending:
        by_asof[p["as_of"]].add(p["ticker"])

    rows: List[dict] = []
    for p in pending:
        a, b, t = p["as_of"], p["evaluate_on"], p["ticker"]
        abs_r = _ret(closes.get(t, {}), a, b)
        if abs_r is None:
            continue
        peers = [_ret(closes.get(x, {}), a, b) for x in by_asof[p["as_of"]]]
        peers = [x for x in peers if x is not None]
        mkt = sum(peers) / len(peers) if peers else 0.0
        spy = _ret(closes.get("SPY", {}), a, b)
        rel = abs_r - mkt
        rows.append({
            "prediction_id": p["id"], "realized_return": round(rel, 6),
            "benchmark_return": round(mkt, 6), "outperformed": bool(abs_r > mkt),
            "detail": {"abs_return": round(abs_r, 6), "mkt_equal_weight": round(mkt, 6),
                       "spy_return": (round(spy, 6) if spy is not None else None),
                       "pred_rel_return": p["prediction"].get("rel_return"),
                       "pct_rank": p["prediction"].get("pct_rank")},
        })
    out = {"matured": len(preds), "pending": len(pending), "evaluable": len(rows), "today": today}
    if dry_run:
        out["dry_run"] = True; return out
    writer.insert_append("prediction_outcomes", rows, on_conflict="prediction_id")
    out["written"] = len(rows)
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    try:
        out = run(get_provider("yahoo"), writer, args.dry_run)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
