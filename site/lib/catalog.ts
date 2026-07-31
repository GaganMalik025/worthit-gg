/** Build-time index of the verdicts we hold, read from site/public/verdicts/. */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const DIR = path.join(process.cwd(), "public/verdicts");

export interface CatalogEntry {
  appid: number;
  game_name: string;
  word: string;
  for_whom: string;
  pool_n: number;
  split_bar: { bucket: string; pct_positive: number; muted: boolean }[];
}

export async function catalog(): Promise<CatalogEntry[]> {
  let files: string[] = [];
  try {
    files = (await readdir(DIR)).filter((f) => f.endsWith(".json"));
  } catch {
    return [];
  }
  const rows = await Promise.all(
    files.map(async (f) => {
      const v = JSON.parse(await readFile(path.join(DIR, f), "utf-8"));
      return {
        appid: Number(v.appid),
        game_name: v.game_name,
        word: v.verdict.word,
        for_whom: v.verdict.for_whom,
        pool_n: v.footer?.pool_n ?? 0,
        split_bar: (v.split_bar ?? []).map((b: CatalogEntry["split_bar"][0]) => ({
          bucket: b.bucket, pct_positive: b.pct_positive, muted: b.muted,
        })),
      };
    }),
  );
  return rows.sort((a, b) => b.pool_n - a.pool_n);
}
