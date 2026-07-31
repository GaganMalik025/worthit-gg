import { readFile } from "node:fs/promises";
import path from "node:path";
import { notFound } from "next/navigation";
import { VerdictPage } from "../../../components/VerdictPage";
import { loadVerdictStatic, normalizeVerdict, type Verdict } from "../../../lib/verdict";
import { catalog } from "../../../lib/catalog";

/** Prerender every verdict we hold; anything else falls through to the proxy. */
export async function generateStaticParams() {
  return (await catalog()).map((e) => ({ appid: String(e.appid) }));
}

const readSite = (p: string) => readFile(path.join(process.cwd(), p), "utf-8");

async function load(appid: string): Promise<Verdict | null> {
  try {
    return await loadVerdictStatic(appid, readSite);
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
    return normalizeVerdict(JSON.parse(await res.text()));
  }
}

export async function generateMetadata({ params }: { params: Promise<{ appid: string }> }) {
  const { appid } = await params;
  const v = await load(appid);
  if (!v) return { title: "Not found — WorthIt.gg" };
  return {
    title: `${v.game_name}: ${v.verdict.word} — WorthIt.gg`,
    description: v.verdict.for_whom,
  };
}

export default async function Page({ params }: { params: Promise<{ appid: string }> }) {
  const { appid } = await params;
  const v = await load(appid);
  if (!v) notFound();
  return <VerdictPage verdict={v} />;
}
