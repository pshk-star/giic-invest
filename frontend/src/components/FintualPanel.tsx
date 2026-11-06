import { useEffect, useMemo, useState } from "react";
import { Panel } from "./Panel";
import {
  addFund, addFundNav, addTransaction, archiveFund, getFunds, getFundNavs, getFxRates,
  type FundNavRow, type FundRow,
} from "../data";
import type { Txn } from "../core/portfolio-tx";
import { valueFund, type FundMove } from "../core/funds";
import { FINTUAL_MX_FUNDS } from "../core/fintual-catalog";
import { money, num } from "../format";

const todayISO = () => new Date().toISOString().slice(0, 10);

// Panel de fondos Fintual dentro de Mi Cartera: alta manual, movimientos (aportación/retiro),
// NAV fechado, valorización en moneda del fondo y consolidación a USD.
export function FintualPanel({ txns, stocksUsd, onChange }:
  { txns: Txn[]; stocksUsd: number; onChange: () => void }) {
  const [funds, setFunds] = useState<FundRow[]>([]);
  const [navs, setNavs] = useState<FundNavRow[]>([]);
  const [fx, setFx] = useState<Record<string, number>>({ USD: 1 });
  const [msg, setMsg] = useState<string | null>(null);
  const [tab, setTab] = useState<"fondo" | "mov" | "nav">("fondo");

  // formularios
  const [fForm, setFForm] = useState({ symbol: "", name: "", currency: "MXN" });
  const [mForm, setMForm] = useState({ fund_id: "", side: "buy", quantity: "", price: "", executed_at: todayISO() });
  const [nForm, setNForm] = useState({ fund_id: "", as_of: todayISO(), nav: "" });

  const reload = async () => {
    const [fs, ns] = await Promise.all([getFunds(), getFundNavs()]);
    setFunds(fs); setNavs(ns);
  };
  useEffect(() => {
    reload().catch(() => {});
    getFxRates("USD").then(setFx).catch(() => setFx({ USD: 1 }));
  }, []);

  const latestNav = (fundId: string): FundNavRow | null => {
    const today = todayISO();
    const c = navs.filter((n) => n.fund_id === fundId && n.as_of <= today);
    return c.length ? c[0] : null; // navs vienen ordenados desc por as_of
  };

  const rows = useMemo(() => funds.map((f) => {
    const moves: FundMove[] = txns.filter((t) => t.fund_id === f.id && (t.side === "buy" || t.side === "sell"))
      .map((t) => ({ side: t.side as "buy" | "sell", quantity: t.quantity, price: t.price, fees: t.fees }));
    const nav = latestNav(f.id);
    const fxToBase = f.currency === "USD" ? 1 : (fx[f.currency] ?? null);
    const v = valueFund(moves, nav?.nav ?? null, nav?.as_of ?? null, f.currency, fxToBase);
    return { f, v };
  }), [funds, navs, txns, fx]);

  const fundsUsd = rows.reduce((s, r) => s + (r.v.valueBase ?? 0), 0);
  const consolidated = stocksUsd + fundsUsd;
  const anyMissingFx = rows.some((r) => r.v.valueFundCcy != null && r.v.valueBase == null);

  const submitFund = async () => {
    try {
      if (!fForm.symbol.trim()) { setMsg("Símbolo requerido."); return; }
      await addFund({ symbol: fForm.symbol, name: fForm.name || undefined, currency: fForm.currency });
      setFForm({ symbol: "", name: "", currency: "MXN" }); setMsg("Fondo agregado.");
      await reload();
    } catch (e) { setMsg(`No se pudo agregar (¿migración 0009 aplicada?): ${String(e).slice(0, 120)}`); }
  };
  const submitMov = async () => {
    try {
      if (!mForm.fund_id || !mForm.quantity || !mForm.price) { setMsg("Fondo, participaciones y NAV requeridos."); return; }
      const f = funds.find((x) => x.id === mForm.fund_id);
      await addTransaction({
        ticker: f?.symbol ?? "FUND", side: mForm.side as "buy" | "sell",
        quantity: Number(mForm.quantity), price: Number(mForm.price), fees: 0,
        currency: f?.currency ?? "MXN", executed_at: mForm.executed_at, fund_id: mForm.fund_id,
      });
      setMForm({ ...mForm, quantity: "", price: "" }); setMsg("Movimiento registrado.");
      onChange(); await reload();
    } catch (e) { setMsg(`No se pudo registrar: ${String(e).slice(0, 120)}`); }
  };
  const submitNav = async () => {
    try {
      if (!nForm.fund_id || !nForm.nav) { setMsg("Fondo y NAV requeridos."); return; }
      const f = funds.find((x) => x.id === nForm.fund_id);
      await addFundNav({ fund_id: nForm.fund_id, as_of: nForm.as_of, nav: Number(nForm.nav), currency: f?.currency ?? "MXN" });
      setNForm({ ...nForm, nav: "" }); setMsg("NAV actualizado.");
      await reload();
    } catch (e) { setMsg(`No se pudo guardar NAV: ${String(e).slice(0, 120)}`); }
  };

  return (
    <Panel title="Fondos (Fintual)">
      {funds.length === 0 ? (
        <p className="text-sm text-term-muted">
          Aún no has agregado fondos. Usa «Agregar fondo» abajo. (Si falla, la migración 0009 aún no está aplicada.)
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-xs uppercase text-term-muted">
                  <th className="py-1.5">Fondo</th><th className="text-right">Participaciones</th>
                  <th className="text-right">NAV (fecha)</th><th className="text-right">Valor</th>
                  <th className="text-right">Valor USD</th><th className="text-right">Ganancia</th><th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map(({ f, v }) => (
                  <tr key={f.id} className="border-b border-term-border last:border-0">
                    <td className="py-2 font-mono font-semibold">{f.symbol}<span className="ml-1 text-xs text-term-faint">{f.currency}</span></td>
                    <td className="text-right tabnum">{num(v.units, 4)}</td>
                    <td className="text-right tabnum">{v.latestNav != null ? `${num(v.latestNav, 4)} · ${v.navDate}` : <span className="text-term-warn">sin NAV</span>}</td>
                    <td className="text-right tabnum">{v.valueFundCcy != null ? `${money(v.valueFundCcy)} ${f.currency}` : "—"}</td>
                    <td className="text-right tabnum">{v.valueBase != null ? money(v.valueBase) : <span className="text-term-warn">sin TC</span>}</td>
                    <td className={`text-right tabnum ${(v.gainFundCcy ?? 0) >= 0 ? "text-term-good" : "text-term-crit"}`}>
                      {v.gainFundCcy != null ? `${v.gainFundCcy >= 0 ? "+" : ""}${money(v.gainFundCcy)} ${f.currency}` : "—"}
                    </td>
                    <td className="text-right">
                      <button onClick={() => archiveFund(f.id).then(reload).catch(() => {})}
                              className="text-[10px] text-term-faint hover:text-term-crit">archivar</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm">
            <span className="text-term-muted">Acciones/ETF: <b className="tabnum text-term-fg">{money(stocksUsd)}</b></span>
            <span className="text-term-muted">Fondos: <b className="tabnum text-term-fg">{money(fundsUsd)}</b></span>
            <span className="text-term-muted">Consolidado (USD): <b className="tabnum text-term-accent">{money(consolidated)}</b></span>
            {fx.MXN ? <span className="text-xs text-term-faint">· 1 MXN = {num(fx.MXN, 4)} USD</span> : null}
          </div>
          {anyMissingFx && <p className="mt-1 text-xs text-term-warn">Algún fondo no tiene tipo de cambio para su moneda; su valor USD no se consolida.</p>}
        </>
      )}

      {/* Formularios */}
      <div className="mt-3 border-t border-term-border pt-3">
        <div className="mb-2 flex gap-1 text-xs">
          {(["fondo", "mov", "nav"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)}
              className={`rounded px-2 py-1 ${tab === t ? "bg-term-panel2 text-term-fg" : "text-term-muted"}`}>
              {t === "fondo" ? "Agregar fondo" : t === "mov" ? "Registrar movimiento" : "Actualizar NAV"}
            </button>
          ))}
        </div>
        {tab === "fondo" && (
          <div className="grid gap-2">
            <select
              className={inp}
              value={FINTUAL_MX_FUNDS.find((f) => f.symbol === fForm.symbol) ? fForm.symbol : ""}
              onChange={(e) => {
                const f = FINTUAL_MX_FUNDS.find((x) => x.symbol === e.target.value);
                if (f) setFForm({ symbol: f.symbol, name: f.name, currency: f.currency });
                else setFForm({ symbol: "", name: "", currency: "MXN" });
              }}>
              <option value="">— Elige un fondo Fintual México —</option>
              {FINTUAL_MX_FUNDS.map((f) => <option key={f.symbol} value={f.symbol}>{f.name} ({f.currency})</option>)}
              <option value="__custom">Otro (manual)…</option>
            </select>
            {(() => {
              const sel = FINTUAL_MX_FUNDS.find((f) => f.symbol === fForm.symbol);
              return sel?.note ? <p className="text-[11px] text-term-faint">{sel.note}</p> : null;
            })()}
            <div className="flex flex-wrap items-end gap-2">
              <input placeholder="Símbolo" value={fForm.symbol}
                onChange={(e) => setFForm({ ...fForm, symbol: e.target.value })} className={inp} />
              <input placeholder="Nombre" value={fForm.name}
                onChange={(e) => setFForm({ ...fForm, name: e.target.value })} className={inp} />
              <select value={fForm.currency} onChange={(e) => setFForm({ ...fForm, currency: e.target.value })} className={inp}>
                <option>MXN</option><option>USD</option>
              </select>
              <button onClick={submitFund} className={btn}>Agregar</button>
            </div>
          </div>
        )}
        {tab === "mov" && (
          <div className="flex flex-wrap items-end gap-2">
            <select value={mForm.fund_id} onChange={(e) => setMForm({ ...mForm, fund_id: e.target.value })} className={inp}>
              <option value="">Fondo…</option>{funds.map((f) => <option key={f.id} value={f.id}>{f.symbol}</option>)}
            </select>
            <select value={mForm.side} onChange={(e) => setMForm({ ...mForm, side: e.target.value })} className={inp}>
              <option value="buy">Aportación (compra)</option><option value="sell">Retiro (venta)</option>
            </select>
            <input type="number" step="any" placeholder="Participaciones" value={mForm.quantity}
              onChange={(e) => setMForm({ ...mForm, quantity: e.target.value })} className={inp} />
            <input type="number" step="any" placeholder="NAV de la operación" value={mForm.price}
              onChange={(e) => setMForm({ ...mForm, price: e.target.value })} className={inp} />
            <input type="date" value={mForm.executed_at}
              onChange={(e) => setMForm({ ...mForm, executed_at: e.target.value })} className={inp} />
            <button onClick={submitMov} className={btn}>Registrar</button>
          </div>
        )}
        {tab === "nav" && (
          <div className="flex flex-wrap items-end gap-2">
            <select value={nForm.fund_id} onChange={(e) => setNForm({ ...nForm, fund_id: e.target.value })} className={inp}>
              <option value="">Fondo…</option>{funds.map((f) => <option key={f.id} value={f.id}>{f.symbol}</option>)}
            </select>
            <input type="date" value={nForm.as_of}
              onChange={(e) => setNForm({ ...nForm, as_of: e.target.value })} className={inp} />
            <input type="number" step="any" placeholder="Valor cuota (NAV)" value={nForm.nav}
              onChange={(e) => setNForm({ ...nForm, nav: e.target.value })} className={inp} />
            <button onClick={submitNav} className={btn}>Guardar NAV</button>
          </div>
        )}
        {msg && <p className="mt-2 text-xs text-term-muted">{msg}</p>}
      </div>
    </Panel>
  );
}

const inp = "rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm text-term-fg";
const btn = "rounded-md bg-term-accent px-3 py-1.5 text-sm font-medium text-term-bg hover:opacity-90";
