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
          accent: "#e0a93c",
          good: "#35c07a",
          warn: "#e0a93c",
          crit: "#e5604d",
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
