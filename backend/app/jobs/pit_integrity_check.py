"""P2.6 (verificación previa) — Integridad temporal de pit_snapshots (solo lectura).

Comprueba, sobre datos reales, que:
  (1) observation_date (fecha del dato observado) <= captured_at (cuándo GIIC lo obtuvo): no hay
      datos "del futuro" respecto a la captura.
  (2) La versión VIGENTE por ticker (la que el frontend selecciona) es la de captured_at MÁS RECIENTE
      entre snapshot_date máximos — no una valoración obsoleta recuperada por accidente.
  (3) Reporta, para una muestra, las versiones por ticker para inspección manual.

No escribe nada. No introduce look-ahead (solo describe el estado actual).
Uso: SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY. python -m app.jobs.pit_integrity_check
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict


def check() -> dict:
    url = os.getenv("SUPABASE_URL", ""); srk = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not srk:
        return {"error": "faltan SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY"}
    from app.jobs.supabase_writer import SupabaseWriter
    w = SupabaseWriter(url, srk)
    rows = w.select_rows("pit_snapshots",
                         select="ticker,observation_date,snapshot_date,captured_at,payload",
                         params={"kind": "eq.fundamental_valuation", "order": "ticker"})

    by_ticker = defaultdict(list)
    for r in rows:
        by_ticker[str(r["ticker"]).upper()].append(r)

    future_data = []        # observation_date > captured_at (violación (1))
    multi_version = {}       # tickers con más de una versión (para (2))
    selected = {}
    for t, rs in by_ticker.items():
        for r in rs:
            obs = str(r.get("observation_date") or "")
            cap = str(r.get("captured_at") or "")[:10]
            if obs and cap and obs > cap:
                future_data.append({"ticker": t, "observation_date": obs, "captured_at": cap})
        # versión vigente = snapshot_date desc, luego captured_at desc (igual que el frontend)
        rs_sorted = sorted(rs, key=lambda x: (str(x.get("snapshot_date") or ""), str(x.get("captured_at") or "")), reverse=True)
        vig = rs_sorted[0]
        pay = vig.get("payload") or {}
        mdl = next((m for m in pay.get("modelos", []) if m.get("margen_seguridad_pct") is not None), {})
        selected[t] = {"observation_date": vig.get("observation_date"), "snapshot_date": vig.get("snapshot_date"),
                       "captured_at": str(vig.get("captured_at") or "")[:19], "origen": pay.get("origen", "P1.9"),
                       "modelo": mdl.get("modelo"), "margen_pct": mdl.get("margen_seguridad_pct"),
                       "n_versiones": len(rs)}
        if len(rs) > 1:
            multi_version[t] = [{"obs": x.get("observation_date"), "snap": x.get("snapshot_date"),
                                 "cap": str(x.get("captured_at") or "")[:19],
                                 "origen": (x.get("payload") or {}).get("origen", "P1.9")} for x in rs_sorted]

    ok = len(future_data) == 0
    return {
        "tickers_valorados": len(by_ticker),
        "snapshots_totales": len(rows),
        "check_1_observation<=captured": {"ok": ok, "violaciones": future_data[:20]},
        "check_2_multi_version": {"tickers_con_multiples_versiones": len(multi_version),
                                  "detalle": {k: multi_version[k] for k in list(multi_version)[:8]}},
        "muestra_version_vigente": {k: selected[k] for k in sorted(selected)[:12]},
        "note": "Solo lectura. La versión vigente usa snapshot_date desc, captured_at desc (sin look-ahead).",
    }


def main() -> int:
    out = check()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0 if out.get("check_1_observation<=captured", {}).get("ok", False) else 1


if __name__ == "__main__":
    sys.exit(main())
