import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // Instrument panel palette. Light, matte, no glow - this is a lab,
        // not a spaceship bridge.
        lab: {
          floor: "#E8E9EB",
          panel: "#F6F6F5",
          card: "#FFFFFF",
          sunk: "#DEDFE2",
          rule: "#C6C9CF",
          hair: "#E1E3E6",
          ink: "#0F1317",
          dim: "#59616D",
          faint: "#8C939E",
        },
        sig: {
          blue: "#12508C",
          green: "#186B45",
          amber: "#9A5B06",
          red: "#A81E12",
        },
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      letterSpacing: { label: "0.14em" },
      animation: {
        "led": "led 2.4s ease-in-out infinite",
        "shimmer": "shimmer 3.2s ease-in-out infinite",
        "trace": "trace 2.6s linear infinite",
      },
      keyframes: {
        led: { "0%,100%": { opacity: "1" }, "50%": { opacity: "0.35" } },
        shimmer: {
          "0%,100%": { transform: "translateY(0) scaleX(1)", opacity: "0.5" },
          "50%": { transform: "translateY(-6px) scaleX(1.04)", opacity: "0.9" },
        },
        trace: { "0%": { strokeDashoffset: "40" }, "100%": { strokeDashoffset: "0" } },
      },
    },
  },
  plugins: [],
};
export default config;
