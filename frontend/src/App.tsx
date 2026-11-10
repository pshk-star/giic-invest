import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./lib/supabase";
import { Login } from "./pages/Login";
import { CommandCenter } from "./pages/CommandCenter";
import { Portfolio } from "./pages/Portfolio";
import { Advisor } from "./pages/Advisor";
import { Opportunities } from "./pages/Opportunities";
import { Research } from "./pages/Research";
import { CompanyFicha } from "./pages/Ficha";
import { Lab } from "./pages/Lab";
import { Forecast } from "./pages/Forecast";
import { FundamentalValuation } from "./pages/FundamentalValuation";

// P1.9 — feature flag REVERSIBLE: VITE_FF_FUNDVAL=1 muestra la vista de valoración fundamental
// (experimental). Ausente o distinto de "1" => oculta (por defecto apagada). No toca nada más.
const FF_FUNDVAL = import.meta.env.VITE_FF_FUNDVAL === "1";

const tabs = [
  { to: "/command", label: "Dashboard" },
  { to: "/portfolio", label: "Mi Cartera" },
  { to: "/forecast", label: "Proyección" },
  { to: "/advisor", label: "Investment Advisor" },
  { to: "/research", label: "Research" },
  { to: "/opportunities", label: "Oportunidades" },
  { to: "/lab", label: "Laboratorio" },
  ...(FF_FUNDVAL ? [{ to: "/fundamental", label: "Valoración ⚗" }] : []),
];

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setReady(true);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (!ready) return <div className="p-8 text-term-muted">Cargando…</div>;
  if (!session) return <Login />;

  const logout = () => supabase.auth.signOut();

  return (
    <div className="mx-auto flex min-h-full max-w-6xl flex-col px-4 pb-16">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-term-border py-4">
        <div className="flex items-center gap-3">
          <span className="font-head text-lg font-bold tracking-tight text-term-fg">GIIC</span>
          <span className="hidden text-xs text-term-muted sm:inline">
            Global Investment Intelligence Console
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden text-xs text-term-muted sm:inline">{session.user.email}</span>
          <button onClick={logout} className="text-xs text-term-muted hover:text-term-fg">
            Salir
          </button>
        </div>
      </header>

      <nav className="flex gap-1 py-3">
        {tabs.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `rounded-lg px-3 py-1.5 text-sm font-medium transition ${
                isActive ? "bg-term-panel2 text-term-fg" : "text-term-muted hover:text-term-fg"
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <main className="flex-1">
        <Routes>
          <Route path="/" element={<Navigate to="/command" replace />} />
          <Route path="/command" element={<CommandCenter />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/advisor" element={<Advisor />} />
          <Route path="/research" element={<Research />} />
          <Route path="/research/:ticker" element={<CompanyFicha />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/forecast" element={<Forecast />} />
          <Route path="/lab" element={<Lab />} />
          {FF_FUNDVAL && <Route path="/fundamental" element={<FundamentalValuation />} />}
        </Routes>
      </main>
    </div>
  );
}
