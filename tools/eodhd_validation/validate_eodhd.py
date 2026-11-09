#!/usr/bin/env python3
"""Validación empírica INDEPENDIENTE de EODHD para GIIC (no es el conector productivo).

Objetivo: comprobar con datos REALES —no asumidos— si el plan/clave de EODHD da acceso a los
fundamentales que necesitamos, con qué cobertura/actualidad, y si mejora la cobertura VIGENTE (B)
frente a EDGAR. No contrata nada, no toca el núcleo de GIIC, no inicia Fair Value.

Seguridad de credenciales:
  - La clave se lee de la variable de entorno EODHD_API_KEY. NUNCA se escribe en disco ni en logs
    (las URLs se redactan antes de imprimirse). Si falta, el script lo informa y termina.
  - EDGAR exige User-Agent con contacto: se lee de EDGAR_USER_AGENT (para el contraste oficial).

Uso:
  export EODHD_API_KEY=...            # clave (gratuita/trial o de pago)
  export EDGAR_USER_AGENT="giic tu@correo"   # opcional: habilita el contraste contra EDGAR
  python validate_eodhd.py                    # informe legible (markdown) a stdout
  python validate_eodhd.py --json out.json    # además guarda el detalle en JSON
  python validate_eodhd.py --selftest         # prueba el pipeline con fixtures (sin red ni clave)

Si la prueba gratuita NO permite consultar fundamentales, el informe lo declara como BLOQUEO y
lista alternativas de validación — sin inventar cifras.
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

# Batería prioritaria. Para ADR internacionales se consulta el símbolo del MERCADO LOCAL (moneda de
# reporte real) y, cuando existe, también el ADR en US. adr_ratio = acciones ordinarias por ADR.
UNIVERSE = [
    {"name": "ASML", "edgar": "ASML", "eodhd_home": "ASML.AS",   "eodhd_adr": "ASML.US", "home_ccy": "EUR", "adr_ratio": 1},
    {"name": "TSM",  "edgar": "TSM",  "eodhd_home": "2330.TW",   "eodhd_adr": "TSM.US",  "home_ccy": "TWD", "adr_ratio": 5},
    {"name": "SAP",  "edgar": "SAP",  "eodhd_home": "SAP.XETRA", "eodhd_adr": "SAP.US",  "home_ccy": "EUR", "adr_ratio": 1},
    {"name": "NVO",  "edgar": "NVO",  "eodhd_home": "NOVO-B.CO", "eodhd_adr": "NVO.US",  "home_ccy": "DKK", "adr_ratio": 1},
    {"name": "AZN",  "edgar": "AZN",  "eodhd_home": "AZN.LSE",   "eodhd_adr": "AZN.US",  "home_ccy": "GBP", "adr_ratio": 2},
    {"name": "BABA", "edgar": "BABA", "eodhd_home": "9988.HK",   "eodhd_adr": "BABA.US", "home_ccy": "HKD", "adr_ratio": 8},
    {"name": "V",    "edgar": "V",    "eodhd_home": "V.US",      "eodhd_adr": "V.US",    "home_ccy": "USD", "adr_ratio": 1},
    {"name": "MA",   "edgar": "MA",   "eodhd_home": "MA.US",     "eodhd_adr": "MA.US",   "home_ccy": "USD", "adr_ratio": 1},
    {"name": "MU",   "edgar": "MU",   "eodhd_home": "MU.US",     "eodhd_adr": "MU.US",   "home_ccy": "USD", "adr_ratio": 1},
]

FV_FIELDS = ["revenue", "net_income", "eps_diluted", "diluted_shares", "ocf", "capex", "fcf", "cash", "total_debt"]

# Claves posibles en el JSON de EODHD por campo (se prueba la primera que exista y sea numérica).
INCOME_KEYS = {"revenue": ["totalRevenue"], "net_income": ["netIncome"],
               "diluted_shares": ["weightedAverageShsOutDil", "weightedAverageShsOut"]}
CASHFLOW_KEYS = {"ocf": ["totalCashFromOperatingActivities"],
                 "capex": ["capitalExpenditures"], "fcf": ["freeCashFlow"]}
BALANCE_KEYS = {"cash": ["cashAndEquivalents", "cash", "cashAndShortTermInvestments"],
                "total_debt": ["shortLongTermDebtTotal"],
                "longTermDebt": ["longTermDebt"], "shortDebt": ["shortTermDebt", "shortLongTermDebt"],
                "netDebt": ["netDebt"]}


def _redact(s: str) -> str:
    return re.sub(r"(api_token=)[^&\s]+", r"\1***", s or "")


def http_get_json(url: str, headers=None, timeout=40):
    """GET → (status, obj|None, error|None). Redacta el token en cualquier mensaje."""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(body), None
            except json.JSONDecodeError:
                return r.status, None, f"respuesta no-JSON ({len(body)} bytes)"
    except urllib.error.HTTPError as e:
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:
        return None, None, f"{type(e).__name__}: {_redact(str(e))}"


# ---------- EODHD ----------
def eodhd_fundamentals(symbol, token, fetch=http_get_json):
    url = f"{EODHD_BASE}/fundamentals/{symbol}?api_token={token}&fmt=json"
    status, obj, err = fetch(url, {"User-Agent": "giic-eodhd-validation"})
    return status, obj, err


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


def _latest_period(section):
    """(period_date, filing_date, row) del período más reciente de una sección yearly/quarterly."""
    if not isinstance(section, dict):
        return None, None, None
    rows = [(k, v) for k, v in section.items() if isinstance(v, dict)]
    if not rows:
        return None, None, None
    rows.sort(key=lambda kv: kv[0])
    k, row = rows[-1]
    return row.get("date") or k, row.get("filing_date"), row


def extract_eodhd(obj):
    """Normaliza el JSON de EODHD a: moneda, último anual y trimestral con fecha+publicación, y los
    9 campos FV en ambos períodos. No inventa: ausente -> None."""
    out = {"currency": None, "annual": {}, "quarterly": {}, "periods": {}}
    if not isinstance(obj, dict):
        return out
    fin = obj.get("Financials", {}) or {}
    out["currency"] = ((fin.get("Income_Statement", {}) or {}).get("currency_symbol")
                       or (obj.get("General", {}) or {}).get("CurrencyCode"))
    for label, sect in (("annual", "yearly"), ("quarterly", "quarterly")):
        inc = ((fin.get("Income_Statement", {}) or {}).get(sect)) or {}
        bal = ((fin.get("Balance_Sheet", {}) or {}).get(sect)) or {}
        cf = ((fin.get("Cash_Flow", {}) or {}).get(sect)) or {}
        ip, ifil, irow = _latest_period(inc)
        bp, bfil, brow = _latest_period(bal)
        cp, cfil, crow = _latest_period(cf)
        vals = {}
        for f, keys in INCOME_KEYS.items():
            vals[f] = _num(irow, keys)
        for f, keys in CASHFLOW_KEYS.items():
            vals[f] = _num(crow, keys)
        vals["cash"] = _num(brow, BALANCE_KEYS["cash"])
        td = _num(brow, BALANCE_KEYS["total_debt"])
        if td is None:
            lt = _num(brow, BALANCE_KEYS["longTermDebt"]); st = _num(brow, BALANCE_KEYS["shortDebt"])
            td = (lt or 0) + (st or 0) if (lt is not None or st is not None) else None
        vals["total_debt"] = td
        if vals.get("fcf") is None and vals.get("ocf") is not None and vals.get("capex") is not None:
            vals["fcf"] = vals["ocf"] - abs(vals["capex"])
        # EPS diluido: EODHD no lo trae en el income; se usa Highlights / Earnings como señal.
        vals["eps_diluted"] = _num(obj.get("Highlights", {}), ["DilutedEpsTTM", "EarningsShare"]) if label == "annual" else None
        out[label] = vals
        out["periods"][label] = {"period_end": ip or bp or cp, "filing_date": ifil or bfil or cfil}
    return out


# ---------- EDGAR (contraste oficial) ----------
def edgar_latest_annual(edgar_ticker, ua, fetch=http_get_json):
    """Último anual oficial de EDGAR: (currency, {revenue, net_income, eps_diluted, period_end})."""
    if not ua or "@" not in ua:
        return None
    st, tk, _ = fetch("https://www.sec.gov/files/company_tickers.json", {"User-Agent": ua})
    if not tk:
        return None
    cik = None
    for r in tk.values():
        if r["ticker"].upper() == edgar_ticker.upper():
            cik = int(r["cik_str"]); break
    if cik is None:
        return None
    st, facts, _ = fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", {"User-Agent": ua})
    if not facts:
        return None

    def latest_annual(concepts, unit_filter):
        best = None
        for tax in ("us-gaap", "ifrs-full"):
            for c in concepts:
                node = (((facts.get("facts", {}) or {}).get(tax, {}) or {}).get(c, {}) or {}).get("units", {}) or {}
                for unit, rows in node.items():
                    if unit_filter(unit):
                        for r in rows:
                            if str(r.get("form", "")).startswith(("10-K", "20-F", "40-F")) and r.get("start") and r.get("end"):
                                try:
                                    d0 = datetime.strptime(r["start"], "%Y-%m-%d").date()
                                    d1 = datetime.strptime(r["end"], "%Y-%m-%d").date()
                                except ValueError:
                                    continue
                                if 330 <= (d1 - d0).days <= 400 and (best is None or d1 > best[0]):
                                    best = (d1, float(r["val"]), unit)
        return best

    def money(u):
        return "/" not in u and len(u) == 3
    rev = latest_annual(["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "RevenueFromContractsWithCustomers", "Revenue"], money)
    ni = latest_annual(["NetIncomeLoss", "ProfitLoss"], money)
    eps = latest_annual(["EarningsPerShareDiluted", "DilutedEarningsLossPerShare"], lambda u: u.endswith("/shares"))
    return {"currency": (rev or ni or (None, None, None))[2],
            "revenue": rev[1] if rev else None, "net_income": ni[1] if ni else None,
            "eps_diluted": eps[1] if eps else None,
            "period_end": (rev or ni or (None,))[0].isoformat() if (rev or ni) else None}


# ---------- Clasificación ----------
def classify(eodhd_val, edgar_val, same_currency, tol=0.02):
    """verificado | inconsistente | parcial | ausente (+ razón)."""
    if eodhd_val is None:
        return "ausente", "sin dato en EODHD"
    if edgar_val is None:
        return "parcial", "presente en EODHD; sin contraste EDGAR"
    if not same_currency:
        return "parcial", "presente; monedas distintas, no comparable directo"
    if edgar_val == 0:
        return "parcial", "EDGAR=0, no comparable"
    diff = abs(eodhd_val - edgar_val) / abs(edgar_val)
    return ("verificado", f"coincide con EDGAR (dif {diff*100:.2f}%)") if diff <= tol else \
        ("inconsistente", f"difiere de EDGAR {diff*100:.1f}%")


def _parse_d(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def validate_one(cfg, token, ua, fetch=http_get_json):
    rec = {"name": cfg["name"], "home_symbol": cfg["eodhd_home"], "adr_ratio": cfg["adr_ratio"]}
    status, obj, err = eodhd_fundamentals(cfg["eodhd_home"], token, fetch)
    rec["http_status"] = status
    if not obj or not isinstance(obj, dict) or "Financials" not in obj:
        rec["acceso"] = f"sin fundamentales ({err or 'respuesta vacía/sin Financials'})"
        rec["campos"] = {f: "ausente" for f in FV_FIELDS}
        return rec
    e = extract_eodhd(obj)
    rec["currency"] = e["currency"]
    rec["ultimo_anual"] = e["periods"]["annual"]
    rec["ultimo_trimestral"] = e["periods"]["quarterly"]
    edg = edgar_latest_annual(cfg["edgar"], ua, fetch)
    rec["edgar"] = {"period_end": edg["period_end"], "currency": edg["currency"]} if edg else None
    same_ccy = bool(edg and e["currency"] and edg["currency"] and e["currency"].upper() == edg["currency"].upper())
    # Clasifica los 3 campos contrastables (revenue/NI/EPS) contra EDGAR; el resto por presencia.
    states, reasons = {}, {}
    annual = e["annual"]
    for f in FV_FIELDS:
        if f in ("revenue", "net_income", "eps_diluted") and edg:
            st, why = classify(annual.get(f), edg.get(f), same_ccy)
        else:
            st, why = ("parcial", "presente (sin contraste directo)") if annual.get(f) is not None else ("ausente", "sin dato")
        states[f], reasons[f] = st, why
    # Actualidad vs EDGAR: ¿EODHD trae un período más reciente que EDGAR? (señal de mejora de B)
    eo_q = _parse_d(e["periods"]["quarterly"]["period_end"])
    eo_a = _parse_d(e["periods"]["annual"]["period_end"])
    eo_latest = max([d for d in (eo_q, eo_a) if d], default=None)
    ed_latest = _parse_d(edg["period_end"]) if edg else None
    rec["eodhd_mas_reciente_que_edgar"] = bool(eo_latest and ed_latest and eo_latest > ed_latest)
    rec["eodhd_period_latest"] = eo_latest.isoformat() if eo_latest else None
    rec["edgar_period_latest"] = ed_latest.isoformat() if ed_latest else None
    rec["same_currency_vs_edgar"] = same_ccy
    rec["campos"] = states
    rec["razones"] = reasons
    rec["acceso"] = "ok"
    return rec


def access_probe(token, fetch=http_get_json):
    """No asume que la clave habilita fundamentales: lo comprueba con AAPL.US."""
    status, obj, err = eodhd_fundamentals("AAPL.US", token, fetch)
    if obj and isinstance(obj, dict) and "Financials" in obj:
        return {"acceso_fundamentales": True, "status": status, "detalle": "AAPL.US devolvió Financials"}
    hint = "402/403 suele indicar endpoint no incluido en el plan/clave" if status in (402, 403) else (err or "sin Financials")
    return {"acceso_fundamentales": False, "status": status, "detalle": hint}


def build_report(probe, results):
    L = ["# Validación empírica EODHD — GIIC", ""]
    L.append(f"- Fecha: {TODAY.isoformat()}")
    L.append(f"- Acceso a fundamentales (prueba AAPL.US): **{'SÍ' if probe['acceso_fundamentales'] else 'NO'}** "
             f"(HTTP {probe['status']}; {probe['detalle']})")
    if not probe["acceso_fundamentales"]:
        L += ["", "> **BLOQUEO**: la clave/plan no da acceso a fundamentales. No se consultaron los 9 emisores.",
              "> Alternativas: (a) clave de pago del plan Fundamentals Data Feed; (b) prueba del endpoint",
              ">   en la consola web de EODHD; (c) contraste manual de 2-3 tickers desde su documentación.",
              "> No se inventan cifras."]
        return "\n".join(L)
    # Tabla por emisor
    L += ["", "## Cobertura y actualidad por emisor", "",
          "| Emisor | símbolo | moneda | últ. anual (pub.) | últ. trim. (pub.) | EODHD>EDGAR | verif. | inconsist. | ausentes |",
          "|---|---|---|---|---|---|---|---|---|"]
    tot = {"verificado": 0, "inconsistente": 0, "ausente": 0, "parcial": 0}
    fresher = 0
    for r in results:
        if r.get("acceso") != "ok":
            L.append(f"| {r['name']} | {r['home_symbol']} | — | — | — | — | — | — | sin acceso: {r.get('acceso')} |")
            continue
        c = r["campos"]
        v = sum(1 for s in c.values() if s == "verificado")
        inc = sum(1 for s in c.values() if s == "inconsistente")
        au = sum(1 for s in c.values() if s == "ausente")
        for s in c.values():
            tot[s] = tot.get(s, 0) + 1
        fresher += 1 if r.get("eodhd_mas_reciente_que_edgar") else 0
        aa = r["ultimo_anual"]; qq = r["ultimo_trimestral"]
        L.append(f"| {r['name']} | {r['home_symbol']} | {r.get('currency')} | "
                 f"{aa.get('period_end')} ({aa.get('filing_date')}) | {qq.get('period_end')} ({qq.get('filing_date')}) | "
                 f"{'sí' if r.get('eodhd_mas_reciente_que_edgar') else 'no'} | {v} | {inc} | {au} |")
    # Campos por emisor (estado de los 9)
    L += ["", "## Estado de los 9 campos (anual, contraste EDGAR donde aplica)", "",
          "| Emisor | " + " | ".join(FV_FIELDS) + " |", "|---|" + "---|" * len(FV_FIELDS)]
    for r in results:
        if r.get("acceso") != "ok":
            continue
        L.append(f"| {r['name']} | " + " | ".join(r["campos"][f][:4] for f in FV_FIELDS) + " |")
    # Resumen / estimación de B SOLO sobre lo comprobado
    intl = [r for r in results if r.get("acceso") == "ok" and r["name"] in ("ASML", "TSM", "SAP", "NVO", "AZN", "BABA")]
    intl_fresher = [r for r in intl if r.get("eodhd_mas_reciente_que_edgar")]
    L += ["", "## Resumen", "",
          f"- Campos: verificado={tot.get('verificado',0)}, inconsistente={tot.get('inconsistente',0)}, "
          f"parcial={tot.get('parcial',0)}, ausente={tot.get('ausente',0)}.",
          f"- Emisores con período más reciente que EDGAR: {fresher}/{sum(1 for r in results if r.get('acceso')=='ok')}.",
          f"- Internacionales prioritarios con dato más fresco que EDGAR (señal de mejora de B): "
          f"{len(intl_fresher)}/{len(intl)} → {[r['name'] for r in intl_fresher]}.",
          "",
          "> Estimación de B: la mejora SOLO se afirma sobre los emisores efectivamente comprobados aquí.",
          "> No se extrapola al resto de los 63 sin probarlos. Para los internacionales con dato más",
          "> fresco Y campos verificados/parciales, EODHD elevaría su cobertura vigente de 0% a cubierta;",
          "> el impacto total sobre B depende de cuántos de los 14 ADR/IFRS repliquen este resultado.",
          "",
          "## Licencia (verificar antes de uso en producto)",
          "- EODHD separa uso personal de comercial/B2B (página de licencia aparte). Para mostrar datos",
          "  en GIIC como producto, confirmar el acuerdo de display/redistribución y atribución en su ToS.",
          "- Este script es de validación; no habilita redistribución."]
    return "\n".join(L)


# ---------- Self-test con fixtures (sin red ni clave) ----------
def _selftest():
    aapl = {"General": {"CurrencyCode": "USD"}, "Highlights": {"DilutedEpsTTM": 6.1},
            "Financials": {"Income_Statement": {"currency_symbol": "USD",
                "yearly": {"2025-09-27": {"date": "2025-09-27", "filing_date": "2025-11-01",
                                           "totalRevenue": 400000, "netIncome": 95000, "weightedAverageShsOutDil": 15000}},
                "quarterly": {"2026-06-27": {"date": "2026-06-27", "filing_date": "2026-08-01",
                                              "totalRevenue": 90000, "netIncome": 22000, "weightedAverageShsOutDil": 14800}}},
                "Balance_Sheet": {"yearly": {"2025-09-27": {"date": "2025-09-27", "cashAndEquivalents": 30000, "longTermDebt": 80000, "shortTermDebt": 10000}}, "quarterly": {}},
                "Cash_Flow": {"yearly": {"2025-09-27": {"date": "2025-09-27", "totalCashFromOperatingActivities": 110000, "capitalExpenditures": 11000, "freeCashFlow": 99000}}, "quarterly": {}}}}
    e = extract_eodhd(aapl)
    assert e["currency"] == "USD"
    assert e["annual"]["revenue"] == 400000 and e["annual"]["net_income"] == 95000
    assert e["annual"]["total_debt"] == 90000 and e["annual"]["fcf"] == 99000
    assert e["periods"]["annual"]["filing_date"] == "2025-11-01"
    assert e["periods"]["quarterly"]["period_end"] == "2026-06-27"
    # clasificación
    assert classify(400000, 400000, True)[0] == "verificado"
    assert classify(400000, 360000, True)[0] == "inconsistente"
    assert classify(None, 1, True)[0] == "ausente"
    assert classify(5, 5, False)[0] == "parcial"
    # validate_one con fetch simulado (EODHD home + EDGAR)
    def fake_fetch(url, headers=None, timeout=40):
        if "fundamentals/ASML.AS" in url:
            return 200, {**aapl, "General": {"CurrencyCode": "EUR"},
                         "Financials": {**aapl["Financials"],
                            "Income_Statement": {"currency_symbol": "EUR",
                               "yearly": {"2025-12-31": {"date": "2025-12-31", "filing_date": "2026-02-01", "totalRevenue": 28000, "netIncome": 7000, "weightedAverageShsOutDil": 400}},
                               "quarterly": {"2026-06-30": {"date": "2026-06-30", "filing_date": "2026-07-16", "totalRevenue": 7000, "netIncome": 1800}}},
                            "Balance_Sheet": {"yearly": {"2025-12-31": {"date": "2025-12-31", "cashAndEquivalents": 5000, "longTermDebt": 4000}}, "quarterly": {}},
                            "Cash_Flow": {"yearly": {"2025-12-31": {"date": "2025-12-31", "totalCashFromOperatingActivities": 9000, "capitalExpenditures": 1000, "freeCashFlow": 8000}}, "quarterly": {}}}}, None
        if "company_tickers" in url:
            return 200, {"0": {"ticker": "ASML", "cik_str": 937966}}, None
        if "companyfacts" in url:
            return 200, {"facts": {"ifrs-full": {"RevenueFromContractsWithCustomers": {"units": {"EUR": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 28000, "form": "20-F"}]}},
                "ProfitLoss": {"units": {"EUR": [{"start": "2025-01-01", "end": "2025-12-31", "val": 7000, "form": "20-F"}]}}}}}, None
        return 404, None, "HTTP 404"
    r = validate_one(UNIVERSE[0], "DUMMY", "giic test@test.com", fake_fetch)
    assert r["currency"] == "EUR" and r["same_currency_vs_edgar"] is True
    assert r["campos"]["revenue"] == "verificado" and r["campos"]["net_income"] == "verificado"
    assert r["eodhd_mas_reciente_que_edgar"] is True   # trim 2026-06-30 > anual EDGAR 2025-12-31
    assert "api_token=***" in _redact("https://x/api/fundamentals/ASML.AS?api_token=SECRET&fmt=json")
    print("SELF-TEST OK: extracción, clasificación, contraste EDGAR, actualidad y redacción de token.")
    return 0


def main(argv):
    if "--selftest" in argv:
        return _selftest()
    token = os.getenv("EODHD_API_KEY", "")
    if not token:
        print("ERROR: falta EODHD_API_KEY en el entorno. No se consulta nada. "
              "Exporta la clave (gratuita o de pago) y reintenta. La clave NUNCA se imprime ni se guarda.")
        return 2
    ua = os.getenv("EDGAR_USER_AGENT", "")
    fetch = http_get_json
    probe = access_probe(token, fetch)
    results = []
    if probe["acceso_fundamentales"]:
        for cfg in UNIVERSE:
            results.append(validate_one(cfg, token, ua, fetch))
    report = build_report(probe, results)
    print(report)
    if "--json" in argv:
        path = argv[argv.index("--json") + 1]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"probe": probe, "results": results, "fecha": TODAY.isoformat()}, fh,
                      ensure_ascii=False, indent=2, default=str)
        print(f"\n(JSON detallado guardado en {path})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
