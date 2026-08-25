import type { Metadata, Viewport } from "next";
import { Montserrat, Lora, Courier_Prime } from "next/font/google";
import "./globals.css";

const fontSans = Montserrat({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const fontSerif = Lora({
  subsets: ["latin"],
  variable: "--font-serif",
  display: "swap",
});

const fontMono = Courier_Prime({
  weight: "400",
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

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
    <html lang="en" className={`${fontSans.variable} ${fontSerif.variable} ${fontMono.variable} antialiased`}>
      <body>{children}</body>
    </html>
  );
}
