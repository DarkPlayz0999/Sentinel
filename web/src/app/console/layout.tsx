import type { Metadata } from "next";
import { ConsoleShell } from "@/components/console/shell";

export const metadata: Metadata = {
  title: "SENTINEL — Screening Console",
  description:
    "Lot-relative anomaly detection, drift forecasting and auditable screening decisions for component burn-in.",
};

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
