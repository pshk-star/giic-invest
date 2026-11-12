"""Sonda read-only: imprime la serie EDGAR derivada (adaptador P1) para tickers dados, para diagnosticar
por qué un ticker queda insuficiente o produce un FV absurdo. NO escribe nada."""
from __future__ import annotations

import json
import os
import sys

from app.research.edgar_series import build_series_from_rows, fetch_edgar_rows


def run(tickers):
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    out = {}
    for t in tickers:
        rows = fetch_edgar_rows(w, t)
        s = build_series_from_rows(rows)
        by = s["by_field"]
        periods = sorted(by.get("revenue", {}))
        last = periods[-1] if periods else None
        campos = {}
        for f in ("revenue", "operating_income", "net_income", "tax", "capex", "dna", "cash",
                  "total_debt", "equity", "invested_capital", "shares", "ocf", "wc_change"):
            d = by.get(f, {})
            campos[f] = d.get(last) if last else None
        # conceptos crudos disponibles (para ver qué falta)
        concepts_present = sorted({r["concept"] for r in rows})
        out[t] = {"filas": len(rows), "moneda": s["currency"], "ultimo_periodo": last,
                  "n_periodos_revenue": len(periods), "campos_ultimo": campos,
                  "meta_ultimo": s["meta"].get(last) if last else None,
                  "conceptos_presentes": concepts_present}
    return out


def main(argv=None):
    tickers = [t.upper() for t in (argv or sys.argv[1:])] or ["PFE", "MRK", "MCD"]
    print(json.dumps(run(tickers), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
