import { useMemo, type ReactNode } from "react";
import { Panel } from "./Panel";
import type { FundamentalsPayload, EnrichedField, HistoryRecord } from "../core/valuation";
import { num, pct } from "../format";

// Escala en MONEDA NATIVA (no fuerza USD): evita confundir divisas (EUR/TWD/DKK/USD).
function scaleNative(v: number | null | undefined, ccy?: string | null): string {
  if (v === null || v === undefined || !isFinite(v)) return "—";
  const a = Math.abs(v), s = v < 0 ? "-" : "", c = ccy || "";
  if (a >= 1e12) return `${s}${(a / 1e12).toFixed(2)} B ${c}`.trim();      // billones (1e12)
  if (a >= 1e9) return `${s}${(a / 1e9).toFixed(a / 1e9 >= 100 ? 0 : 1)} mm ${c}`.trim(); // mil millones
  if (a >= 1e6) return `${s}${(a / 1e6).toFixed(0)} M ${c}`.trim();        // millones
  return `${s}${a.toFixed(0)} ${c}`.trim();
}

const PERIOD_LABEL: Record<string, string> = {
  anual: "Anual", ttm: "TTM", trimestre_individual: "Trim", ytd_acumulado: "YTD",
  balance_instantaneo: "Balance", indeterminado: "Período ?",
};
const QUALITY_CLASS: Record<string, string> = {
  verificado: "text-term-good border-term-good/40", parcial: "text-term-info border-term-info/40",
  desactualizado: "text-term-muted border-term-border", inconsistente: "text-term-crit border-term-crit/40",
  faltante: "text-term-faint border-term-border",
};

function Tag({ children, cls = "text-term-faint border-term-border" }: { children: ReactNode; cls?: string }) {
  return <span className={`inline-block px-1.5 py-[1px] rounded border text-[10px] font-mono leading-tight ${cls}`}>{children}</span>;
}

// Tarjeta KPI: valor + badges (período · fuente · calidad). Nunca presenta parcial como verificado.
function Kpi({ label, value, help, period, source, quality, eligible }: {
  label: string; value: string; help?: string; period?: string | null;
  source?: "EDGAR" | "EODHD" | null; quality?: string | null; eligible?: boolean;
}) {
  return (
    <div className="border border-term-border rounded bg-term-panel2/40 p-2.5 flex flex-col gap-1">
      <div className="text-[11px] text-term-muted leading-tight">{label}</div>
      <div className="text-lg font-mono text-term-fg tabnum leading-none">{value}</div>
      <div className="flex flex-wrap gap-1 items-center mt-0.5">
        {period && <Tag>{PERIOD_LABEL[period] ?? period}</Tag>}
        {source && <Tag cls={source === "EDGAR" ? "text-term-good border-term-good/40" : "text-term-accent border-term-accent/40"}>{source}</Tag>}
        {quality && quality !== "verificado" && <Tag cls={QUALITY_CLASS[quality] ?? ""}>{quality}</Tag>}
        {eligible === true && <Tag cls="text-term-info border-term-info/40">valoración</Tag>}
      </div>
      {help && <div className="text-[10px] text-term-faint leading-tight mt-0.5">{help}</div>}
    </div>
  );
}

// Mini-gráfico SVG de líneas (serie temporal corta). Sin dependencias; colores de la paleta de datos.
function MiniChart({ series, height = 90, bars = false }: {
  series: { name: string; color: string; points: Array<{ x: string; y: number | null }> }[]; height?: number; bars?: boolean;
}) {
  const W = 320, H = height, pad = 6;
  const xs = series[0]?.points.map((p) => p.x) ?? [];
  const vals = series.flatMap((s) => s.points.map((p) => p.y).filter((y): y is number => y !== null && isFinite(y)));
  if (!vals.length || xs.length < 2) return <div className="text-[11px] text-term-faint py-6 text-center">Sin serie suficiente</div>;
  let lo = Math.min(...vals, 0), hi = Math.max(...vals, 0);
  if (lo === hi) { hi = lo + 1; }
  const x = (i: number) => pad + (i * (W - 2 * pad)) / Math.max(1, xs.length - 1);
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo)) * (H - 2 * pad);
  const zeroY = y(0);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }}>
      {lo < 0 && hi > 0 && <line x1={pad} x2={W - pad} y1={zeroY} y2={zeroY} stroke="#263142" strokeWidth={1} />}
      {series.map((s, si) => bars ? (
        <g key={si}>{s.points.map((p, i) => p.y === null ? null : (
          <rect key={i} x={x(i) - 4 + si * 4} y={Math.min(y(p.y), zeroY)} width={4}
                height={Math.abs(y(p.y) - zeroY)} fill={s.color} opacity={0.85} />
        ))}</g>
      ) : (
        <polyline key={si} fill="none" stroke={s.color} strokeWidth={1.75}
                  points={s.points.map((p, i) => p.y === null ? "" : `${x(i)},${y(p.y)}`).filter(Boolean).join(" ")} />
      ))}
      {xs.map((xl, i) => (i === 0 || i === xs.length - 1) && (
        <text key={i} x={x(i)} y={H - 1} fontSize={8} fill="#5c6676" textAnchor={i === 0 ? "start" : "end"}>{xl.slice(0, 4)}</text>
      ))}
    </svg>
  );
}

function ChartCard({ title, children, legend }: { title: string; children: ReactNode; legend?: ReactNode }) {
  return (
    <div className="border border-term-border rounded bg-term-panel2/30 p-3">
      <div className="flex items-center justify-between mb-1">
        <div className="text-[11px] text-term-muted font-head tracking-wide uppercase">{title}</div>
        <div className="flex gap-2 text-[10px] text-term-faint">{legend}</div>
      </div>
      {children}
    </div>
  );
}

export function FinancialFiche({ fund }: { fund: FundamentalsPayload }) {
  const enr = fund.enrichment ?? null;
  const hist = (fund.history?.annual ?? []).filter((h) => h && h.period_end) as HistoryRecord[];
  const reportCcy = fund.history?.currency ?? fund.currency ?? enr?.currency ?? "USD";
  const last = hist.length ? hist[hist.length - 1] : null;
  const prev = hist.length > 1 ? hist[hist.length - 2] : null;
  const ef = (k: string): EnrichedField | null => (enr?.fields ?? {})[k] ?? null;
  const quarantine = Object.entries(enr?.quarantine ?? {});

  const revGrowth = useMemo(() => {
    if (last?.revenue != null && prev?.revenue) return last.revenue / prev.revenue - 1;
    return fund.rev_growth_yoy ?? null;
  }, [last, prev, fund.rev_growth_yoy]);

  const hasEnrich = !!enr && (Object.keys(enr.fields ?? {}).length > 0 || quarantine.length > 0);
  const hasHistory = hist.length >= 2;
  const noData = !hasHistory && !hasEnrich && fund.pe_ttm == null && fund.fcf_annual == null && last == null;

  if (noData) {
    return (
      <Panel title="Ficha financiera">
        <div className="text-sm text-term-muted">
          No hay fundamentales persistidos para este instrumento. Si es una empresa internacional fuera del
          universo diario, puede enriquecerse on-demand desde Research.
        </div>
      </Panel>
    );
  }

  // Interino fresco (EODHD) para OCF/FCF/caja/deuda cuando aplica (solo recencia, no valoración salvo balance).
  const interimTag = (k: string) => {
    const f = ef(k); if (!f || f.value == null) return undefined;
    return `${PERIOD_LABEL[f.period_type ?? ""] ?? ""} ${f.period_end ?? ""} (EODHD)`.trim();
  };

  return (
    <div className="flex flex-col gap-3">
      <Panel title="Ficha financiera">
        <div className="text-[11px] text-term-faint mb-2">
          Moneda de reporte <span className="text-term-muted">{reportCcy}</span>
          {fund.as_of && <> · último ejercicio EDGAR <span className="text-term-muted">{fund.as_of}</span></>}
          {enr?.edgar_data_end && enr.generated_at && <> · interino EODHD al <span className="text-term-muted">{enr.fields?.revenue?.period_end ?? "—"}</span></>}
          {fund.source_kind === "eodhd_primary" && <> · <span className="text-term-accent">fuente primaria EODHD (sin ancla SEC)</span></>}
        </div>

        {/* KPIs principales */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <Kpi label="Ingresos (anual)" value={scaleNative(last?.revenue, reportCcy)}
               period="anual" source="EDGAR" help={revGrowth != null ? `crec. ${pct(revGrowth)}` : undefined} />
          <Kpi label="Margen operativo" value={pct(last?.op_margin ?? fund.operating_margin)} period="anual" source="EDGAR" />
          <Kpi label="Margen neto" value={pct(last?.net_margin ?? fund.net_margin)} period="anual" source="EDGAR" />
          <Kpi label="Utilidad neta (anual)" value={scaleNative(last?.net_income, reportCcy)} period="anual" source="EDGAR" />

          <Kpi label="EPS (anual)" value={fund.eps_annual != null ? num(fund.eps_annual, 2) : (fund.eps != null ? num(fund.eps, 2) : "—")} period="anual" source="EDGAR" />
          <Kpi label="EPS (TTM)" value={fund.eps_ttm != null ? num(fund.eps_ttm, 2) : "—"} period="ttm" source="EDGAR" help="diluido, split-safe" />
          <Kpi label="OCF (anual)" value={scaleNative(last?.ocf, reportCcy)} period="anual" source="EDGAR" help={interimTag("ocf")} />
          <Kpi label="CAPEX (anual)" value={scaleNative(last?.capex, reportCcy)} period="anual" source="EDGAR" />

          <Kpi label="FCF (anual)" value={scaleNative(fund.fcf_annual ?? last?.fcf, reportCcy)} period="anual" source="EDGAR" />
          <Kpi label="FCF (TTM)" value={fund.fcf_ttm != null ? scaleNative(fund.fcf_ttm, reportCcy) : "—"} period="ttm" source="EDGAR" />
          <Kpi label="Caja" value={scaleNative(fund.cash_and_sti ?? last?.cash, reportCcy)} period="balance" source={ef("cash") ? "EODHD" : "EDGAR"}
               quality={ef("cash")?.quality_state ?? undefined} eligible={ef("cash")?.valuation_eligible} help={interimTag("cash")} />
          <Kpi label="Deuda neta" value={scaleNative(fund.net_debt ?? last?.net_debt, reportCcy)} period="balance"
               source={ef("total_debt") ? "EODHD" : "EDGAR"} quality={ef("total_debt")?.quality_state ?? undefined} help={interimTag("total_debt")} />

          <Kpi label="ROE" value={pct(fund.roe)} period="anual" source="EDGAR" />
          <Kpi label="ROIC" value={fund.roic != null ? pct(fund.roic) : "no disp."} />
          <Kpi label="P/E" value={fund.pe_ttm != null ? `${num(fund.pe_ttm, 1)}×` : "—"} period="anual" source="EDGAR" help="sobre EPS anual (no TTM)" />
          <Kpi label="FCF yield" value={pct(fund.fcf_yield)} source="EDGAR" help={fund.fcf_yield ? `P/FCF ≈ ${num(1 / fund.fcf_yield, 1)}×` : undefined} />
        </div>
        {fund.ev_ebitda == null && (
          <div className="text-[10px] text-term-faint mt-2">EV/EBITDA y EBITDA no disponibles de forma confiable con datos oficiales gratuitos; no se estiman.</div>
        )}
      </Panel>

      {/* Gráficos de evolución histórica */}
      {hasHistory && (
        <Panel title="Evolución histórica (anual · SEC EDGAR)">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <ChartCard title={`Ingresos (${reportCcy})`}>
              <MiniChart bars series={[{ name: "Ingresos", color: "#4ea1d3", points: hist.map((h) => ({ x: h.period_end, y: h.revenue })) }]} />
            </ChartCard>
            <ChartCard title="Márgenes" legend={<><span className="text-term-good">● neto</span><span className="text-term-info">● operativo</span></>}>
              <MiniChart series={[
                { name: "op", color: "#4ea1d3", points: hist.map((h) => ({ x: h.period_end, y: h.op_margin != null ? h.op_margin * 100 : null })) },
                { name: "net", color: "#35c07a", points: hist.map((h) => ({ x: h.period_end, y: h.net_margin != null ? h.net_margin * 100 : null })) },
              ]} />
            </ChartCard>
            <ChartCard title={`Free Cash Flow (${reportCcy})`}>
              <MiniChart bars series={[{ name: "FCF", color: "#48c9b0", points: hist.map((h) => ({ x: h.period_end, y: h.fcf })) }]} />
            </ChartCard>
            <ChartCard title={`Caja vs deuda neta (${reportCcy})`} legend={<><span className="text-term-good">● caja</span><span className="text-term-crit">● deuda neta</span></>}>
              <MiniChart series={[
                { name: "caja", color: "#35c07a", points: hist.map((h) => ({ x: h.period_end, y: h.cash })) },
                { name: "deuda", color: "#e5604d", points: hist.map((h) => ({ x: h.period_end, y: h.net_debt })) },
              ]} />
            </ChartCard>
          </div>
        </Panel>
      )}

      {/* Calidad, actualidad y cuarentena */}
      {(hasEnrich || enr) && (
        <Panel title="Procedencia, actualidad y calidad del dato">
          <div className="flex flex-wrap gap-2 items-center text-[11px] mb-2">
            <Tag cls="text-term-good border-term-good/40">EDGAR oficial (ancla)</Tag>
            {hasEnrich && <Tag cls="text-term-accent border-term-accent/40">EODHD {enr?.symbol} · {enr?.currency}</Tag>}
            {enr?.generated_at && <span className="text-term-faint">generado {enr.generated_at}</span>}
            {enr?.carried_forward && <Tag cls="text-term-muted border-term-border">conservado (scan EDGAR-only)</Tag>}
          </div>
          <div className="text-[11px] text-term-faint leading-snug">
            <span className="text-term-info">valoración</span> = período/definición apto; <b>no</b> implica dato
            verificado (ver calidad por campo). Interinos de un trimestre o YTD y EPS de EODHD no son aptos para
            valoración directa.
          </div>
          {quarantine.length > 0 && (
            <div className="mt-3 border-t border-term-border pt-2">
              <div className="text-[11px] text-term-crit mb-1">En cuarentena (discrepancia material vs EDGAR — no se usa):</div>
              {quarantine.map(([k, v]) => (
                <div key={k} className="text-[11px] text-term-muted font-mono">
                  {k}: {scaleNative(v.value, v.currency)} · {v.quality_state} · {String(v.source).slice(0, 48)}
                </div>
              ))}
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
