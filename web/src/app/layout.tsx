import type { Metadata } from "next";
import { Archivo } from "next/font/google";
import "./globals.css";

// One variable family. The width axis does the work a second typeface would:
// expanded for display, normal for reading, condensed for column heads.
const archivo = Archivo({
  subsets: ["latin"],
  axes: ["wdth"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "SENTINEL — Burn-in screening",
  description:
    "Find the burn-in components that pass every datasheet limit but are abnormal in their own lot, forecast drift from the first 24 hours, and give every rejection a reason an inspector can check.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={archivo.variable}>
      <body className="bg-paper font-sans text-base text-ink antialiased">{children}</body>
    </html>
  );
}
