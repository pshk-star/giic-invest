import { useState } from "react";
import { supabase } from "../lib/supabase";

// GIIC es de un solo usuario autorizado: NO hay registro público. Solo iniciar
// sesión y restablecer contraseña. El alta del usuario se hace una vez desde el
// panel de Supabase (ver DEPLOY_FREE.md) y los registros públicos se deshabilitan allí.
type Mode = "signin" | "reset";

export function Login() {
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      if (mode === "signin") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(email);
        if (error) throw error;
        setMsg("Si el correo existe, recibirás un enlace para restablecer la contraseña.");
      }
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Error de autenticación.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-col justify-center px-4">
      <div className="rounded-xl border border-term-border bg-term-panel p-6">
        <h1 className="font-head text-xl font-bold text-term-fg">GIIC</h1>
        <p className="mb-5 text-sm text-term-muted">Global Investment Intelligence Console</p>
        <form onSubmit={submit} className="flex flex-col gap-3">
          <input
            autoFocus type="email" placeholder="Correo" value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-sm"
          />
          {mode === "signin" && (
            <input
              type="password" placeholder="Contraseña" value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="rounded-md border border-term-border bg-term-panel2 px-3 py-2 text-sm"
            />
          )}
          {err && <p className="text-sm text-term-crit">{err}</p>}
          {msg && <p className="text-sm text-term-good">{msg}</p>}
          <button type="submit" disabled={busy}
            className="rounded-md bg-term-accent px-4 py-2 text-sm font-semibold text-black hover:brightness-110 disabled:opacity-50">
            {busy ? "…" : mode === "signin" ? "Entrar" : "Enviar enlace"}
          </button>
        </form>
        <div className="mt-4 flex gap-3 text-xs text-term-muted">
          <button onClick={() => { setMode("signin"); setErr(null); setMsg(null); }} className="hover:text-term-fg">
            Iniciar sesión
          </button>
          <button onClick={() => { setMode("reset"); setErr(null); setMsg(null); }} className="hover:text-term-fg">
            Olvidé mi contraseña
          </button>
        </div>
      </div>
    </div>
  );
}
