"""Verificación de INTEGRIDAD de la emisión prospectiva (SOLO LECTURA).

No modifica ninguna predicción. Comprueba:
  1. Que evaluate_on = as_of + horizon_sessions sesiones NYSE (recalculado con el
     calendario oficial us_market_calendar) coincide con lo almacenado.
  2. Inventario inmutable: conteo por (modelo, versión, horizonte) y rango de emitted_at.
  3. Consistencia de precios/retorno objetivo: documenta que el retorno se define sobre
     el cierre AJUSTADO de Yahoo (splits + dividendos), la misma serie usada en backtest,
     emisión y evaluación -> sin saltos espurios por split ni look-ahead de split.

Uso: python -m app.jobs.verify_emission
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

from ..research import us_market_calendar as cal
from ..research.calendar import evaluate_on


def _d(s: str) -> date:
    y, m, dd = map(int, s.split("-")); return date(y, m, dd)


def run(writer) -> dict:
    preds = writer.select_rows(
        "predictions",
        select="id,model_name,model_version,ticker,as_of,evaluate_on,horizon_sessions,emitted_at,origin",
        params={"origin": "eq.production"})
    if not preds:
        return {"production_predictions": 0, "note": "no hay predicciones de producción"}

    by = defaultdict(set)
    emitted = []
    asof_set = set()
    for p in preds:
        by[(p["model_name"], p["model_version"], p["horizon_sessions"])].add(p["ticker"])
        if p.get("emitted_at"):
            emitted.append(p["emitted_at"])
        asof_set.add(p["as_of"])

    # recomputar evaluate_on con calendario oficial, por as_of presente
    sess_cache = {}
    def sessions_for(asof):
        if asof not in sess_cache:
            sess_cache[asof] = cal.sessions(_d(asof) - timedelta(days=5), _d(asof) + timedelta(days=430))
        return sess_cache[asof]

    mism = []
    checked = 0
    for p in preds:
        exp = evaluate_on(sessions_for(p["as_of"]), p["as_of"], p["horizon_sessions"])
        checked += 1
        if exp != p["evaluate_on"]:
            mism.append({"id": p["id"], "ticker": p["ticker"], "h": p["horizon_sessions"],
                         "stored": p["evaluate_on"], "expected": exp})

    return {
        "production_predictions": len(preds),
        "as_of_dates": sorted(asof_set),
        "inventory": {f"{k[0]} {k[1]} @{k[2]}s": len(v) for k, v in sorted(by.items())},
        "emitted_at_min": min(emitted) if emitted else None,
        "emitted_at_max": max(emitted) if emitted else None,
        "evaluate_on_checked": checked,
        "evaluate_on_mismatches": mism,
        "evaluate_on_ok": len(mism) == 0,
        "return_definition": {
            "price_series": "Yahoo adjusted close (ajustado por splits y dividendos)",
            "consistency": "misma serie en backtest, emisión y evaluación -> sin salto espurio por split",
            "limitation": "el cierre ajustado se re-ajusta retroactivamente ante nuevos dividendos/splits; "
                          "limitación PIT menor sobre el nivel histórico, no sobre el retorno prospectivo medido.",
        },
        "immutability": "verificación de SOLO LECTURA; no se modificó ninguna fila. Los triggers "
                        "prevent_mutation() de la BD bloquean UPDATE/DELETE sobre predictions.",
    }


def main(argv=None):
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    try:
        out = run(writer)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
