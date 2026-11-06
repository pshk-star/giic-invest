"""Análisis de COBERTURA histórica y pérdida de información al excluir NFCI y HY del
set macro PIT (SOLO LECTURA; NO modifica C ni ninguna especificación).

Motivo: en el experimento A/B/C el cuello de botella de historia común era la macro,
porque NFCI (vintages desde 2023) y HY-OAS (BAMLH0A0HYM2, desde 2017) tienen vintages
cortos. Aquí se cuantifica, de forma PIT estricta (vintage<=d y release_date<=d), cuánta
historia común se GANA si se excluyen esas dos series, conservando las de vintage largo
(CPI, UNRATE, DGS2/10, T10Y2Y). Cualquier nueva especificación de C deberá versionarse y
evaluarse por separado.

Uso: python -m app.research.macro_coverage
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict

LONG = ["CPIAUCSL", "UNRATE", "DGS2", "DGS10", "T10Y2Y"]
SHORT = ["NFCI", "BAMLH0A0HYM2"]
ALL = LONG + SHORT


def pit_window(by, series_ids):
    """Ventana en que TODAS las series son PIT-disponibles a la vez. La restricción
    vinculante es la ÚLTIMA serie en volverse conocida: inicio = max(primer vintage).
    Fin = min(última obs). Correcto con frecuencias mixtas (mensual vs diaria): NO usa
    intersección de fechas exactas (que se vaciaría por calendarios distintos)."""
    first_vints, last_obs = [], []
    for s in series_ids:
        rs = by.get(s, [])
        vs = [r["vintage"] for r in rs if r.get("vintage")]
        ob = [r["obs_date"] for r in rs if r.get("value") is not None]
        if not vs or not ob:
            return {"start": None, "end": None, "years": 0, "binding_series": s}
        first_vints.append((min(vs), s)); last_obs.append(max(ob))
    start, binding = max(first_vints)          # la última en estar disponible manda
    end = min(last_obs)
    years = round(_y(end) - _y(start), 1) if (start and end and end >= start) else 0
    return {"start": start, "end": end, "years": years, "binding_series": binding}


def run(writer) -> dict:
    rows = writer.select_rows("macro_pit", select="series_id,obs_date,value,release_date,vintage",
                              params={"series_id": "in.(" + ",".join(ALL) + ")"})
    by = defaultdict(list)
    for r in rows:
        by[r["series_id"]].append(r)

    spans = {}
    for s in ALL:
        rs = by.get(s, [])
        obs = sorted(r["obs_date"] for r in rs if r.get("value") is not None)
        vints = sorted(r["vintage"] for r in rs if r.get("vintage"))
        spans[s] = {
            "rows": len(rs),
            "first_obs": obs[0] if obs else None, "last_obs": obs[-1] if obs else None,
            "first_vintage": vints[0] if vints else None,
            "included_in": "LONG" if s in LONG else "SHORT (candidato a excluir)",
        }

    long_present = [s for s in LONG if by.get(s)]
    all_present = [s for s in ALL if by.get(s)]
    missing = [s for s in ALL if not by.get(s)]

    with_all = pit_window(by, all_present)
    with_long = pit_window(by, long_present)
    gained_years = round((with_long["years"] or 0) - (with_all["years"] or 0), 1)

    return {
        "read_only": True, "modifies_C": False,
        "long_series_used": long_present, "series_missing_in_db": missing,
        "series_spans": spans,
        "pit_window_with_all_6": with_all,
        "pit_window_long_only_excluding_NFCI_HY": with_long,
        "information_change": {
            "start_moves_from": with_all["start"], "start_moves_to": with_long["start"],
            "binding_series_all": with_all["binding_series"],
            "binding_series_long": with_long["binding_series"],
            "extra_years": gained_years,
            "interpretation": (
                f"La disponibilidad PIT conjunta de las 6 series arranca en {with_all['start']} "
                f"(la vinculante es {with_all['binding_series']}). Excluyendo NFCI y HY, arranca en "
                f"{with_long['start']} (vinculante {with_long['binding_series']}): +{gained_years} años "
                "de historia PIT utilizable. Se pierde la señal de condiciones financieras (NFCI) y "
                "crédito HY; pero en el experimento A/B/C la macro NO aportó señal transversal (es "
                "constante por fecha), por lo que para ESTE uso transversal la pérdida informativa es "
                "baja. Cualquier C nueva debe versionarse y evaluarse por separado."),
        },
        "caveat": "Ventana por restricción de vintage (la última serie en estar disponible manda). "
                  "Frecuencias mixtas: no se usa intersección de fechas exactas.",
    }


def _y(s):
    from datetime import date
    y, m, d = map(int, s.split("-")); return date(y, m, d).toordinal() / 365.25


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
