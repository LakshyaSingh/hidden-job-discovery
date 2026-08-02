import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// SF Pro is used where it exists (see --font-body in globals.css); Inter is
// the fallback everywhere else, so non-Apple platforms get the same metrics
// rather than dropping to Arial.
const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Hidden Job Discovery",
  description: "Newly posted jobs, straight from company career portals.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={sans.variable}>
      <body>{children}</body>
    </html>
  );
}
