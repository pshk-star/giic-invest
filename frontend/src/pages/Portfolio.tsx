import { useEffect, useRef, useState } from "react";
import { Panel } from "../components/Panel";
import { addPosition, deletePosition, getFxRates, getPositions, getPrices } from "../data";
import { distribution, valuation, type Position, type Valuation } from "../core/analytics";
import { money, pct } from "../format";

const EMPTY = { ticker: "", quantity: "", avg_cost: "", asset_class: "equity", sector: "", currency: "USD", country: "US" };

export function Portfolio() {
  const [positions, setPositions] = useState<(Position & { id: string })[]>([]);
  const [val, setVal] = useState<Valuation | null>(null);
  const [form, setForm] = useState({ ...EMPTY });
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const refresh = async () => {
    const pos = (await getPositions()) as (Position & { id: string })[];
    setPositions(pos);
    if (pos.length) {
      const prices = await getPrices(pos.map((p) => p.ticker));
      const fx = await getFxRates("USD");
      setVal(valuation(pos, prices, fx));
    } else {
      setVal(null);
    }
  };

  useEffect(() => {
    refresh().catch((e) => setMsg(String(e)));
  }, []);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await addPosition({
        ticker: form.ticker.toUpperCase(),
        name: form.ticker.toUpperCase(),
        quantity: Number(form.quantity),
        avg_cost: Number(form.avg_cost),
        asset_class: form.asset_class,
        sector: form.sector || null,
        currency: form.currency.toUpperCase(),
        country: form.country.toUpperCase(),
      });
      setForm({ ...EMPTY });
      setMsg(null);
      await refresh();
    } catch (e) {
      setMsg(String(e));
    }
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      const text = await f.text();
      const [header, ...lines] = text.trim().split(/\r?\n/);
      const cols = header.split(",").map((c) => c.trim().toLowerCase());
      let created = 0;
      for (const line of lines) {
        const cells = line.split(",");
        const row: Record<string, string> = {};
        cols.forEach((c, i) => (row[c] = (cells[i] ?? "").trim()));
        if (!row.ticker) continue;
        await addPosition({
          ticker: row.ticker.toUpperCase(),
          name: (row.name || row.ticker).toUpperCase(),
          quantity: Number(row.quantity),
          avg_cost: Number(row.avg_cost ?? row.avg_price ?? 0),
          asset_class: (row.asset_class || "equity").toLowerCase(),
          sector: row.sector || null,
          currency: (row.currency || "USD").toUpperCase(),
          country: (row.country || "US").toUpperCase(),
        });
        created++;
      }
      setMsg(`Importadas ${created} posiciones.`);
      await refresh();
    } catch (err) {
      setMsg(String(err));
    }
    if (fileRef.current) fileRef.current.value = "";
  };

  const byTicker: Record<string, any> = {};
  val?.positions.forEach((p) => (byTicker[p.ticker] = p));

  return (
    <div className="grid gap-4">
      <Panel
        title="Agregar posición"
        right={
          <label className="cursor-pointer text-xs text-term-accent hover:underline">
            Importar CSV
            <input ref={fileRef} type="file" accept=".csv" onChange={onFile} className="hidden" />
          </label>
        }
      >
        <form onSubmit={add} className="grid grid-cols-2 gap-2 sm:grid-cols-7">
          <input required placeholder="Ticker" value={form.ticker}
            onChange={(e) => setForm({ ...form, ticker: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm uppercase" />
          <input required type="number" step="any" placeholder="Cantidad" value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
          <input required type="number" step="any" placeholder="Costo prom." value={form.avg_cost}
            onChange={(e) => setForm({ ...form, avg_cost: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
          <select value={form.asset_class} onChange={(e) => setForm({ ...form, asset_class: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm">
            <option value="equity">Acción</option>
            <option value="etf">ETF</option>
          </select>
          <input placeholder="Sector" value={form.sector}
            onChange={(e) => setForm({ ...form, sector: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm" />
          <input placeholder="Moneda" value={form.currency}
            onChange={(e) => setForm({ ...form, currency: e.target.value })}
            className="rounded-md border border-term-border bg-term-panel2 px-2 py-1.5 text-sm uppercase" />
          <button type="submit"
            className="rounded-md bg-term-accent px-3 py-1.5 text-sm font-semibold text-black hover:brightness-110">
            Agregar
          </button>
        </form>
        {msg && <p className="mt-2 text-xs text-term-muted">{msg}</p>}
      </Panel>

      <Panel title="Posiciones">
        {positions.length === 0 ? (
          <p className="text-sm text-term-muted">Sin posiciones. Agrega una arriba o importa un CSV.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-term-border text-left text-xs uppercase text-term-muted">
                  <th className="py-2">Ticker</th><th>Clase</th><th>Cant.</th><th>Costo</th>
                  <th className="text-right">Precio</th><th className="text-right">Valor</th>
                  <th className="text-right">P&L</th><th className="text-right">Peso</th><th></th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => {
                  const v = byTicker[p.ticker];
                  return (
                    <tr key={p.id} className="border-b border-term-border last:border-0">
                      <td className="py-2 font-mono font-semibold">{p.ticker}</td>
                      <td className="text-term-muted">{p.asset_class}</td>
                      <td className="tabnum">{p.quantity}</td>
                      <td className="tabnum text-term-muted">{p.avg_cost}</td>
                      <td className="text-right tabnum">{v?.price != null ? money(v.price, p.currency) : "—"}</td>
                      <td className="text-right tabnum">{v?.market_value != null ? money(v.market_value, "USD") : "—"}</td>
                      <td className={`text-right tabnum ${v?.pnl != null && v.pnl >= 0 ? "text-term-good" : "text-term-crit"}`}>
                        {v?.pnl_pct != null ? pct(v.pnl_pct) : "—"}
                      </td>
                      <td className="text-right tabnum">{v?.weight != null ? pct(v.weight) : "—"}</td>
                      <td className="text-right">
                        <button onClick={() => deletePosition(p.id).then(refresh)}
                          className="text-xs text-term-muted hover:text-term-crit">✕</button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            {val && val.missing_prices.length > 0 && (
              <p className="mt-2 text-xs text-term-warn">
                Sin precio actualizado para: {val.missing_prices.join(", ")} (fuera del universo del job o sin tasa FX).
              </p>
            )}
          </div>
        )}
      </Panel>

      {val && (
        <div className="grid gap-4 md:grid-cols-3">
          {(["sector", "country", "asset_class"] as const).map((k) => (
            <Panel key={k} title={`Distribución · ${k}`}>
              <ul className="flex flex-col gap-1.5 text-sm">
                {Object.entries(distribution(val, k)).map(([name, w]) => (
                  <li key={name} className="flex items-center justify-between gap-2">
                    <span className="truncate text-term-muted">{name}</span>
                    <span className="tabnum">{pct(w)}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      )}
    </div>
  );
}
