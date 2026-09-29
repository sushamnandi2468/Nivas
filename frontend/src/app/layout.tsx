import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "NivasOps | Society Operations",
  description: "Secure helpdesk and facility operations for modern communities.",
  applicationName: "NivasOps",
  authors: [{ name: "Susham Nandi", url: "https://github.com/sushamnandi2468/Nivas" }],
  generator: "NivasOps Engine v0.1.0",
  other: {
    "nivas-engine": "NivasOps",
    "nivas-license": "AGPL-3.0-or-later",
    "nivas-author": "Susham Nandi",
    "nivas-provenance": "7b3f94e1-2a8d-5e63-91c7-d4f092b1a852",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" data-engine="nivasops" data-provenance="7b3f94e1">
      <body>{children}</body>
    </html>
  );
}
