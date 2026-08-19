import type { Config } from "tailwindcss";

// Claude-desktop-inspired warm dark palette. Everything routes through CSS
// variables in globals.css so a future theme is a variable swap, not a refactor.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "var(--bg)",
        deep: "var(--bg-deep)",
        panel: "rgb(var(--panel-rgb) / <alpha-value>)",
        elev: "var(--elev)",
        line: "var(--line)",
        ink: "var(--ink)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "rgb(var(--accent-rgb) / <alpha-value>)",
        "accent-soft": "var(--accent-soft)",
        ok: "rgb(var(--ok-rgb) / <alpha-value>)",
        warn: "rgb(var(--warn-rgb) / <alpha-value>)",
        err: "rgb(var(--err-rgb) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "Cascadia Code", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};
export default config;
