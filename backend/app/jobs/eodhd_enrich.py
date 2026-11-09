"""P0.2 — Enriquecimiento productivo de fundamentales EODHD sobre el ancla oficial EDGAR.

Orquesta la obtención de datos y DELEGA toda la decisión de calidad/precedencia/cuarentena en
`app.core.connectors.fundamentals_enrich.enrich_fundamentals` (única implementación, compartida con
la evaluación). No reimplementa reglas. No escribe en Supabase ni toca el ranking/predicciones.

Modo DRY-RUN (`--dry-run`, por defecto): compara el payload de fundamentales ACTUAL (EDGAR, lo que
hoy ve la UI) con el ENRIQUECIDO (EDGAR + EODHD), sin modificar nada. Reporta por instrumento: campos
nuevos usables, fuente/período/estado, campos rechazados o en cuarentena, diferencias respecto del
payload anterior y consumo real de API (medido contra el endpoint /api/user de EODHD).

Controles (precisiones del usuario):
  - EDGAR es el ancla oficial; EODHD complementa. No sobrescribe EDGAR vigente y verificado.
  - Vehículos (ETF/trust): EODHD NO se consulta (no_aplica) → control de costo.
  - Si no hay clave EODHD o el conector falla, el resultado es el payload EDGAR actual (sin cambios).
  - Las acciones diluidas nunca provienen de EODHD; FCF/net_debt no se fabrican.
  - Períodos, moneda, procedencia y estado por campo se conservan; anual y TTM no se mezclan.

Uso:
    EODHD_API_KEY + EDGAR_USER_AGENT en env
    python -m app.jobs.eodhd_enrich --dry-run                 # set representativo por defecto
    python -m app.jobs.eodhd_enrich --dry-run --tickers AAPL,META,ASML
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import date

from app.providers.edgar import EDGARProvider, parse_companyfacts
from app.services.identity import resolve_identity
from app.core.recency import assess_recency
from app.core.connectors.eodhd import EodhdFundamentalsConnector
from app.core.connectors.fundamentals_enrich import edgar_annual_series, enrich_fundamentals
from app.jobs.coverage_battery import ADR_SEED, FX
from app.jobs.e3_coverage_diag import _pick_tax, _ref_period
from app.jobs.e3_final_eval import _submissions_recency, _fiscal_cadence, build_edgar_states
from app.jobs.eodhd_ab_eval import _data_end

# Set representativo obligatorio del dry-run (precisión 4): US core, ADR/IFRS, banco y ETF.
DEFAULT_SET = ["AAPL", "META", "ASML", "TSM", "XOM", "JPM", "SPY"]
EODHD_UNITS_PER_FUNDAMENTALS = 10   # coste declarado por consulta de fundamentales (a verificar/medir)


def _num(d, k):
    v = (d or {}).get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ser(sect, key):
    out = {}
    for k, row in (sect or {}).items():
        v = _num(row, key)
        if v is not None:
            out[(row.get("date") or k)[:10]] = v
    return out


# Concepto EODHD por campo núcleo (para clasificar el tipo de período desde las series crudas).
_FLOW_CONCEPT = {"revenue": ("Income_Statement", "totalRevenue"),
                 "net_income": ("Income_Statement", "netIncome"),
                 "ocf": ("Cash_Flow", "totalCashFromOperatingActivities"),
                 "capex": ("Cash_Flow", "capitalExpenditures"),
                 "fcf": ("Cash_Flow", "freeCashFlow")}
_BALANCE_FIELDS = {"cash", "total_debt"}
_EPS_FIELDS = {"eps_ttm", "eps_annual"}


def field_period_types(obj: dict) -> dict:
    """Tipo de período VERIFICADO por campo EODHD, a partir de las series crudas (no de period_end).
    Flujos (revenue/ni/ocf/capex/fcf): trimestre_individual|ytd_acumulado|indeterminado. Balances
    (cash/total_debt): balance_instantaneo. Variantes _annual: anual. EPS: ttm/anual (base ambigua)."""
    from app.core.connectors.fundamentals_enrich import classify_period_type
    fin = (obj or {}).get("Financials", {}) or {}
    pt = {}
    for fld, (stmt, concept) in _FLOW_CONCEPT.items():
        q = _ser((fin.get(stmt, {}) or {}).get("quarterly", {}), concept)
        y = _ser((fin.get(stmt, {}) or {}).get("yearly", {}), concept)
        pt[fld] = classify_period_type(q, y) if (q or y) else "indeterminado"
    # FCF conservador: si OCF o CAPEX no son trimestre_individual compatibles, no lo presentamos limpio.
    if pt.get("fcf") == "indeterminado" and pt.get("ocf") == "trimestre_individual" and pt.get("capex") == "trimestre_individual":
        pt["fcf"] = "trimestre_individual"
    elif pt.get("ocf") in ("ytd_acumulado", "indeterminado") or pt.get("capex") in ("ytd_acumulado", "indeterminado"):
        pt["fcf"] = "indeterminado"
    for b in _BALANCE_FIELDS:
        pt[b] = "balance_instantaneo"
    # Variantes anuales y de balance de cierre.
    for base in ("revenue", "net_income", "ocf", "capex", "fcf"):
        pt[f"{base}_annual"] = "anual"
    for b in _BALANCE_FIELDS:
        pt[f"{b}_annual"] = "balance_instantaneo"
    pt["eps_ttm"] = "ttm"
    pt["eps_annual"] = "anual"
    return pt


def annotate_valuation(enriched: dict, period_types: dict) -> dict:
    """Anota cada campo enriquecido con period_type y valuation_eligible (regla financiera verificada).
    Un interino de un solo trimestre o YTD NO es apto para valoración; sí los anuales, TTM y saldos de
    balance; EPS de EODHD nunca (base ambigua)."""
    from app.core.connectors.fundamentals_enrich import valuation_eligible
    for name, info in enriched.items():
        ptype = period_types.get(name, "indeterminado")
        amb = name in _EPS_FIELDS
        info["period_type"] = ptype
        info["valuation_eligible"] = bool(info.get("usable") and valuation_eligible(ptype, eps_base_ambigua=amb))
        if not info["valuation_eligible"] and info.get("usable"):
            info["valuation_note"] = ("no apto para valoración directa: "
                                      + ("EPS base ambigua" if amb else f"período '{ptype}' (se requiere anual/TTM/saldo)"))
    return enriched


# Campos que EODHD puede aportar y que decide el gate (núcleo de flujo + saldos de balance).
GATE_FIELDS = ("revenue", "net_income", "ocf", "cash", "capex", "net_debt")


def should_query_eodhd(edgar_states: dict, needed=GATE_FIELDS) -> bool:
    """Gate por disponibilidad real: consultar EODHD si ALGÚN campo requerido no está vigente en
    EDGAR (faltante / presente_no_vigente / bloqueado). Si todos están 'vigente' o 'no_aplica'
    (el emisor no los reporta), EDGAR es suficiente y NO se consulta EODHD."""
    for fld in needed:
        st = edgar_states.get(fld, "faltante")
        if st in ("faltante", "presente_no_vigente", "bloqueado"):
            return True
    return False


def classify_enriched(enriched: dict, edgar_payload: dict):
    """Clasifica el resultado de enrich_fundamentals para el reporte y calcula el diff contra el
    payload EDGAR ACTUAL. Pura (sin red): cuarentena (inconsistente), nuevos usables, rechazados, y
    diferencias (si el campo usable llena un hueco de EDGAR o lo complementa)."""
    from app.core.connectors.fundamentals_enrich import _COUNTERPART
    nuevos, cuarentena, rechazados = {}, {}, {}
    for name, info in enriched.items():
        if info["state"] == "inconsistente":
            cuarentena[name] = info
        elif info["usable"]:
            nuevos[name] = info
        else:
            rechazados[name] = info
    diffs = {}
    for name, info in nuevos.items():
        cp = _COUNTERPART.get(name, name)
        edgar_val = (edgar_payload or {}).get(cp, None)
        diffs[name] = {"contraparte_edgar": cp, "edgar_actual": edgar_val,
                       "eodhd_valor": info["value"], "estado": info["state"], "periodo": info["period"],
                       "tipo": "nuevo (EDGAR vacío)" if edgar_val is None else "complementa (EDGAR presente)"}
    return nuevos, cuarentena, rechazados, diffs


def eodhd_user_info(key: str) -> dict:
    """Consulta /api/user: límites y consumo REALES del plan (verificación, no supuesto)."""
    import httpx
    try:
        r = httpx.get("https://eodhd.com/api/user", params={"api_token": key, "fmt": "json"}, timeout=20.0)
        if r.status_code == 200:
            j = r.json()
            return {"apiRequests": j.get("apiRequests"), "dailyRateLimit": j.get("dailyRateLimit"),
                    "apiRequestsDate": j.get("apiRequestsDate"), "name": j.get("name"), "extraLimit": j.get("extraLimit")}
        return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": type(e).__name__}


def enrich_one(prov: EDGARProvider, conn, t: str, eval_date: date) -> dict:
    """Prepara EDGAR (ancla), construye edgar_states con la lógica del eval, consulta EODHD (si
    aplica) y delega en enrich_fundamentals. Devuelve el bloque de comparación para el dry-run."""
    facts = prov._facts(t)
    if facts is None:
        return {"ticker": t, "status": "sin_edgar", "eodhd_called": False}
    cik = prov._cik.get(t.upper())
    lag, latest_report, sic = _submissions_recency(prov._client, cik)
    try:
        itype = resolve_identity(t).get("instrument_type")
    except Exception:
        itype = None
    f = parse_companyfacts(facts, t, price=None, instrument_type=itype, sic=sic,
                           adr_ratio=ADR_SEED.get(t.upper(), 1.0), fx_map=FX)

    # Vehículos (ETF/trust) u otros no operativos: NO se consulta EODHD (control de costo).
    if f.data_quality in ("no_aplica", "indeterminado"):
        return {"ticker": t, "status": "no_aplica", "instrument_class": f.instrument_class,
                "edgar_data_quality": f.data_quality, "eodhd_called": False,
                "nota": "vehículo/no operativo: EDGAR marca no_aplica; EODHD no se consulta"}

    tax, ccy, M = _pick_tax(facts)
    ref = _ref_period(facts, tax, M, ccy)
    cadence = _fiscal_cadence(facts, tax, M, ccy)
    data_end = _data_end(facts, tax, M, ccy, f)
    series = edgar_annual_series(facts, tax, M, ccy)
    later = bool(latest_report and data_end and (latest_report - data_end).days > 20)
    rec = assess_recency(data_end, eval_date, cadence_days=cadence, lag_days=lag,
                         later_report_exists=later, window=f.eps_ttm_window)
    blocked = f.data_quality == "bloqueado"

    edgar_states = build_edgar_states(facts, tax, M, ref, f, sic, blocked, rec["estado"])
    # Alias EPS: EDGAR lleva estado 'eps' (anual); el conector emite eps_ttm/eps_annual.
    edgar_states["eps_ttm"] = edgar_states.get("eps_ttm") or edgar_states.get("eps", "faltante")
    edgar_states["eps_annual"] = edgar_states.get("eps", "faltante")

    # Gate de costo POR DISPONIBILIDAD REAL de campos (no sólo por vigencia del ejercicio anual):
    # si EDGAR ya cubre y tiene vigentes TODOS los campos núcleo/balance, EODHD no aporta → no se
    # consulta (ahorro de API). Basta que falte o esté no-vigente uno para justificar la consulta.
    if not should_query_eodhd(edgar_states):
        return {"ticker": t, "status": "edgar_suficiente", "eodhd_called": False,
                "edgar_vigencia": rec["estado"], "edgar_data_end": data_end.isoformat() if data_end else None,
                "nota": "EDGAR vigente en todos los campos núcleo/balance; EODHD no se consulta"}

    # EODHD: una consulta por instrumento (el conector resuelve símbolo/ADR y cachea).
    eodhd_called = False
    fm = {}
    try:
        got = conn.fetch([t]) or {}
        eodhd_called = True
        fm = got.get(t, {}) or {}
    except Exception as e:
        return {"ticker": t, "status": "eodhd_error", "error": str(e)[:100], "eodhd_called": True}

    eo_ccy = next((pf.currency for pf in fm.values() if getattr(pf, "currency", None)), None)
    same_ccy = bool(eo_ccy and eo_ccy.upper() == (ccy or "").upper())
    enriched = enrich_fundamentals(fm, series, data_end, same_ccy, edgar_states)

    # Tipo de período VERIFICADO + elegibilidad para valoración (precisión 1). obj cacheado (sin red extra).
    try:
        _sym, _adr, obj = conn._resolve(t)
    except Exception:
        obj = None
    period_types = field_period_types(obj) if obj else {}
    enriched = annotate_valuation(enriched, period_types)
    eodhd_symbol = _sym if obj else None

    edgar_payload = asdict(f)   # lo que HOY se escribe en Supabase y ve la UI (no se modifica)
    nuevos, cuarentena, rechazados, diffs = classify_enriched(enriched, edgar_payload)

    enrichment_block = build_enrichment_block(
        t, eodhd_symbol, eo_ccy, data_end.isoformat() if data_end else None, enriched)

    return {
        "ticker": t, "status": "ok", "eodhd_called": eodhd_called,
        "moneda_edgar": ccy, "moneda_eodhd": eo_ccy, "misma_moneda": same_ccy,
        "eodhd_symbol": eodhd_symbol,
        "edgar_data_end": data_end.isoformat() if data_end else None,
        "edgar_vigencia": rec["estado"], "segmento_sic": sic,
        "campos_nuevos_usables": nuevos, "cuarentena_inconsistente": cuarentena,
        "campos_rechazados": rechazados, "diferencias_vs_payload_actual": diffs,
        "edgar_states": edgar_states, "enrichment_block": enrichment_block,
    }


# --- Esquema aditivo de Supabase y hook de escritura (aislado, sin tocar producción) ---

ENRICHMENT_SCHEMA_VERSION = "p0.3-1"


def build_enrichment_block(ticker: str, symbol, currency, edgar_data_end, enriched: dict) -> dict:
    """Bloque ADITIVO para fundamentals.payload.enrichment. Cada métrica lleva valor, moneda,
    fuente+símbolo, fecha de cierre, tipo de período, estado de calidad y elegibilidad de valoración.
    NO altera los campos EDGAR (viven en el nivel superior del payload)."""
    fields, quarantine = {}, {}
    for name, info in enriched.items():
        if info.get("value") is None:
            continue
        rec = {
            "value": info["value"],
            "currency": info.get("currency"),
            "source": info.get("source"),
            "symbol": symbol,
            "period_end": info.get("period"),
            "period_type": info.get("period_type"),
            "quality_state": info["state"],
            "usable_recency": bool(info.get("usable")),
            "valuation_eligible": bool(info.get("valuation_eligible")),
        }
        if info.get("valuation_note"):
            rec["valuation_note"] = info["valuation_note"]
        # Cuarentena: los inconsistentes se CONSERVAN (auditoría) en un bloque aparte y NUNCA en
        # 'fields' (nunca usables). valuation_eligible/verified aquí son orthogonales: 'fields' puede
        # tener datos elegibles por período pero sólo 'parcial' (no verificados) — la valoración
        # aplica sus propios controles además de valuation_eligible.
        if info["state"] == "inconsistente":
            quarantine[name] = rec
        else:
            fields[name] = rec
    return {
        "schema_version": ENRICHMENT_SCHEMA_VERSION,
        "source": "EODHD Fundamentals Data Feed",
        "symbol": symbol,
        "currency": currency,
        "edgar_data_end": edgar_data_end,
        "valuation_eligible_meaning": ("período/definición apto para valoración; NO implica "
                                       "verificación: revisar quality_state y controles de Fair Value"),
        "fields": fields,
        "quarantine": quarantine,
    }


def attach_enrichment(edgar_payload: dict, enrichment_block, enabled: bool = True,
                      prev_block=None) -> dict:
    """Combina el payload EDGAR actual con el bloque de enriquecimiento, de forma ADITIVA e
    IDEMPOTENTE. Protección contra sobrescritura: NUNCA modifica un campo EDGAR existente; sólo fija
    la clave 'enrichment'. `enabled=False` → payload EDGAR intacto (fail-safe).

    PRESERVACIÓN ENTRE SCANS (carry-forward): si en este scan no hay bloque fresco (EODHD caído,
    sin clave o gate), pero existe uno previo (`prev_block`), se conserva marcándolo `carried_forward`
    para NO borrar el enriquecimiento ya publicado. Los campos EDGAR siempre quedan intactos."""
    out = dict(edgar_payload or {})
    if "enrichment" in (edgar_payload or {}) and not isinstance(edgar_payload.get("enrichment"), dict):
        raise ValueError("colisión: el payload EDGAR ya usa 'enrichment' con otro tipo")
    fresh = bool(enabled and enrichment_block and (enrichment_block.get("fields") or enrichment_block.get("quarantine")))
    if fresh:
        out["enrichment"] = enrichment_block
    elif prev_block and isinstance(prev_block, dict) and prev_block.get("fields"):
        carried = dict(prev_block)
        carried["carried_forward"] = True           # no se refrescó en este scan; se preserva
        out["enrichment"] = carried
    # si no hay fresco ni previo → no se añade nada (EDGAR intacto)
    return out


def build_enrich_universe(writer, scanner_tickers) -> dict:
    """Universo UNIFICADO y deduplicado de enriquecimiento con su origen. Unión de: scanner US,
    cartera (transacciones), instrumentos añadidos por Research (tabla instruments) e internacionales
    soportados por el conector (EODHD_SYMBOLS). La elegibilidad final (emisor corporativo con ancla
    EDGAR, no vehículo) la decide enrich_one por instrumento; aquí sólo se arma el conjunto y el origen."""
    from app.core.connectors.eodhd import EODHD_SYMBOLS
    origin = {}

    def add(tickers, src):
        for t in tickers or []:
            tu = str(t).upper()
            origin.setdefault(tu, []).append(src)

    add(scanner_tickers, "scanner")
    if writer is not None:
        try:
            add(writer.get_transaction_tickers(), "cartera")
        except Exception:
            pass
        try:
            rows = writer.select_rows("instruments", select="ticker", params={"order": "ticker"})
            add([r["ticker"] for r in rows if r.get("ticker")], "research/instruments")
        except Exception:
            pass
    add(list(EODHD_SYMBOLS.keys()), "internacional")
    return origin


def preserve_enrichment_blocks(payloads: dict, prev_payloads: dict) -> int:
    """PRESERVACIÓN en la capa de escritura, INDEPENDIENTE del flag. Para cada ticker cuyo payload
    nuevo (EDGAR-only, p. ej. un scan con EODHD DESACTIVADO) no trae bloque `enrichment` pero que YA
    tenía uno persistido, se arrastra el previo (carry-forward). Garantiza que un scan EDGAR-only no
    borre el enriquecimiento ya escrito. No toca los campos EDGAR ni los payloads que ya traen bloque."""
    carried = 0
    for t, p in (payloads or {}).items():
        if not isinstance(p, dict) or p.get("enrichment"):
            continue
        prev = prev_payloads.get(t) if isinstance(prev_payloads.get(t), dict) else None
        prev_block = (prev or {}).get("enrichment")
        if prev_block and isinstance(prev_block, dict) and (prev_block.get("fields") or prev_block.get("quarantine")):
            blk = dict(prev_block); blk["carried_forward"] = True
            p["enrichment"] = blk
            carried += 1
    return carried


def read_fundamentals_payloads(writer, tickers=None) -> dict:
    """Lee {ticker: payload} de 'fundamentals'. La tabla se indexa por ticker (sin columna 'id'),
    por eso se ordena por ticker; con `tickers`, filtra server-side."""
    params = {"order": "ticker"}
    if tickers:
        params["ticker"] = f"in.({','.join(t.upper() for t in tickers)})"
    try:
        rows = writer.select_rows("fundamentals", select="ticker,payload", params=params)
        return {r["ticker"].upper(): r.get("payload") for r in rows if r.get("ticker")}
    except Exception:
        return {}


def enrich_scan_payloads(payloads: dict, tickers, prev_payloads=None, eval_date=None,
                         enabled: bool = True, create_missing: bool = False) -> dict:
    """Cableado productivo (invocado por run_scan tras el ranking, flag-gated). Enriquece EN SITIO
    los payloads EDGAR con el bloque EODHD, aplicando gate de costo, carry-forward y fail-safe. NO toca
    ranking/factores/predicciones (opera sobre el payload ya calculado). Construye EDGARProvider +
    conector desde env; sin clave → no hace nada (payloads intactos).

    `create_missing`: para tickers del universo unificado que NO están en `payloads` (internacionales
    de cartera/Research fuera del scanner), se construye su payload EDGAR oficial (igual que el scan
    para un ticker de cartera) y se añade a `payloads` para que se persista. Sin ancla EDGAR → excluido."""
    ua = os.getenv("EDGAR_USER_AGENT", "")
    key = os.getenv("EODHD_API_KEY", "")
    prev_payloads = prev_payloads or {}
    eval_date = eval_date or date.today()
    summary = {"enabled": bool(enabled), "equities_evaluados": 0, "enriquecidos": 0,
               "edgar_suficiente": 0, "carry_forward": 0, "sin_edgar_o_vehiculo": 0,
               "creados_desde_edgar": 0, "sin_ancla_edgar": [], "fetches_eodhd": 0, "errores": 0, "muestra": {}}
    if not (enabled and key and ua and "@" in ua):
        summary["fail_safe"] = "sin clave/UA o deshabilitado: payloads EDGAR intactos"
        return summary

    prov = EDGARProvider(user_agent=ua)
    conn = EodhdFundamentalsConnector(api_key=key)
    for t in tickers:
        base = payloads.get(t)
        if base is None:
            if not create_missing:
                continue
            try:                                   # flujo real de cartera: construir ancla EDGAR oficial
                funds = prov.get_fundamentals([t]); f = funds.get(t)
                base = asdict(f) if f is not None else None
            except Exception:
                base = None
            if base is None:
                summary["sin_ancla_edgar"].append(t)   # internacional sin presentaciones EDGAR → se omite
                continue
            payloads[t] = base                     # se persistirá (nuevo emisor en fundamentals)
            summary["creados_desde_edgar"] += 1
        summary["equities_evaluados"] += 1
        prev_block = (prev_payloads.get(t) or {}).get("enrichment") if isinstance(prev_payloads.get(t), dict) else None
        try:
            r = enrich_one(prov, conn, t, eval_date)
        except Exception:
            summary["errores"] += 1
            # fail-safe por ticker: conserva el bloque previo si lo había
            payloads[t] = attach_enrichment(base, None, enabled=True, prev_block=prev_block)
            continue
        status = r.get("status")
        if r.get("eodhd_called"):
            summary["fetches_eodhd"] += 1
        if status == "ok":
            block = r.get("enrichment_block")
            payloads[t] = attach_enrichment(base, block, enabled=True, prev_block=prev_block)
            if block and block.get("fields"):
                summary["enriquecidos"] += 1
                flds = block["fields"]
                summary["muestra"][t] = {
                    "symbol": block.get("symbol"), "currency": block.get("currency"),
                    "n_campos": len(flds),
                    "aptos_valoracion": sorted(k for k, v in flds.items() if v.get("valuation_eligible")),
                    "solo_recencia": sorted(k for k, v in flds.items() if not v.get("valuation_eligible")),
                }
            elif prev_block:
                summary["carry_forward"] += 1
        elif status == "edgar_suficiente":
            summary["edgar_suficiente"] += 1
            payloads[t] = attach_enrichment(base, None, enabled=True, prev_block=prev_block)  # preserva previo si lo hay
            if prev_block:
                summary["carry_forward"] += 1
        else:  # sin_edgar, no_aplica, eodhd_error
            summary["sin_edgar_o_vehiculo"] += 1
            payloads[t] = attach_enrichment(base, None, enabled=True, prev_block=prev_block)
            if prev_block:
                summary["carry_forward"] += 1
    return summary


def dry_run(tickers=None, eval_date=None) -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    key = os.getenv("EODHD_API_KEY", "")
    eval_date = eval_date or date.today()
    tickers = tickers or DEFAULT_SET
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    if not key:
        # Fail-safe explícito: sin clave, el comportamiento es el actual (EDGAR-only).
        return {"error": "sin EODHD_API_KEY", "fail_safe": "sin enriquecimiento; payload = EDGAR actual"}

    prov = EDGARProvider(user_agent=ua)
    conn = EodhdFundamentalsConnector(api_key=key)
    user_before = eodhd_user_info(key)

    resultados = []
    for t in tickers:
        try:
            resultados.append(enrich_one(prov, conn, t, eval_date))
        except Exception as e:
            resultados.append({"ticker": t, "status": "error", "error": f"{type(e).__name__}: {str(e)[:120]}"})
        time.sleep(0.15)

    user_after = eodhd_user_info(key)
    llamadas_eodhd = sum(1 for r in resultados if r.get("eodhd_called"))
    delta = None
    if isinstance(user_before.get("apiRequests"), int) and isinstance(user_after.get("apiRequests"), int):
        delta = user_after["apiRequests"] - user_before["apiRequests"]

    resumen = {
        "instrumentos": len(resultados),
        "con_edgar": sum(1 for r in resultados if r.get("status") in ("ok", "no_aplica")),
        "no_aplica_vehiculo": sum(1 for r in resultados if r.get("status") == "no_aplica"),
        "enriquecidos_con_nuevos": sum(1 for r in resultados if r.get("campos_nuevos_usables")),
        "con_cuarentena": sum(1 for r in resultados if r.get("cuarentena_inconsistente")),
    }
    consumo_api = {
        "fetches_eodhd_contados": llamadas_eodhd,
        "unidades_estimadas": llamadas_eodhd * EODHD_UNITS_PER_FUNDAMENTALS,
        "apiRequests_antes": user_before.get("apiRequests"),
        "apiRequests_despues": user_after.get("apiRequests"),
        "consumo_real_medido": delta,
        "dailyRateLimit_real": user_after.get("dailyRateLimit") or user_before.get("dailyRateLimit"),
        "nota": "unidades_estimadas es referencia; consumo_real_medido es la verdad (delta /api/user)",
    }
    return {"eval_date": eval_date.isoformat(), "modo": "DRY-RUN (sin escritura en Supabase)",
            "resumen": resumen, "consumo_api": consumo_api, "resultados": resultados}


def main(argv=None):
    p = argparse.ArgumentParser(description="Dry-run de enriquecimiento EODHD (sin escribir en Supabase).")
    p.add_argument("--dry-run", action="store_true", default=True, help="comparar sin escribir (por defecto)")
    p.add_argument("--tickers", default="", help="lista separada por comas; vacío = set representativo")
    args = p.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()] or None
    out = dry_run(tickers=tickers)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
