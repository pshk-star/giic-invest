/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// El frontend habla con Supabase (VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  test: {
    environment: "node", // las pruebas de analytics son puras (sin DOM)
    include: ["src/**/*.test.ts"],
  },
});
