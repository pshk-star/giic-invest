"""P1.1 — Enriquecimiento ON-DEMAND de UN emisor consultado en Research (fuera del universo diario).

Reutiliza íntegramente el conector y sus controles (enrich_scan_payloads + create_missing): ancla
EDGAR cuando existe, EODHD-primary explícito si no, gate por disponibilidad, precedencia, cuarentena,
historia oficial y carry-forward. Escribe SÓLO ese ticker. Idempotente. Evita consultas repetidas: si
ya hay enriquecimiento fresco del día, no vuelve a consultar.

NO incorpora el catálogo completo al batch; es puntual, por ticker. Doble control de escritura:
`--commit` y GIIC_ONDEMAND_COMMIT=1.

Uso: SUPABASE_URL/KEY + EODHD_API_KEY + EDGAR_USER_AGENT; python -m app.jobs.eodhd_enrich_ondemand --ticker SPOT --commit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

from .eodhd_enrich import enrich_scan_payloads, read_fundamentals_payloads


def run(ticker: str, commit: bool = False) -> dict:
    t = (ticker or "").strip().upper()
    if not t:
        return {"error": "sin ticker"}
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not (url and srk):
        return {"error": "sin credenciales Supabase"}
    from .supabase_writer import SupabaseWriter
    writer = SupabaseWriter(url, srk)
    will_write = bool(commit and os.getenv("GIIC_ONDEMAND_COMMIT") == "1")

    prev = read_fundamentals_payloads(writer, [t])
    # Evitar consulta repetida: si ya hay enriquecimiento del mismo día, no re-consultar.
    today = date.today().isoformat()
    existing = prev.get(t) or {}
    enr = existing.get("enrichment") or {}
    if enr and not enr.get("carried_forward") and (enr.get("generated_at") == today):
        return {"ticker": t, "estado": "ya_fresco_hoy", "escrito": False}

    payloads = {t: dict(existing)} if existing else {}
    summary = enrich_scan_payloads(payloads, [t], prev_payloads=prev, eval_date=date.today(),
                                   enabled=True, create_missing=True)
    new_payload = payloads.get(t)
    out = {"ticker": t, "escribira": will_write, "resumen": summary,
           "tiene_enrichment": bool((new_payload or {}).get("enrichment")),
           "source_kind": (new_payload or {}).get("source_kind", "edgar+eodhd"),
           "tiene_history": bool((new_payload or {}).get("history"))}
    fi = (new_payload or {}).get("fcff_inputs") or {}
    if fi.get("error"):
        out["fcff_coverage"] = {"error": fi["error"]}
    elif fi:
        elig = fi.get("eligibility", {}); merged = fi.get("merged_history", {})
        last = sorted(merged)[-1] if merged else None
        extra = (fi.get("extra_by_year", {}) or {}).get(last, {})
        out["fcff_coverage"] = {
            "ultimo": last, "elegibilidad": elig.get("status"),
            "faltan": elig.get("missing_critical"), "na": elig.get("na"), "stale": elig.get("stale"),
            "merge_state": fi.get("merge_log", {}).get("state"),
            "campos_presentes": sorted(k for k, v in extra.items() if v.get("value") is not None),
            "escala_issue": fi.get("integrity", {}).get("shares_scale_issue"),
        }
    if new_payload is None:
        out["estado"] = "sin_datos (ni EDGAR ni EODHD)"; return out
    if will_write:
        try:
            writer.upsert("fundamentals", [{"ticker": t, "payload": new_payload}], on_conflict="ticker")
            out["escrito"] = True
            post = read_fundamentals_payloads(writer, [t]).get(t) or {}
            out["post_tiene_enrichment"] = "enrichment" in post
        except Exception as e:
            out["error_escritura"] = f"{type(e).__name__}: {str(e)[:100]}"
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Enriquecimiento on-demand de un emisor (Research).")
    p.add_argument("--ticker", required=True)
    p.add_argument("--commit", action="store_true", help="escribir (requiere además GIIC_ONDEMAND_COMMIT=1)")
    args = p.parse_args(argv)
    print(json.dumps(run(args.ticker, commit=args.commit), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
