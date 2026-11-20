import type { Metadata } from "next";
import type { ReactNode } from "react";
import { GoogleGate } from "@/components/layout/google-gate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Office document dashboard",
  description: "Preview and send office documents through WhatsApp.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body><GoogleGate>{children}</GoogleGate></body>
    </html>
  );
}
