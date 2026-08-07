import type { Metadata } from "next";
import { WaveBackdrop } from "../components/WaveBackdrop";
import { SITE_URL } from "../lib/site";
import "./globals.css";

const TAGLINE = "Should you buy it? The verdict, with receipts.";
const BLURB =
  "Steam verdicts built from real reviews, segmented by how long the reviewer actually played.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: `WorthIt.gg — ${TAGLINE}`,
  description: BLURB,
  openGraph: {
    type: "website",
    siteName: "WorthIt.gg",
    url: SITE_URL,
    title: `WorthIt.gg — ${TAGLINE}`,
    description: BLURB,
  },
  twitter: { card: "summary_large_image", title: "WorthIt.gg", description: BLURB },
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
