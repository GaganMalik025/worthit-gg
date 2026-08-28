/** Build-time index of the verdicts we hold, read from site/public/verdicts/. */
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const DIR = path.join(process.cwd(), "public/verdicts");

/**
 * Cover art captured at generation time (pipeline/art.py).
 *
 * `grid` is COMMUNITY-UPLOADED fan art from SteamGridDB and is licensed here
 * for grid tiles only. It must never reach an OpenGraph image - see
 * lib/site.ts, which reads header_image and cannot see this field - and as of
 * 2026-08-28 it does not reach the case hero either: lib/art.ts gates it behind
 * `allowGrid`, which only the home grid passes.
 *
 * One definition, in lib/art.ts, beside the chain that consumes it.
 */
export type { Art } from "./art";
import type { Art } from "./art";

export interface CatalogEntry {
  appid: number;
  game_name: string;
  word: string;
  pool_n: number;
  art: Art;
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
        // no header prose here on purpose: the home grid is poster + title +
        // chip (DESIGN.md), so carrying it would be a field nothing renders
        pool_n: v.footer?.pool_n ?? 0,
        // Older verdicts predate the art block; {} keeps them on the legacy
        // pattern rather than crashing the grid.
        art: (v.art ?? {}) as CatalogEntry["art"],
        split_bar: (v.split_bar ?? []).map((b: CatalogEntry["split_bar"][0]) => ({
          bucket: b.bucket, pct_positive: b.pct_positive, muted: b.muted,
        })),
      };
    }),
  );
  return rows.sort((a, b) => b.pool_n - a.pool_n);
}
