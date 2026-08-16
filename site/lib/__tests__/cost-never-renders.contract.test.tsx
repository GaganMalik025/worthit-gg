/**
 * THE COST FIELD IS A PIPELINE DIAGNOSTIC AND MUST NEVER REACH A READER
 *
 * synthesize.py now writes `cost.model_calls` into every verdict it produces,
 * so the live path can read back what a generation really spent and hand the
 * unused part of its reservation back to the quota ledger. That number is
 * bookkeeping about OUR budget. It says nothing about the game, and invariant
 * 13 is explicit that pipeline diagnostics - how many reviews a quota kept, how
 * many a filter spared, how many an LLM read - never render.
 *
 * The risk is specific rather than theoretical. normalizeVerdict spreads the
 * raw object (`...v`), which is what lets `art` and future fields survive
 * without being enumerated - so `cost` is ALREADY present on the Verdict object
 * both loaders hand to the page. Nothing but this test stands between it and a
 * component that decides to be helpful with an unrecognised field.
 *
 * A comment could not hold this. The og-tags contract test exists for the same
 * reason about SteamGridDB art, and it is the model here: assert against the
 * surfaces a reader actually sees.
 */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VerdictPage } from "../../components/VerdictPage";
import { verdictMetadata } from "../site";
import { normalizeVerdict, type Verdict } from "../verdict";

const REPO = path.resolve(__dirname, "../..");
const APPID = 233860; // Kenshi - committed seed, real pipeline output

const readRepoFile = (p: string) => readFile(path.join(REPO, p), "utf-8");

/**
 * Deliberately not a plausible call count. The assertion is about
 * DETECTABILITY in markup: a realistic 9 appears in a hundred innocent places
 * (percentages, pool counts, hour ranges), so it could not distinguish "the
 * cost field rendered" from "the page contains the digit 9". These cannot occur
 * by accident.
 */
const SENTINEL_CALLS = 8675309;
const SENTINEL_BASIS = "COST-BASIS-SENTINEL-DO-NOT-RENDER";

async function verdictWithCost(): Promise<Verdict> {
  const raw = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
  raw.cost = { model_calls: SENTINEL_CALLS, basis: SENTINEL_BASIS };
  return normalizeVerdict(raw);
}

describe("cost never renders", () => {
  it("survives normalizeVerdict - so this test is guarding something real", async () => {
    // If a future normalizeVerdict strips unknown keys, the field is gone by
    // construction and the assertions below would pass vacuously. This pins
    // WHY they are non-trivial: the field genuinely reaches the component.
    const v = (await verdictWithCost()) as Verdict & {
      cost?: { model_calls: number };
    };
    expect(v.cost?.model_calls).toBe(SENTINEL_CALLS);
  });

  it("the rendered page contains neither the number nor the basis", async () => {
    const markup = renderToStaticMarkup(
      <VerdictPage verdict={await verdictWithCost()} />,
    );
    expect(markup).not.toContain(String(SENTINEL_CALLS));
    expect(markup).not.toContain(SENTINEL_BASIS);
    expect(markup.toLowerCase()).not.toContain("model_calls");
  });

  it("the canary proves the search would find it if it DID render", async () => {
    // A "not.toContain" assertion is worthless if the haystack is empty or the
    // component threw. Something known-visible must be found by the same means.
    const markup = renderToStaticMarkup(
      <VerdictPage verdict={await verdictWithCost()} />,
    );
    expect(markup).toContain("Kenshi");
    expect(markup.length).toBeGreaterThan(1000);
  });

  it("no share surface carries it either", async () => {
    // The unfurl card is the other place verdict data reaches a stranger.
    const m = verdictMetadata(await verdictWithCost(), APPID);
    const serialized = JSON.stringify(m);
    expect(serialized).not.toContain(String(SENTINEL_CALLS));
    expect(serialized).not.toContain(SENTINEL_BASIS);
  });

  it("a verdict with no cost block renders identically to one with", async () => {
    // The strongest form: presence or absence of the field must make no
    // difference to a single byte the reader sees.
    const withCost = await verdictWithCost();
    const raw = JSON.parse(await readRepoFile(`public/verdicts/${APPID}.json`));
    delete raw.cost;
    const without = normalizeVerdict(raw);
    expect(renderToStaticMarkup(<VerdictPage verdict={withCost} />)).toBe(
      renderToStaticMarkup(<VerdictPage verdict={without} />),
    );
  });
});
