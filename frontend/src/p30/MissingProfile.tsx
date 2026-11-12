// P3.0 — estado de datos faltantes: GIIC no inventa el perfil; lo pide con claridad.
import { Link } from "react-router-dom";

export function MissingProfile({ missing }: { missing: string[] }) {
  return (
    <div className="missing">
      <div className="s-head"><div><div className="s-kick">Configuración</div><div className="s-title">Falta tu perfil</div></div></div>
      <div className="mbox">
        <div style={{ fontSize: 13 }}>
          Para calcular recomendaciones GIIC necesita datos esenciales que <b>no inventa</b>:
          <b style={{ color: "var(--gold)" }}> {missing.join(", ")}</b>.
        </div>
        <div style={{ fontSize: 12.5, color: "var(--muted)", marginTop: 10 }}>
          Configúralos una vez en el asesor y los análisis correrán automáticamente.
        </div>
        <Link to="/asesor" style={{ display: "inline-block", marginTop: 12, fontSize: 13, fontWeight: 600, color: "var(--gold)", border: "1px solid var(--gold)", borderRadius: 9, padding: "9px 14px" }}>
          Configurar perfil →
        </Link>
      </div>
    </div>
  );
}
