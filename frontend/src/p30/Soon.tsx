// P3.0 — destino aún no implementado (entrega por etapas). Mantiene la navegación completa.
export function P30Soon({ stage, title }: { stage: string; title: string }) {
  return (
    <div>
      <div className="s-head"><div><div className="s-kick">{stage}</div><div className="s-title">{title}</div></div></div>
      <div className="minibox" style={{ marginTop: 16 }}>
        <div style={{ fontSize: 13 }}>Esta pantalla llega en <b style={{ color: "var(--gold)" }}>{stage}</b>.</div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 8 }}>
          Inicio y Oportunidades ya están conectados a datos reales. Mi cartera, Asignación e Historial se implementan a continuación, reutilizando los mismos motores.
        </div>
      </div>
    </div>
  );
}
