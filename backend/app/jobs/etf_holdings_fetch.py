"""Ingesta de holdings OFICIALES de ETFs (emisores públicos). No inventa datos.

Flujo: detecta los ETFs de la cartera (transactions + instruments) -> descarga el archivo
oficial del emisor -> normaliza líneas (ticker/cusip/peso/clase) -> evalúa calidad del
snapshot (complete/partial/failed) -> escribe etf_snapshots + etf_holdings SOLO si es
'complete' (no reemplaza un snapshot válido por uno incompleto). ETF sin adaptador => se
reporta 'pendiente de cobertura'.

Credenciales: usa SUPABASE_SERVICE_ROLE_KEY (escritura). Los usuarios autenticados solo leen.

Uso: python -m app.jobs.etf_holdings_fetch [--etfs SPY QQQ ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import httpx

UA = {"User-Agent": "Mozilla/5.0 (compatible; GIIC/1.0; research)"}

# ETFs cubiertos por adaptador oficial (emisor + slug). Lo demás => pendiente de cobertura.
SSGA = ["SPY", "DIA", "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
COMMODITY = {"GLD": "Oro (bullion)", "SLV": "Plata (bullion)", "IAU": "Oro (bullion)"}
VANGUARD_ID = {"VOO": "0968", "VTI": "0970", "VOOG": "0968", "VGT": "0958"}
ISSUER: Dict[str, str] = {**{t: "ssga" for t in SSGA}, "QQQ": "invesco",
                          **{t: "vanguard" for t in VANGUARD_ID}, **{t: "commodity" for t in COMMODITY}}


KNOWN_ETFS = set(SSGA) | {"QQQ", "VOO", "VTI", "SMH", "SCHD", "IWM", "DIA", "GLD", "SLV", "VOOG", "SOXX", "VGT"}


def detect_etfs(writer, diag: Optional[dict] = None) -> List[str]:
    try:
        tx = writer.select_rows("transactions", select="ticker,fund_id")
        tickers = sorted({r["ticker"].upper() for r in tx if not r.get("fund_id")})
        if diag is not None:
            diag["tx_tickers"] = tickers
        if not tickers:
            return []
        classes = {}
        try:
            inst = writer.select_rows("instruments", select="ticker,asset_class",
                                      params={"ticker": "in.(" + ",".join(tickers) + ")"})
            classes = {r["ticker"].upper(): (r.get("asset_class") or "").lower() for r in inst}
        except Exception as e:
            if diag is not None:
                diag["instruments_query_error"] = f"{type(e).__name__}: {str(e)[:80]}"
        if diag is not None:
            diag["instrument_classes"] = classes
        # ETF si: clasificado en instruments, o en lista conocida, o aparece en el catálogo de
        # fondos/ETFs de la SEC (genérico: cualquier ETF nuevo se detecta sin tocar código).
        etfs = []
        for t in tickers:
            is_etf = classes.get(t) in ("etf", "fund") or t in KNOWN_ETFS
            if not is_etf:
                try:
                    is_etf = _mf_lookup(t) is not None
                except Exception:
                    pass
            if is_etf:
                etfs.append(t)
        return sorted(set(etfs))
    except Exception as e:
        if diag is not None:
            diag["detect_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        return []


def _num(x) -> Optional[float]:
    try:
        v = float(str(x).replace(",", "").replace("%", "").strip())
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


def fetch_ssga(ticker: str) -> Tuple[Optional[str], List[dict]]:
    import pandas as pd
    url = (f"https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/"
           f"etfs/us/holdings-daily-us-en-{ticker.lower()}.xlsx")
    r = httpx.get(url, headers=UA, timeout=60, follow_redirects=True)
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), header=None, engine="openpyxl")
    # as_of: busca "as of" en las primeras filas
    as_of = None
    for i in range(min(12, len(raw))):
        row = " ".join(str(c) for c in raw.iloc[i].tolist() if c == c)
        if "as of" in row.lower():
            import re
            mdt = re.search(r"as of\s+([A-Za-z0-9,\s/\-]+)", row, re.I)
            if mdt:
                for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%d-%b-%Y"):
                    try:
                        as_of = datetime.strptime(mdt.group(1).strip()[:20].strip(" ."), fmt).date().isoformat(); break
                    except Exception:
                        pass
    # localizar fila de encabezados (contiene 'Weight' y 'Ticker'/'Name')
    hrow = None
    for i in range(min(15, len(raw))):
        cells = [str(c).strip().lower() for c in raw.iloc[i].tolist()]
        if any("weight" in c for c in cells) and any(c in ("ticker", "name") for c in cells):
            hrow = i; break
    if hrow is None:
        return as_of, []
    cols = [str(c).strip() for c in raw.iloc[hrow].tolist()]
    df = raw.iloc[hrow + 1:].copy(); df.columns = cols
    def col(*names):
        for n in names:
            for c in cols:
                if c.strip().lower() == n:
                    return c
        return None
    cN, cT, cId, cW, cSec = col("name"), col("ticker"), col("identifier", "sedol"), col("weight"), col("sector")
    lines = []
    for _, row in df.iterrows():
        nm = str(row.get(cN, "")).strip() if cN else ""
        if not nm or nm.lower() == "nan":
            continue
        w = _num(row.get(cW)) if cW else None
        tk = str(row.get(cT, "")).strip() if cT else ""
        sec = str(row.get(cSec, "")).strip() if cSec else ""
        ac = "equity"
        low = (nm + " " + sec).lower()
        if any(k in low for k in ("cash", "usd", "money market", "repo")):
            ac = "cash"
        lines.append({"name": nm, "ticker": (tk or None), "cusip": None, "weight": (w / 100.0 if w is not None else None),
                      "asset_class": ac, "sector": sec or None})
    return as_of, lines


def fetch_invesco(ticker: str) -> Tuple[Optional[str], List[dict]]:
    import pandas as pd
    url = (f"https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0"
           f"?audienceType=Investor&action=download&ticker={ticker.upper()}")
    h = {**UA, "Accept": "text/csv,application/octet-stream,*/*",
         "Accept-Language": "en-US,en;q=0.9",
         "Referer": "https://www.invesco.com/us/financial-products/etfs/holdings"}
    r = httpx.get(url, headers=h, timeout=60, follow_redirects=True)
    r.raise_for_status()
    df = pd.read_csv(io.BytesIO(r.content))
    cols = {c.strip().lower(): c for c in df.columns}
    def col(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None
    cN = col("name", "security name", "holding name")
    cT = col("holding ticker", "ticker")
    cW = col("weight", "% weight", "weight (%)", "percentageoffund")
    cId = col("security identifier", "identifier", "cusip")
    cClass = col("class of holdings", "security type", "asset class")
    as_of = None
    cDate = col("date", "as of date", "holdings date")
    if cDate and len(df):
        try:
            as_of = str(df.iloc[0][cDate]).strip()[:10]
            # normaliza formatos comunes
            for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
                try:
                    as_of = datetime.strptime(str(df.iloc[0][cDate]).strip()[:10], fmt).date().isoformat(); break
                except Exception:
                    pass
        except Exception:
            as_of = None
    lines = []
    for _, row in df.iterrows():
        nm = str(row.get(cN, "")).strip() if cN else ""
        if not nm or nm.lower() == "nan":
            continue
        w = _num(row.get(cW)) if cW else None
        tk = str(row.get(cT, "")).strip() if cT else ""
        cls = str(row.get(cClass, "")).strip().lower() if cClass else ""
        ac = "equity"
        if "cash" in cls or "money" in nm.lower():
            ac = "cash"
        elif any(k in cls for k in ("future", "swap", "option", "derivative")):
            ac = "derivative"
        lines.append({"name": nm, "ticker": (tk or None),
                      "cusip": (str(row.get(cId)).strip() if cId and str(row.get(cId)) != "nan" else None),
                      "weight": (w / 100.0 if w is not None else None), "asset_class": ac, "sector": None})
    return as_of, lines


def fetch_vanguard(ticker: str) -> Tuple[Optional[str], List[dict]]:
    fid = VANGUARD_ID.get(ticker.upper())
    lines: List[dict] = []
    as_of = date.today().isoformat()
    urls = [
        f"https://api.vanguard.com/rs/ire/01/pe/fund/{fid}/portfolio-holding/stock.json",
        f"https://investor.vanguard.com/investment-products/etfs/profile/api/{ticker.upper()}/portfolio-holding/stock",
    ]
    data = None
    for u in urls:
        try:
            r = httpx.get(u, headers={**UA, "Accept": "application/json",
                                      "Referer": "https://investor.vanguard.com/"},
                          timeout=60, follow_redirects=True)
            if r.status_code == 200:
                data = r.json(); break
        except Exception:
            continue
    if data is None:
        raise RuntimeError("vanguard: sin respuesta JSON (403/estructura)")
    # estructura variable: buscar lista de holdings con ticker/nombre/porcentaje
    def walk(o):
        found = []
        if isinstance(o, dict):
            keys = {k.lower() for k in o.keys()}
            if ("ticker" in keys or "symbol" in keys) and any("percent" in k or "weight" in k for k in keys):
                found.append(o)
            for v in o.values():
                found += walk(v)
        elif isinstance(o, list):
            for v in o:
                found += walk(v)
        return found
    for h in walk(data):
        low = {k.lower(): v for k, v in h.items()}
        tk = str(low.get("ticker") or low.get("symbol") or "").strip()
        nm = str(low.get("longname") or low.get("name") or low.get("shortname") or "").strip()
        wk = next((low[k] for k in low if "percent" in k or "weight" in k), None)
        w = _num(wk)
        if w is None:
            continue
        sec = str(low.get("sector") or "").strip()
        lines.append({"name": nm or tk, "ticker": (tk or None), "cusip": None,
                      "weight": w / 100.0, "asset_class": "equity", "sector": sec or None})
    return as_of, lines


def fetch_commodity(ticker: str) -> Tuple[Optional[str], List[dict]]:
    # asset_class 'other' (etf_holdings no permite 'commodity'); no es exposición a empresas.
    name = COMMODITY.get(ticker.upper(), "Materia prima")
    return date.today().isoformat(), [{"name": name, "ticker": None, "cusip": None,
                                       "weight": 1.0, "asset_class": "other", "sector": "Materias primas"}]


SEC_UA = {"User-Agent": "GIIC research admin@giic.app"}
_MF_CACHE: Dict[str, dict] = {}


def _mf_lookup(ticker: str) -> Optional[dict]:
    """ticker de fondo/ETF -> {cik, seriesId} vía company_tickers_mf.json (SEC)."""
    if not _MF_CACHE:
        r = httpx.get("https://www.sec.gov/files/company_tickers_mf.json", headers=SEC_UA, timeout=60)
        r.raise_for_status()
        j = r.json()
        fields = j.get("fields", ["cik", "seriesId", "classId", "symbol"])
        si, ti, ci = fields.index("seriesId"), fields.index("symbol"), fields.index("cik")
        for row in j.get("data", []):
            _MF_CACHE[str(row[ti]).upper()] = {"cik": row[ci], "seriesId": row[si]}
    return _MF_CACHE.get(ticker.upper())


def _nport_asset_class(cat: str, has_ticker: bool) -> str:
    c = (cat or "").upper()
    if c in ("EC", "EP"):
        return "equity"
    if c in ("DBT",):
        return "bond"
    if c in ("STIV",):
        return "cash"
    return "equity" if has_ticker else "other"


def fetch_nport(ticker: str) -> Tuple[Optional[str], List[dict]]:
    """Holdings COMPLETOS desde el último NPORT-P del ETF en EDGAR (oficial, gratuito, genérico).
    Nota: datos con rezago (mensual, publicados ~30-60 días después). Respaldo diario = importación."""
    import time
    import xml.etree.ElementTree as ET
    mf = _mf_lookup(ticker)
    if not mf:
        raise RuntimeError(f"nport: ticker {ticker} no está en company_tickers_mf.json")
    sid = mf["seriesId"]
    atom = httpx.get("https://www.sec.gov/cgi-bin/browse-edgar", headers=SEC_UA, timeout=60,
                     params={"action": "getcompany", "CIK": sid, "type": "NPORT-P",
                             "dateb": "", "owner": "include", "count": "3", "output": "atom"})
    atom.raise_for_status()
    root = ET.fromstring(atom.text)
    acc, cik = None, None
    for e in root.iter():
        tag = e.tag.split("}")[-1]
        if tag == "accession-number" and acc is None:
            acc = e.text.strip()
        if tag == "filing-href" and cik is None and e.text:
            m = re.search(r"/data/(\d+)/", e.text)
            if m:
                cik = m.group(1)
    if not acc:
        raise RuntimeError("nport: sin filings NPORT-P para la serie")
    if not cik:
        cik = str(mf["cik"])
    time.sleep(0.3)
    accn = acc.replace("-", "")
    url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/primary_doc.xml"
    r = httpx.get(url, headers=SEC_UA, timeout=90)
    r.raise_for_status()
    xroot = ET.fromstring(r.content)

    def local(e):
        return e.tag.split("}")[-1]
    as_of = None
    lines: List[dict] = []
    for e in xroot.iter():
        if local(e) == "repPdDate" and as_of is None:
            as_of = (e.text or "").strip()[:10]
    for sec in xroot.iter():
        if local(sec) != "invstOrSec":
            continue
        d = {local(c): c for c in sec}
        name = (d.get("name").text if d.get("name") is not None else "") or ""
        cusip = (d.get("cusip").text if d.get("cusip") is not None else None)
        pct = d.get("pctVal")
        w = _num(pct.text) if pct is not None else None
        cat = (d.get("assetCat").text if d.get("assetCat") is not None else "")
        tk = None
        ident = d.get("identifiers")
        if ident is not None:
            for ch in ident.iter():
                if local(ch) == "ticker":
                    tk = (ch.get("value") or ch.text or "").strip() or None
        ac = _nport_asset_class(cat, bool(tk))
        if "cash" in name.lower() or "money market" in name.lower():
            ac = "cash"
        lines.append({"name": name.strip() or None, "ticker": tk,
                      "cusip": (cusip.strip() if cusip else None),
                      "weight": (w / 100.0 if w is not None else None),
                      "asset_class": ac, "sector": None})
    _resolve_tickers_openfigi(lines)
    return (as_of or date.today().isoformat()), lines


def _resolve_tickers_openfigi(lines: List[dict]) -> None:
    """Rellena ticker faltante desde CUSIP vía OpenFIGI (gratuito, sin key). Solo líneas equity
    con CUSIP y sin ticker. Lotes de 10, con pausa por límite de tasa."""
    import time
    pend = [ln for ln in lines if not ln.get("ticker") and ln.get("cusip")
            and ln.get("asset_class") == "equity" and len(str(ln["cusip"])) >= 8]
    uniq = {}
    for ln in pend:
        uniq.setdefault(str(ln["cusip"])[:9], []).append(ln)
    cusips = list(uniq.keys())
    for i in range(0, min(len(cusips), 700), 10):
        batch = cusips[i:i + 10]
        try:
            r = httpx.post("https://api.openfigi.com/v3/mapping",
                           headers={"Content-Type": "application/json", "User-Agent": "GIIC/1.0"},
                           json=[{"idType": "ID_CUSIP", "idValue": c} for c in batch], timeout=45)
            if r.status_code != 200:
                time.sleep(3); continue
            for c, res in zip(batch, r.json()):
                data = (res or {}).get("data") or []
                tk = None
                for d in data:
                    if (d.get("exchCode") in ("US", "UV", "UW", "UN", "UQ")) and d.get("ticker"):
                        tk = d["ticker"]; break
                if not tk and data:
                    tk = data[0].get("ticker")
                if tk:
                    for ln in uniq[c]:
                        ln["ticker"] = tk
        except Exception:
            pass
        time.sleep(2.6)  # límite ~25 req/min sin key


ADAPTERS = {"ssga": fetch_ssga, "invesco": fetch_invesco,
            "vanguard": fetch_vanguard, "commodity": fetch_commodity, "nport": fetch_nport}

_TICKER_CIK: Dict[str, str] = {}
_SECTOR_CACHE: Dict[str, Optional[str]] = {}

# Mapa SIC (descripción de la SEC) -> sector GICS aproximado. Verificable (fuente SEC); no inventa.
_SECTOR_RULES = [
    (("semiconductor", "prepackaged software", "computer", "electronic", "instruments", "communications equip"), "Tecnología"),
    (("pharmaceutical", "biological", "medicinal", "surgical", "medical", "health", "in vitro"), "Salud"),
    (("national commercial bank", "state commercial bank", "bank", "insurance", "security brokers", "investment", "finance services", "credit"), "Financiero"),
    (("crude petroleum", "petroleum", "oil", "natural gas", "drilling", "coal mining"), "Energía"),
    (("retail", "grocery", "eating places", "apparel", "department store", "catalog"), "Consumo discrecional"),
    (("beverage", "food", "tobacco", "household", "soap"), "Consumo básico"),
    (("telephone", "telecommunications", "television", "cable", "motion picture", "advertising"), "Comunicaciones"),
    (("electric", "gas", "water supply", "utilit"), "Servicios públicos"),
    (("real estate", "reit", "land subdividers"), "Inmobiliario"),
    (("aircraft", "motor vehicle", "machinery", "industrial", "construction", "railroad", "air transport", "trucking"), "Industriales"),
    (("chemical", "metal mining", "steel", "paper", "mining", "plastics"), "Materiales"),
]


def _sic_to_sector(sicdesc: str) -> Optional[str]:
    s = (sicdesc or "").lower()
    if not s:
        return None
    for keys, sector in _SECTOR_RULES:
        if any(k in s for k in keys):
            return sector
    return None


def _sector_for(ticker: str) -> Optional[str]:
    """Sector por código SIC de la SEC (ticker->CIK->sicDescription). Best-effort, cacheado."""
    import time
    t = ticker.upper()
    if t in _SECTOR_CACHE:
        return _SECTOR_CACHE[t]
    if len(_SECTOR_CACHE) > 600:   # cota de seguridad por corrida
        return None
    if not _TICKER_CIK:
        try:
            r = httpx.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA, timeout=60)
            for row in r.json().values():
                _TICKER_CIK[str(row["ticker"]).upper()] = str(row["cik_str"]).zfill(10)
        except Exception:
            pass
    cik = _TICKER_CIK.get(t)
    sector = None
    if cik:
        try:
            r = httpx.get(f"https://data.sec.gov/submissions/CIK{cik}.json", headers=SEC_UA, timeout=45)
            if r.status_code == 200:
                sector = _sic_to_sector(r.json().get("sicDescription", ""))
            time.sleep(0.12)
        except Exception:
            pass
    _SECTOR_CACHE[t] = sector
    return sector


def enrich_sectors(rows: List[dict]) -> None:
    # por peso descendente para priorizar la exposición principal dentro de la cota
    for r in sorted(rows, key=lambda x: -(x.get("weight") or 0)):
        if r.get("asset_class") == "equity" and r.get("ticker") and not r.get("sector"):
            r["sector"] = _sector_for(r["ticker"])


def normalize(etf: str, provider: str, as_of: str, lines: List[dict]) -> Tuple[List[dict], dict]:
    out = []
    for i, ln in enumerate(lines):
        cusip = ln.get("cusip")
        tk = ln.get("ticker")
        company_key = (cusip[:6] if cusip and len(cusip) >= 6 else (tk or None))
        line_key = cusip or tk or f"UNIDENT-{i}"
        out.append({
            "etf": etf, "provider": provider, "as_of": as_of,
            "name": ln.get("name"), "ticker": tk, "cusip": cusip,
            "company_key": company_key, "sector": ln.get("sector"),
            "asset_class": ln.get("asset_class") or "equity",
            "weight": ln.get("weight"), "line_key": line_key,
        })
    wsum = sum(r["weight"] for r in out if r["weight"] is not None)
    eqsum = sum(r["weight"] for r in out if r["weight"] is not None and r["asset_class"] == "equity")
    status = "complete" if (0.97 <= wsum <= 1.03 and len(out) >= 1) else ("partial" if out else "failed")
    meta = {"etf": etf, "provider": provider, "as_of": as_of, "status": status,
            "n_lines": len(out), "weight_sum": round(wsum, 4),
            "equity_pct": round(eqsum, 4)}
    return out, meta


def run(writer, etfs: Optional[List[str]], dry: bool) -> dict:
    diag: dict = {}
    targets = [t.upper() for t in etfs] if etfs else detect_etfs(writer, diag)
    report = {"detected": targets, "diag": diag, "covered": [], "pending_coverage": [], "results": []}
    for etf in targets:
        # cadena: adaptador del emisor (si existe) y luego N-PORT (genérico, oficial, gratuito).
        chain = ([ISSUER[etf]] if etf in ISSUER else []) + (["nport"] if ISSUER.get(etf) != "commodity" else [])
        report["covered"].append(etf)
        rows, meta, provider, errors = None, None, None, []
        for prov in chain:
            try:
                as_of, lines = ADAPTERS[prov](etf)
                if not as_of:
                    as_of = date.today().isoformat()
                r, m = normalize(etf, prov, as_of, lines)
                if m["status"] == "complete" or rows is None:
                    rows, meta, provider = r, m, prov
                if m["status"] == "complete":
                    break
            except Exception as e:
                errors.append(f"{prov}: {type(e).__name__}: {str(e)[:90]}")
        if meta is None:
            report["covered"].remove(etf); report["pending_coverage"].append(etf)
            report["results"].append({"etf": etf, "status": "failed", "errors": errors})
            continue
        issuer = provider
        enrich_sectors(rows)
        sample = sorted([r for r in rows if r["weight"]], key=lambda r: -(r["weight"] or 0))[:5]
        meta["top5"] = [{"ticker": r["ticker"], "name": (r["name"] or "")[:28], "weight": r["weight"]} for r in sample]
        if not dry and meta["status"] == "complete":
            writer.upsert("etf_snapshots", [{k: meta[k] for k in ("etf", "provider", "as_of", "status", "n_lines", "weight_sum", "equity_pct")}],
                          on_conflict="etf,provider,as_of")
            writer.insert_append("etf_holdings", rows, on_conflict="etf,provider,as_of,line_key")
            meta["written"] = len(rows)
        elif not dry:
            writer.upsert("etf_snapshots", [{k: meta[k] for k in ("etf", "provider", "as_of", "status", "n_lines", "weight_sum", "equity_pct")}],
                          on_conflict="etf,provider,as_of")
            meta["written"] = 0  # no se escriben líneas de un snapshot incompleto
        report["results"].append(meta)
    return report


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--etfs", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    from ..jobs.supabase_writer import SupabaseWriter
    writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))
    try:
        out = run(writer, args.etfs, args.dry_run)
    except Exception as e:
        import traceback
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:300], "tb": traceback.format_exc()[-900:]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
