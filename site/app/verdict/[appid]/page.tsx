import { readFile } from "node:fs/promises";
import path from "node:path";
import { notFound } from "next/navigation";
import { VerdictPage } from "../../../components/VerdictPage";
import { VerdictView } from "../../../components/VerdictView";
import { loadVerdictStatic, normalizeVerdict, type Verdict } from "../../../lib/verdict";
import { catalog } from "../../../lib/catalog";
import { verdictMetadata } from "../../../lib/site";

/** Prerender every verdict we hold; anything else falls through to the proxy. */
export async function generateStaticParams() {
  return (await catalog()).map((e) => ({ appid: String(e.appid) }));
}

const readSite = (p: string) => readFile(path.join(process.cwd(), p), "utf-8");

/** Carries WHICH path answered alongside the verdict, because that is the
 *  cache/live distinction `verdict_view` reports and this is the only place
 *  that can tell them apart. Callers that do not care destructure `.verdict`. */
type Loaded = { verdict: Verdict; source: "cache" | "live" };

async function load(appid: string): Promise<Loaded | null> {
  try {
    return { verdict: await loadVerdictStatic(appid, readSite), source: "cache" };
  } catch {
    // freshly generated, not yet merged to main - serve from the verdicts branch
    const repo = process.env.GH_REPO;
    const token = process.env.GH_DISPATCH_TOKEN;
    if (!repo || !token) return null;
    const res = await fetch(
      `https://api.github.com/repos/${repo}/contents/site/public/verdicts/${appid}.json?ref=verdicts`,
      { headers: { accept: "application/vnd.github.raw", authorization: `Bearer ${token}` },
        next: { revalidate: 300 } },
    );
    if (!res.ok) return null;
    return { verdict: normalizeVerdict(JSON.parse(await res.text())), source: "live" };
  }
}

/**
 * Unfurl card. DESIGN.md's quality floor asks for real title AND OG tags per
 * game, because Reddit is the distribution channel - a shared link that renders
 * as a bare URL is a post nobody clicks.
 *
 * BOTH RENDER PATHS ARE COVERED BY CONSTRUCTION: this calls the same `load()`
 * the page component does, so a freshly generated title fetched through the
 * proxy gets the same card as a prerendered one. There is no second source of
 * metadata that could drift from the first.
 *
 * The image is Steam's `header.jpg`. Not `capsule_616x353.jpg`, which is larger
 * and better-proportioned but 301-redirects on some titles (GTA:SA among them),
 * and unfurlers are not required to follow redirects. header.jpg is a straight
 * 200 on every app checked, and 460x215 clears the summary_large_image floor.
 */
export async function generateMetadata({ params }: { params: Promise<{ appid: string }> }) {
  const { appid } = await params;
  const loaded = await load(appid);
  if (!loaded) return { title: "Not found — WorthIt.gg" };
  return verdictMetadata(loaded.verdict, appid);
}

export default async function Page({ params }: { params: Promise<{ appid: string }> }) {
  const { appid } = await params;
  const loaded = await load(appid);
  if (!loaded) notFound();
  return (
    <>
      <VerdictView
        appid={loaded.verdict.appid}
        verdictWord={loaded.verdict.verdict.word}
        source={loaded.source}
      />
      <VerdictPage verdict={loaded.verdict} />
    </>
  );
}
