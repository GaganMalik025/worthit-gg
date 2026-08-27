// @vitest-environment jsdom

/**
 * THE CITATION EXPAND MUST KEEP FIRING ITS EVENT
 *
 * PRD §3's headline metric is verdict → citation-expand rate ≥30% - the direct
 * test of the "claims with receipts" thesis. Analytics is fail-silent by
 * design (lib/analytics.ts swallows everything), which is right for a verdict
 * page and wrong for confidence: a refactor that drops the `capture` call
 * breaks nothing, renders identically, throws nothing, and quietly zeroes the
 * one number this product is trying to learn. Nothing else in the repo would
 * notice. That is what this file is for.
 *
 * It asserts the WIRING, not delivery. Delivery to PostHog's ingestion was
 * verified separately from a real browser click (evals/posthog-events-2026-08-26.txt);
 * no test here talks to the network.
 *
 * jsdom, opted into per-file, so vitest.config.ts's `node` default - and
 * therefore every existing contract test, which renders to static markup with
 * no DOM - is left alone.
 *
 * KNOWN LIMIT, recorded rather than discovered later, in the spirit of
 * verdict-render.contract.test.tsx's own: jsdom's <summary> activation
 * behaviour is what flips `open` and emits `toggle` here. That is the same
 * event path a real browser uses, but it is jsdom's implementation of it, not
 * Chrome's. The real-browser run is what covers the difference.
 *
 * Run: cd site && npm test
 */

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// vi.hoisted, because vi.mock's factory is hoisted above every top-level
// binding and would otherwise close over an uninitialised `capture`.
const { capture } = vi.hoisted(() => ({ capture: vi.fn() }));
vi.mock("posthog-js", () => ({ default: { capture } }));

import { Receipts } from "../../components/Receipts";
import type { Citation } from "../verdict";

const CITATIONS: Citation[] = [
  {
    recommendationid: "230637493",
    hours_at_review: 3.2,
    minutes_at_review: 192,
    voted_up: true,
    date: "2026-05-31",
    review_text: "review text that must stay behind the expand",
  },
  {
    recommendationid: "230637494",
    hours_at_review: 1.1,
    minutes_at_review: 66,
    voted_up: false,
    date: "2026-05-27",
    review_text: "second review",
  },
];

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  // posthog-js is mocked, but lib/analytics.ts also gates on the key being
  // present - without this the wrapper returns before it ever reaches capture,
  // and the test would pass for the wrong reason.
  vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "phx_test_key");
  capture.mockClear();
  container = document.createElement("div");
  document.body.appendChild(container);
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllEnvs();
});

/** The HTML spec queues the <details> `toggle` event as a task rather than
 *  firing it synchronously, and jsdom implements it that way. A click followed
 *  by an immediate assertion therefore reads zero captures on a perfectly
 *  working handler - so every open here goes through this flush. Found by the
 *  test failing before it passed, which is the only reason it is written down.
 */
async function open(summary: HTMLElement) {
  await act(async () => {
    summary.click();
    await new Promise((r) => setTimeout(r, 0));
  });
}

function mount() {
  act(() => {
    root.render(
      <Receipts
        appid="233860"
        verdictWord="Wait"
        bucket="early"
        citations={CITATIONS}
      />,
    );
  });
  const details = container.querySelector("details") as HTMLDetailsElement;
  const summary = container.querySelector("summary") as HTMLElement;
  return { details, summary };
}

describe("citation_expand", () => {
  it("renders closed, with no event, before anyone touches it", () => {
    const { details } = mount();
    expect(details.open).toBe(false);
    expect(capture).not.toHaveBeenCalled();
  });

  it("fires exactly once, with appid and verdict word, when opened", async () => {
    const { summary, details } = mount();
    await open(summary);

    expect(details.open).toBe(true);
    expect(capture).toHaveBeenCalledTimes(1);
    expect(capture).toHaveBeenCalledWith("citation_expand", {
      appid: "233860",
      verdict: "Wait",
    });
  });

  /** A close is not an expand. Counting both would roughly double the
   *  numerator of the metric this event exists to measure. */
  it("fires nothing when closed again", async () => {
    const { summary } = mount();
    await open(summary);
    capture.mockClear();

    await open(summary); // same control, now closing
    expect(capture).not.toHaveBeenCalled();
  });

  /** Invariant 11's neighbour: the payload is what we promised in BACKLOG
   *  2026-08-26 and nothing else. Review text in particular must never leave
   *  the browser - it is the thing invariant 9 keeps behind this very click. */
  it("sends no review text, no recommendationid and no third property", async () => {
    const { summary } = mount();
    await open(summary);

    const [, props] = capture.mock.calls[0] as [string, Record<string, unknown>];
    expect(Object.keys(props).sort()).toEqual(["appid", "verdict"]);
    const serialised = JSON.stringify(props);
    for (const c of CITATIONS) {
      expect(serialised).not.toContain(c.review_text);
      expect(serialised).not.toContain(c.recommendationid);
    }
  });

  /** The other half of the fail-silent contract: with no key configured,
   *  lib/analytics.ts must not reach posthog at all. This is the CI and
   *  fresh-checkout path - .env.local is gitignored. */
  it("captures nothing when no PostHog key is configured", async () => {
    vi.stubEnv("NEXT_PUBLIC_POSTHOG_KEY", "");
    const { summary, details } = mount();
    await open(summary);

    expect(details.open).toBe(true); // the expand still works
    expect(capture).not.toHaveBeenCalled();
  });
});
