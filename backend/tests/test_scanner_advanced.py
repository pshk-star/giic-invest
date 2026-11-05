"""Pruebas de las capacidades avanzadas del scanner: reponderación por cobertura
y ranking comparable por sector."""
from app.core import scanner as sc
from app.core.types import Fundamentals


def _inp(ticker, sector, **f):
    tech = {k: f.pop(k) for k in list(f) if k in ("mom_6m", "mom_12m", "vol_1y", "rsi_14", "drawdown")}
    return sc.ScanInput(ticker=ticker, fundamentals=Fundamentals(ticker=ticker, **f),
                        technical=tech, sector=sector, is_sample=True)


def test_usable_factors_excludes_factor_from_composite():
    universe = [
        _inp("A", "Tech", pe_forward=10, roic=0.3, rev_growth_yoy=0.3),
        _inp("B", "Tech", pe_forward=40, roic=0.05, rev_growth_yoy=0.02),
    ]
    # Con growth excluido, el compuesto se reponderra sobre value+quality+mom+lowrisk
    full = {s.ticker: s for s in sc.score_universe(universe)}
    no_growth = {s.ticker: s for s in sc.score_universe(universe, usable_factors=["value", "quality", "momentum", "low_risk"])}
    # A sigue ganando pero el valor del compuesto cambia al reponderar
    assert no_growth["A"].composite != full["A"].composite
    assert no_growth["A"].composite >= no_growth["B"].composite


def test_sector_relative_ranks_within_sector():
    # Globalmente 'cara', pero la más barata de su sector => value alto en modo sectorial.
    universe = [
        _inp("CHEAP_TECH", "Tech", pe_forward=30, ev_ebitda=20, fcf_yield=0.02),
        _inp("RICH_TECH", "Tech", pe_forward=60, ev_ebitda=40, fcf_yield=0.01),
        _inp("CHEAP_STAPLE", "Staples", pe_forward=8, ev_ebitda=6, fcf_yield=0.10),
        _inp("RICH_STAPLE", "Staples", pe_forward=16, ev_ebitda=12, fcf_yield=0.05),
    ]
    glob = {s.ticker: s for s in sc.score_universe(universe, sector_relative=False)}
    sect = {s.ticker: s for s in sc.score_universe(universe, sector_relative=True)}
    # Global: CHEAP_TECH pierde en value frente a los staples baratos.
    assert glob["CHEAP_TECH"].value < glob["CHEAP_STAPLE"].value
    # Sectorial: CHEAP_TECH es la mejor de su sector => value máximo dentro de Tech.
    assert sect["CHEAP_TECH"].value > sect["RICH_TECH"].value
    assert sect["CHEAP_TECH"].value >= 90


def test_sector_relative_singleton_is_neutral():
    universe = [_inp("ONLY", "Niche", pe_forward=10, ev_ebitda=8, fcf_yield=0.05)]
    s = sc.score_universe(universe, sector_relative=True)[0]
    assert s.value == 50.0  # único en su sector => neutral
