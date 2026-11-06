import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Panel, Stat } from "../components/Panel";
import {
  addTransaction, deleteTransaction, getCorporateActions, getInstruments, getPrices, getQuotes,
  getTransactions, searchInstruments, type InstrumentRow, type QuoteRow,
} from "../data";
import type { PriceInfo } from "../core/analytics";
import {
  derivePositions, portfolioTotals, type InstrumentMeta, type Side, type Split, type Txn,
} from "../core/portfolio-tx";
import { classifyQuote } from "../core/quotefmt";
import { mergeValuation } from "../core/price-source";
import { investmentCashFlows, xirr } from "../core/returns";
import { ValuationStamp } from "../components/ValuationStamp";
import { FintualPanel } from "../components/FintualPanel";
import { money, num, pct } from "../format";

const todayISO = () => new Date().toISOString().slice(0, 10);

const EMPTY = {
  ticker: "", side: "buy" as Side, quantity: "", price: "", fees: "0",
  amount: "", executed_at: todayISO(), notes: "",
};

export function Portfolio() {
  const [txns, setTxns] = useState<Txn[]>([]);
  const [instMap, setInstMap] = useState<Record<string, InstrumentMeta>>({});
  const [eod, setEod] = useState<Record<string, PriceInfo>>({});
  const [quotes, setQuotes] = useState<Record<string, QuoteRow>>({});
  const [splits, setSplits] = useState<Split[]>([]);
  const [form, setForm] = useState({ ...EMPTY });
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // autocompletado de tickers
  const [sugs, setSugs] = useState<InstrumentRow[]>([]);
  const [showSugs, setShowSugs] = useState(false);
  const [picked, setPicked] = useState<InstrumentRow | null>(null);
  const searchTimer = useRef<number | null>(null);

  const load = async () => {
    const t = await getTransactions();
    setTxns(t);
    const tickers = Array.from(new Set(t.map((x) => x.ticker.toUpperCase())));
    const [pr, inst, qs, ca] = await Promise.all([
      getPrices(tickers), getInstruments(tickers), getQuotes(tickers), getCorporateActions(tickers),
    ]);
    setEod(pr); setInstMap(inst); setQuotes(qs); setSplits(ca);
  };

  useEffect(() => { load().catch((e) => setMsg(String(e))); }, []);

  // Auto-actualización: re-consulta cotizaciones cada 60 s (lee de Supabase, barato).
  // Si falla, conserva las últimas (nunca pone cero ni inventa un precio).
  useEffect(() => {
    const tickers = Array.from(new Set(txns.map((x) => x.ticker.toUpperCase())));
    if (!tickers.length) return;
    const id = window.setInterval(() => {
      getQuotes(tickers).then(setQuotes).catch(() => { /* conserva últimas */ });
    }, 60000);
    return () => window.clearInterval(id);
  }, [txns]);

  // Transacciones de ACCIONES/ETF (excluye movimientos de fondos, que maneja FintualPanel).
  const secTxns = useMemo(() => txns.filter((t) => !t.fund_id), [txns]);

  // Precio efectivo + metadatos: MISMA regla que el Dashboard (core/valuation).
  const heldTickers = useMemo(
    () => Array.from(new Set(secTxns.map((x) => x.ticker.toUpperCase()))), [secTxns]);
  const valuation = useMemo(
    () => mergeValuation(heldTickers, eod, quotes), [heldTickers, eod, quotes]);
  const mergedPrices = valuation.prices;

  const positions = useMemo(() => derivePositions(secTxns, mergedPrices, instMap, splits), [secTxns, mergedPrices, instMap, splits]);
  const totals = useMemo(() => portfolioTotals(positions), [positions]);

  // P&L del día: suma de qty × (precio − cierre previo) para posiciones con cotización.
  const dayPL = useMemo(() => {
    let s = 0, any = false;
    for (const p of positions) {
      const q = quotes[p.ticker];
      if (p.qty > 1e-9 && q && q.previous_close != null) { s += p.qty * (q.price - q.previous_close); any = true; }
    }
    return any ? s : null;
  }, [positions, quotes]);

  // Rentabilidad money-weighted (TIR/XIRR) de las inversiones: flujos de compra/venta/dividendo
  // + valor de mercado actual como flujo terminal. Excluye depósitos/retiros de efectivo (son
  // financiamiento, no retorno). Base USD; si hay transacciones en otra moneda, no se calcula
  // aún (requiere FX; llega con Fintual/multimoneda).
  const xirrPct = useMemo(() => {
    const b = investmentCashFlows(secTxns, totals.marketValue, todayISO(), "USD");
    return { value: b.mixedCurrency ? null : xirr(b.flows), mixed: b.mixedCurrency };
  }, [secTxns, totals.marketValue]);

  const appliedSplits = useMemo(
    () => splits.filter((s) => positions.some((p) => p.qty > 1e-9 && p.ticker === s.ticker.toUpperCase())),
    [splits, positions]
  );

  // Advertencia si se mezclan precios de fechas distintas.
  const priceDates = useMemo(() => {
    const ds = new Set<string>();
    for (const p of positions) if (p.qty > 1e-9 && p.priceAsOf) ds.add(p.priceAsOf);
    return Array.from(ds).sort();
  }, [positions]);

  const onTicker = (v: string) => {
    setForm({ ...form, ticker: v.toUpperCase() });
    setPicked(null);
    if (searchTimer.current) window.clearTimeout(searchTimer.current);
    if (!v.trim()) { setSugs([]); setShowSugs(false); return; }
    searchTimer.current = window.setTimeout(async () => {
      try {
        const r = await searchInstruments(v);
        setSugs(r); setShowSugs(true);
      } catch { /* sin sugerencias */ }
    }, 200);
  };

  const pick = (r: InstrumentRow) => {
    setForm({ ...form, ticker: r.ticker });
    setPicked(r); setShowSugs(false);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    try {
      const isCash = form.side === "dividend";
      await addTransaction({
        ticker: form.ticker.toUpperCase(),
        side: form.side,
        quantity: isCash ? null : Number(form.quantity),
        price: isCash ? null : Number(form.price),
        fees: Number(form.fees || 0),
        amount: isCash ? Number(form.amount) : null,
        currency: picked?.currency || "USD",
        executed_at: form.executed_at,
        notes: form.notes || null,
      });
      setForm({ ...EMPTY });
      setPicked(null);
      await load();
    } catch (e) {
      setMsg(String(e));
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    await deleteTransaction(id);
    await load();
  };

  const cash = form.side === "dividend";

  return (
    <div className="grid gap-4">
      {positions.length > 0 && (
        <Panel title="Resumen de mi cartera">
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Stat label="Valor de mercado" value={money(totals.marketValue)} />
            <Stat label="P&L del día"
              value={dayPL !== null ? `${dayPL >= 0 ? "+" : ""}${money(dayPL)}` : "—"}
              tone={dayPL === null ? "text-term-muted" : dayPL >= 0 ? "text-term-good" : "text-term-crit"} />
            <Stat label="P&L no realizado"
              value={`${money(totals.unrealized)} (${totals.unrealizedPct !== null ? pct(totals.unrealizedPct) : "—"})`}
              tone={totals.unrealized >= 0 ? "text-term-good" : "text-term-crit"} />
            <Stat label="Realizado + dividendos"
              value={money(totals.realized + totals.dividends)}
              tone={totals.realized + totals.dividends >= 0 ? "text-term-good" : "text-term-crit"} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
            <ValuationStamp meta={valuation.meta} />
            <span className="text-xs text-term-muted">
              · Rentabilidad (TIR anual, money-weighted):{" "}
              {xirrPct.mixed ? (
                <span className="text-term-faint">pendiente (transacciones multimoneda)</span>
              ) : xirrPct.value !== null ? (
                <span className={`tabnum font-semibold ${xirrPct.value >= 0 ? "text-term-good" : "text-term-crit"}`}>
                  {pct(xirrPct.value)}
                </span>
              ) : (
                <span className="text-term-faint">n/d</span>
              )}
            </span>
          </div>
          <p className="mt-1 text-xs text-term-muted">
            Las cotizaciones se actualizan solas cada 60 s mientras usas GIIC (fuente gratuita
            <strong> retrasada</strong>, no tiempo real). P&L del día = Σ cantidad × (precio − cierre previo).
          </p>
          {priceDates.length > 1 && (
            <p className="mt-1 text-xs text-term-warn">
              Aviso: tus posiciones usan precios de fechas distintas ({priceDates.join(", ")}); el valor total los mezcla.
            </p>
          )}
          {appliedSplits.length > 0 && (
            <p className="mt-1 text-xs text-term-muted">
              Ajustes por split aplicados automáticamente (costo total intacto):{" "}
              {appliedSplits.map((s) => `${s.ticker} ${s.ratio >= 1 ? `${s.ratio}:1` : `1:${Math.round(1 / s.ratio)}`} (ex ${s.ex_date})`).join(" · ")}.
            </p>
          )}
        </Panel>
      )}

      <FintualPanel txns={txns} stocksUsd={totals.marketValue} onChange={() => { load().catch(() => {}); }} />

      <Panel title="Registrar operación">
        <form onSubmit={submit} className="grid gap-2">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            <div className="relative sm:col-span-2">
              <input
                required placeholder="Ticker (ej. NVDA)" value={form.ticker}
                onChange={(e) => onTicker(e.target.value)}
                onFocus={() => sugs.length && setShowSugs(true)}
                onBlur={() => setTimeout(() => setShowSugs(false), 150)}
                className="w-full rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm uppercase"
                autoComplete="off"
              />
              {showSugs && sugs.length > 0 && (
                <ul className="absolute z-10 mt-1 max-h-56 w-full overflow-auto rounded-md border border-term-border bg-term-panel shadow-lg">
                  {sugs.map((s) => (
                    <li key={s.ticker}>
                      <button type="button" onMouseDown={() => pick(s)}
                        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-term-panel2">
                        <span className="font-mono font-semibold">{s.ticker}</span>
                        <span className="truncate text-term-muted">{s.name ?? "—"}</span>
                        <span className="text-xs text-term-accent">{s.asset_class ?? ""}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <select value={form.side} onChange={(e) => setForm({ ...form, side: e.target.value as Side })}
              className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm">
              <option value="buy">Compra</option>
              <option value="sell">Venta</option>
              <option value="dividend">Dividendo</option>
            </select>
            {!cash && (
              <input required type="number" step="any" placeholder="Cantidad" value={form.quantity}
                onChange={(e) => setForm({ ...form, quantity: e.target.value })}
                className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
            )}
            {!cash && (
              <input required type="number" step="any" placeholder="Precio/acción" value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value })}
                className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
            )}
            {cash && (
              <input required type="number" step="any" placeholder="Monto USD" value={form.amount}
                onChange={(e) => setForm({ ...form, amount: e.target.value })}
                className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm sm:col-span-2" />
            )}
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-6">
            {!cash && (
              <input type="number" step="any" placeholder="Comisiones" value={form.fees}
                onChange={(e) => setForm({ ...form, fees: e.target.value })}
                className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
            )}
            <input type="date" value={form.executed_at}
              onChange={(e) => setForm({ ...form, executed_at: e.target.value })}
              className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm sm:col-span-2" />
            <input placeholder="Notas (opcional)" value={form.notes}
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm sm:col-span-2" />
            <button type="submit" disabled={busy}
              className="rounded-md bg-term-accent px-3 py-1.5 text-sm font-semibold text-black hover:brightness-110 disabled:opacity-50">
              {busy ? "…" : "Registrar"}
            </button>
          </div>
          {picked && (
            <p className="text-xs text-term-good">
              ✓ {picked.ticker} — {picked.name ?? "sin nombre"} · {picked.asset_class ?? "?"} · {picked.exchange ?? ""}
            </p>
          )}
          {form.ticker && !picked && (
            <p className="text-xs text-term-warn">
              {form.ticker}: aún no verificado. Puedes registrarlo; se identificará y tomará precio en la
              próxima actualización diaria.
            </p>
          )}
          {msg && <p className="text-xs text-term-crit">{msg}</p>}
        </form>
      </Panel>

      <Panel title="Posiciones">
        {positions.filter((p) => p.qty > 1e-9).length === 0 ? (
          <p className="text-sm text-term-muted">Sin posiciones abiertas. Registra una compra arriba.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">Ticker</th><th>Nombre</th>
                  <th className="text-right">Cant.</th><th className="text-right">Costo prom.</th>
                  <th className="text-right">Precio</th><th className="text-right">P&L día</th>
                  <th className="text-right">Valor</th>
                  <th className="text-right">P&L no real.</th><th className="text-right">Peso</th>
                </tr>
              </thead>
              <tbody>
                {positions.filter((p) => p.qty > 1e-9).map((p) => {
                  const q = quotes[p.ticker];
                  const fresh = q ? classifyQuote(q.quote_time, q.market_state, q.delayed) : null;
                  const dot = !fresh ? "" : fresh.freshness === "live" ? "bg-term-good" : fresh.freshness === "stale" ? "bg-term-crit" : "bg-term-warn";
                  const dp = q && q.previous_close != null ? p.qty * (q.price - q.previous_close) : null;
                  return (
                  <tr key={p.ticker} className="border-b border-term-border last:border-0">
                    <td className="py-2"><Link to={`/research/${p.ticker}`} className="font-mono font-semibold text-term-accent hover:underline">{p.ticker}</Link></td>
                    <td className="max-w-[180px] truncate text-term-muted">{p.name ?? "—"}</td>
                    <td className="text-right tabnum">{num(p.qty, 4)}</td>
                    <td className="text-right tabnum">{money(p.avgCost)}</td>
                    <td className="text-right tabnum">
                      <span className="inline-flex items-center justify-end gap-1">
                        {dot && <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} title={fresh?.label} />}
                        {p.price !== null ? money(p.price) : <span className="text-term-warn">pendiente</span>}
                      </span>
                      {p.priceAsOf && <div className="text-[10px] text-term-faint">{p.priceAsOf}</div>}
                    </td>
                    <td className={`text-right tabnum ${dp === null ? "text-term-muted" : dp >= 0 ? "text-term-good" : "text-term-crit"}`}>
                      {dp !== null ? `${dp >= 0 ? "+" : ""}${money(dp)}` : "—"}
                    </td>
                    <td className="text-right tabnum">{p.marketValue !== null ? money(p.marketValue) : "—"}</td>
                    <td className={`text-right tabnum ${p.unrealized !== null && p.unrealized >= 0 ? "text-term-good" : p.unrealized !== null ? "text-term-crit" : ""}`}>
                      {p.unrealized !== null ? `${money(p.unrealized)} (${p.unrealizedPct !== null ? pct(p.unrealizedPct) : "—"})` : "—"}
                    </td>
                    <td className="text-right tabnum">
                      {totals.weights[p.ticker] !== undefined ? pct(totals.weights[p.ticker]) : "—"}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
            {totals && totals.missingPrices.length > 0 && (
              <p className="mt-2 text-xs text-term-warn">
                Sin precio todavía: {totals.missingPrices.join(", ")} (se cargan en la próxima actualización diaria).
              </p>
            )}
          </div>
        )}
      </Panel>

      <Panel title="Historial de operaciones">
        {txns.length === 0 ? (
          <p className="text-sm text-term-muted">Aún no hay operaciones registradas.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">Fecha</th><th>Ticker</th><th>Tipo</th>
                  <th className="text-right">Cant.</th><th className="text-right">Precio</th>
                  <th className="text-right">Comis.</th><th></th>
                </tr>
              </thead>
              <tbody>
                {[...txns].reverse().map((t) => (
                  <tr key={t.id} className="border-b border-term-border last:border-0">
                    <td className="py-2 tabnum text-term-muted">{t.executed_at}</td>
                    <td className="font-mono">{t.ticker}</td>
                    <td>{labelSide(t.side)}</td>
                    <td className="text-right tabnum">{t.quantity ?? (t.amount != null ? money(t.amount) : "—")}</td>
                    <td className="text-right tabnum">{t.price != null ? money(t.price) : "—"}</td>
                    <td className="text-right tabnum text-term-muted">{t.fees ? money(t.fees) : "—"}</td>
                    <td className="text-right">
                      <button onClick={() => remove(t.id)}
                        className="text-xs text-term-muted hover:text-term-crit">✕</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}

function labelSide(s: Side): string {
  return { buy: "Compra", sell: "Venta", dividend: "Dividendo", deposit: "Depósito",
           withdrawal: "Retiro", split: "Split" }[s] ?? s;
}
