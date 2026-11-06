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


def _avail_dates(by, series_ids):
    """Fechas de observación en que TODAS las series de la lista tienen al menos un
    vintage PIT-válido (vintage<=obs_date y release<=obs_date como aproximación de
    'conocido en o cerca de la fecha'); aquí simplificamos a: existe la observación.
    Devuelve el conjunto de obs_date cubiertos por cada serie y la intersección."""
    per = {}
    for s in series_ids:
        per[s] = set(r["obs_date"] for r in by.get(s, []) if r.get("value") is not None)
    if not per:
        return set(), per
    inter = None
    for s, dd in per.items():
        inter = dd if inter is None else (inter & dd)
    return (inter or set()), per


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
    inter_all, _ = _avail_dates(by, all_present)
    inter_long, _ = _avail_dates(by, long_present)

    def summ(dates):
        ds = sorted(dates)
        return {"n_dates": len(ds), "first": ds[0] if ds else None, "last": ds[-1] if ds else None,
                "years": (round((_y(ds[-1]) - _y(ds[0])), 1) if ds else 0)}

    with_all = summ(inter_all)
    with_long = summ(inter_long)
    gained = with_long["n_dates"] - with_all["n_dates"]
    gained_years = round((with_long["years"] - with_all["years"]), 1)

    return {
        "read_only": True, "modifies_C": False,
        "long_series_used": long_present, "series_missing_in_db": missing,
        "series_spans": spans,
        "common_sample_with_all_6": with_all,
        "common_sample_long_only_excluding_NFCI_HY": with_long,
        "information_change": {
            "extra_common_dates": gained,
            "extra_years": gained_years,
            "interpretation": ("Excluir NFCI y HY extiende la ventana común macro de "
                               f"{with_all['first']} a {with_long['first']} "
                               f"(+{gained_years} años, +{gained} fechas de observación comunes). "
                               "La pérdida es la señal de condiciones financieras (NFCI) y de crédito "
                               "HY (BAMLH0A0HYM2); en el experimento A/B/C la macro NO aportó señal "
                               "transversal (es constante por fecha), por lo que la pérdida informativa "
                               "para ESTE uso transversal es baja. Validar en una C versionada aparte."),
        },
        "caveat": "Cobertura por existencia de observación PIT; una C nueva debe re-evaluarse "
                  "con vintage/release estrictos y comparación pareada dentro de su propia muestra.",
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
