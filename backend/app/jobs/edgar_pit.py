"""Ingesta POINT-IN-TIME de fundamentales desde SEC EDGAR (companyfacts) -> fundamentals_pit.

Clave: cada hecho se guarda con su FECHA DE FILING real (`filed`) y su accession estable
(`accn`), de modo que en backtest solo se usen hechos con filing_date <= as_of (sin
look-ahead). Las reexpresiones posteriores entran como filas nuevas (otro accession).

Append-only: insert con ignore-duplicates (los triggers de 0007/0008 rechazan UPDATE).

Uso:
    python -m app.jobs.edgar_pit --tickers MU NVDA --dry-run
    python -m app.jobs.edgar_pit                 # cartera + universo -> escribe en Supabase
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, date
from typing import Dict, List, Optional

# Conceptos clave (tags us-gaap). Se amplía con disciplina; cada uno con su unidad esperada.
CONCEPTS = [
    "Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss", "GrossProfit", "OperatingIncomeLoss",
    "EarningsPerShareDiluted", "EarningsPerShareBasic",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "StockholdersEquity", "Assets", "Liabilities", "LongTermDebtNoncurrent",
]

# Conceptos equivalentes en IFRS (tags ifrs-full). Emisores extranjeros que presentan
# 20-F reportan bajo IFRS y NO aparecen en us-gaap (p. ej. ASML, TSM). Esto deja preparada
# la ingesta cruda de su point-in-time; el mapeo IFRS->payload de ratios (run_scan) es el
# paso siguiente (ver RESEARCH_BACKLOG).
IFRS_CONCEPTS = [
    "Revenue", "RevenueFromContractsWithCustomers",
    "ProfitLoss", "GrossProfit", "ProfitLossFromOperatingActivities",
    "DilutedEarningsLossPerShare", "BasicEarningsLossPerShare",
    "CashFlowsFromUsedInOperatingActivities",
    "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    "Equity", "Assets", "Liabilities", "Borrowings",
]


def _extract_taxonomy(node: dict, concepts: List[str], taxonomy: str,
                      ticker: str, cik: Optional[int]) -> List[dict]:
    out: List[dict] = []
    tax = node or {}
    for concept in concepts:
        cnode = tax.get(concept)
        if not cnode:
            continue
        for unit, rows in (cnode.get("units", {}) or {}).items():
            for f in rows:
                filed = f.get("filed")
                end = f.get("end")
                if not filed or not end:
                    continue
                accn = f.get("accn")
                form = f.get("form") or ""
                fy, fp = f.get("fy"), f.get("fp")
                frame = f.get("frame")
                start = f.get("start")
                # context_ref DEBE distinguir la DURACIÓN del periodo (trimestral vs YTD):
                # el frame de EDGAR ya la codifica; si no hay frame, usamos start_end.
                context = frame or f"{start or 'NA'}_{end}"
                out.append({
                    "provider": "edgar",
                    "cik": str(cik) if cik is not None else None,
                    "ticker": ticker.upper(),
                    "accession": accn,
                    "form_type": form,
                    "concept": concept,
                    "context_ref": context,
                    "unit": unit,
                    "taxonomy": taxonomy,
                    "period_start": f.get("start"),
                    "period_end": end,
                    "fiscal_period": (f"{fp}-{fy}" if (fp or fy) else None),
                    "value": f.get("val"),
                    "filing_date": filed,
                    "amended": form.endswith("/A"),
                    "source_doc": accn,
                })
    return out


def extract_pit_rows(facts: dict, ticker: str, cik: Optional[int],
                     concepts: List[str] = None,
                     ifrs_concepts: List[str] = None) -> List[dict]:
    """Extrae filas fundamentals_pit (puro, testeable) desde companyfacts JSON.

    Cubre us-gaap (emisores domésticos) e ifrs-full (emisores extranjeros 20-F).
    """
    concepts = concepts or CONCEPTS
    ifrs_concepts = ifrs_concepts or IFRS_CONCEPTS
    root = ((facts or {}).get("facts", {}) or {})
    out = _extract_taxonomy(root.get("us-gaap", {}) or {}, concepts, "us-gaap", ticker, cik)
    out += _extract_taxonomy(root.get("ifrs-full", {}) or {}, ifrs_concepts, "ifrs-full", ticker, cik)
    return out


def execute(tickers: List[str] = None, dry_run: bool = False) -> dict:
    ua = os.getenv("EDGAR_USER_AGENT", "")
    from ..providers.edgar import EDGARProvider
    prov = EDGARProvider(user_agent=ua)
    prov._load_ciks()

    writer = None
    if not dry_run:
        from .supabase_writer import SupabaseWriter
        writer = SupabaseWriter(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""))

    if not tickers:
        uni = []
        try:
            from .universe import get_universe
            uni = [i.ticker for i in get_universe(include_etfs=False)]
        except Exception:
            uni = []
        port = []
        if writer is not None:
            try:
                port = writer.get_transaction_tickers()
            except Exception:
                port = []
        tickers = sorted(set([t.upper() for t in port] + [t.upper() for t in uni]))

    run_id = f"edgar-{datetime.utcnow().date().isoformat()}"
    total, written, per = 0, 0, {}
    sample = []
    for t in tickers:
        try:
            facts = prov._facts(t)
        except Exception:
            facts = None
        if not facts:
            per[t] = 0
            continue
        cik = prov._cik.get(t.upper())
        rows = extract_pit_rows(facts, t, cik)
        for r in rows:
            r["ingest_run_id"] = run_id
        per[t] = len(rows)
        total += len(rows)
        if not sample and rows:
            sample = sorted(rows, key=lambda x: x["filing_date"])[-3:]
        if not dry_run and rows:
            for i in range(0, len(rows), 500):
                written += writer.insert_append("fundamentals_pit", rows[i:i + 500],
                                                on_conflict="provider,accession,concept,context_ref,unit")

    summary = {
        "provider": "edgar", "tickers": len(tickers), "rows_extracted": total,
        "with_data": sum(1 for v in per.values() if v > 0),
        "empty": sorted([t for t, n in per.items() if n == 0])[:20],
        "sample_latest_filings": [{k: s[k] for k in ("ticker", "concept", "period_end", "filing_date", "accession", "value")} for s in sample],
    }
    if dry_run:
        summary["written"] = False
        return summary
    writer.upsert("data_coverage", [{
        "dataset": "fundamentals_pit:edgar", "provider": "edgar",
        "as_of": date.today().isoformat(), "is_complete": False, "n_rows": written,
        "note": "EDGAR us-gaap conceptos clave con filing_date; cobertura parcial (solo emisores con companyfacts).",
    }], on_conflict="dataset,provider")
    summary["rows_written"] = written
    summary["written"] = True
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="GIIC EDGAR point-in-time ingestion")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    try:
        out = execute([t.upper() for t in args.tickers] if args.tickers else None, args.dry_run)
    except Exception as e:
        print(json.dumps({"error": type(e).__name__, "message": str(e)[:200]}, indent=2))
        return 1
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
