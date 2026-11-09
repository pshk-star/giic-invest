#!/usr/bin/env python3
"""Validación empírica RIGUROSA de EODHD para GIIC (v2). No es el conector productivo.

Mejoras sobre v1 (según revisión):
  - Concilia SOLO cifras del MISMO ejercicio, MONEDA y UNIDAD (empareja por fecha de cierre).
  - Separa EPS ANUAL, TRIMESTRAL y TTM (fuentes distintas; no las mezcla).
  - Distingue ACCIONES EN CIRCULACIÓN (outstandingShares) de PROMEDIO PONDERADO DILUIDO
    (weightedAverageShsOutDil). Nunca usa una por la otra.
  - Mapea correctamente OCF, CAPEX, FCF, cash y deuda total.
  - Identifica ordinaria vs ADR y su factor de conversión; concilia LOCAL-vs-LOCAL contra EDGAR.
  - Conserva procedencia (símbolo, período, filing_date).
  - NO declara 'verificado' sólo porque el dato exista en EODHD: exige coincidencia con la fuente
    oficial en período y moneda comparables. Distingue ANOMALÍA real de LIMITACIÓN del validador.

Seguridad: clave sólo de EODHD_API_KEY (env); nunca en disco ni en logs (URLs redactadas).
EDGAR: EDGAR_USER_AGENT (contraste oficial). Uso: ver README. --selftest corre sin red ni clave.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

TODAY = date.today()
EODHD_BASE = "https://eodhd.com/api"

# Universo: 9 prioritarios + resto de ADR/IFRS de la batería. Para cada uno, símbolos EODHD a probar
# (local primero, ADR US como respaldo), moneda local esperada y factor ADR (acciones ord. por ADR).
UNIVERSE = [
    {"name": "ASML", "edgar": "ASML", "symbols": ["ASML.AS", "ASML.US"], "adr": 1,  "seg": "adr_ifrs"},
    {"name": "TSM",  "edgar": "TSM",  "symbols": ["2330.TW", "TSM.US"],  "adr": 5,  "seg": "adr_ifrs"},
    {"name": "SAP",  "edgar": "SAP",  "symbols": ["SAP.XETRA", "SAP.US"], "adr": 1,  "seg": "adr_ifrs"},
    {"name": "NVO",  "edgar": "NVO",  "symbols": ["NOVO-B.CO", "NVO.US"], "adr": 1,  "seg": "adr_ifrs"},
    {"name": "AZN",  "edgar": "AZN",  "symbols": ["AZN.LSE", "AZN.US"],   "adr": 2,  "seg": "adr_ifrs"},
    {"name": "BABA", "edgar": "BABA", "symbols": ["9988.HK", "BABA.US"],  "adr": 8,  "seg": "adr_ifrs"},
    {"name": "V",    "edgar": "V",    "symbols": ["V.US"],                "adr": 1,  "seg": "us"},
    {"name": "MA",   "edgar": "MA",   "symbols": ["MA.US"],               "adr": 1,  "seg": "us"},
    {"name": "MU",   "edgar": "MU",   "symbols": ["MU.US"],               "adr": 1,  "seg": "us"},
    # Resto ADR/IFRS de la batería
    {"name": "TM",   "edgar": "TM",   "symbols": ["7203.TSE", "TM.US"],   "adr": 1,  "seg": "adr_ifrs"},
    {"name": "SHEL", "edgar": "SHEL", "symbols": ["SHEL.LSE", "SHEL.US"], "adr": 2,  "seg": "adr_ifrs"},
    {"name": "BP",   "edgar": "BP",   "symbols": ["BP.LSE", "BP.US"],     "adr": 6,  "seg": "adr_ifrs"},
    {"name": "SONY", "edgar": "SONY", "symbols": ["6758.TSE", "SONY.US"], "adr": 1,  "seg": "adr_ifrs"},
    {"name": "UL",   "edgar": "UL",   "symbols": ["ULVR.LSE", "UL.US"],   "adr": 1,  "seg": "adr_ifrs"},
    {"name": "RIO",  "edgar": "RIO",  "symbols": ["RIO.LSE", "RIO.US"],   "adr": 2,  "seg": "adr_ifrs"},
    {"name": "SE",   "edgar": "SE",   "symbols": ["SE.US"],               "adr": 1,  "seg": "adr_ifrs"},
    {"name": "NVS",  "edgar": "NVS",  "symbols": ["NVS.US", "NOVN.SW"],   "adr": 1,  "seg": "adr_ifrs"},
    {"name": "HSBC", "edgar": "HSBC", "symbols": ["HSBA.LSE", "HSBC.US"], "adr": 5,  "seg": "adr_ifrs"},
]

FV_FIELDS = ["revenue", "net_income", "eps_diluted_annual", "diluted_shares_wavg", "ocf", "capex", "fcf", "cash", "total_debt"]
# Conceptos EDGAR por campo (us-gaap / ifrs-full).
EDGAR_CONCEPTS = {
    "revenue": (["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractsWithCustomers", "Revenue", "SalesRevenueNet"], "money", "dur"),
    "net_income": (["NetIncomeLoss", "ProfitLoss"], "money", "dur"),
    "eps_diluted_annual": (["EarningsPerShareDiluted", "DilutedEarningsLossPerShare", "DilutedEarningsPerShare"], "pershare", "dur"),
    "diluted_shares_wavg": (["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageShares", "AdjustedWeightedAverageShares"], "shares", "dur"),
    "ocf": (["NetCashProvidedByUsedInOperatingActivities", "CashFlowsFromUsedInOperatingActivities"], "money", "dur"),
    "capex": (["PaymentsToAcquirePropertyPlantAndEquipment", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"], "money", "dur"),
    "cash": (["CashAndCashEquivalentsAtCarryingValue", "CashAndCashEquivalents"], "money", "inst"),
    "total_debt": None,  # se arma de LT+corriente
}


def _redact(s):
    return re.sub(r"(api_token=)[^&\s]+", r"\1***", s or "")


def http_get_json(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body), None
            except json.JSONDecodeError:
                return r.status, None, "no-JSON"
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {_redact(str(e))}"


def _num(d, keys):
    for k in keys:
        v = (d or {}).get(k)
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
    return None


def _pd(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ---------- EODHD ----------
def eodhd_fetch(symbol, token, fetch):
    url = f"{EODHD_BASE}/fundamentals/{symbol}?api_token={token}&fmt=json"
    return fetch(url, {"User-Agent": "giic-eodhd-validation"})


def eodhd_extract(obj):
    """Devuelve estructura normalizada SIN mezclar conceptos:
       currency, annual{year_end:{campos}}, quarterly_latest, eps (anual/trim/ttm por separado),
       filing dates y acciones (ponderadas diluidas vs en circulación, distintas)."""
    fin = (obj or {}).get("Financials", {}) or {}
    inc_y = (fin.get("Income_Statement", {}) or {}).get("yearly", {}) or {}
    bal_y = (fin.get("Balance_Sheet", {}) or {}).get("yearly", {}) or {}
    cf_y = (fin.get("Cash_Flow", {}) or {}).get("yearly", {}) or {}
    currency = (fin.get("Income_Statement", {}) or {}).get("currency_symbol") or (obj.get("General", {}) or {}).get("CurrencyCode")

    def row_fields(irow, brow, crow):
        f = {}
        f["revenue"] = _num(irow, ["totalRevenue"])
        f["net_income"] = _num(irow, ["netIncome"])
        f["operating_income"] = _num(irow, ["operatingIncome"])
        # Acciones: PONDERADO DILUIDO (para EPS) — NO outstanding.
        f["diluted_shares_wavg"] = _num(irow, ["weightedAverageShsOutDil"])
        f["basic_shares_wavg"] = _num(irow, ["weightedAverageShsOut"])
        f["ocf"] = _num(crow, ["totalCashFromOperatingActivities"])
        f["capex"] = _num(crow, ["capitalExpenditures"])
        fcf = _num(crow, ["freeCashFlow"])
        if fcf is None and f["ocf"] is not None and f["capex"] is not None:
            fcf = f["ocf"] - abs(f["capex"])
        f["fcf"] = fcf
        f["cash"] = _num(brow, ["cashAndEquivalents", "cash", "cashAndShortTermInvestments"])
        td = _num(brow, ["shortLongTermDebtTotal"])
        if td is None:
            lt = _num(brow, ["longTermDebt"]); st = _num(brow, ["shortTermDebt", "shortLongTermDebt"])
            td = (lt or 0) + (st or 0) if (lt is not None or st is not None) else None
        f["total_debt"] = td
        f["net_debt"] = _num(brow, ["netDebt"])
        return f

    annual = {}
    for y, irow in inc_y.items():
        if not isinstance(irow, dict):
            continue
        end = irow.get("date") or y
        annual[end] = row_fields(irow, bal_y.get(end) or bal_y.get(y) or {}, cf_y.get(end) or cf_y.get(y) or {})
        annual[end]["filing_date"] = irow.get("filing_date")
    # EPS separado por base:
    earn = (obj.get("Earnings", {}) or {})
    eps_annual = {}
    for y, row in (earn.get("Annual", {}) or {}).items():
        if isinstance(row, dict):
            eps_annual[row.get("date") or y] = _num(row, ["epsActual", "epsActualDiluted"])
    eps_hist_q = (earn.get("History", {}) or {})
    q_eps = None
    if eps_hist_q:
        qk = sorted([k for k, v in eps_hist_q.items() if isinstance(v, dict) and v.get("reportDate")])
        if qk:
            q_eps = _num(eps_hist_q[qk[-1]], ["epsActual"])
    eps_ttm = _num(obj.get("Highlights", {}), ["DilutedEpsTTM"])
    # Último trimestral (income/balance/cashflow) para actualidad.
    inc_q = (fin.get("Income_Statement", {}) or {}).get("quarterly", {}) or {}
    bal_q = (fin.get("Balance_Sheet", {}) or {}).get("quarterly", {}) or {}
    cf_q = (fin.get("Cash_Flow", {}) or {}).get("quarterly", {}) or {}
    qkeys = sorted(inc_q.keys())
    q_latest = None
    if qkeys:
        qk = qkeys[-1]
        qrow = inc_q[qk]
        q_latest = {"period_end": qrow.get("date") or qk, "filing_date": qrow.get("filing_date"),
                    "fields": row_fields(qrow, bal_q.get(qk, {}), cf_q.get(qk, {}))}
    a_keys = sorted(annual.keys())
    return {"currency": currency, "annual": annual, "eps_annual": eps_annual,
            "eps_quarterly_latest": q_eps, "eps_ttm": eps_ttm,
            "latest_annual": a_keys[-1] if a_keys else None, "quarterly_latest": q_latest,
            "shares_outstanding_present": bool(obj.get("outstandingShares"))}


# ---------- EDGAR ----------
def edgar_series(ticker, ua, fetch):
    if not ua or "@" not in ua:
        return None
    _, tk, _ = fetch("https://www.sec.gov/files/company_tickers.json", {"User-Agent": ua})
    if not tk:
        return None
    cik = next((int(r["cik_str"]) for r in tk.values() if r["ticker"].upper() == ticker.upper()), None)
    if cik is None:
        return None
    _, facts, _ = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", {"User-Agent": ua})
    if not facts:
        return None
    F = (facts.get("facts", {}) or {})

    def unit_ok(u, kind):
        if kind == "money":
            return "/" not in u and len(u) == 3
        if kind == "pershare":
            return u.endswith("/shares")
        if kind == "shares":
            return u == "shares"
        return False

    def series(concepts, kind, dur):
        out, ccy = {}, None
        for tax in ("us-gaap", "ifrs-full"):
            for c in concepts:
                node = (((F.get(tax, {}) or {}).get(c, {}) or {}).get("units", {}) or {})
                for u, rows in node.items():
                    if not unit_ok(u, kind):
                        continue
                    for r in rows:
                        if not str(r.get("form", "")).startswith(("10-K", "20-F", "40-F")):
                            continue
                        e = _pd(r.get("end"))
                        if not e:
                            continue
                        if dur == "dur":
                            s = _pd(r.get("start"))
                            if not s or not (330 <= (e - s).days <= 400):
                                continue
                        filed = _pd(r.get("filed")) or date.min
                        key = e.isoformat()
                        if key not in out or filed >= out[key][1]:
                            out[key] = (float(r["val"]), filed)
                            if kind == "money" and not ccy:
                                ccy = u
                if out:
                    break
            if out:
                break
        return {k: v[0] for k, v in out.items()}, ccy

    res, ccy = {}, None
    for field, spec in EDGAR_CONCEPTS.items():
        if spec is None:
            continue
        concepts, kind, dur = spec
        s, c = series(concepts, kind, dur)
        res[field] = s
        if kind == "money" and c and not ccy:
            ccy = c
    # deuda total = LT no corriente + corriente (instantáneos)
    lt, _ = series(["LongTermDebtNoncurrent", "LongTermDebt", "NoncurrentBorrowings", "Borrowings"], "money", "inst")
    cur, _ = series(["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CurrentBorrowings"], "money", "inst")
    td = {}
    for k in set(lt) | set(cur):
        td[k] = (lt.get(k, 0) or 0) + (cur.get(k, 0) or 0)
    res["total_debt"] = td
    allk = sorted({k for s in res.values() for k in s})
    return {"currency": ccy, "series": res, "latest_period": allk[-1] if allk else None}


# ---------- Conciliación ----------
def _match_year(eodhd_end, edgar_keys, tol=20):
    ed = _pd(eodhd_end)
    if not ed:
        return None
    best = None
    for k in edgar_keys:
        d = _pd(k)
        if d and abs((d - ed).days) <= tol and (best is None or abs((d - ed).days) < best[1]):
            best = (k, abs((d - ed).days))
    return best[0] if best else None


def reconcile_field(eodhd_val, edgar_map, eodhd_end, same_ccy):
    """Compara MISMO AÑO y MISMA MONEDA. Devuelve (estado, razon, edgar_val, diff)."""
    if eodhd_val is None:
        return "ausente", "sin dato en EODHD", None, None
    if not edgar_map:
        return "sin_contraste", "EDGAR no reporta este campo", None, None
    yk = _match_year(eodhd_end, edgar_map.keys())
    if yk is None:
        return "sin_contraste_periodo", "EDGAR no tiene el mismo ejercicio", None, None
    ev = edgar_map[yk]
    if not same_ccy:
        return "no_comparable_moneda", "monedas distintas (no se convierte)", ev, None
    if ev == 0:
        return "no_comparable", "EDGAR=0", ev, None
    diff = (eodhd_val - ev) / abs(ev)
    # tolerancia de escala: a veces miles vs unidades
    for scale, lab in ((1000, "x1000"), (0.001, "/1000"), (1e6, "x1e6")):
        if abs(eodhd_val / scale - ev) / abs(ev) <= 0.02:
            return "inconsistente_escala", f"difiere por factor {lab} (unidades)", ev, diff
    if abs(diff) <= 0.02:
        return "verificado", f"coincide (dif {diff*100:.2f}%)", ev, diff
    if abs(diff) <= 0.05:
        return "diferencia_menor", f"dif {diff*100:.1f}% (2-5%)", ev, diff
    return "inconsistente", f"dif {diff*100:.1f}%", ev, diff


def validate_one(cfg, token, ua, fetch):
    rec = {"name": cfg["name"], "seg": cfg["seg"], "adr": cfg["adr"]}
    obj, used = None, None
    for sym in cfg["symbols"]:
        st, o, err = eodhd_fetch(sym, token, fetch)
        rec["last_status"] = st
        if o and isinstance(o, dict) and o.get("Financials"):
            obj, used = o, sym
            break
    if obj is None:
        rec["acceso"] = f"sin fundamentales ({rec.get('last_status')})"
        return rec
    rec["symbol_usado"] = used
    e = eodhd_extract(obj)
    rec["currency"] = e["currency"]
    rec["shares_outstanding_present"] = e["shares_outstanding_present"]
    edg = edgar_series(cfg["edgar"], ua, fetch)
    rec["edgar_currency"] = edg["currency"] if edg else None
    rec["edgar_latest"] = edg["latest_period"] if edg else None
    same_ccy = bool(edg and e["currency"] and edg["currency"] and e["currency"].upper() == edg["currency"].upper())
    rec["same_currency"] = same_ccy
    # Último anual EODHD para conciliar
    la = e["latest_annual"]
    arow = e["annual"].get(la, {}) if la else {}
    rec["latest_annual"] = la
    rec["latest_annual_filing"] = arow.get("filing_date")
    ql = e["quarterly_latest"]
    rec["latest_quarter"] = ql["period_end"] if ql else None
    rec["latest_quarter_filing"] = ql["filing_date"] if ql else None
    # Estados por campo (conciliación mismo-año/moneda)
    states, detail = {}, {}
    for f in FV_FIELDS:
        if f == "eps_diluted_annual":
            val = e["eps_annual"].get(la) if la else None
            if val is None and arow.get("net_income") and arow.get("diluted_shares_wavg"):
                val = arow["net_income"] / arow["diluted_shares_wavg"]
            st, why, ev, diff = reconcile_field(val, (edg["series"].get("eps_diluted_annual") if edg else None), la, same_ccy)
        else:
            val = arow.get(f)
            st, why, ev, diff = reconcile_field(val, (edg["series"].get(f) if edg else None), la, same_ccy)
        states[f] = st
        detail[f] = {"eodhd": val, "edgar": ev, "diff": (round(diff, 4) if diff is not None else None), "razon": why}
    rec["eps_separado"] = {"anual": e["eps_annual"].get(la) if la else None,
                           "trimestral": e["eps_quarterly_latest"], "ttm": e["eps_ttm"]}
    rec["campos"] = states
    rec["detalle"] = detail
    # Actualidad
    eo_latest = max([d for d in (_pd(la), _pd(rec["latest_quarter"])) if d], default=None)
    ed_latest = _pd(edg["latest_period"]) if edg else None
    rec["eodhd_mas_reciente_que_edgar"] = bool(eo_latest and ed_latest and eo_latest > ed_latest)
    rec["acceso"] = "ok"
    return rec


def access_probe(token, fetch):
    st, o, err = eodhd_fetch("AAPL.US", token, fetch)
    ok = bool(o and isinstance(o, dict) and o.get("Financials"))
    return {"acceso": ok, "status": st, "detalle": "AAPL.US con Financials" if ok else (err or "sin Financials")}


ANOMALIA = {"inconsistente", "inconsistente_escala"}
LIMITACION = {"no_comparable_moneda", "sin_contraste", "sin_contraste_periodo", "no_comparable"}


def build_report(probe, results):
    L = ["# Validación EODHD v2 — GIIC", "", f"- Fecha: {TODAY.isoformat()}",
         f"- Acceso fundamentales: **{'SÍ' if probe['acceso'] else 'NO'}** (HTTP {probe['status']}; {probe['detalle']})"]
    if not probe["acceso"]:
        L += ["", "> BLOQUEO: la clave/plan no da acceso a fundamentales. No se consultó el universo."]
        return "\n".join(L)
    L += ["", "## Por emisor", "",
          "| Emisor | seg | símbolo | moneda(E/EDGAR) | últ.anual (pub) | últ.trim (pub) | fresco>EDGAR | verif | dif.menor | inconsist | no-compar | ausente |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    agg = {}
    for r in results:
        if r.get("acceso") != "ok":
            L.append(f"| {r['name']} | {r.get('seg')} | — | — | — | — | — | — | — | — | — | sin acceso ({r.get('acceso')}) |")
            continue
        c = r["campos"]
        n = lambda *s: sum(1 for v in c.values() if v in s)
        verif = n("verificado"); dmen = n("diferencia_menor"); inc = n(*ANOMALIA); nc = n(*LIMITACION); au = n("ausente")
        agg.setdefault(r["seg"], []).append(r)
        L.append(f"| {r['name']} | {r['seg']} | {r.get('symbol_usado')} | {r.get('currency')}/{r.get('edgar_currency')} | "
                 f"{r.get('latest_annual')} ({r.get('latest_annual_filing')}) | {r.get('latest_quarter')} ({r.get('latest_quarter_filing')}) | "
                 f"{'sí' if r.get('eodhd_mas_reciente_que_edgar') else 'no'} | {verif} | {dmen} | {inc} | {nc} | {au} |")
    # Campos por emisor
    L += ["", "## Estado por campo (anual, conciliación mismo-año/moneda vs EDGAR)", "",
          "| Emisor | " + " | ".join(f.replace("_diluted_annual", "").replace("_shares_wavg", "_sh") for f in FV_FIELDS) + " |",
          "|---|" + "---|" * len(FV_FIELDS)]
    abbr = {"verificado": "veri", "diferencia_menor": "dif<5", "inconsistente": "INCON", "inconsistente_escala": "ESCALA",
            "no_comparable_moneda": "mon", "sin_contraste": "s/edg", "sin_contraste_periodo": "s/año", "no_comparable": "n/c", "ausente": "AUSE"}
    for r in results:
        if r.get("acceso") != "ok":
            continue
        L.append(f"| {r['name']} | " + " | ".join(abbr.get(r["campos"][f], r["campos"][f]) for f in FV_FIELDS) + " |")
    # EPS separado
    L += ["", "## EPS separado (anual / trimestral / TTM) — bases distintas, no se mezclan", "",
          "| Emisor | EPS anual | EPS trim | EPS TTM |", "|---|---|---|---|"]
    for r in results:
        if r.get("acceso") != "ok":
            continue
        s = r.get("eps_separado", {})
        L.append(f"| {r['name']} | {s.get('anual')} | {s.get('trimestral')} | {s.get('ttm')} |")
    # Anomalías reales
    L += ["", "## Anomalías reales (inconsistencia mismo-año/moneda) vs limitaciones del validador", ""]
    any_anom = False
    for r in results:
        if r.get("acceso") != "ok":
            continue
        anoms = [(f, r["detalle"][f]) for f in FV_FIELDS if r["campos"][f] in ANOMALIA]
        if anoms:
            any_anom = True
            for f, d in anoms:
                L.append(f"- **{r['name']}.{f}**: EODHD={d['eodhd']} vs EDGAR={d['edgar']} → {d['razon']}")
    if not any_anom:
        L.append("- (ninguna anomalía material de inconsistencia mismo-año/moneda)")
    # Resumen de cobertura A/B comprobada
    L += ["", "## Cobertura comprobada por segmento (sobre lo validado aquí)", "",
          "| Segmento | n | campos verif/dif.menor (usables) | fresco>EDGAR |", "|---|---|---|---|"]
    for seg, rows in agg.items():
        usable = sum(sum(1 for v in r["campos"].values() if v in ("verificado", "diferencia_menor")) for r in rows)
        total = len(rows) * len(FV_FIELDS)
        fresh = sum(1 for r in rows if r.get("eodhd_mas_reciente_que_edgar"))
        L.append(f"| {seg} | {len(rows)} | {usable}/{total} ({round(100*usable/total)}%) | {fresh}/{len(rows)} |")
    L += ["", "> 'usable' = verificado o diferencia_menor contra EDGAR mismo-año/moneda. 'no-comparable'",
          "> (moneda/periodo distinto) NO es anomalía: es límite del contraste, no de EODHD. No se declara",
          "> verificado por mera existencia en EODHD.",
          "", "## Licencia", "- Confirmar acuerdo de display/redistribución de EODHD antes de uso como producto."]
    return "\n".join(L)


def _selftest():
    inc_y = {"2025-12-31": {"date": "2025-12-31", "filing_date": "2026-02-01", "totalRevenue": 28000,
                            "netIncome": 8000, "weightedAverageShsOutDil": 400, "weightedAverageShsOut": 405}}
    inc_q = {"2026-06-30": {"date": "2026-06-30", "filing_date": "2026-07-16", "totalRevenue": 7000, "netIncome": 2000}}
    bal_y = {"2025-12-31": {"date": "2025-12-31", "cashAndEquivalents": 5000, "longTermDebt": 4000, "shortTermDebt": 1000}}
    cf_y = {"2025-12-31": {"date": "2025-12-31", "totalCashFromOperatingActivities": 9000, "capitalExpenditures": 1000, "freeCashFlow": 8000}}
    obj = {
        "General": {"CurrencyCode": "EUR"},
        "Highlights": {"DilutedEpsTTM": 22.0},
        "outstandingShares": {"annual": {"0": {"shares": 400}}},
        "Earnings": {"Annual": {"2025-12-31": {"date": "2025-12-31", "epsActual": 20.0}},
                     "History": {"2026-06-30": {"reportDate": "2026-07-16", "epsActual": 5.0}}},
        "Financials": {
            "Income_Statement": {"currency_symbol": "EUR", "yearly": inc_y, "quarterly": inc_q},
            "Balance_Sheet": {"yearly": bal_y, "quarterly": {}},
            "Cash_Flow": {"yearly": cf_y, "quarterly": {}},
        },
    }
    e = eodhd_extract(obj)
    assert e["currency"] == "EUR"
    a = e["annual"]["2025-12-31"]
    assert a["revenue"] == 28000 and a["diluted_shares_wavg"] == 400 and a["total_debt"] == 5000 and a["fcf"] == 8000
    assert e["eps_annual"]["2025-12-31"] == 20.0 and e["eps_quarterly_latest"] == 5.0 and e["eps_ttm"] == 22.0
    assert e["shares_outstanding_present"] is True
    # conciliación mismo-año/moneda
    st, why, ev, diff = reconcile_field(28000, {"2025-12-31": 28000}, "2025-12-31", True)
    assert st == "verificado"
    st, *_ = reconcile_field(28000, {"2024-12-31": 25000}, "2025-12-31", True)
    assert st == "sin_contraste_periodo"            # distinto año → no se compara
    st, *_ = reconcile_field(28000, {"2025-12-31": 28000}, "2025-12-31", False)
    assert st == "no_comparable_moneda"
    st, *_ = reconcile_field(28000000, {"2025-12-31": 28000}, "2025-12-31", True)
    assert st == "inconsistente_escala"             # factor x1000 detectado
    assert "api_token=***" in _redact("x?api_token=SECRET&fmt=json")
    print("SELF-TEST v2 OK: extracción, EPS separado, acciones ponderadas, conciliación mismo-año/moneda, escala, redacción.")
    return 0


def main(argv):
    if "--selftest" in argv:
        return _selftest()
    token = os.getenv("EODHD_API_KEY", "")
    if not token:
        print("ERROR: falta EODHD_API_KEY en el entorno. No se consulta nada. La clave nunca se imprime ni se guarda.")
        return 2
    ua = os.getenv("EDGAR_USER_AGENT", "")
    fetch = http_get_json
    probe = access_probe(token, fetch)
    results = []
    if probe["acceso"]:
        for cfg in UNIVERSE:
            results.append(validate_one(cfg, token, ua, fetch))
    print(build_report(probe, results))
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"probe": probe, "results": results, "fecha": TODAY.isoformat()}, fh, ensure_ascii=False, indent=2, default=str)
        print(f"\n(JSON en {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
