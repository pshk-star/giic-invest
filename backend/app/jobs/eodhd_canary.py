"""P0.3 — Primera corrida CANARY del enriquecimiento EODHD (escritura controlada y reversible).

Escribe el bloque `enrichment` SÓLO para un conjunto pequeño y explícito de instrumentos, con
respaldo previo de los payloads originales. Doble candado para escribir: `--commit` Y
`GIIC_CANARY_COMMIT=1`. Rechaza cualquier ticker fuera del set. Por defecto DRY-RUN: respalda,
calcula y reporta lo que escribiría, sin tocar Supabase.

ASML/TSM se procesan por el FLUJO REAL (si no tienen fila de fundamentales, se construye el payload
EDGAR con el proveedor oficial, igual que haría el scan para un ticker de cartera) — no se asume que
pertenecen al universo del scanner.

Uso:
    # DRY-RUN (respaldo + reporte, sin escribir):
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... EODHD_API_KEY=... EDGAR_USER_AGENT=... \
        python -m app.jobs.eodhd_canary
    # ESCRITURA real (requiere aprobación): --commit + GIIC_CANARY_COMMIT=1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import date

CANARY_SET = ["XOM", "JPM", "ASML", "TSM", "AAPL", "META"]   # AAPL/META = control de precedencia


def _edgar_fields_equal(a: dict, b: dict) -> bool:
    """¿Los campos EDGAR (todo salvo 'enrichment') son idénticos entre dos payloads?"""
    ax = {k: v for k, v in (a or {}).items() if k != "enrichment"}
    bx = {k: v for k, v in (b or {}).items() if k != "enrichment"}
    return ax == bx


def run(commit: bool = False, tickers=None, mode: str = "enrich") -> dict:
    from .supabase_writer import SupabaseWriter
    from ..providers.edgar import EDGARProvider
    from ..core.connectors.eodhd import EodhdFundamentalsConnector
    from .eodhd_enrich import enrich_one, attach_enrichment

    tickers = [t.upper() for t in (tickers or CANARY_SET)]
    # CANDADO DE ALCANCE: ningún ticker fuera del set autorizado.
    outside = [t for t in tickers if t not in CANARY_SET]
    if outside:
        return {"error": f"tickers fuera del set canary autorizado: {outside}"}

    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    ua = os.getenv("EDGAR_USER_AGENT", ""); key = os.getenv("EODHD_API_KEY", "")
    if not (url and srk):
        return {"error": "sin credenciales Supabase"}
    if not (ua and "@" in ua and key):
        return {"error": "sin EDGAR_USER_AGENT o EODHD_API_KEY"}

    commit_env = os.getenv("GIIC_CANARY_COMMIT") == "1"
    will_write = bool(commit and commit_env)   # DOBLE candado

    writer = SupabaseWriter(url, srk)
    prov = EDGARProvider(user_agent=ua)
    conn = EodhdFundamentalsConnector(api_key=key)
    eval_date = date.today()

    # 1) RESPALDO de los payloads actuales (los que existan).
    # fundamentals se indexa por ticker (sin columna 'id'): se filtra por ticker y se ordena por ticker.
    read_params = {"order": "ticker", "ticker": f"in.({','.join(tickers)})"}
    existing = {}
    try:
        rows = writer.select_rows("fundamentals", select="ticker,payload", params=read_params)
        existing = {r["ticker"].upper(): r.get("payload") for r in rows if r.get("ticker", "").upper() in set(tickers)}
    except Exception as e:
        return {"error": f"no se pudo leer fundamentals para respaldo: {type(e).__name__}: {str(e)[:80]}"}
    backup = {t: existing.get(t) for t in tickers}

    # 2) Construir el payload enriquecido por instrumento (sin escribir aún).
    resultados = {}
    to_write = []
    for t in tickers:
        base = existing.get(t)
        creado = False
        if base is None:                       # flujo real de cartera: construir payload EDGAR oficial
            try:
                funds = prov.get_fundamentals([t])
                f = funds.get(t)
                base = asdict(f) if f is not None else None
                creado = base is not None
            except Exception as e:
                resultados[t] = {"estado": "sin_edgar", "error": str(e)[:80]}
                continue
        if base is None:
            resultados[t] = {"estado": "sin_fila_ni_edgar", "nota": "requiere alta por cartera primero"}
            continue
        prev_block = base.get("enrichment") if isinstance(base, dict) else None
        if mode == "edgar_only":
            # Simula un rescan EDGAR-only (EODHD desactivado): payload EDGAR fresco SIN bloque nuevo;
            # debe PRESERVAR el bloque previo (carry-forward). Valida la condición 42 en la BD real.
            try:
                funds = prov.get_fundamentals([t]); f = funds.get(t)
                base = asdict(f) if f is not None else base   # EDGAR fresco, sin enrichment
            except Exception:
                pass
            new_payload = attach_enrichment(base, None, enabled=True, prev_block=prev_block)
            r = {"status": "edgar_only_rescan", "eodhd_called": False}
        else:
            try:
                r = enrich_one(prov, conn, t, eval_date)
            except Exception as e:
                resultados[t] = {"estado": "enrich_error", "error": str(e)[:80]}
                continue
            block = r.get("enrichment_block") if r.get("status") == "ok" else None
            new_payload = attach_enrichment(base, block, enabled=True, prev_block=prev_block)
        resultados[t] = {
            "existia_fila": existing.get(t) is not None, "payload_creado_desde_edgar": creado,
            "edgar_status": r.get("status"), "eodhd_called": r.get("eodhd_called"),
            "enrichment_fields": sorted((new_payload.get("enrichment", {}) or {}).get("fields", {}).keys()),
            "enrichment_quarantine": sorted((new_payload.get("enrichment", {}) or {}).get("quarantine", {}).keys()),
            "carried_forward": bool((new_payload.get("enrichment", {}) or {}).get("carried_forward")),
            "edgar_preservado": _edgar_fields_equal(base, new_payload),
            "tiene_enrichment": "enrichment" in new_payload,
        }
        if "enrichment" in new_payload:
            to_write.append({"ticker": t, "payload": new_payload})

    report = {
        "modo": "COMMIT (escritura real)" if will_write else "DRY-RUN (sin escritura)",
        "mode": mode,
        "doble_candado": {"--commit": commit, "GIIC_CANARY_COMMIT": commit_env, "escribira": will_write},
        "set_canary": tickers, "alcance_limitado_a": [w["ticker"] for w in to_write],
        "respaldo_tickers": {t: ("presente" if backup.get(t) is not None else "ausente") for t in tickers},
        "respaldo_payloads": backup,   # RESPALDO COMPLETO de los payloads originales (conservar)
        "resultados": resultados,
    }

    # Estado del sistema (evidencia real de BD): nº de predicciones de producción (deben ser 309) y
    # la última corrida de scan completada (integridad de ranking). Sólo lectura.
    try:
        preds = writer.select_rows("predictions", select="id", params={"order": "id", "origin": "eq.production"})
        report["predicciones_produccion"] = len(preds)
    except Exception as e:
        report["predicciones_produccion"] = f"error: {type(e).__name__}"
    try:
        runs = writer.select_rows("scan_runs", select="id,as_of,status",
                                  params={"order": "as_of.desc", "status": "eq.completed", "limit": "1"})
        report["ultimo_scan_completado"] = runs[0] if runs else None
    except Exception as e:
        report["ultimo_scan_completado"] = f"error: {type(e).__name__}"

    # 3) ESCRITURA (sólo con doble candado), limitada al set.
    if will_write:
        safe = [w for w in to_write if w["ticker"] in CANARY_SET]
        try:
            writer.upsert("fundamentals", safe, on_conflict="ticker")
            report["escritos"] = [w["ticker"] for w in safe]
            # Reverificación post-escritura.
            rows = writer.select_rows("fundamentals", select="ticker,payload", params=read_params)
            post = {r["ticker"].upper(): r.get("payload") for r in rows if r.get("ticker", "").upper() in set(tickers)}
            report["post_verificacion"] = {
                t: {"tiene_enrichment": "enrichment" in (post.get(t) or {}),
                    "edgar_preservado": _edgar_fields_equal(backup.get(t) or {}, {k: v for k, v in (post.get(t) or {}).items() if k != "enrichment"})}
                for t in report["escritos"]}
        except Exception as e:
            report["error_escritura"] = f"{type(e).__name__}: {str(e)[:100]}"
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Canary de enriquecimiento EODHD (escritura controlada).")
    p.add_argument("--commit", action="store_true", help="escribir de verdad (requiere además GIIC_CANARY_COMMIT=1)")
    p.add_argument("--tickers", default="", help="subconjunto del set canary (por defecto, todo el set)")
    p.add_argument("--mode", default="enrich", choices=["enrich", "edgar_only"],
                   help="enrich: escribe el bloque EODHD; edgar_only: simula rescan EDGAR-only (carry-forward)")
    args = p.parse_args(argv)
    tk = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None
    out = run(commit=args.commit, tickers=tk, mode=args.mode)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
