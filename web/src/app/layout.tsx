import type { Metadata } from "next";
import { Atkinson_Hyperlegible, Bricolage_Grotesque } from "next/font/google";
import "./globals.css";

// Atkinson Hyperlegible for reading - drawn for low-vision legibility, so
// 0/O and 1/l/I never get confused in a serial or a reading. Bricolage
// Grotesque for display, its optical-size axis tightening at large sizes.
const body = Atkinson_Hyperlegible({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-sans",
  display: "swap",
});
const display = Bricolage_Grotesque({
  subsets: ["latin"],
  axes: ["opsz", "wdth"],
  variable: "--font-display",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SENTINEL — Burn-in screening",
  description:
    "Find the burn-in components that pass every datasheet limit but are abnormal in their own lot, forecast drift from the first 24 hours, and give every rejection a reason an inspector can check.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${body.variable} ${display.variable}`}>
      <body className="bg-paper font-sans text-base text-ink antialiased">{children}</body>
    </html>
  );
}
