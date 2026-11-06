import { useMemo, useState } from "react";
import { valuateCompany, type CompanyValuation } from "../core/fundamental";
import type { FundamentalsPayload } from "../core/valuation";
import { money, pct } from "../format";

const COMMODITY = ["GLD", "SLV", "IAU", "PPLT", "PALL", "SGOL", "SIVR"];

export interface FundRow {
  ticker: string;
  name: string | null;
  sector: string | null;
  assetClass: string | null;
  price: number | null;
  priceAsOf: string | null;
  qty: number;
  marketValue: number | null;
}

type Kind = "equity" | "etf" | "commodity";
function classify(r: FundRow): Kind {
  const ac = (r.assetClass ?? "").toLowerCase();
  if (COMMODITY.includes(r.ticker.toUpperCase()) || ac === "commodity") return "commodity";
  if (ac === "etf" || ac === "fund" || ac === "etn" || ac === "mutualfund") return "etf";
  return "equity";
}

export function FundamentalView({ rows, fundamentals }: { rows: FundRow[]; fundamentals: Record<string, FundamentalsPayload> }) {
  const equities = rows.filter((r) => classify(r) === "equity");
  const etfs = rows.filter((r) => classify(r) === "etf");
  const commodities = rows.filter((r) => classify(r) === "commodity");

  const valuations = useMemo(
    () => equities.map((r) => ({
      row: r,
      val: valuateCompany({
        ticker: r.ticker, name: r.name, sector: r.sector,
        price: r.price, priceAsOf: r.priceAsOf, f: fundamentals[r.ticker.toUpperCase()] ?? fundamentals[r.ticker],
      }),
    })),
    [equities, fundamentals]
  );

  const equityValue = equities.reduce((s, r) => s + (r.marketValue ?? 0), 0);
  const coveredValue = valuations.filter((v) => v.val.available).reduce((s, v) => s + (v.row.marketValue ?? 0), 0);
  const nCovered = valuations.filter((v) => v.val.available).length;

  return (
    <div className="grid gap-4">
      <div className="rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs text-term-muted">
        <b className="text-term-fg">Valoración fundamental por empresa.</b> Estima el valor económico
        razonable bajo escenarios con <b>supuestos explícitos</b> (EPS × múltiplo razonado), no una
        predicción. Horizonte 12 meses. No usa estimaciones de analistas inventadas; los escenarios
        <b> no son probabilidades</b>.
      </div>

      {/* Cobertura (semilla de la agregación de cartera) */}
      <div className="flex flex-wrap gap-4 rounded-lg border border-term-border bg-term-panel2 px-3 py-2 text-xs text-term-muted">
        <span>Acciones directas con valoración: <b className="text-term-fg tabnum">{nCovered}/{equities.length}</b></span>
        <span>Valor con cobertura fundamental: <b className="text-term-fg tabnum">{money(coveredValue)}</b>{equityValue > 0 && <> ({pct(coveredValue / equityValue)} del valor en acciones directas)</>}</span>
        <span className="text-term-faint">ETFs y materias primas se tratan aparte (abajo).</span>
      </div>

      {valuations.map(({ row, val }) => <CompanyCard key={row.ticker} row={row} val={val} />)}

      {valuations.length === 0 && (
        <p className="text-sm text-term-muted">No tienes acciones directas valorables (tu exposición a empresas es vía ETFs; su look-through fundamental llega en la siguiente entrega).</p>
      )}

      {(etfs.length > 0 || commodities.length > 0) && (
        <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-term-faint">Posiciones tratadas aparte</div>
          <ul className="flex flex-col gap-1 text-xs text-term-muted">
            {etfs.map((r) => (
              <li key={r.ticker}><span className="font-mono font-semibold text-term-fg">{r.ticker}</span> — ETF: exposición económica por <b>look-through</b> de X-Ray; valoración fundamental consolidada de sus subyacentes pendiente (Fase 3). No se le asigna un valor de empresa.</li>
            ))}
            {commodities.map((r) => (
              <li key={r.ticker}><span className="font-mono font-semibold text-term-fg">{r.ticker}</span> — Materia prima: exposición a oro/plata, <b>sin fundamentales de empresa</b>. No se inventa una proyección fundamental.</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function qualityTone(q: CompanyValuation["quality"]): string {
  return q === "alta" ? "text-term-good" : q === "baja" ? "text-term-crit" : "text-term-muted";
}

function CompanyCard({ row, val }: { row: FundRow; val: CompanyValuation }) {
  const [open, setOpen] = useState(false);
  if (!val.available) {
    return (
      <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
        <div className="flex items-center justify-between">
          <span className="text-sm"><span className="font-mono font-semibold text-term-fg">{row.ticker}</span>{row.name && <span className="text-term-muted"> · {row.name}</span>}</span>
          <span className="text-xs text-term-warn">Proyección fundamental no disponible</span>
        </div>
        <p className="mt-1 text-xs text-term-faint">{val.unavailableReason}</p>
      </div>
    );
  }
  const central = val.scenarios.find((s) => s.key === "central")!;
  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm">
          <span className="font-mono font-semibold text-term-fg">{row.ticker}</span>
          {row.name && <span className="text-term-muted"> · {row.name}</span>}
          <span className="ml-2 text-xs text-term-faint">Precio {money(val.price)}{val.priceAsOf ? ` · ${val.priceAsOf}` : ""}</span>
        </span>
        <span className="text-xs">
          Método: <b className="text-term-fg">{val.method === "pe_eps" ? "EPS × P/E" : "Rend. FCF (respaldo)"}</b>
          <span className="ml-2">Calidad: <b className={qualityTone(val.quality)}>{val.quality}</b></span>
        </span>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        {val.scenarios.map((s) => (
          <div key={s.key} className="rounded-lg border border-term-border bg-term-panel px-2 py-2">
            <div className="text-[10px] uppercase text-term-muted">{s.label}</div>
            <div className="text-base font-semibold tabnum text-term-fg">{money(s.fairValue)}</div>
            <div className={`text-xs tabnum ${s.upside >= 0 ? "text-term-good" : "text-term-crit"}`}>{s.upside >= 0 ? "+" : ""}{pct(s.upside)}</div>
          </div>
        ))}
      </div>
      <p className="mt-2 text-xs text-term-muted">
        Valor razonable central <b className="text-term-fg">{money(central.fairValue)}</b> a {val.horizonLabel}
        ({central.upside >= 0 ? "+" : ""}{pct(central.upside)} vs precio). Es valor estimado bajo supuestos, no precio objetivo garantizado.
      </p>

      <button onClick={() => setOpen(!open)} className="mt-2 text-xs text-term-accent">{open ? "▲ ocultar detalle" : "▼ ver supuestos, sensibilidad y límites"}</button>
      {open && (
        <div className="mt-2 grid gap-2 text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-term-faint">Supuestos por escenario</div>
            {val.scenarios.map((s) => (
              <div key={s.key} className="mt-0.5 text-term-muted"><b className="text-term-fg">{s.label}:</b> {s.assumptions.join("; ")}.</div>
            ))}
          </div>
          {val.sensitivity.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-term-faint">Sensibilidad (valor y vs precio)</div>
              <div className="mt-0.5 flex flex-wrap gap-x-4 gap-y-0.5 text-term-muted">
                {val.sensitivity.map((s) => (
                  <span key={s.label}>{s.label}: <b className="text-term-fg">{money(s.fairValue)}</b> ({s.upside >= 0 ? "+" : ""}{pct(s.upside)})</span>
                ))}
              </div>
            </div>
          )}
          <Block title="Datos usados" items={val.dataSources} />
          <Block title="Limitaciones" items={val.limitations} />
        </div>
      )}
    </div>
  );
}

function Block({ title, items }: { title: string; items: string[] }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-term-faint">{title}</div>
      <ul className="mt-0.5 flex flex-col gap-0.5 text-term-muted">
        {items.map((x, i) => <li key={i}>• {x}</li>)}
      </ul>
    </div>
  );
}
