/**
 * CROSS-LANGUAGE THEME GUARD
 *
 * Theme values are produced by the Python extraction schema and rendered by the
 * TypeScript UI. VerdictPage falls back to `?? t.theme`, so a theme the UI does
 * not know about does not throw - it renders the raw lowercase enum value as a
 * section header. That is a silent, shipping-quality bug, and adding `access`
 * to the Python enum was exactly the kind of change that causes it.
 *
 * Same shape as quota-mirror.contract.test.ts: parse the Python, compare.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { THEME_LABEL } from "../../components/VerdictPage";

const REPO = path.resolve(__dirname, "../../..");

/** Read the THEMES list out of pipeline/extract_claims.py. */
function pythonThemes(): string[] {
  const src = readFileSync(path.join(REPO, "pipeline/extract_claims.py"), "utf-8");
  const m = src.match(/^THEMES\s*=\s*\[([\s\S]*?)\]/m);
  if (!m) throw new Error("THEMES not found in extract_claims.py");
  return [...m[1].matchAll(/"([a-z_]+)"/g)].map((x) => x[1]);
}

describe("THEME_LABEL mirrors pipeline THEMES", () => {
  const themes = pythonThemes();

  it("found the Python enum", () => {
    expect(themes.length).toBeGreaterThan(1);
    expect(themes).toContain("performance");
  });

  it("every Python theme has a UI label", () => {
    const missing = themes.filter((t) => !(t in THEME_LABEL));
    expect(missing).toEqual([]);
  });

  it("access is a first-class theme, not folded into monetization", () => {
    // A launcher or a mandatory account is a barrier to PLAYING, not a price.
    // 11 claims across 8 published titles were filed as monetization because no
    // access bucket existed.
    expect(themes).toContain("access");
    expect(THEME_LABEL.access).toBe("Access");
  });

  it("no UI label invents a theme the pipeline cannot emit", () => {
    const extra = Object.keys(THEME_LABEL).filter((k) => !themes.includes(k));
    expect(extra).toEqual([]);
  });
});
