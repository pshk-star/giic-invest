"""Offline replay of a write=false run plus an independent cash-flow ledger.

These assertions preserve traceability of model arithmetic. They are not targets
for economic valuation and do not compare intrinsic values to market quotes.
"""
import json
from pathlib import Path
import pytest
from app.research.valuation_engine import NormInputs, value_from_norm, RF, ERP

FIXTURE = json.loads((Path(__file__).parent / "fixtures/p0_valuation_inputs.json").read_text())


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["ticker"])
def test_replay_and_independent_ev_equity_ledger(case):
    n = NormInputs(**case["norm"])
    r = value_from_norm(n, case["price_usd"], adr=case["adr"])
    assert r.fair_value_usd == case["expected_fv"]
    assert n.w_equity + n.w_debt == pytest.approx(1, abs=1e-12)
    # Independent projection, using only the recorded inputs and published equations.
    wacc = n.w_equity * (RF[n.ccy] + n.beta * ERP[n.ccy]) + n.w_debt * n.kd_after_tax
    assert wacc > n.gT
    terminal_roiic = min(.18, max(.10, 2*wacc))
    nopat = n.nopat0
    cashflows = []
    for i in range(10):
        growth = n.g1 + (n.gT - n.g1)*i/9
        roiic = case["roiic0"] + (terminal_roiic-case["roiic0"])*i/9
        nopat *= 1 + growth
        cashflows.append(nopat * (1 - growth/roiic) / (1+wacc)**(i+1))
    terminal = nopat*(1+n.gT)*(1-n.gT/terminal_roiic)/(wacc-n.gT)/(1+wacc)**10
    ev = sum(cashflows) + terminal
    equity = ev - n.net_debt
    assert ev == pytest.approx(case["expected_ev"], abs=1, rel=0)
    assert equity == pytest.approx(case["expected_equity"], abs=1, rel=0)
    assert round(equity/n.shares*case["adr"]*case["fx"],2) == case["expected_fv"]
