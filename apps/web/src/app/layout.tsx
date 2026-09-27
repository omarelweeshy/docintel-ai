import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Shell } from "@/components/shell";
export const metadata: Metadata = { title: "DocIntel AI | Document intelligence", description: "Explore your documents with grounded answers and inspectable sources." };
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><Providers><Shell>{children}</Shell></Providers></body></html>;
}
