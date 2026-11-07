"""E2 — reporte del registro de conectores (solo lectura). Evidencia del diseño.

Imprime el CATÁLOGO declarado (cobertura/prioridad/procedencia/calidad/costo/caché/estado/
limitaciones) del registro por defecto — legible sin red. Si hay EDGAR_USER_AGENT, además
demuestra en VIVO el merge por calidad del registro sobre unos pocos tickers representativos
(operativa, trust no_aplica, bloqueado), mostrando la procedencia por campo.

Uso: python -m app.jobs.connector_registry_report
No escribe nada. No incorpora conectores por empresa.
"""
from __future__ import annotations

import json
import os
import sys

from app.core.connectors import build_default_registry
from app.services.identity import resolve_identity

DEMO = ["AAPL", "GLD", "MU"]       # operativa | commodity trust (no_aplica) | bloqueado


def run() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    reg = build_default_registry(edgar_user_agent=ua or None)
    out = {"catalogo": reg.health()}

    if ua and "@" in ua:
        ctx = {}
        for t in DEMO:
            try:
                ctx[t] = {"instrument_type": resolve_identity(t).get("instrument_type")}
            except Exception:
                ctx[t] = {}
        merged = reg.fetch_merged("fundamentals", DEMO, context=ctx)
        demo = {}
        for t in DEMO:
            fields = merged.get(t, {})
            demo[t] = {
                "instrument_type": ctx[t].get("instrument_type"),
                "campos": {k: {"value": v.value, "quality": v.quality, "fuente": v.connector_id,
                               "procedencia": v.provenance, "as_of": v.as_of, "metodo": v.method}
                           for k, v in sorted(fields.items())},
            }
        out["demo_merge_en_vivo"] = demo
    else:
        out["demo_merge_en_vivo"] = "omitida (sin EDGAR_USER_AGENT): catálogo es declarativo"
    return out


def main(argv=None):
    try:
        print(json.dumps(run(), indent=2, default=str, ensure_ascii=False))
        return 0
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300],
                          "tb": traceback.format_exc()[-800:]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
