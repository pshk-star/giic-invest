import { useState } from "react";
import * as XLSX from "xlsx";
import { addUserEtfHoldings } from "../data";
import { normalizeHoldings, parseCsv, type ParsedHoldings } from "../core/holdings-parse";

const todayISO = () => new Date().toISOString().slice(0, 10);

// Importación MANUAL de un archivo OFICIAL de holdings (CSV/XLSX) para un ETF.
// Parsea en el navegador, previsualiza y guarda en Supabase (tabla por usuario, 0011).
export function HoldingsImport({ etfs, onImported }: { etfs: string[]; onImported: () => void }) {
  const [etf, setEtf] = useState("");
  const [asOf, setAsOf] = useState(todayISO());
  const [fileName, setFileName] = useState("");
  const [parsed, setParsed] = useState<ParsedHoldings | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const onFile = async (file: File) => {
    setMsg(null); setParsed(null); setFileName(file.name);
    try {
      let matrix: string[][];
      if (/\.xlsx?$/i.test(file.name)) {
        const buf = await file.arrayBuffer();
        const wb = XLSX.read(buf, { type: "array" });
        const ws = wb.Sheets[wb.SheetNames[0]];
        const rows = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, raw: false, defval: "" });
        matrix = rows.map((r) => (r as unknown[]).map((c) => String(c ?? "")));
      } else {
        matrix = parseCsv(await file.text());
      }
      setParsed(normalizeHoldings(matrix));
    } catch (e) {
      setMsg(`No se pudo leer el archivo: ${String(e).slice(0, 120)}`);
    }
  };

  const confirm = async () => {
    if (!etf) { setMsg("Elige el ETF al que corresponde el archivo."); return; }
    if (!parsed || parsed.lines.length === 0) { setMsg("Nada que importar."); return; }
    setBusy(true); setMsg(null);
    try {
      const rows = parsed.lines.map((l) => ({
        etf: etf.toUpperCase(), as_of: asOf, provider: "manual", source_file: fileName,
        ticker: l.ticker, name: l.name, cusip: l.cusip, company_key: l.companyKey,
        sector: l.sector, asset_class: l.assetClass, weight: l.weight, line_key: l.lineKey,
      }));
      await addUserEtfHoldings(rows);
      setMsg(`Importado: ${rows.length} líneas de ${etf.toUpperCase()} (${parsed.status === "complete" ? "completo" : "parcial"}).`);
      setParsed(null); setFileName("");
      onImported();
    } catch (e) {
      setMsg(`No se pudo guardar (¿migración 0011 aplicada?): ${String(e).slice(0, 140)}`);
    } finally { setBusy(false); }
  };

  const top5 = parsed ? [...parsed.lines].filter((l) => l.weight != null).sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0)).slice(0, 5) : [];

  return (
    <div className="rounded-lg border border-term-border bg-term-panel2 p-3">
      <div className="mb-2 text-xs uppercase text-term-muted">Importar composición oficial (CSV/XLSX del emisor)</div>
      <div className="flex flex-wrap items-end gap-2">
        <select value={etf} onChange={(e) => setEtf(e.target.value)} className={inp}>
          <option value="">ETF…</option>{etfs.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        <label className="text-xs text-term-muted">Vigencia
          <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} className={`${inp} ml-1`} /></label>
        <input type="file" accept=".csv,.xlsx,.xls"
          onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
          className="text-xs text-term-muted" />
      </div>

      {parsed && (
        <div className="mt-2 text-xs">
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            <span>Líneas: <b>{parsed.nLines}</b></span>
            <span>Σ pesos: <b className={parsed.status === "complete" ? "text-term-good" : "text-term-warn"}>{(parsed.weightSum * 100).toFixed(1)}%</b></span>
            <span>Estado: <b className={parsed.status === "complete" ? "text-term-good" : "text-term-warn"}>{parsed.status === "complete" ? "completo" : "parcial"}</b></span>
            {parsed.columns.ticker && <span className="text-term-faint">col ticker: {parsed.columns.ticker}</span>}
          </div>
          {parsed.status !== "complete" && <p className="mt-1 text-term-warn">Composición parcial (pesos no suman ~100%): se marcará como parcial, no como exacta.</p>}
          <div className="mt-1 text-term-faint">Top: {top5.map((l) => `${l.ticker ?? l.name} ${((l.weight ?? 0) * 100).toFixed(1)}%`).join(" · ")}</div>
          <button onClick={confirm} disabled={busy} className={`${btn} mt-2`}>{busy ? "Guardando…" : "Importar a mi cartera"}</button>
        </div>
      )}
      {msg && <p className="mt-2 text-xs text-term-muted">{msg}</p>}
      <p className="mt-2 text-[10px] text-term-faint">
        Descarga el archivo de holdings desde el sitio OFICIAL del emisor (Vanguard, Invesco, Schwab…) y súbelo.
        No se inventan composiciones; se conserva el nombre del archivo como procedencia.
      </p>
    </div>
  );
}

const inp = "rounded-md border border-term-border bg-term-panel px-2 py-1.5 text-sm text-term-fg";
const btn = "rounded-md bg-term-accent px-3 py-1.5 text-sm font-medium text-term-bg hover:opacity-90 disabled:opacity-50";
