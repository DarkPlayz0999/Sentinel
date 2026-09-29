import type { Config } from "tailwindcss";
import { C } from "./src/lib/theme";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: C,
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["var(--font-display)", "var(--font-sans)", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      // 15 px body, ~1.25 steps. Nothing in the product is set below 12 px.
      fontSize: {
        xs: ["12px", "16px"],
        sm: ["13px", "19px"],
        base: ["15px", "24px"],
        lg: ["18px", "26px"],
        xl: ["22px", "28px"],
        "2xl": ["28px", "32px"],
        "3xl": ["36px", "40px"],
        "4xl": ["48px", "50px"],
        "5xl": ["62px", "62px"],
      },
      borderRadius: { card: "6px", ctl: "4px" },
      maxWidth: { prose: "68ch" },
    },
  },
  plugins: [],
};
export default config;
