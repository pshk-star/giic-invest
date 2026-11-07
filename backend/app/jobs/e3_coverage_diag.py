"""E3 — DIAGNÓSTICO de cobertura para Fair Value (solo lectura). No desarrolla extractores.

Mide, sobre la batería de 76 instrumentos, la presencia REAL de los campos que Fair Value necesita
(ingresos, utilidad operativa, utilidad neta, EPS, acciones diluidas, flujo operativo, CAPEX, FCF,
deuda, efectivo; anual y TTM) usando SÓLO EDGAR gratuito, y CLASIFICA cada hueco por causa raíz y
recuperabilidad:
  - dimensional_candidato : el concepto NO está en las APIs agregadas (companyfacts/companyconcept)
                            pero el emisor es operativo y grande → probable XBRL dimensional del
                            10-K (p. ej. EPS por clase). Recuperable con extractor dimensional (E3).
  - interino_no_tagueado  : hay anual pero no TTM (6-K/20-F sin XBRL interino). No recuperable gratis.
  - desactualizado        : el concepto existe pero el último corte es viejo (>400d).
  - bloqueado             : marcado por el guard de plausibilidad (p. ej. MU). Se mantiene bloqueado.
  - no_aplica             : vehículo (ETF/trust). El campo no corresponde.
  - ausente               : el emisor no taguea el concepto en ninguna variante.

Además hace una CONFIRMACIÓN dimensional dirigida (Visa, GOOGL) parseando el XBRL inline del último
10-K para demostrar que EPS/acciones por CLASE existen y son recuperables — evidencia para el plan,
no el extractor final.

Uso: python -m app.jobs.e3_coverage_diag   (requiere EDGAR_USER_AGENT; httpx + pandas)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import date, datetime

from app.core.normalize import (US_GAAP_MAP, IFRS_MAP, _at, _best_annual, _best_instant,
                                 _currency_for, _ttm_best, _annual_points, _concept, ttm_flow)
from app.providers.edgar import parse_companyfacts
from app.services.identity import resolve_identity
from app.jobs.coverage_battery import UNIVERSE, ADR_SEED, FX

# Campos Fair Value → (grupo de conceptos, tipo). "flow"=duración (anual+TTM); "instant"=balance.
FV_FLOW = {"revenue": "rev", "operating_income": "op_income", "net_income": "ni",
           "ocf": "ocf", "capex": "capex"}
FV_INSTANT = {"cash": "cash"}        # efectivo; la deuda se arma aparte


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _pick_tax(facts):
    """Detecta (taxonomía, moneda, mapa) con datos anuales reales (us-gaap o ifrs-full)."""
    for tax, M in (("us-gaap", US_GAAP_MAP), ("ifrs-full", IFRS_MAP)):
        c = _currency_for(facts, tax, M["rev"] + M["ni"] + M["equity"])
        if not c:
            continue
        if _best_annual(facts, tax, M["rev"], c) or _best_annual(facts, tax, M["ni"], c):
            return tax, c, M
    return "us-gaap", "USD", US_GAAP_MAP


def _ref_period(facts, tax, M, ccy):
    eps = _best_annual(facts, tax, M["eps"], f"{ccy}/shares")
    ni = _best_annual(facts, tax, M["ni"], ccy)
    rev = _best_annual(facts, tax, M["rev"], ccy)
    for pts in (eps, ni, rev):
        if pts:
            return pts[-1][0]
    return None


def _concept_present_any(facts, tax, names, unit):
    """¿El emisor taguea el concepto en ALGUNA variante/período (aunque sea viejo)?"""
    return bool(_best_annual(facts, tax, names, unit) or _best_instant(facts, tax, names, unit))


def _fieldstate(annual_ok, ttm_ok, present_any, is_instant, stale):
    if annual_ok and (is_instant or ttm_ok):
        return "completo"
    if annual_ok and not ttm_ok and not is_instant:
        return "solo_anual"
    if present_any and stale:
        return "desactualizado"
    if present_any:
        return "parcial"
    return "ausente"


def diag_ticker(facts, ticker, sic, sic_desc, itype):
    f = parse_companyfacts(facts, ticker, price=None, instrument_type=itype, sic=sic, sic_desc=sic_desc,
                           adr_ratio=ADR_SEED.get(ticker.upper(), 1.0), fx_map=FX)
    if f.data_quality in ("no_aplica", "indeterminado"):
        return {"instrument_class": f.instrument_class, "data_quality": f.data_quality, "fields": {}}
    tax, ccy, M = _pick_tax(facts)
    ref = _ref_period(facts, tax, M, ccy)
    fields = {}
    # flujos (anual + TTM)
    for name, key in FV_FLOW.items():
        ann = _at(_best_annual(facts, tax, M[key], ccy), ref) is not None
        if key == "capex":
            ann = ann or _at(_best_annual(facts, tax, M.get("capex_alt", []), ccy), ref) is not None
        ttmd = _ttm_best(facts, tax, M[key], ccy) or (_ttm_best(facts, tax, M.get("capex_alt", []), ccy) if key == "capex" else None)
        ttm_ok = bool(ttmd and "YTD" in ttmd.get("window", ""))
        present_any = _concept_present_any(facts, tax, M[key], ccy)
        fields[name] = _fieldstate(ann, ttm_ok, present_any, False, False)
    # EPS (unidad ccy/shares) y acciones diluidas (shares)
    eps_ann = _at(_best_annual(facts, tax, M["eps"], f"{ccy}/shares"), ref) is not None or \
        bool(_best_annual(facts, tax, M["eps"], "USD/shares"))
    eps_concept_any = _concept_present_any(facts, tax, M["eps"], f"{ccy}/shares") or \
        _concept_present_any(facts, tax, M["eps"], "USD/shares")
    fields["eps"] = ("completo" if (f.eps_ttm is not None) else ("solo_anual" if eps_ann else
                     ("ausente_agregado" if not eps_concept_any else "parcial")))
    sh_ann = _at(_best_annual(facts, tax, M.get("wdil", []), "shares"), ref) is not None
    sh_any = _concept_present_any(facts, tax, M.get("wdil", []), "shares")
    fields["diluted_shares"] = ("completo" if sh_ann else ("ausente_agregado" if not sh_any else "parcial"))
    # FCF (anual + TTM) y deuda neta (derivados que ya calcula el parser)
    fields["fcf_annual"] = "completo" if f.fcf_annual is not None else "ausente"
    fields["fcf_ttm"] = "completo" if f.fcf_ttm is not None else "ausente"
    fields["net_debt"] = "completo" if f.net_debt is not None else ("parcial" if (f.gross_debt is not None or f.cash_and_sti is not None) else "ausente")
    fields["cash"] = "completo" if f.cash_and_sti is not None else "ausente"
    fields["gross_debt"] = "completo" if f.gross_debt is not None else "ausente"
    return {"instrument_class": f.instrument_class, "data_quality": f.data_quality,
            "taxonomy": tax, "currency": ccy, "ref": ref.isoformat() if ref else None,
            "eps_ttm_recuperado": f.eps_ttm is not None, "fields": fields}


# ---- Confirmación dimensional (XBRL inline del último 10-K) ----
def _latest_10k_instance(cli, cik):
    """URL del documento principal (inline XBRL) del último 10-K."""
    j = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
    recent = j.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    for i, fm in enumerate(forms):
        if fm == "10-K":
            acc = recent["accessionNumber"][i].replace("-", "")
            doc = recent["primaryDocument"][i]
            return f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
    return None


def dimensional_probe(cli, cikmap, tickers):
    """Parsea el XBRL inline del último 10-K y detecta hechos de EPS diluido / acciones diluidas
    con DIMENSIONES (clases accionarias) → confirma recuperabilidad por extractor dimensional."""
    out = {}
    concepts = ("EarningsPerShareDiluted", "WeightedAverageNumberOfDilutedSharesOutstanding")
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"error": "sin CIK"}
            continue
        try:
            url = _latest_10k_instance(cli, cik)
            time.sleep(0.15)
            if not url:
                out[t] = {"error": "sin 10-K"}
                continue
            html = cli.get(url).text
            # Contextos con dimensión (explicitMember) = desglose por clase/segmento.
            dim_ctx = set()
            for cid, body in re.findall(r'<(?:xbrli:)?context\s+id="([^"]+)"[^>]*>(.*?)</(?:xbrli:)?context>',
                                        html, re.S | re.I):
                if "explicitmember" in body.lower():
                    dim_ctx.add(cid)
            # Hechos ix:nonFraction por concepto (atributos en cualquier orden, case-insensitive).
            tags = re.findall(r'<ix:nonfraction\b[^>]*>', html, re.I)
            res = {}
            for c in concepts:
                ctxrefs = []
                for tag in tags:
                    nm = re.search(r'name="([^"]+)"', tag, re.I)
                    if not nm or not nm.group(1).lower().endswith(c.lower()):
                        continue
                    cx = re.search(r'contextref="([^"]+)"', tag, re.I)
                    if cx:
                        ctxrefs.append(cx.group(1))
                dim_hits = [cx for cx in ctxrefs if cx in dim_ctx]
                res[c] = {"hechos_totales": len(ctxrefs), "con_dimension": len(dim_hits),
                          "solo_dimensional": len(ctxrefs) > 0 and len(dim_hits) == len(ctxrefs),
                          "clases_dimension_ejemplo": sorted(set(dim_hits))[:4]}
            out[t] = {"url_10k": url, "n_contextos_dimensionales": len(dim_ctx), "conceptos": res}
            time.sleep(0.2)
        except Exception as e:
            out[t] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out


# ---- Sonda de CAUSA del TTM faltante (no suponer: medir) ----
def _dur_summary(facts, tax, names, ccy):
    """Resumen de hechos de DURACIÓN del mejor concepto: conteos anual/interino, últimos cortes,
    y el resultado de ttm_flow (ventana). Permite ver por qué NO se cierra el TTM."""
    best_rows, best_name = [], None
    for n in names:
        rows = _concept(facts, tax, n, ccy)
        durs = [(_parse_date(r.get("start")), _parse_date(r.get("end")), r.get("val"), r.get("form"), r.get("filed"))
                for r in rows if _parse_date(r.get("start")) and _parse_date(r.get("end")) and r.get("val") is not None]
        if len(durs) > len(best_rows):
            best_rows, best_name = durs, n
    annual = [d for d in best_rows if 330 <= (d[1] - d[0]).days <= 400]
    interim = [d for d in best_rows if 60 <= (d[1] - d[0]).days <= 300]
    tf = ttm_flow(_concept(facts, tax, best_name, ccy)) if best_name else None
    latest_annual = max((d[1] for d in annual), default=None)
    latest_interim = max((d[1] for d in interim), default=None)
    # Verdicto de causa.
    if not best_rows:
        causa = "ausente_en_edgar"
    elif tf and "YTD" in tf.get("window", ""):
        causa = "recuperable_TTM"
    elif latest_interim is None or (latest_annual and latest_interim <= latest_annual):
        causa = "ultimo_es_anual (TTM=anual; no expuesto por exigir ventana YTD)"
    elif interim:
        causa = "disponible_no_recuperado (hay interinos; la identidad rodante no cierra)"
    else:
        causa = "indeterminado"
    return {"concepto": best_name, "n_anual": len(annual), "n_interino": len(interim),
            "ultimo_anual": latest_annual.isoformat() if latest_annual else None,
            "ultimo_interino": latest_interim.isoformat() if latest_interim else None,
            "ttm_flow_window": (tf or {}).get("window"), "causa": causa}


def ttm_cause_probe(cli, cikmap, tickers):
    """Para cada ticker, clasifica por qué falta el TTM en NI/OCF/CAPEX: ausente en EDGAR vs
    disponible-no-recuperado vs último-es-anual vs rechazado-por-calidad. NO supone la causa."""
    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"error": "sin CIK"}
            continue
        try:
            facts = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
            time.sleep(0.12)
        except Exception as e:
            out[t] = {"error": type(e).__name__}
            continue
        tax, ccy, M = _pick_tax(facts)
        dq = parse_companyfacts(facts, t, price=None).data_quality
        out[t] = {"taxonomy": tax, "currency": ccy, "data_quality": dq,
                  "net_income": _dur_summary(facts, tax, M["ni"], ccy),
                  "ocf": _dur_summary(facts, tax, M["ocf"], ccy),
                  "capex": _dur_summary(facts, tax, M["capex"], ccy)}
    return out


def e31_value_check(cli, cikmap, tickers):
    """Validación independiente del VALOR de E3.1: el eps_ttm (=anual) expuesto debe coincidir con el
    EPS diluido anual que la SEC publica en su endpoint `companyconcept` (fuente oficial separada del
    camino de parseo). Confirma que no hay distorsión de unidad/FX/ADR. Reporta diferencia relativa."""
    out = {}
    for t in tickers:
        cik = cikmap.get(t.upper())
        if not cik:
            out[t] = {"error": "sin CIK"}; continue
        try:
            facts = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
            time.sleep(0.12)
            f = parse_companyfacts(facts, t, price=None)
            cc = cli.get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/us-gaap/EarningsPerShareDiluted.json")
            time.sleep(0.12)
            official = None
            if cc.status_code == 200:
                rows = cc.json().get("units", {}).get("USD/shares", [])
                ann = [r for r in rows if str(r.get("form", "")).startswith("10-K")
                       and r.get("start") and r.get("end")
                       and 330 <= (_parse_date(r["end"]) - _parse_date(r["start"])).days <= 400]
                if ann:
                    official = max(ann, key=lambda r: r["end"])  # último anual
            off_val = official["val"] if official else None
            diff = (abs(f.eps_ttm - off_val) / abs(off_val)) if (f.eps_ttm is not None and off_val) else None
            out[t] = {"eps_ttm_expuesto": f.eps_ttm, "eps_annual_expuesto": f.eps_annual,
                      "eps_window": f.eps_ttm_window, "eps_diluido_oficial_SEC": off_val,
                      "periodo_oficial": official["end"] if official else None,
                      "diferencia_relativa": round(diff, 6) if diff is not None else None,
                      "coincide": (diff is not None and diff < 0.005)}
        except Exception as e:
            out[t] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    return out


def e32_dimensional_validation(cli, cikmap, ua, tickers):
    """E3.2 — valida el extractor dimensional: recupera EPS/acciones diluidas por CLASE desde el 10-K
    y reconcilia la clase principal contra la utilidad neta AGREGADA oficial (EPS×acciones ≈ NI).
    No combina clases. Para Visa (sólo dimensional) es la prueba de que el valor es correcto."""
    from app.core.connectors.adapters import EdgarDimensionalConnector
    conn = EdgarDimensionalConnector(user_agent=ua)
    out = {}
    got = conn.fetch(tickers)
    for t in tickers:
        cik = cikmap.get(t.upper())
        fm = got.get(t, {})
        eps_bc = fm.get("eps_diluted_by_class")
        sh_bc = fm.get("diluted_shares_by_class")
        rec = {"eps_por_clase": eps_bc.value if eps_bc else None,
               "acciones_por_clase": sh_bc.value if sh_bc else None,
               "procedencia": eps_bc.provenance if eps_bc else None}
        # Reconciliación contra NI agregado oficial (companyfacts).
        try:
            facts = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json").json()
            tax, ccy, M = _pick_tax(facts)
            ni = _at(_best_annual(facts, tax, M["ni"], ccy), _ref_period(facts, tax, M, ccy))
            rec["ni_agregado_oficial"] = ni
            if eps_bc and sh_bc and ni:
                # Clase principal = la de mayor número de acciones (base as-converted).
                classes = {k: sh_bc.value[k]["value"] for k in sh_bc.value if sh_bc.value[k]["value"]}
                if classes:
                    main = max(classes, key=classes.get)
                    eps_m = (eps_bc.value.get(main) or {}).get("value")
                    sh_m = classes[main]
                    if eps_m and sh_m:
                        implied = eps_m * sh_m
                        rec["clase_principal"] = main
                        rec["implied_NI(EPS_clase×acciones_clase)"] = implied
                        rec["reconciliacion_vs_NI"] = round(implied / ni, 4)
                        rec["cuadra_5pct"] = abs(implied / ni - 1.0) < 0.05
        except Exception as e:
            rec["error_reconciliacion"] = f"{type(e).__name__}: {str(e)[:80]}"
        out[t] = rec
        time.sleep(0.2)
    return out


def run() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=40.0, headers={"User-Agent": ua}, follow_redirects=True)
    tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    cikmap = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}

    corp_cats = ["us_large", "us_mid_small", "multi_class", "recent_splits", "financials", "adr_ifrs", "regression"]
    per_ticker = {}
    cat_of = {t: c for c, ts in UNIVERSE.items() for t in ts}
    for t in [x for ts in UNIVERSE.values() for x in ts]:
        cik = cikmap.get(t.upper())
        if not cik:
            per_ticker[t] = {"category": cat_of[t], "nota": "sin CIK (ETF/fondo sin companyfacts)"}
            continue
        sic, sic_desc = None, None
        try:
            js = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json").json()
            _s = js.get("sic"); sic = int(_s) if _s not in (None, "") else None
            sic_desc = js.get("sicDescription")
        except Exception:
            pass
        time.sleep(0.12)
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                per_ticker[t] = {"category": cat_of[t], "nota": f"companyfacts {r.status_code}"}
                time.sleep(0.12); continue
            facts = r.json()
            itype = resolve_identity(t).get("instrument_type")
            d = diag_ticker(facts, t, sic, sic_desc, itype)
            d["category"] = cat_of[t]
            per_ticker[t] = d
        except Exception as e:
            per_ticker[t] = {"category": cat_of[t], "error": f"{type(e).__name__}: {str(e)[:100]}"}
        time.sleep(0.12)

    # Cobertura por campo sobre EMPRESAS OPERATIVAS con fundamentales.
    op = [t for t, d in per_ticker.items() if d.get("fields") and cat_of[t] in corp_cats
          and d.get("data_quality") not in ("no_aplica", "indeterminado")]
    all_fields = ["revenue", "operating_income", "net_income", "eps", "diluted_shares",
                  "ocf", "capex", "fcf_annual", "fcf_ttm", "net_debt", "cash", "gross_debt"]
    GOOD = {"completo"}

    def cov(field):
        n = len(op) or 1
        return round(sum(1 for t in op if per_ticker[t]["fields"].get(field) in GOOD) / n, 3)

    cobertura = {f: cov(f) for f in all_fields}
    # Huecos por campo (estado != completo) en operativas.
    huecos = {}
    for f in all_fields:
        g = {t: per_ticker[t]["fields"].get(f) for t in op if per_ticker[t]["fields"].get(f) not in GOOD}
        if g:
            huecos[f] = g

    # Probe dimensional dirigido (evidencia de recuperabilidad).
    dim = dimensional_probe(cli, cikmap, ["V", "GOOGL", "MA"])
    # Sonda de causa del TTM faltante: fallan (AAPL/AMZN/COST/C) vs funcionan (MSFT/NVDA/META).
    ttm_causas = ttm_cause_probe(cli, cikmap, ["AAPL", "AMZN", "COST", "C", "MSFT", "NVDA", "META"])
    # Validación de VALOR E3.1 contra el endpoint oficial companyconcept de la SEC.
    e31_val = e31_value_check(cli, cikmap, ["AAPL", "AMZN", "COST", "C", "WMT", "HD"])
    # Validación E3.2: extractor dimensional por clase + reconciliación contra NI agregado.
    e32_val = e32_dimensional_validation(cli, cikmap, ua, ["V", "GOOGL"])

    return {
        "n_operativas_con_fundamentales": len(op),
        "cobertura_fair_value(operativas)": cobertura,
        "huecos_por_campo": huecos,
        "bloqueados": {t: d.get("data_quality") for t, d in per_ticker.items() if d.get("data_quality") == "bloqueado"},
        "confirmacion_dimensional(V/GOOGL/MA)": dim,
        "ttm_causas_muestra": ttm_causas,
        "e31_validacion_valor_vs_SEC": e31_val,
        "e32_validacion_dimensional": e32_val,
        "por_ticker": per_ticker,
    }


def main(argv=None):
    try:
        print(json.dumps(run(), indent=2, default=str, ensure_ascii=False))
        return 0
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
