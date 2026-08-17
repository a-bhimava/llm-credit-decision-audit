import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Credit Decision Audit",
    template: "%s | Credit Decision Audit",
  },
  description: "Inspectable evidence for a causal underwriting-agent audit.",
};

export const viewport: Viewport = {
  themeColor: "#10212b",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

