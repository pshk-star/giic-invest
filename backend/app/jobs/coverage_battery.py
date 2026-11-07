"""E0 — Batería de cobertura REAL del Financial Data Engine (solo lectura).

Corre el motor ACTUAL (parse_companyfacts) sobre ~100 instrumentos representativos y MIDE la
cobertura por campo y por tipo, la clasificación de calidad y los errores/bloqueos — sin código
por empresa. Prueba que incorporar un ticker nuevo no requiere parches. No escribe nada.

Uso: python -m app.jobs.coverage_battery   (requiere EDGAR_USER_AGENT; httpx + pandas)
"""
from __future__ import annotations

import json
import os
import sys
import time

from app.providers.edgar import parse_companyfacts, ADR_RATIO

# Universo representativo (sectores, tamaños, US-GAAP/IFRS, ADR, multiclase, splits, ETF, trusts,
# y casos de regresión V/MU/ASML/TSM). Las categorías fijan la EXPECTATIVA (p. ej. ETF no debe
# tener fundamentales de empresa).
UNIVERSE = {
    "us_large": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "JPM", "XOM", "JNJ",
                 "WMT", "PG", "KO", "PEP", "HD", "MRK", "ABBV", "COST", "CVX", "ORCL"],
    "us_mid_small": ["ROKU", "ETSY", "CROX", "WING", "DKNG", "RIVN", "CELH", "DXCM"],
    "multi_class": ["GOOG", "FOXA", "FOX", "NWSA", "UAA"],
    "recent_splits": ["NFLX", "SHOP", "AVGO", "LRCX", "ISRG"],
    "financials": ["BAC", "WFC", "C", "GS", "MS", "AXP", "V", "MA"],
    "adr_ifrs": ["ASML", "TSM", "SAP", "TM", "SHEL", "BP", "NVO", "AZN", "BABA", "SONY",
                 "UL", "RIO", "SE", "NVS", "HSBC"],
    "etf": ["SPY", "QQQ", "VOO", "SCHD", "VTI", "IWM", "DIA", "XLF"],
    "commodity_trust": ["GLD", "SLV", "IAU", "PPLT", "PALL"],
    "regression": ["MU", "LLY"],
}

# Semillas de ADR verificables (hecho, no estimación). El resto = 1.0. Un motor universal las
# toma de la resolución de identidad; aquí basta un seed pequeño para medir cobertura.
ADR_SEED = {"TSM": 5.0, "ASML": 1.0, "SAP": 1.0, "TM": 1.0, "SHEL": 2.0, "BP": 6.0, "NVO": 1.0,
            "AZN": 2.0, "BABA": 8.0, "SONY": 1.0, "UL": 1.0, "RIO": 2.0, "NVS": 1.0, "HSBC": 5.0}

# FX aproximado SÓLO para medir cobertura (no para valoración). USD por 1 unidad de divisa.
FX = {"EUR": 1.08, "TWD": 0.031, "JPY": 0.0067, "GBP": 1.27, "DKK": 0.145, "CHF": 1.10,
      "HKD": 0.128, "CNY": 0.14, "SEK": 0.095, "AUD": 0.66, "KRW": 0.00072, "ILS": 0.27,
      "CAD": 0.73, "SGD": 0.74, "BRL": 0.18}

FIELDS = ["eps_annual", "eps_ttm", "fcf_annual", "fcf_ttm", "net_debt", "diluted_shares",
          "gross_margin", "operating_margin", "net_margin", "roe"]


def run() -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    if not ua or "@" not in ua:
        return {"error": "sin EDGAR_USER_AGENT"}
    import httpx
    cli = httpx.Client(timeout=30.0, headers={"User-Agent": ua})
    try:
        tk = cli.get("https://www.sec.gov/files/company_tickers.json").json()
    except Exception as e:
        return {"error": f"company_tickers: {type(e).__name__}"}
    cikmap = {r["ticker"].upper(): int(r["cik_str"]) for r in tk.values()}

    per_ticker = {}
    cat_of = {t: cat for cat, ts in UNIVERSE.items() for t in ts}
    all_tickers = [t for ts in UNIVERSE.values() for t in ts]

    for t in all_tickers:
        cat = cat_of[t]
        cik = cikmap.get(t.upper())
        if cik is None:
            per_ticker[t] = {"category": cat, "resolved": False,
                             "note": "sin CIK en SEC (típico de ETF/fondo: no presenta companyfacts)"}
            continue
        # SIC (señal universal de tipo de instrumento) desde submissions — para el routing.
        sic, sic_desc = None, None
        try:
            rs = cli.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
            if rs.status_code == 200:
                js = rs.json()
                _s = js.get("sic")
                sic = int(_s) if _s not in (None, "") else None
                sic_desc = js.get("sicDescription")
        except Exception:
            pass
        time.sleep(0.12)
        try:
            r = cli.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
            if r.status_code != 200:
                per_ticker[t] = {"category": cat, "resolved": True, "companyfacts": False,
                                 "http_status": r.status_code, "sic": sic, "sic_desc": sic_desc}
                time.sleep(0.12)
                continue
            facts = r.json()
        except Exception as e:
            per_ticker[t] = {"category": cat, "resolved": True, "error": type(e).__name__}
            time.sleep(0.12)
            continue
        try:
            f = parse_companyfacts(facts, t, price=None,
                                   adr_ratio=ADR_SEED.get(t.upper(), ADR_RATIO.get(t.upper(), 1.0)),
                                   fx_map=FX, sic=sic, sic_desc=sic_desc)
            present = {k: (getattr(f, k) not in (None, "")) for k in FIELDS}
            per_ticker[t] = {
                "category": cat, "resolved": True, "companyfacts": True,
                "sic": sic, "sic_desc": sic_desc, "instrument_class": f.instrument_class,
                "taxonomy": f.taxonomy, "currency": f.currency, "period_as_of": f.as_of,
                "data_quality": f.data_quality, "quality_reason": f.quality_reason,
                "eps_source": f.eps_source, "consistency_independent": f.consistency_independent,
                "present": present,
                "n_present": sum(present.values()),
            }
        except Exception as e:
            per_ticker[t] = {"category": cat, "resolved": True, "companyfacts": True,
                             "parse_error": f"{type(e).__name__}: {str(e)[:100]}"}
        time.sleep(0.12)      # respeta el límite de la SEC (~8 req/s)

    # Agregados: cobertura por campo global y por categoría; conteo por estado de calidad.
    corp_cats = ["us_large", "us_mid_small", "multi_class", "recent_splits", "financials", "adr_ifrs", "regression"]
    # Empresas operativas: con companyfacts, con campos y NO ruteadas a no_aplica (vehículos).
    corp = [t for t, d in per_ticker.items() if d.get("companyfacts") and d.get("present")
            and cat_of[t] in corp_cats and d.get("data_quality") != "no_aplica"]
    def field_cov(tickers):
        n = len(tickers) or 1
        return {k: round(sum(per_ticker[t]["present"][k] for t in tickers) / n, 3) for k in FIELDS}
    by_cat = {}
    for cat in UNIVERSE:
        # "con fundamentales" = tiene campos Y no fue ruteado a no_aplica (vehículo).
        ts = [t for t in UNIVERSE[cat] if per_ticker.get(t, {}).get("present")
              and per_ticker.get(t, {}).get("data_quality") != "no_aplica"]
        n_no_aplica = sum(1 for t in UNIVERSE[cat] if per_ticker.get(t, {}).get("data_quality") == "no_aplica")
        by_cat[cat] = {"n_con_fundamentales": len(ts), "n_total": len(UNIVERSE[cat]),
                       "n_no_aplica": n_no_aplica,
                       "cobertura_campos": field_cov(ts) if ts else {}}
    quality_counts = {}
    for d in per_ticker.values():
        q = d.get("data_quality", "sin_companyfacts")
        quality_counts[q] = quality_counts.get(q, 0) + 1
    blocked = {t: d.get("quality_reason") for t, d in per_ticker.items() if d.get("data_quality") in ("bloqueado", "sospechoso")}
    # Routing por tipo de instrumento (E1): vehículos ruteados a no_aplica, con su SIC (evidencia).
    no_operativos = {t: {"sic": d.get("sic"), "sic_desc": d.get("sic_desc"), "categoria": d.get("category")}
                     for t, d in per_ticker.items() if d.get("data_quality") == "no_aplica"}
    instrument_class_counts = {}
    for d in per_ticker.values():
        ic = d.get("instrument_class")
        if ic:
            instrument_class_counts[ic] = instrument_class_counts.get(ic, 0) + 1

    return {
        "n_universo": len(all_tickers),
        "n_resueltos_cik": sum(1 for d in per_ticker.values() if d.get("resolved")),
        "n_con_companyfacts": sum(1 for d in per_ticker.values() if d.get("companyfacts")),
        "cobertura_campos_corporativos(US+ADR)": field_cov(corp),
        "cobertura_por_categoria": by_cat,
        "estado_calidad_conteo": quality_counts,
        "clase_instrumento_conteo": instrument_class_counts,
        "routed_no_aplica(ETF/trust por SIC)": no_operativos,
        "marcados_sospechoso_o_bloqueado": blocked,
        "por_ticker": per_ticker,
    }


def main(argv=None):
    try:
        print(json.dumps(run(), indent=2, default=str, ensure_ascii=False))
        return 0
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-800:]}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
