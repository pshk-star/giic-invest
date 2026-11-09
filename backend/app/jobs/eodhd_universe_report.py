"""P0.4 — Reporte LIGERO del universo unificado de enriquecimiento (sin scan financiero).

Construye el universo efectivo SÓLO con lecturas de Supabase + metadatos locales (asset_class del
scanner, semillas internacionales). NO corre el scanner, NO consulta EDGAR ni EODHD. Mide el tiempo de
cada fuente para diagnosticar demoras y estima (cota superior) las consultas EODHD previstas.

Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY en env; python -m app.jobs.eodhd_universe_report
"""
from __future__ import annotations

import json
import os
import sys
import time

from app.core.types import AssetClass
from app.jobs.universe import get_universe
from app.core.connectors.eodhd import EODHD_SYMBOLS


def report() -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    timings = {}

    t0 = time.monotonic()
    uni = get_universe()                       # scanner (local, sin red)
    scanner = {i.ticker.upper(): i for i in uni}
    vehiculos = {t for t, i in scanner.items() if i.asset_class != AssetClass.EQUITY}   # ETF/trust
    timings["get_universe_local"] = round(time.monotonic() - t0, 3)

    origin = {}
    def add(ts, src):
        for t in ts or []:
            origin.setdefault(str(t).upper(), []).append(src)
    add(scanner.keys(), "scanner")

    writer = None
    cartera = instruments = []
    if url and srk:
        from app.jobs.supabase_writer import SupabaseWriter
        writer = SupabaseWriter(url, srk)
        t1 = time.monotonic()
        try:
            cartera = writer.get_transaction_tickers()
        except Exception as e:
            cartera = []; origin["_error_cartera"] = type(e).__name__
        timings["supabase_cartera"] = round(time.monotonic() - t1, 3)
        t2 = time.monotonic()
        try:
            rows = writer.select_rows("instruments", select="ticker", params={"order": "ticker"})
            instruments = [r["ticker"] for r in rows if r.get("ticker")]
        except Exception as e:
            instruments = []; origin["_error_instruments"] = type(e).__name__
        timings["supabase_instruments"] = round(time.monotonic() - t2, 3)
    add(cartera, "cartera")
    add(instruments, "research/instruments")
    add(list(EODHD_SYMBOLS.keys()), "internacional")

    tickers = {t for t in origin if not t.startswith("_")}
    # Clasificación LOCAL: vehículos del scanner (ETF/trust) → excluidos (tratamiento específico).
    excluidos = {t: "ETF/vehículo (tratamiento específico, sin EODHD)" for t in tickers if t in vehiculos}
    corporativos = sorted(t for t in tickers if t not in vehiculos)

    por_origen = {o: sum(1 for v in origin.values() if isinstance(v, list) and o in v)
                  for o in ("scanner", "cartera", "research/instruments", "internacional")}
    return {
        "emisores_unicos_total": len(tickers),
        "corporativos_candidatos": len(corporativos),
        "excluidos_vehiculo": len(excluidos),
        "por_origen": por_origen,
        "consultas_eodhd_previstas_cota_superior": len(corporativos),
        "nota_consultas": "cota superior; el gate por disponibilidad omite los vigentes en EDGAR (menos consultas reales)",
        "internacionales_eodhd": sorted(EODHD_SYMBOLS.keys()),
        "excluidos_detalle": excluidos,
        "tiempos_s": timings,
        "diagnostico_demora": ("la construcción del universo es sólo lectura Supabase (ver tiempos); "
                               "la demora del dry-run completo proviene del SCAN (histórico de precios "
                               "yahoo/stooq) y de las consultas EDGAR/EODHD por emisor, NO de armar el universo"),
    }


def main(argv=None):
    print(json.dumps(report(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
