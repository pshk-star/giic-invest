// P3.0 Ficha de empresa — DINÁMICA por ticker. Lee lo que el motor ya calculó (valoración, modelos,
// fundamentales); no recalcula ni modifica Fair Values. Conserva acceso al análisis financiero profundo
// existente (/research/:ticker).
import { useParams, useNavigate, Link } from "react-router-dom";
import { useP30 } from "./P30Layout";
import { num, pct } from "../format";
import type { OpportunityRec } from "../core/advisor-engine";

function stateChip(o?: OpportunityRec): { cls: string; label: string } {
  if (!o) return { cls: "c-insuf", label: "en cartera / s/clasificar" };
  switch (o.class) {
    case "compra_recomendada": return { cls: "c-buy", label: "Comprar" };
    case "oportunidad_analizada": return o.buyable ? { cls: "c-buy", label: "Comprar · experimental" } : { cls: "c-res", label: "Analizada · restringida" };
    case "candidata_investigacion": return { cls: "c-res", label: "Investigar · no comprable" };
    case "poco_atractiva": return { cls: "c-insuf", label: "Poco atractiva" };
    default: return { cls: "c-insuf", label: "Evidencia insuficiente" };
  }
}
const f1 = (x: number | null | undefined, suf = "") => (x == null ? "n/d" : num(x, 1) + suf);

export function FichaP30() {
  const { ticker = "" } = useParams();
  const t = ticker.toUpperCase();
  const d = useP30();
  const nav = useNavigate();

  if (d.loading) return <div className="state">Cargando…</div>;
  if (d.err) return <div className="state err">No se pudieron cargar los datos: {d.err}</div>;

  const cv = d.fv[t];
  const inst = d.instruments[t];
  const opp = d.report?.opportunities.find((o) => o.ticker === t);
  const chip = stateChip(opp);
  const models = cv?.modelos ?? [];
  const gov = models.find((m) => m.modelo === "DCF_productivo" && m.disponible !== false && m.fair_value_usd != null)
    ?? models.find((m) => m.modelo === "FCFF_GIIC" && m.disponible !== false && m.fair_value_usd != null)
    ?? models.find((m) => m.disponible !== false && m.fair_value_usd != null);
  const price = cv?.precio ?? d.prices[t]?.close ?? null;
  const fvUsd = gov?.fair_value_usd ?? null;
  const margin = gov?.margen_seguridad_pct != null ? gov.margen_seguridad_pct / 100 : (opp?.margin ?? null);
  const fu = d.fundamentals[t] ?? {};

  // gauge precio vs FV (0..100% del eje): precio y FV normalizados a un rango común
  let pricePos = 50, fvPos = 50;
  if (price != null && fvUsd != null && price > 0 && fvUsd > 0) {
    const lo = Math.min(price, fvUsd) * 0.9, hi = Math.max(price, fvUsd) * 1.1, span = hi - lo || 1;
    pricePos = ((price - lo) / span) * 100;
    fvPos = ((fvUsd - lo) / span) * 100;
  }

  return (
    <div>
      <button className="ficha-back" onClick={() => nav("/p30/oportunidades")}>‹ Volver a oportunidades</button>
      <div className="ficha-head">
        <div>
          <div className="nm2">{inst?.name ?? t} <small>{t}</small></div>
          <div className="sct">{[inst?.sector, inst?.exchange].filter(Boolean).join(" · ") || "—"}</div>
        </div>
        <span className={"mini-chip " + chip.cls} style={{ alignSelf: "center" }}>{chip.label}</span>
      </div>

      {cv == null ? (
        <div className="minibox" style={{ marginTop: 16 }}>
          Sin valoración concluyente para {t}: evidencia insuficiente. GIIC no inventa un Fair Value.
        </div>
      ) : (
        <>
          <div className="fv-row">
            <div className="m"><div className="l">Precio</div><div className="v">{price != null ? num(price, 2) : "n/d"}</div></div>
            <div className="m"><div className="l">Fair Value ({gov?.modelo === "DCF_productivo" ? "productivo" : "FCFF"})</div><div className="v" style={{ color: margin != null && margin > 0 ? "var(--buy)" : "var(--fg)" }}>{fvUsd != null ? num(fvUsd, 2) : "n/d"}</div></div>
            <div className="m"><div className="l">Margen de seguridad</div><div className="v" style={{ color: margin == null ? "var(--muted)" : margin > 0 ? "var(--buy)" : "var(--reduce)" }}>{margin != null ? (margin >= 0 ? "+" : "") + pct(margin, 0) : "n/d"}</div></div>
          </div>

          {price != null && fvUsd != null && (
            <div className="minibox">
              <h6>Precio vs Fair Value</h6>
              <div style={{ position: "relative", height: 30, margin: "4px 0" }}>
                <div style={{ position: "absolute", top: 15, left: 0, right: 0, height: 2, background: "var(--line)" }} />
                <div style={{ position: "absolute", top: 15, height: 2, background: "var(--buy)", left: `${Math.min(pricePos, fvPos)}%`, width: `${Math.abs(fvPos - pricePos)}%` }} />
                <span style={{ position: "absolute", top: 8, height: 14, width: 2, background: "var(--fg)", left: `${pricePos}%` }} />
                <span style={{ position: "absolute", top: -2, left: `${pricePos}%`, transform: "translateX(-50%)", fontSize: 10, color: "var(--fg)", whiteSpace: "nowrap" }}>precio {num(price, 0)}</span>
                <span style={{ position: "absolute", top: 15, height: 14, width: 2, background: "var(--buy)", left: `${fvPos}%` }} />
                <span style={{ position: "absolute", top: 22, left: `${fvPos}%`, transform: "translateX(-50%)", fontSize: 10, color: "var(--buy)", whiteSpace: "nowrap" }}>FV {num(fvUsd, 0)}</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--faint)", marginTop: 6 }}>
                {margin != null && margin > 0 ? "Precio por debajo del Fair Value: margen de seguridad positivo." : "Precio por encima del Fair Value: sin margen de seguridad."}
              </div>
            </div>
          )}

          <div className="sub-grid">
            <div className="minibox"><h6>Modelos</h6>
              {models.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>Sin modelos disponibles.</div>}
              {models.map((m) => {
                const ms = m.disponible === false ? null : m.margen_seguridad_pct;
                return (
                  <div className="kv" key={m.modelo}>
                    <span>{m.modelo}</span>
                    <b style={{ color: ms == null ? "var(--faint)" : "var(--fg)" }}>
                      {ms == null ? "no disponible" : `${ms >= 0 ? "+" : ""}${pct(ms / 100, 0)}${m.confianza ? " · " + m.confianza : ""}`}
                    </b>
                  </div>
                );
              })}
              {opp && <div className="kv"><span>Fuente gobernante</span><b>{opp.source}{opp.confidence ? " · " + opp.confidence : ""}</b></div>}
            </div>
            <div className="minibox"><h6>Fundamentales</h6>
              <div className="kv"><span>ROIC</span><b>{f1(fu.roic != null ? fu.roic * (Math.abs(fu.roic) < 1 ? 100 : 1) : null, "%")}</b></div>
              <div className="kv"><span>Crecimiento ventas</span><b>{f1(fu.rev_growth_yoy != null ? fu.rev_growth_yoy * (Math.abs(fu.rev_growth_yoy) < 1 ? 100 : 1) : null, "%")}</b></div>
              <div className="kv"><span>Margen operativo</span><b>{f1(fu.operating_margin != null ? fu.operating_margin * (Math.abs(fu.operating_margin) < 1 ? 100 : 1) : null, "%")}</b></div>
              <div className="kv"><span>Margen neto</span><b>{f1(fu.net_margin != null ? fu.net_margin * (Math.abs(fu.net_margin) < 1 ? 100 : 1) : null, "%")}</b></div>
            </div>
          </div>

          <div className="minibox" style={{ marginTop: 12 }}><h6>Lectura y riesgos</h6>
            <ul className="risks">
              {opp?.why && <li style={{ color: "var(--muted)" }}>{opp.why}</li>}
              {gov?.modelo !== "DCF_productivo" && <li>Valoración apoyada en FCFF (experimental): menor convicción que un FV productivo; requiere valoración productiva para ser confiable.</li>}
              {margin != null && Math.abs(margin) >= 0.8 && <li>Margen extremo (≥80%): confianza degradada por control de calidad; no habilita asignación.</li>}
            </ul>
          </div>
        </>
      )}

      <Link className="deep" to={`/research/${t}`}>Abrir análisis financiero profundo →</Link>
      <div className="note"><span className="i">◆</span><span>Esta ficha solo muestra lo que el motor ya calcula: no recalcula valoraciones ni modifica Fair Values.</span></div>
    </div>
  );
}
