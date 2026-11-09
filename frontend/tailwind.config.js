/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        term: {
          bg: "#0b0f16",
          panel: "#121824",
          panel2: "#1a2230",
          border: "#263142",
          fg: "#e6eaf0",
          muted: "#8b95a5",
          faint: "#5c6676",   // 3er nivel de texto (antes indefinido → clases inertes): jerarquía
          accent: "#e0a93c",  // ámbar: selección / acento de marca
          good: "#35c07a",    // verde: positivo / verificado
          warn: "#d8863a",    // naranja: atención (distinto del acento, antes idéntico)
          crit: "#e5604d",    // rojo: negativo / crítico
          info: "#4ea1d3",    // azul: informativo / vigente
        },
        // Paleta de DATOS (series/factores) — separada de la semántica; buen contraste en dark.
        data: {
          1: "#4ea1d3",   // azul
          2: "#35c07a",   // verde
          3: "#e0a93c",   // ámbar
          4: "#b07de0",   // violeta
          5: "#e5604d",   // rojo/coral
          6: "#48c9b0",   // teal
        },
      },
      fontFamily: {
        mono: ["IBM Plex Mono", "ui-monospace", "monospace"],
        sans: ["IBM Plex Sans", "system-ui", "sans-serif"],
        head: ["Saira Semi Condensed", "sans-serif"],
      },
    },
  },
  plugins: [],
};
