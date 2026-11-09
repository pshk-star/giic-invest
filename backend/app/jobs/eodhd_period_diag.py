"""P0.3 — Diagnóstico del TIPO DE PERÍODO económico de los datos EODHD (solo lectura).

Verifica, con datos reales y sin suponer, qué representa cada serie EODHD: trimestre individual,
acumulado YTD, ejercicio anual o saldo de balance (instantáneo). No basta `period_end`: se coteja la
serie trimestral contra la anual (¿Σ4T ≈ anual → trimestres individuales?, ¿el T de cierre ≈ anual →
YTD acumulado?). Para flujos (revenue/ocf/capex/fcf) la distinción es crítica: un trimestre o un YTD
NO es un TTM ni comparable con un ejercicio anual. Los saldos (cash/total_debt) son instantáneos.

Uso: EODHD_API_KEY en env; python -m app.jobs.eodhd_period_diag [--tickers ASML,TSM,XOM]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from app.core.connectors.eodhd import EodhdFundamentalsConnector

DEFAULT = ["ASML", "TSM", "XOM"]
TOL = 0.10   # tolerancia relativa para clasificar (±10%)


def _num(d, k):
    v = (d or {}).get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _series(sect, key):
    """{fecha: valor} ordenado por fecha, para un concepto del statement."""
    out = {}
    for k, row in (sect or {}).items():
        v = _num(row, key)
        if v is not None:
            out[(row.get("date") or k)[:10]] = v
    return dict(sorted(out.items()))


def _classify_flow(quarterly: dict, yearly: dict) -> dict:
    """Clasifica un FLUJO: trimestre individual vs YTD acumulado vs indeterminado, cotejando contra
    el ejercicio anual más reciente que tenga 4 trimestres disponibles."""
    if not yearly:
        return {"tipo": "indeterminado", "motivo": "sin serie anual"}
    yk = sorted(yearly)[-1]
    A = yearly[yk]
    if not A:
        return {"tipo": "indeterminado", "motivo": "anual nulo/0"}
    y = int(yk[:4])
    # Trimestres dentro de los 12 meses que terminan en el cierre anual.
    qin = {d: v for d, v in quarterly.items() if f"{y-1}-" < d <= yk}
    q_at_close = quarterly.get(yk)
    sum4 = sum(list(qin.values())[-4:]) if qin else None
    info = {"anual": A, "anual_fecha": yk, "n_trim_en_ejercicio": len(qin),
            "suma_4T": sum4, "trim_en_cierre": q_at_close,
            "ratio_suma4T/anual": round(sum4 / A, 3) if sum4 else None,
            "ratio_Tcierre/anual": round(q_at_close / A, 3) if q_at_close else None}
    if q_at_close is not None and abs(q_at_close / A - 1) <= TOL:
        info["tipo"] = "YTD acumulado (el T de cierre ≈ ejercicio anual)"
    elif sum4 is not None and abs(sum4 / A - 1) <= TOL:
        info["tipo"] = "trimestre individual (Σ4T ≈ ejercicio anual)"
    else:
        info["tipo"] = "indeterminado (ni Σ4T ni T-cierre coinciden con el anual)"
    return info


def diagnose(tickers=None) -> dict:
    key = os.getenv("EODHD_API_KEY", "")
    if not key:
        return {"error": "sin EODHD_API_KEY"}
    conn = EodhdFundamentalsConnector(api_key=key)
    out = {}
    for t in (tickers or DEFAULT):
        sym, adr, obj = conn._resolve(t)
        if obj is None:
            out[t] = {"error": "sin fundamentales EODHD"}
            continue
        fin = obj.get("Financials", {}) or {}
        inc_q = (fin.get("Income_Statement", {}) or {}).get("quarterly", {})
        inc_y = (fin.get("Income_Statement", {}) or {}).get("yearly", {})
        cf_q = (fin.get("Cash_Flow", {}) or {}).get("quarterly", {})
        cf_y = (fin.get("Cash_Flow", {}) or {}).get("yearly", {})
        bal_q = (fin.get("Balance_Sheet", {}) or {}).get("quarterly", {})

        rev = {"quarterly": _series(inc_q, "totalRevenue"), "yearly": _series(inc_y, "totalRevenue")}
        ocf = {"quarterly": _series(cf_q, "totalCashFromOperatingActivities"),
               "yearly": _series(cf_y, "totalCashFromOperatingActivities")}
        capex = {"quarterly": _series(cf_q, "capitalExpenditures"), "yearly": _series(cf_y, "capitalExpenditures")}
        cash = _series(bal_q, "cashAndEquivalents") or _series(bal_q, "cash")

        def last_n(d, n=6):
            return dict(list(d.items())[-n:])

        out[t] = {
            "symbol": sym, "currency": ((fin.get("Income_Statement", {}) or {}).get("currency_symbol")),
            "revenue": {"clasificacion": _classify_flow(rev["quarterly"], rev["yearly"]),
                        "ult_trimestrales": last_n(rev["quarterly"]), "ult_anuales": last_n(rev["yearly"], 3)},
            "ocf": {"clasificacion": _classify_flow(ocf["quarterly"], ocf["yearly"]),
                    "ult_trimestrales": last_n(ocf["quarterly"]), "ult_anuales": last_n(ocf["yearly"], 3)},
            "capex": {"clasificacion": _classify_flow(capex["quarterly"], capex["yearly"]),
                      "ult_trimestrales": last_n(capex["quarterly"]), "ult_anuales": last_n(capex["yearly"], 3)},
            "cash_balance": {"tipo": "saldo de balance (instantáneo)", "ult_trimestrales": last_n(cash)},
        }
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default="")
    args = p.parse_args(argv)
    tk = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None
    print(json.dumps(diagnose(tk), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
