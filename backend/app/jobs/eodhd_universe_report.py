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
    cartera = []
    catalogo_instruments = 0
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
            # Sólo para CONTEXTO: tamaño del catálogo de identidad (NO entra al universo diario).
            rows = writer.select_rows("instruments", select="ticker", params={"order": "ticker"})
            catalogo_instruments = len([r for r in rows if r.get("ticker")])
        except Exception:
            catalogo_instruments = -1
        timings["supabase_instruments_catalogo"] = round(time.monotonic() - t2, 3)
    add(cartera, "cartera")
    add(list(EODHD_SYMBOLS.keys()), "internacional")

    tickers = {t for t in origin if not t.startswith("_")}
    # Clasificación LOCAL: vehículos del scanner (ETF/trust) → excluidos (tratamiento específico).
    excluidos = {t: "ETF/vehículo (tratamiento específico, sin EODHD)" for t in tickers if t in vehiculos}
    corporativos = sorted(t for t in tickers if t not in vehiculos)

    por_origen = {o: sum(1 for v in origin.values() if isinstance(v, list) and o in v)
                  for o in ("scanner", "cartera", "internacional")}
    return {
        "emisores_unicos_total": len(tickers),
        "corporativos_candidatos": len(corporativos),
        "excluidos_vehiculo": len(excluidos),
        "por_origen": por_origen,
        "catalogo_instruments_filas": catalogo_instruments,
        "nota_catalogo": "el catálogo instruments (~identidad/autocompletado) NO entra al universo diario; "
                         "Research se enriquece on-demand para no superar el límite de API",
        "consultas_eodhd_previstas_cota_superior": len(corporativos),
        "nota_consultas": "cota superior; el gate por disponibilidad omite los vigentes en EDGAR (menos consultas reales)",
        "internacionales_eodhd": sorted(EODHD_SYMBOLS.keys()),
        "excluidos_detalle": excluidos,
        "tiempos_s": timings,
        "diagnostico_demora": ("la construcción del universo es sólo lectura Supabase (ver tiempos); "
                               "la demora del dry-run completo proviene del SCAN (histórico de precios "
                               "yahoo/stooq) y de las consultas EDGAR/EODHD por emisor, NO de armar el universo"),
    }


def verify_enrichment(tickers) -> dict:
    """Lectura directa de Supabase (evidencia): para cada ticker, resumen del bloque enrichment
    persistido (fuente, campos, cuarentena, estados) y preservación de EDGAR. Más la cuenta de las
    309 predicciones y el último scan completado (integridad)."""
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    tu = [t.upper() for t in tickers]
    rows = w.select_rows("fundamentals", select="ticker,payload",
                         params={"order": "ticker", "ticker": f"in.({','.join(tu)})"})
    pay = {r["ticker"].upper(): (r.get("payload") or {}) for r in rows}
    out = {}
    for t in tu:
        p = pay.get(t)
        if p is None:
            out[t] = {"fila": "ausente"}; continue
        enr = p.get("enrichment") or {}
        fl = enr.get("fields", {}) or {}
        out[t] = {
            "source_kind": p.get("source_kind", "edgar+eodhd"),
            "tiene_enrichment": bool(enr),
            "symbol": enr.get("symbol"), "currency": enr.get("currency"),
            "n_fields": len(fl), "quarantine": sorted((enr.get("quarantine") or {}).keys()),
            "carried_forward": bool(enr.get("carried_forward")),
            "aptos_valoracion": sorted(k for k, v in fl.items() if v.get("valuation_eligible")),
            "edgar_pe_ttm": p.get("pe_ttm"), "edgar_as_of": p.get("as_of"),
            "muestra_campo": next(({"campo": k, **{x: v.get(x) for x in ("period_type", "quality_state", "period_end", "currency")}}
                                   for k, v in fl.items()), None),
        }
    try:
        preds = w.select_rows("predictions", select="id", params={"order": "id", "origin": "eq.production"})
        out["_predicciones_produccion"] = len(preds)
    except Exception as e:
        out["_predicciones_produccion"] = f"error: {type(e).__name__}"
    try:
        runs = w.select_rows("scan_runs", select="id,as_of,status",
                             params={"order": "as_of.desc", "status": "eq.completed", "limit": "1"})
        out["_ultimo_scan"] = runs[0] if runs else None
    except Exception:
        out["_ultimo_scan"] = None
    return out


def dump_payloads(tickers) -> dict:
    """Volcado SOLO LECTURA del payload persistido (subconjunto que consume la ficha Research):
    enrichment completo, history anual y campos fundamentales núcleo. Evidencia para capturas P1.1
    con datos REALES (no fabricados). No escribe nada."""
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    tu = [t.upper() for t in tickers]
    rows = w.select_rows("fundamentals", select="ticker,payload",
                         params={"order": "ticker", "ticker": f"in.({','.join(tu)})"})
    pay = {r["ticker"].upper(): (r.get("payload") or {}) for r in rows}
    # Campos que lee FinancialFiche.tsx (más enrichment/history completos).
    KEEP = ("pe_ttm", "eps", "eps_annual", "eps_ttm", "eps_basis", "fcf_annual", "fcf_ttm",
            "net_debt", "gross_debt", "cash_and_sti", "operating_margin", "gross_margin",
            "net_margin", "rev_growth_yoy", "roe", "roic", "fcf_yield", "ev_ebitda",
            "diluted_shares", "debt_to_equity", "market_cap", "currency", "as_of",
            "taxonomy", "source_kind")
    out = {}
    for t in tu:
        p = pay.get(t)
        if p is None:
            out[t] = {"_fila": "ausente"}; continue
        d = {k: p.get(k) for k in KEEP}
        d["enrichment"] = p.get("enrichment")
        d["history"] = p.get("history")
        out[t] = d
    return out


def dump_prices(tickers, cap=1300) -> dict:
    """Volcado SOLO LECTURA del historial de precios AJUSTADOS (price_history) + precio actual
    (prices), por ticker. Para validar la proyección de precio con datos reales. No escribe."""
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    out = {}
    for t in [x.upper() for x in tickers]:
        bars = w.select_rows("price_history", select="as_of,close,adjusted",
                             params={"ticker": f"eq.{t}", "order": "as_of.asc"})
        bars = [{"as_of": b.get("as_of"), "close": b.get("close"), "adjusted": b.get("adjusted")}
                for b in bars if b.get("close")]
        if cap and len(bars) > cap:
            bars = bars[-cap:]
        pr = w.select_rows("prices", select="ticker,close,as_of", params={"ticker": f"eq.{t}"})
        out[t] = {"price": (pr[0].get("close") if pr else None),
                  "price_as_of": (pr[0].get("as_of") if pr else None), "bars": bars}
    return out


def main(argv=None):
    prices = os.getenv("GIIC_PRICES_TICKERS", "")
    if prices:
        tickers = [t.strip() for t in prices.split(",") if t.strip()]
        print(json.dumps(dump_prices(tickers), ensure_ascii=False, default=str))
        return 0
    dump = os.getenv("GIIC_DUMP_TICKERS", "")
    if dump:
        tickers = [t.strip() for t in dump.split(",") if t.strip()]
        print(json.dumps(dump_payloads(tickers), ensure_ascii=False, indent=1, default=str))
        return 0
    verify = os.getenv("GIIC_VERIFY_TICKERS", "")
    if verify:
        tickers = [t.strip() for t in verify.split(",") if t.strip()]
        print(json.dumps(verify_enrichment(tickers), ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps(report(), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
