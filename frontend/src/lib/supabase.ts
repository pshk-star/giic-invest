import { createClient } from "@supabase/supabase-js";

// URL y ANON KEY son públicas por diseño (protegidas por RLS en la BD).
// Nunca se usa aquí la service_role key: esa vive solo en GitHub Actions.
const url = import.meta.env.VITE_SUPABASE_URL as string;
const anon = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!url || !anon) {
  // Mensaje claro en consola si falta configuración (ver DEPLOY_FREE.md).
  console.warn("Faltan VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY");
}

export const supabase = createClient(url ?? "", anon ?? "", {
  auth: { persistSession: true, autoRefreshToken: true },
});
