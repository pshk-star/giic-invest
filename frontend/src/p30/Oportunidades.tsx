// P3.0 Oportunidades — listado simple por estado (del motor). Toca una empresa para abrir su ficha.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useP30 } from "./P30Layout";
import { MissingProfile } from "./MissingProfile";
import type { OpportunityRec } from "../core/advisor-engine";
import { pct } from "../format";

type Filter = "todo" | "comprable" | "investig";

function stateOf(o: OpportunityRec): { cls: string; label: string; color: string } {
  switch (o.class) {
    case "compra_recomendada": return { cls: "c-buy", label: "Comprar", color: "var(--buy)" };
    case "oportunidad_analizada": return o.buyable
      ? { cls: "c-buy", label: "Comprar · exp", color: "var(--buy)" }
      : { cls: "c-res", label: "Analizada", color: "var(--research)" };
    case "candidata_investigacion": return { cls: "c-res", label: "Investigar", color: "var(--research)" };
    case "poco_atractiva": return { cls: "c-insuf", label: "Poco atractiva", color: "var(--insuf)" };
    default: return { cls: "c-insuf", label: "Insuficiente", color: "var(--insuf)" };
  }
}

export function Oportunidades() {
  const d = useP30();
  const nav = useNavigate();
  const [f, setF] = useState<Filter>("todo");

  if (d.loading) return <div className="state">Calculando…</div>;
  if (d.missing) return <MissingProfile missing={d.missing} />;
  if (d.err) return <div className="state err">No se pudieron cargar los datos: {d.err}</div>;
  if (!d.report) return <div className="state">Sin datos.</div>;

  const all = d.report.opportunities;
  const list = all.filter((o) =>
    f === "todo" ? true : f === "comprable" ? o.buyable : o.class === "candidata_investigacion");

  return (
    <div>
      <div className="s-head">
        <div><div className="s-kick">Universo · {d.report.coverage.total} nombres, {d.report.coverage.evaluated} valorados</div><div className="s-title">Oportunidades</div></div>
      </div>
      <div className="opp-filter">
        <button className={f === "todo" ? "on" : ""} onClick={() => setF("todo")}>Todo</button>
        <button className={f === "comprable" ? "on" : ""} onClick={() => setF("comprable")}>Comprables</button>
        <button className={f === "investig" ? "on" : ""} onClick={() => setF("investig")}>Investigación</button>
      </div>
      <div className="block" style={{ marginTop: 8 }}>
        {list.length === 0 && <div className="state">Nada en este filtro.</div>}
        {list.map((o) => {
          const st = stateOf(o);
          return (
            <button key={o.ticker} className="opp" onClick={() => nav(`/p30/oportunidades/${o.ticker}`)}>
              <div className="score" style={{ color: st.color }}>{o.margin != null ? (o.margin >= 0 ? "+" : "") + pct(o.margin, 0) : "—"}</div>
              <div className="meta">
                <div className="t">{o.ticker}{o.name ? <small>{o.name}</small> : null}</div>
                <div className="d">{o.why}</div>
              </div>
              <span className={"mini-chip " + st.cls}>{st.label}</span>
              <span className="chev">›</span>
            </button>
          );
        })}
      </div>
      <div className="note"><span className="i">◆</span><span>Toca cualquier empresa para abrir su ficha: precio, Fair Value, modelos, fundamentales, riesgos y acceso al análisis profundo.</span></div>
    </div>
  );
}
