/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./templates/**/*.html", "./static/app.js"],
  safelist: [
    "status-new",
    "status-progress",
    "status-done",
    "status-cancelled",
    "priority-low",
    "priority-medium",
    "priority-high",
    "priority-urgent",
    "chip-neutral",
    "chip-accent",
    "bg-emerald-600",
    "bg-blue-600",
    "bg-amber-600",
    "bg-rose-600",
    "bg-zinc-500",
    "text-emerald-700",
    "text-blue-700",
    "text-amber-700",
    "text-rose-700",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#f5f5f2",
        surface: "#ffffff",
        ink: {
          DEFAULT: "#15181b",
          soft: "#3c4248",
          muted: "#666d75",
          dim: "#98a0a8",
        },
        line: {
          DEFAULT: "#e6e4de",
          strong: "#d6d3ca",
        },
        accent: {
          DEFAULT: "#1b6b4f",
          hover: "#15553e",
          soft: "#e9f3ed",
          ink: "#0f3d2e",
        },
        sidebar: "#101413",
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        display: ["Inter Tight Variable", "Inter Tight", "Inter Variable", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(20, 24, 27, 0.04), 0 1px 3px rgba(20, 24, 27, 0.03)",
        lift: "0 10px 30px -12px rgba(20, 24, 27, 0.25)",
      },
      borderRadius: {
        xl: "12px",
        "2xl": "16px",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        "fade-up": "fade-up .28s cubic-bezier(.22,1,.36,1) both",
        "fade-in": "fade-in .2s ease both",
      },
    },
  },
  plugins: [],
};
