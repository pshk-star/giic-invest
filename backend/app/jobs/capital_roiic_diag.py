"""Diagnóstico de CAPITAL INVERTIDO y ROIIC OBSERVADO desde balances oficiales (SEC companyfacts).

Items 2-4,6 del encargo. Read-only. Para cada empresa y año fiscal:
 - Capital invertido (dos vistas): FINANCIAMIENTO = Equity + Deuda total − Caja − Inversiones CP;
   OPERATIVA = PP&E neto + NWC operativo + Goodwill + Intangibles.
 - NOPAT = EBIT·(1−tasa efectiva).
 - ROIIC OBSERVADO = ΔNOPAT/ΔCapital invertido en ventanas 1a/2a/3a/plurianual (muestra estabilidad).
 - Descomposición REAL del puente NOPAT→FCFF→FCF con líneas del estado de flujos (D&A, CAPEX, ΔNWC por
   componentes, SBC, adquisiciones, interés). NO clasifica nada automáticamente.
No fabrica ROIIC ni ajusta al precio. Distingue FCF=OCF−CAPEX de FCFF=NOPAT+D&A−CAPEX−ΔNWC.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

VALID = {"10-K", "10-K/A"}  # usamos el ANUAL auditado para balances y flujos plurianuales

# Conceptos (us-gaap). Instantáneos (balance) y de flujo (anual).
INSTANT = {
    "equity": ["StockholdersEquity"],
    "debt_lt_nc": ["LongTermDebtNoncurrent"], "debt_lt_cur": ["LongTermDebtCurrent"],
    "debt_total": ["LongTermDebt"], "debt_short": ["ShortTermBorrowings", "DebtCurrent"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue"],
    "sti": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesCurrent"],
    "ppe_net": ["PropertyPlantAndEquipmentNet"],
    "assets_cur": ["AssetsCurrent"], "liab_cur": ["LiabilitiesCurrent"],
    "goodwill": ["Goodwill"], "intang": ["FiniteLivedIntangibleAssetsNet", "IntangibleAssetsNetExcludingGoodwill"],
    "assets": ["Assets"], "liab": ["Liabilities"],
}
FLOW = {
    "ebit": ["OperatingIncomeLoss"], "tax": ["IncomeTaxExpenseBenefit"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"],
    "ni": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipment"],
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization"],
    "sbc": ["ShareBasedCompensation"],
    "acq": ["PaymentsToAcquireBusinessesNetOfCashAcquired"],
    "interest": ["InterestExpense"],
    "d_recv": ["IncreaseDecreaseInAccountsReceivable"],
    "d_inv": ["IncreaseDecreaseInInventories"],
    "d_ap": ["IncreaseDecreaseInAccountsPayable", "IncreaseDecreaseInAccountsPayableTrade"],
    "d_opcap": ["IncreaseDecreaseInOperatingCapital", "IncreaseDecreaseInOtherOperatingCapitalNet"],
}


def _d(s):
    try: return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception: return None


def _annual_flow(usg, concepts):
    """Valor anual (duración 330-400d) por año fiscal (end year) del primer concepto con datos; 10-K."""
    for c in concepts:
        node = (usg or {}).get(c) or {}
        best = {}
        for unit, rows in (node.get("units", {}) or {}).items():
            for f in rows:
                s, e, v = f.get("start"), f.get("end"), f.get("val")
                if v is None or not s or not e or (f.get("form") or "") not in VALID: continue
                ds, de = _d(s), _d(e)
                if not ds or not de or not (330 <= (de - ds).days <= 400): continue
                y = de.year
                if y not in best or (f.get("filed") or "") > (best[y]["filed"] or ""):
                    best[y] = {"val": float(v), "end": e, "filed": f.get("filed"), "accn": f.get("accn"), "concepto": c}
        if best: return best
    return {}


def _instant(usg, concepts):
    """Valor instantáneo por año fiscal (fin de año) del primer concepto con datos; 10-K."""
    for c in concepts:
        node = (usg or {}).get(c) or {}
        best = {}
        for unit, rows in (node.get("units", {}) or {}).items():
            for f in rows:
                s, e, v = f.get("start"), f.get("end"), f.get("val")
                if v is None or s is not None or not e or (f.get("form") or "") not in VALID: continue
                de = _d(e)
                if not de: continue
                y = de.year
                if y not in best or (f.get("filed") or "") > (best[y]["filed"] or ""):
                    best[y] = {"val": float(v), "end": e, "filed": f.get("filed"), "concepto": c}
        if best: return best
    return {}


def analyze(usg) -> dict:
    I = {k: _instant(usg, c) for k, c in INSTANT.items()}
    F = {k: _annual_flow(usg, c) for k, c in FLOW.items()}
    years = sorted({y for m in list(I.values()) + list(F.values()) for y in m})
    rows = []
    for y in years:
        def iv(k):
            d = I[k].get(y); return d["val"] if d else None
        def fv(k):
            d = F[k].get(y); return d["val"] if d else None
        ebit = fv("ebit"); tax = fv("tax"); pretax = fv("pretax")
        teff = (abs(tax) / pretax) if (tax is not None and pretax and pretax > 0) else None
        nopat = ebit * (1 - teff) if (ebit is not None and teff is not None) else (ebit * 0.85 if ebit is not None else None)
        # capital invertido FINANCIAMIENTO
        debt = iv("debt_total")
        if debt is None:
            debt = sum(x for x in [iv("debt_lt_nc"), iv("debt_lt_cur"), iv("debt_short")] if x is not None) or None
        eq = iv("equity"); cash = iv("cash"); sti = iv("sti")
        ic_fin = None
        if eq is not None and debt is not None:
            ic_fin = eq + debt - (cash or 0) - (sti or 0)
        # capital invertido OPERATIVA
        ppe = iv("ppe_net"); ac = iv("assets_cur"); lc = iv("liab_cur"); gw = iv("goodwill"); intg = iv("intang")
        nwc_op = None
        if ac is not None and lc is not None:
            # NWC operativo = (activo corriente − caja − inversiones CP) − (pasivo corriente − deuda corto)
            nwc_op = (ac - (cash or 0) - (sti or 0)) - (lc - (iv("debt_lt_cur") or 0) - (iv("debt_short") or 0))
        ic_op = None
        if ppe is not None and nwc_op is not None:
            ic_op = ppe + nwc_op + (gw or 0) + (intg or 0)
        rows.append({"y": y, "ebit": ebit, "tax_eff": teff, "nopat": nopat, "ocf": fv("ocf"),
                     "capex": fv("capex"), "dna": fv("dna"), "sbc": fv("sbc"), "acq": fv("acq"),
                     "interest": fv("interest"), "ni": fv("ni"),
                     "d_recv": fv("d_recv"), "d_inv": fv("d_inv"), "d_ap": fv("d_ap"), "d_opcap": fv("d_opcap"),
                     "equity": eq, "debt": debt, "cash": cash, "sti": sti, "ppe_net": ppe,
                     "nwc_op": nwc_op, "goodwill": gw, "intang": intg, "ic_fin": ic_fin, "ic_op": ic_op})
    # ROIIC observado = ΔNOPAT/ΔIC en ventanas
    def roiic(window):
        pts = [r for r in rows if r["nopat"] is not None and r["ic_fin"] is not None][-(window + 1):]
        if len(pts) < 2: return None, None
        dn = pts[-1]["nopat"] - pts[0]["nopat"]; di = pts[-1]["ic_fin"] - pts[0]["ic_fin"]
        return (dn / di if di and abs(di) > 1 else None), {"desde": pts[0]["y"], "hasta": pts[-1]["y"], "dNOPAT": dn, "dIC": di}
    roiic_1, d1 = roiic(1); roiic_3, d3 = roiic(3); roiic_all, dall = roiic(len(rows))
    # puente NOPAT→FCFF→FCF del último año
    last = rows[-1] if rows else {}
    bridge = {}
    if last:
        nopat = last["nopat"]; dna = last["dna"]; capex = last["capex"]
        # ΔNWC real por componentes (signos de cash flow: + = libera caja)
        comp = [last.get(k) for k in ("d_recv", "d_inv", "d_ap", "d_opcap")]
        dnwc_cf = sum(x for x in comp if x is not None) if any(x is not None for x in comp) else None
        fcf = (last["ocf"] - abs(capex)) if (last["ocf"] is not None and capex is not None) else None
        fcff = None
        if nopat is not None and dna is not None and capex is not None and dnwc_cf is not None:
            # FCFF = NOPAT + D&A − CAPEX − ΔNWC ; ΔNWC(uso)= −(efecto en caja)
            fcff = nopat + dna - abs(capex) + dnwc_cf
        bridge = {"nopat": nopat, "dna": dna, "capex": capex, "dnwc_cf_componentes": {k: last.get(k) for k in ("d_recv", "d_inv", "d_ap", "d_opcap")},
                  "dnwc_cf_total": dnwc_cf, "sbc": last.get("sbc"), "acq": last.get("acq"),
                  "interest": last.get("interest"), "ni": last.get("ni"), "ocf": last["ocf"],
                  "FCF=OCF−CAPEX": fcf, "FCFF=NOPAT+D&A−CAPEX−ΔNWC": fcff,
                  "NOPAT−FCF": (nopat - fcf) if (nopat is not None and fcf is not None) else None,
                  "NOPAT−FCFF": (nopat - fcff) if (nopat is not None and fcff is not None) else None}
    return {"serie": rows[-6:], "ROIIC_observado": {"1a": [roiic_1, d1], "3a": [roiic_3, d3], "plurianual": [roiic_all, dall]},
            "puente_ultimo_anio": bridge}


def run(tickers):
    from app.providers.edgar import EDGARProvider
    prov = EDGARProvider(user_agent=os.getenv("EDGAR_USER_AGENT") or "GIIC research noreply@giic.example")
    prov._load_ciks()
    out = {}
    for t in tickers:
        facts = prov._facts(t)
        if not facts:
            out[t] = {"error": "sin companyfacts"}; continue
        usg = (facts.get("facts", {}) or {}).get("us-gaap", {}) or {}
        out[t] = analyze(usg)
    return out


def main(argv=None):
    tickers = [t.upper() for t in (argv or sys.argv[1:])] or ["NVDA", "META", "PFE", "LOW", "HD"]
    print(json.dumps(run(tickers), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
