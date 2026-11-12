// P3.0 — Shell de navegación (riel + barra inferior) con carga ÚNICA de datos compartida por contexto.
// Reversible: vive bajo VITE_FF_P30 y /p30; la interfaz anterior permanece intacta y accesible.
import { createContext, useContext } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAdvisorData, type AdvisorData } from "./useAdvisorData";
import "./p30.css";

const Ctx = createContext<AdvisorData | null>(null);
export function useP30(): AdvisorData {
  const v = useContext(Ctx);
  if (!v) throw new Error("useP30 fuera de P30Layout");
  return v;
}

const DEST = [
  { to: "/p30", end: true, ic: "◎", label: "Inicio", short: "Inicio" },
  { to: "/p30/oportunidades", end: false, ic: "◈", label: "Oportunidades", short: "Oportun." },
  { to: "/p30/cartera", end: false, ic: "▣", label: "Mi cartera", short: "Cartera" },
  { to: "/p30/historial", end: false, ic: "↻", label: "Historial", short: "Historial" },
];

export function P30Layout() {
  const data = useAdvisorData();
  return (
    <div className="p30">
      <Ctx.Provider value={data}>
        <div className="p30-shell">
          <aside className="p30-rail">
            <div className="rb"><span className="dot" />GIIC</div>
            {DEST.map((d) => (
              <NavLink key={d.to} to={d.to} end={d.end}
                className={({ isActive }) => "p30-nav" + (isActive ? " active" : "")}>
                <span className="ic">{d.ic}</span>{d.label}
              </NavLink>
            ))}
            <div className="foot">
              Recomendaciones simuladas · política única · motores sin cambios.
              <br /><NavLink to="/command">← interfaz anterior</NavLink>
            </div>
          </aside>
          <main className="p30-main"><Outlet /></main>
          <nav className="p30-tabs">
            {DEST.map((d) => (
              <NavLink key={d.to} to={d.to} end={d.end}
                className={({ isActive }) => (isActive ? "active" : "")}>
                <span className="ic">{d.ic}</span>{d.short}
              </NavLink>
            ))}
          </nav>
        </div>
      </Ctx.Provider>
    </div>
  );
}
