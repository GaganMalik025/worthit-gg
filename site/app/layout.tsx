import type { Metadata } from "next";
import { WaveBackdrop } from "../components/WaveBackdrop";
import "./globals.css";

export const metadata: Metadata = {
  title: "WorthIt.gg — Should you buy it? The verdict, with receipts.",
  description:
    "Steam verdicts built from real reviews, segmented by how long the reviewer actually played.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <WaveBackdrop />
        {children}
      </body>
    </html>
  );
}
