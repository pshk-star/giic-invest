"""Inspección de SOLO LECTURA de tablas en Supabase (no modifica nada).

Comprueba existencia, columnas (desde el OpenAPI de PostgREST) y nº de filas de
fx_rates / etf_holdings / settings. Las políticas RLS no se exponen por REST: para eso se
imprime la consulta SQL exacta que Pablo puede correr en el editor SQL de Supabase.

Uso: python -m app.jobs.inspect_tables
"""
from __future__ import annotations

import json
import math
import os
import sys

TABLES = ["fx_rates", "etf_holdings", "settings", "user_funds", "fund_navs"]

# Tickers a verificar en detalle (evidencia de datos reales llegando a la UI).
FUND_TICKERS = ["ASML", "TSM", "NVDA", "META", "NFLX"]

# Validación de la CORRECCIÓN del Advisor (motor de oportunidades por valoración).
OPP_TICKERS = ["V", "MU", "LLY", "MA", "PG"]

# --- Espejo EXACTO de valuateCompany (EPS×P/E preliminar) + buildOpportunities ---
# Reproduce la lógica de frontend/src/core/fundamental.ts y opportunities.ts para
# mostrar la DECISIÓN resultante con datos reales. La app desplegada usa el TS real;
# este espejo es solo evidencia (mismos números y umbrales).
_GROWTH_FLOOR, _GROWTH_CAP, _GROWTH_STEP = -0.15, 0.35, 0.05
_STALE_SOFT, _STALE_HARD = 400, 550
_REFERENCE_YIELD = 0.07          # rendimiento de referencia DESCRIPTIVO (= fundamental.ts)
_REFERENCE_BAND = 0.15           # ±15% alrededor de la referencia = "cerca"
_CYCLICAL_GROWTH_ABS = 0.75


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _age_days(as_of, ref):
    try:
        from datetime import date
        a = date.fromisoformat(str(as_of)[:10])
        r = date.fromisoformat(str(ref)[:10]) if ref else date.today()
        return (r - a).days
    except Exception:
        return None


def _is_fin(x):
    return isinstance(x, (int, float)) and math.isfinite(x)


def opp_decision(payload, price, price_as_of):
    """Espejo del motor DEGRADADO: NO emite COMPRAR/VENDER (sin valoración fundada).
    Muestra señales descriptivas (rendimiento de beneficios/FCF, posición vs una
    referencia que NO implica cara/barata), alerta de ciclicidad, consistencia de EPS,
    y distingue brecha-de-datos (INVESTIGAR) de en-observación (ESPERAR)."""
    f = payload or {}
    if not _is_fin(price) or price <= 0:
        return {"action": "INVESTIGAR", "available": False, "reason": "brecha de datos: sin precio actual"}
    egy, rgy = f.get("eps_growth_yoy"), f.get("rev_growth_yoy")
    g = _clamp(egy, _GROWTH_FLOOR, _GROWTH_CAP) if _is_fin(egy) \
        else _clamp(rgy, _GROWTH_FLOOR, _GROWTH_CAP) if _is_fin(rgy) else 0.0
    pe = f.get("pe_ttm")
    fcf_yield = f.get("fcf_yield") if _is_fin(f.get("fcf_yield")) else None
    age = _age_days(f.get("as_of"), price_as_of)
    # EPS reportado → rendimiento de beneficios NO circular (si el payload trae eps).
    eps_rep = f.get("eps") if _is_fin(f.get("eps")) else (price / pe if (_is_fin(pe) and pe > 0) else None)
    earnings_yield = (eps_rep / price) if (eps_rep is not None and price > 0) else None
    central_up = g   # proyección 12m circular (= crecimiento acotado); SÓLO contexto

    if _is_fin(pe) and pe > 0:
        method, available = "pe_eps", True
        quality = "alta" if (_is_fin(egy) and abs(egy) < 0.5) \
            else "media" if (_is_fin(egy) or _is_fin(rgy)) else "baja"
        if age is not None and age > _STALE_HARD:
            quality = "baja"
        elif age is not None and age > _STALE_SOFT and quality == "alta":
            quality = "media"
    elif fcf_yield is not None and fcf_yield > 0:
        method, available, quality = "fcf_fallback", True, "baja"
    else:
        return {"action": "INVESTIGAR", "available": False, "method": None,
                "reason": "brecha de datos: sin P/E positivo ni FCF yield (no es veredicto de inversión)",
                "fund_as_of": f.get("as_of"), "fund_age_days": age}

    yld = earnings_yield if earnings_yield is not None else fcf_yield
    yield_vs_reference = "n/d" if yld is None \
        else "encima" if yld >= _REFERENCE_YIELD * (1 + _REFERENCE_BAND) \
        else "debajo" if yld <= _REFERENCE_YIELD * (1 - _REFERENCE_BAND) else "cerca"
    cyclical_alert = _is_fin(egy) and abs(egy) >= _CYCLICAL_GROWTH_ABS

    # NO se emite COMPRAR: no hay valoración fundada. Con datos → ESPERAR (señal en observación);
    # brecha/calidad baja → INVESTIGAR. El rendimiento vs referencia NO implica cara/barata.
    action = "INVESTIGAR" if quality == "baja" else "ESPERAR"
    return {
        "action": action, "decision_ready": False,
        "decision_block": "sin valoración fundada (faltan TTM/forward/múltiplos históricos/normalizada)",
        "available": available, "method": method, "quality": quality,
        "price": price, "price_as_of": price_as_of,
        "eps_reported": eps_rep, "earnings_basis": f.get("eps_basis"),
        "eps_consistent": f.get("eps_consistent"), "eps_check_ratio": f.get("eps_check_ratio"),
        "earnings_yield": round(earnings_yield, 4) if earnings_yield is not None else None,
        "fcf_yield": round(fcf_yield, 4) if fcf_yield is not None else None,
        "reference_yield": _REFERENCE_YIELD, "yield_vs_reference": yield_vs_reference,
        "cyclical_alert": cyclical_alert, "eps_growth_yoy_raw": egy, "rev_growth_yoy_raw": rgy,
        "pe_ttm": pe, "projection_12m_circular": round(central_up, 4),
        "roe": f.get("roe"), "net_margin": f.get("net_margin"),
        "fund_as_of": f.get("as_of"), "fund_age_days": age,
        "taxonomy": f.get("taxonomy"), "currency": f.get("currency"),
        "note": "Señal DESCRIPTIVA, no decisión. El rendimiento vs referencia no implica cara/barata; la proyección 12m es circular (contexto).",
    }

RLS_SQL = (
    "-- Columnas, tipos y RLS (correr en el editor SQL de Supabase):\n"
    "select table_name, column_name, data_type, is_nullable, column_default\n"
    "  from information_schema.columns\n"
    " where table_schema='public' and table_name in "
    "('fx_rates','etf_holdings','settings')\n"
    " order by table_name, ordinal_position;\n\n"
    "select schemaname, tablename, rowsecurity from pg_tables\n"
    " where schemaname='public' and tablename in ('fx_rates','etf_holdings','settings');\n\n"
    "select tablename, policyname, cmd, qual, with_check from pg_policies\n"
    " where schemaname='public' and tablename in ('fx_rates','etf_holdings','settings')\n"
    " order by tablename, policyname;"
)


def run() -> dict:
    import httpx
    base = os.getenv("SUPABASE_URL", "").rstrip("/") + "/rest/v1"
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    cli = httpx.Client(timeout=30.0, headers=headers)

    # OpenAPI expone las tablas y sus columnas (definitions/properties)
    spec = cli.get(f"{base}/").json()
    defs = spec.get("definitions", spec.get("components", {}).get("schemas", {})) or {}

    out = {}
    for t in TABLES:
        exists = t in defs
        cols = {}
        if exists:
            props = (defs[t] or {}).get("properties", {}) or {}
            cols = {c: (p.get("format") or p.get("type")) for c, p in props.items()}
        # conteo (HEAD con count=exact) — bypass RLS por service role
        n = None
        try:
            r = cli.get(f"{base}/{t}", params={"select": "*", "limit": "0"},
                        headers={"Prefer": "count=exact"})
            cr = r.headers.get("content-range", "")
            if "/" in cr:
                n = cr.split("/")[-1]
        except Exception as e:
            n = f"error: {type(e).__name__}"
        out[t] = {"exists_in_rest": exists, "columns": cols, "row_count": n}
    # volcado de fx_rates (solo lectura) para confirmar par MXN/USD utilizable
    fx = []
    try:
        fx = cli.get(f"{base}/fx_rates", params={"select": "base,currency,rate,as_of",
                                                 "order": "as_of.desc", "limit": "50"}).json()
    except Exception as e:
        fx = [{"error": f"{type(e).__name__}"}]

    # EVIDENCIA: fundamentales reales + precios por ticker objetivo (ASML/TSM/…).
    inlist = ",".join(FUND_TICKERS)
    fundamentals = []
    try:
        fundamentals = cli.get(f"{base}/fundamentals",
                               params={"select": "ticker,payload", "ticker": f"in.({inlist})"}).json()
    except Exception as e:
        fundamentals = [{"error": f"{type(e).__name__}"}]
    prices_now = []
    try:
        prices_now = cli.get(f"{base}/prices",
                             params={"select": "ticker,close,as_of,currency", "ticker": f"in.({inlist})"}).json()
    except Exception as e:
        prices_now = [{"error": f"{type(e).__name__}"}]
    # Comparación de precio para ASML (Prioridad 3): últimas filas de price_history.
    asml_hist = []
    try:
        asml_hist = cli.get(f"{base}/price_history",
                            params={"select": "ticker,close,as_of", "ticker": "eq.ASML",
                                    "order": "as_of.desc", "limit": "3"}).json()
    except Exception as e:
        asml_hist = [{"error": f"{type(e).__name__}"}]

    # Conteo de price_history por ticker (viabilidad de proyección estadística individual).
    hist_counts = {}
    for t in FUND_TICKERS + ["VOO", "QQQ", "SCHD", "GLD", "SLV"]:
        try:
            r = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "limit": "0"},
                        headers={"Prefer": "count=exact"})
            cr = r.headers.get("content-range", "")
            hist_counts[t] = int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else cr
        except Exception as e:
            hist_counts[t] = f"error: {type(e).__name__}"

    # Validación del historial: rango REAL (min/max con consultas de 1 fila), campos de
    # ajuste/proveedor, y chequeo de saltos sobre las 1000 MÁS RECIENTES (order desc).
    hist_validation = {}
    for t in ["ASML", "TSM", "NVDA"]:
        try:
            cnt = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "limit": "0"},
                          headers={"Prefer": "count=exact"})
            total = cnt.headers.get("content-range", "").split("/")[-1]
            first = cli.get(f"{base}/price_history", params={"select": "as_of", "ticker": f"eq.{t}", "order": "as_of.asc", "limit": "1"}).json()
            last = cli.get(f"{base}/price_history", params={"select": "as_of,close,adjusted,source", "ticker": f"eq.{t}", "order": "as_of.desc", "limit": "1"}).json()
            recent = cli.get(f"{base}/price_history", params={"select": "as_of,close", "ticker": f"eq.{t}", "order": "as_of.desc", "limit": "1000"}).json()
            recent = list(reversed(recent))
            closes = [float(r["close"]) for r in recent if r.get("close") is not None]
            rets = [abs(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes)) if closes[i - 1] > 0]
            hist_validation[t] = {
                "total_rows": total,
                "min_date": (first[0]["as_of"] if first else None),
                "max_date": (last[0]["as_of"] if last else None),
                "last_close": (last[0].get("close") if last else None),
                "adjusted_field": (last[0].get("adjusted") if last else None),
                "source_field": (last[0].get("source") if last else None),
                "recent_sample": len(closes),
                "max_abs_daily_return_recent1000": round(max(rets), 4) if rets else None,
                "days_over_40pct_recent1000": sum(1 for r in rets if r > 0.40),
            }
        except Exception as e:
            hist_validation[t] = {"error": f"{type(e).__name__}: {str(e)[:80]}"}

    # VALIDACIÓN DEL ADVISOR CORREGIDO: V/MU/LLY/MA/PG con datos reales → decisión.
    opp_list = ",".join(OPP_TICKERS)
    opp_funds, opp_prices = {}, {}
    try:
        for r in cli.get(f"{base}/fundamentals",
                         params={"select": "ticker,payload", "ticker": f"in.({opp_list})"}).json():
            opp_funds[r["ticker"].upper()] = r.get("payload")
    except Exception as e:
        opp_funds = {"_error": f"{type(e).__name__}"}
    try:
        for r in cli.get(f"{base}/prices",
                         params={"select": "ticker,close,as_of", "ticker": f"in.({opp_list})"}).json():
            opp_prices[r["ticker"].upper()] = (r.get("close"), r.get("as_of"))
    except Exception as e:
        opp_prices = {"_error": f"{type(e).__name__}"}
    advisor_validation = {}
    for t in OPP_TICKERS:
        px, asof = opp_prices.get(t, (None, None)) if isinstance(opp_prices, dict) else (None, None)
        has_fund = isinstance(opp_funds, dict) and t in opp_funds
        advisor_validation[t] = {
            "fundamentals_present": has_fund,
            "decision": opp_decision(opp_funds.get(t) if has_fund else None, px, asof),
        }

    # Identidad PERSISTIDA en instruments (verificación de columnas pobladas).
    instr_identity = []
    try:
        instr_identity = cli.get(f"{base}/instruments", params={
            "select": "ticker,country_issuer,country_listing,quote_currency,report_currency,instrument_type,adr_ratio,cik,figi,isin,lei,identity_as_of",
            "ticker": "in.(NVDA,TSM,ASML,VOO,MELI)"}).json()
    except Exception as e:
        instr_identity = [{"error": f"{type(e).__name__}"}]

    # Conteo de predicciones A/B/C (deben permanecer en 309, intactas).
    pred_count = None
    try:
        pr = cli.get(f"{base}/predictions", params={"select": "ticker", "limit": "0"},
                     headers={"Prefer": "count=exact"})
        pred_count = pr.headers.get("content-range", "").split("/")[-1]
    except Exception as e:
        pred_count = f"error: {type(e).__name__}"
    # ¿Columnas de identidad presentes? (indica si 0012 ya fue aplicada)
    instr_cols = sorted(((defs.get("instruments") or {}).get("properties", {}) or {}).keys())

    return {
        "tables": out, "fx_rates_rows": fx,
        "predictions_count": pred_count,
        "instruments_columns": instr_cols,
        "instruments_identity_persisted": instr_identity,
        "advisor_opportunity_validation": advisor_validation,
        "fundamentals_target": fundamentals,
        "prices_target": prices_now,
        "asml_price_history_latest": asml_hist,
        "price_history_counts": hist_counts,
        "price_history_validation": hist_validation,
        "edgar_audit_3a": edgar_audit(["V", "MA", "ASML", "TSM", "NFLX", "NVDA", "PG", "LLY", "MU"]),
        "edgar_diagnostic": edgar_diag(["ASML", "TSM"]),
        "identity_resolution": identity_diag(["NVDA", "TSM", "ASML", "VOO", "MELI"]),
        "rls_sql_for_pablo": RLS_SQL,
    }


def identity_diag(tickers: list) -> dict:
    """Resuelve identidad EN VIVO desde fuentes verificables (Yahoo meta, SEC, OpenFIGI)
    y la pasa por resolve_identity. Prueba que GIIC identifica cualquier ticker sin listas."""
    import datetime as _dt
    import httpx
    from ..services.identity import resolve_identity
    today = _dt.date.today().isoformat()
    ua = os.getenv("EDGAR_USER_AGENT", "") or "GIIC research admin@giic.app"
    cli = httpx.Client(timeout=30.0, headers={"User-Agent": ua})

    cikmap = {}
    try:
        tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
        cikmap = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}
    except Exception:
        cikmap = {}

    def yahoo_meta(t):
        try:
            p = cli.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}", params={"range": "5d", "interval": "1d"}).json()
            m = (((p or {}).get("chart", {}) or {}).get("result") or [{}])[0].get("meta", {}) or {}
            it = (m.get("instrumentType") or "").upper()
            return {"name": m.get("longName") or m.get("shortName"),
                    "asset_class": "equity" if it == "EQUITY" else "etf" if it == "ETF" else "unknown",
                    "quote_currency": m.get("currency"), "currency": m.get("currency"),
                    "exchange": m.get("fullExchangeName") or m.get("exchangeName"),
                    "exchange_code": m.get("exchangeName"),
                    "timezone": m.get("exchangeTimezoneName")}
        except Exception as e:
            return {"_error": f"{type(e).__name__}"}

    def report_ccy(cik):
        if not cik:
            return (None, None)
        try:
            f = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json().get("facts", {})
            for tax, names in (("us-gaap", ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss"]),
                               ("ifrs-full", ["RevenueFromContractsWithCustomers", "Revenue", "ProfitLoss"])):
                node = f.get(tax, {})
                for n in names:
                    for u in ((node.get(n, {}) or {}).get("units", {}) or {}):
                        if "/" not in u and len(u) == 3 and u.isalpha():
                            return (u.upper(), tax)
        except Exception:
            pass
        return (None, None)

    def figi(t):
        try:
            r = cli.post("https://api.openfigi.com/v3/mapping", json=[{"idType": "TICKER", "idValue": t, "exchCode": "US"}])
            data = r.json()
            d = (data[0].get("data") if data and isinstance(data, list) else None) or []
            return d[0].get("figi") if d else None
        except Exception:
            return None

    def issuer_country(cik):
        """País del EMISOR desde EDGAR submissions (no la zona horaria de la bolsa)."""
        if not cik:
            return {}
        try:
            s = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
            addr = ((s.get("addresses", {}) or {}).get("business", {}) or {})
            return {
                "stateOfIncorporation": s.get("stateOfIncorporation"),
                "stateOfIncorporationDescription": s.get("stateOfIncorporationDescription"),
                "business_stateOrCountry": addr.get("stateOrCountry"),
                "ein_country_hint": s.get("entityType"),
            }
        except Exception as e:
            return {"error": f"{type(e).__name__}"}

    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        rc, tax = report_ccy(cik)
        sub = issuer_country(cik)
        r = resolve_identity(t, ymeta=yahoo_meta(t), cik=cik, report_currency=rc,
                             taxonomy=tax, figi=figi(t),
                             edgar_incorp=sub.get("stateOfIncorporation"),
                             edgar_state_country=sub.get("business_stateOrCountry"),
                             today=today)
        r["_submissions_country_raw"] = sub
        out[t] = r
    return out


def edgar_diag(tickers: list) -> dict:
    """Diagnóstico EN VIVO de companyfacts de EDGAR: qué taxonomías y conceptos
    publica cada emisor (causa raíz de cobertura). Requiere EDGAR_USER_AGENT.
    Usa httpx directo (sin importar el provider, que depende de pandas)."""
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=30.0, headers={"User-Agent": ua})
    try:
        tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    except Exception as e:
        return {"error": f"company_tickers: {type(e).__name__}: {str(e)[:80]}"}
    cikmap = {row["ticker"].upper(): int(row["cik_str"]) for row in tk.values()}
    KEYS = ("revenue", "profit", "netincome", "earningspershare", "equity",
            "operatingactivities", "cashflowsfromused")
    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"cik": None, "note": "ticker no está en company_tickers.json de la SEC"}
            continue
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                out[t] = {"cik": cik, "http_status": r.status_code}
                continue
            facts = r.json()
        except Exception as e:
            out[t] = {"cik": cik, "error": f"{type(e).__name__}: {str(e)[:80]}"}
            continue
        f = (facts.get("facts", {}) or {})
        summ = {"cik": cik, "taxonomies": list(f.keys())}
        for tax in ("us-gaap", "ifrs-full"):
            node = f.get(tax)
            if not node:
                continue
            interesting = [c for c in node.keys() if any(k in c.lower() for k in KEYS)][:25]
            detail = {}
            for c in interesting[:12]:
                u = list((node[c].get("units", {}) or {}).keys())
                rows = (node[c].get("units", {}) or {}).get(u[0], []) if u else []
                last = rows[-1] if rows else {}
                detail[c] = {"units": u, "last_form": last.get("form"), "last_end": last.get("end")}
            # Todas las unidades "per share" (para detectar EPS en USD por ADR) + último valor
            # real de EPS por unidad (resuelve si el USD es por ADR o por acción ordinaria).
            per_share = {}
            eps_values = {}
            for c in node.keys():
                cl = c.lower()
                if "pershare" in cl:
                    units = (node[c].get("units", {}) or {})
                    u = list(units.keys())
                    if u:
                        per_share[c] = u
                    if "earningspershare" in cl or cl.startswith("dilutedearnings") or cl.startswith("basicearnings"):
                        for un, rows in units.items():
                            annual = [r for r in rows if str(r.get("form", "")).startswith(("10-K", "20-F", "40-F"))
                                      and r.get("start") and r.get("end")]
                            if annual:
                                last = sorted(annual, key=lambda r: r["end"])[-1]
                                eps_values[f"{c} [{un}]"] = {"val": last.get("val"), "end": last.get("end"), "form": last.get("form")}
            summ[tax] = {"n_concepts": len(node), "concepts": interesting,
                         "detail": detail, "per_share_units": per_share, "eps_latest": eps_values}
        out[t] = summ
    return out


def edgar_audit(tickers: list) -> dict:
    """AUDITORÍA 3A: por ticker, evidencia de las brechas concretas — EPS (anual y
    trimestral), utilidad neta, acciones (portada vs promedio ponderado diluido),
    consistencia EPS×acciones≈NI por AMBOS métodos (portada vs ponderado), divisa,
    antigüedad y splits (Yahoo). Solo lectura; no decide nada."""
    import datetime as _dt
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=30.0, headers={"User-Agent": ua})
    yc = httpx.Client(timeout=30.0, headers={"User-Agent": "GIIC research admin@giic.app"})
    try:
        tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    except Exception as e:
        return {"error": f"company_tickers: {type(e).__name__}"}
    cikmap = {row["ticker"].upper(): int(row["cik_str"]) for row in tk.values()}
    ANNUAL = ("10-K", "20-F", "40-F")
    today = _dt.date.today()

    def _d(s):
        try:
            return _dt.date.fromisoformat(str(s)[:10])
        except Exception:
            return None

    def _rows(node, concept):
        units = (node.get(concept, {}) or {}).get("units", {}) or {}
        return units

    def _annual(units):
        """(end,val,form,fy,fp,filed) para duración anual ~365d, por unidad."""
        out = {}
        for un, rows in units.items():
            pts = []
            for r in rows or []:
                s, e, form = _d(r.get("start")), _d(r.get("end")), str(r.get("form", ""))
                if r.get("val") is None or not s or not e or not any(form.startswith(p) for p in ANNUAL):
                    continue
                if 330 <= (e - s).days <= 400:
                    pts.append({"end": e.isoformat(), "val": r.get("val"), "form": form,
                                "fy": r.get("fy"), "fp": r.get("fp"), "filed": r.get("filed")})
            if pts:
                out[un] = sorted(pts, key=lambda x: x["end"])[-3:]
        return out

    def _quarterly_count(units):
        """nº de puntos trimestrales (3 meses) recientes — viabilidad de EPS TTM."""
        out = {}
        for un, rows in units.items():
            n = 0
            for r in rows or []:
                s, e = _d(r.get("start")), _d(r.get("end"))
                if r.get("val") is None or not s or not e:
                    continue
                if 80 <= (e - s).days <= 100 and e >= today - _dt.timedelta(days=550):
                    n += 1
            if n:
                out[un] = n
        return out

    def _last_instant(node, concept):
        best = None
        for un, rows in _rows(node, concept).items():
            for r in rows or []:
                e = _d(r.get("end"))
                if r.get("val") is None or not e:
                    continue
                if best is None or e > best["_e"]:
                    best = {"_e": e, "unit": un, "end": e.isoformat(), "val": r.get("val"), "filed": r.get("filed")}
        if best:
            best.pop("_e")
        return best

    def _last_annual_val(units):
        flat = []
        for un, pts in _annual(units).items():
            for p in pts:
                flat.append((p["end"], p["val"], un))
        if not flat:
            return None, None, None
        flat.sort()
        return flat[-1][1], flat[-1][0], flat[-1][2]

    def yahoo_splits(t):
        try:
            p = yc.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{t}",
                       params={"range": "6y", "interval": "1d", "events": "split"}).json()
            res = (((p or {}).get("chart", {}) or {}).get("result") or [{}])[0]
            ev = ((res.get("events", {}) or {}).get("splits", {}) or {})
            return [{"date": _dt.date.fromtimestamp(int(s["date"])).isoformat(),
                     "ratio": f'{s.get("numerator")}/{s.get("denominator")}'} for s in ev.values()]
        except Exception as e:
            return [{"_error": type(e).__name__}]

    EPS_US = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
    EPS_IFRS = ["DilutedEarningsLossPerShare", "BasicEarningsLossPerShare", "DilutedEarningsPerShare", "BasicEarningsPerShare"]
    NI_US, NI_IFRS = ["NetIncomeLoss"], ["ProfitLoss"]
    SH_DIL = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstandingAdjustment"]
    SH_BAS = ["WeightedAverageNumberOfSharesOutstandingBasic", "WeightedAverageNumberOfShareOutstandingBasicAndDiluted"]

    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"cik": None, "note": "no está en company_tickers.json"}
            continue
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                out[t] = {"cik": cik, "http_status": r.status_code}
                continue
            data = r.json()
        except Exception as e:
            out[t] = {"cik": cik, "error": f"{type(e).__name__}"}
            continue
        f = data.get("facts", {}) or {}
        gaap, ifrs, dei = f.get("us-gaap", {}) or {}, f.get("ifrs-full", {}) or {}, f.get("dei", {}) or {}
        is_ifrs = bool(ifrs) and not any(c in gaap for c in NI_US)
        node = ifrs if is_ifrs else gaap
        eps_names = EPS_IFRS if is_ifrs else EPS_US
        ni_names = NI_IFRS if is_ifrs else NI_US

        eps_detail = {c: {"annual": _annual(_rows(node, c)), "quarterly_3m_recent": _quarterly_count(_rows(node, c))}
                      for c in eps_names if _rows(node, c)}
        ni_val, ni_end, ni_unit = None, None, None
        for c in ni_names:
            v, e, u = _last_annual_val(_rows(node, c))
            if v is not None:
                ni_val, ni_end, ni_unit = v, e, u
                break
        # EPS diluido anual (preferir el primer concepto diluido con datos)
        eps_val, eps_end = None, None
        for c in eps_names:
            v, e, _ = _last_annual_val(_rows(node, c))
            if v is not None:
                eps_val, eps_end = v, e
                break
        # Dónde vive el dato reciente: TODOS los conceptos con net income / EPS / revenue
        # y su último ANUAL (revela si MA usa otra etiqueta para NI reciente, o V para EPS).
        income_latest = {}
        for cn, cnode in node.items():
            cl = cn.lower()
            if not any(k in cl for k in ("netincome", "profitloss", "earningspershare",
                                         "revenue", "incomeloss", "earningsloss")):
                continue
            v, e, u = _last_annual_val(_rows(node, cn))
            if v is not None:
                income_latest[cn] = {"end": e, "val": v, "unit": u}
        # ordenar por fecha fin desc para leer rápido
        income_latest = dict(sorted(income_latest.items(), key=lambda kv: kv[1]["end"], reverse=True)[:18])

        entity_sh = _last_instant(dei, "EntityCommonStockSharesOutstanding")
        wdil_val, wdil_end, _ = _last_annual_val(_rows(node, SH_DIL[0]))
        wbas_val, wbas_end, _ = _last_annual_val(_rows(node, SH_BAS[0]))

        def ratio(sh):
            if eps_val and sh and ni_val:
                return round(eps_val * sh / ni_val, 4)
            return None

        last_annual_date = _d(eps_end) or _d(ni_end)
        age = (today - last_annual_date).days if last_annual_date else None
        out[t] = {
            "cik": cik, "entity": data.get("entityName"),
            "taxonomy": "ifrs-full" if is_ifrs else "us-gaap",
            "ni_unit_currency": ni_unit,
            "eps_concepts": eps_detail,
            "eps_diluted_annual_latest": {"val": eps_val, "end": eps_end},
            "net_income_annual_latest": {"val": ni_val, "end": ni_end, "unit": ni_unit},
            "shares_entity_coverpage": entity_sh,
            "shares_weighted_diluted_annual": {"val": wdil_val, "end": wdil_end},
            "shares_weighted_basic_annual": {"val": wbas_val, "end": wbas_end},
            "consistency_eps_x_shares_over_ni": {
                "using_coverpage_shares (actual/bug)": ratio(entity_sh["val"] if entity_sh else None),
                "using_weighted_diluted (correcto)": ratio(wdil_val),
                "ok_if_near_1.0": True,
            },
            "last_annual_age_days": age,
            "stale_gt_400d": (age is not None and age > 400),
            "splits_6y_yahoo": yahoo_splits(t),
            "income_concepts_latest_annual": income_latest,
        }
    return out


def main(argv=None):
    try:
        out = run()
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-800:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
