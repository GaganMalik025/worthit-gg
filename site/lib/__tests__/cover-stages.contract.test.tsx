// @vitest-environment jsdom

/**
 * COVER ART FALLBACK ORDER
 *
 * Three defects landed together on 2026-08-28 and all three were ordering or
 * visibility bugs that rendered without erroring - the exact shape that gets
 * silently reintroduced:
 *
 *   - CaseHero could not see the art block at all, so 2806050 fell to the
 *     blank motif with a live captured header_image unread in its own JSON;
 *   - the chain preferred a stored 460x215 LANDSCAPE over a working 300x450
 *     PORTRAIT, so 1641890's tile letterboxed for no reason;
 *   - the order existed in two places and had drifted apart.
 *
 * None of that throws, and none of it shows up in a snapshot of the initial
 * markup, because the whole mechanism is the onError walk. So it gets a test
 * that drives the walk.
 *
 * The `allowGrid` split is pinned here too. SteamGridDB art is
 * community-uploaded: it is allowed in a home-grid tile and NOT on the case
 * face (owner decision 2026-08-28; DESIGN.md:132 "the game's real Steam library
 * art"). og-tags.contract.test.ts already pins the separate, older rule that it
 * never reaches an unfurl.
 *
 * Run: cd site && npm test
 */

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { coverStages } from "../art";
import { CaseHero } from "../../components/CaseHero";

const CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps";
const APPID = 2806050; // Halo: Campaign Evolved - the title that surfaced this
const GRID = "https://cdn2.steamgriddb.com/grid/deadbeef.png";
const HEADER = "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/2806050/abc123/header.jpg";

const FULL = { grid: GRID, header_image: HEADER, capsule_image: "x" };

describe("coverStages order", () => {
  it("tiles: grid, then the legacy portrait, then landscapes", () => {
    expect(coverStages(APPID, FULL, { allowGrid: true })).toEqual([
      { src: GRID, letterbox: false },
      { src: `${CDN}/${APPID}/library_600x900.jpg`, letterbox: false },
      { src: HEADER, letterbox: true },
      { src: `${CDN}/${APPID}/header.jpg`, letterbox: true },
    ]);
  });

  /** THE REGRESSION THAT PROMPTED THIS. A working portrait must never lose to
   *  a letterboxed landscape - 1641890 rendered its 460x215 header in a
   *  portrait tile while its own 300x450 portrait sat two stages down. */
  it("every portrait comes before every landscape", () => {
    for (const allowGrid of [true, false]) {
      for (const art of [FULL, { header_image: HEADER }, {}, null]) {
        const stages = coverStages(APPID, art, { allowGrid });
        const firstLandscape = stages.findIndex((s) => s.letterbox);
        if (firstLandscape === -1) continue;
        expect(stages.slice(firstLandscape).every((s) => s.letterbox)).toBe(true);
      }
    }
  });

  it("header.jpg is always the true last resort", () => {
    for (const art of [FULL, { header_image: HEADER }, { grid: GRID }, {}, null]) {
      const stages = coverStages(APPID, art, { allowGrid: true });
      expect(stages.at(-1)).toEqual({
        src: `${CDN}/${APPID}/header.jpg`, letterbox: true,
      });
    }
  });

  /** The hero half of the 2026-08-28 decision, in code rather than prose. */
  it("the hero never emits SteamGridDB fan art", () => {
    const stages = coverStages(APPID, FULL, { allowGrid: false });
    expect(JSON.stringify(stages)).not.toContain("steamgriddb");
    expect(stages[0].src).toBe(`${CDN}/${APPID}/library_600x900.jpg`);
  });

  it("a verdict with no art block still gets the two legacy stages", () => {
    expect(coverStages(APPID, null, { allowGrid: true })).toEqual([
      { src: `${CDN}/${APPID}/library_600x900.jpg`, letterbox: false },
      { src: `${CDN}/${APPID}/header.jpg`, letterbox: true },
    ]);
  });
});

describe("CaseHero cover walk", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    // CaseHero's effect reads matchMedia, which jsdom does not implement.
    // prefers-reduced-motion: true takes the early-return branch and attaches
    // no scroll listener - the art chain under test is unaffected either way.
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (q: string) => ({
        matches: q.includes("prefers-reduced-motion"),
        media: q, addEventListener() {}, removeEventListener() {},
      }),
    });
    container = document.createElement("div");
    document.body.appendChild(container);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  function mount(art: Parameters<typeof coverStages>[1]) {
    act(() => {
      root.render(
        <CaseHero appid={APPID} gameName="Halo: Campaign Evolved" splitBar={[]} art={art} />,
      );
    });
    const img = container.querySelector("img.art") as HTMLImageElement;
    return { img, wrap: img.parentElement as HTMLElement };
  }

  const fail = (img: HTMLImageElement) =>
    act(() => { img.dispatchEvent(new Event("error")); });

  it("starts on the legacy portrait, not the stored landscape", () => {
    const { img, wrap } = mount(FULL);
    expect(img.getAttribute("src")).toBe(`${CDN}/${APPID}/library_600x900.jpg`);
    expect(wrap.className).not.toContain("letterbox");
  });

  /**
   * THE 2806050 PATH. Both legacy URLs 404 on that title (measured
   * 2026-08-27). Before this change the walk jumped portrait -> header.jpg and
   * landed on the motif; now the captured header_image sits between them and
   * actually renders.
   */
  it("falls to the stored header_image, letterboxed, before header.jpg", () => {
    const { img, wrap } = mount(FULL);
    fail(img);
    expect(img.getAttribute("src")).toBe(HEADER);
    expect(wrap.className).toContain("letterbox");
    // the blurred fill behind a letterboxed face tracks the same stage
    expect(wrap.querySelector<HTMLImageElement>(".art-bg")?.getAttribute("src")).toBe(HEADER);
  });

  it("then header.jpg, then the motif", () => {
    const { img, wrap } = mount(FULL);
    fail(img);
    fail(img);
    expect(img.getAttribute("src")).toBe(`${CDN}/${APPID}/header.jpg`);
    fail(img);
    expect(wrap.className).toContain("motif");
    expect(wrap.className).not.toContain("letterbox");
  });

  it("a verdict with no art block walks portrait -> header.jpg -> motif", () => {
    const { img, wrap } = mount(null);
    fail(img);
    expect(img.getAttribute("src")).toBe(`${CDN}/${APPID}/header.jpg`);
    fail(img);
    expect(wrap.className).toContain("motif");
  });

  /** Invariant 9's neighbour: fan art may not reach the case face even when the
   *  verdict carries it. Asserted on the SERVER markup too, because that is
   *  what a crawler and a no-JS reader see. */
  it("never renders SteamGridDB art on the case face", () => {
    const { img } = mount(FULL);
    expect(img.getAttribute("src")).not.toContain("steamgriddb");
    const html = renderToStaticMarkup(
      <CaseHero appid={APPID} gameName="Halo" splitBar={[]} art={FULL} />,
    );
    expect(html).not.toContain("steamgriddb");
  });
});
