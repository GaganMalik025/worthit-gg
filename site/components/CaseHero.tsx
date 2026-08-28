"use client";

/**
 * The PC case hero, ported from mockups/kenshi-verdict.html.
 *
 * The mockup is the source of truth (DESIGN.md), so the markup and CSS here are
 * the mockup's, not a re-derivation from the prose. The CSS lives verbatim in
 * app/globals.css under the "case hero" banner; this component only supplies
 * the same DOM and the same scroll drive.
 *
 * Three things the choreography must never do, all inherited from DESIGN.md:
 *   - gate the answer: the stamp and Split Bar live in the sibling column and
 *     are on screen at load, whatever the case is doing
 *   - run on mobile: <768px gets a static closed case, no 3D, no pinning
 *   - move under prefers-reduced-motion: the case renders already open and
 *     settled, and no scroll listener is attached at all
 */

import { useEffect, useRef } from "react";
import { coverStages, type Art } from "../lib/art";

const CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps";

export function CaseHero({
  appid,
  gameName,
  splitBar,
  art,
}: {
  appid: number | string;
  gameName: string;
  splitBar: { bucket: string; pct_positive: number }[];
  /** The verdict's captured art block. Absent on pre-2026-08-13 verdicts, which
   *  simply fall through to the legacy stages exactly as they did before. */
  art?: Art | null;
}) {
  const caseRef = useRef<HTMLDivElement>(null);
  const coverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const prm = matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (prm) {
      document.documentElement.classList.add("prm");
      return; // open + settled via CSS; nothing scroll-linked, per DESIGN.md
    }
    const desk = matchMedia("(min-width: 768px)");
    const el = caseRef.current, cover = coverRef.current;
    if (!el || !cover) return;

    let ticking = false;
    const drive = () => {
      ticking = false;
      if (!desk.matches) {
        el.style.transform = "";
        cover.style.transform = "";
        return;
      }
      const p = Math.min(1, Math.max(0, (window.scrollY - 40) / 460));
      const e = 1 - Math.pow(1 - p, 3); // ease-out cubic
      cover.style.transform = `translateZ(13px) rotateY(${-150 * e}deg)`;
      el.style.transform = `rotateY(${22 - 14 * e}deg)`;
    };
    const onScroll = () => {
      if (!ticking) { ticking = true; requestAnimationFrame(drive); }
    };
    addEventListener("scroll", onScroll, { passive: true });
    desk.addEventListener("change", drive);
    drive();
    return () => {
      removeEventListener("scroll", onScroll);
      desk.removeEventListener("change", drive);
    };
  }, []);

  const stages = coverStages(appid, art, { allowGrid: false });

  /** Mini Split Bar motif: the last-resort face, and the disc label. */
  const motif = (
    <div className="ms" aria-hidden="true">
      {splitBar.map((b) => (
        <i key={b.bucket}>
          <b style={{ width: `${b.pct_positive}%` }} />
        </i>
      ))}
    </div>
  );

  /**
   * Cover chain, from lib/art.ts so the hero and the home grid cannot drift:
   * library_600x900 -> art.header_image (letterboxed) -> header.jpg
   * (letterboxed) -> Split Bar motif.
   *
   * `allowGrid: false` - SteamGridDB fan art is a TILE asset and does not go on
   * the case face (lib/art.ts, DESIGN.md:132). The hero is Valve art or nothing.
   *
   * THE STORED HEADER IS THE WHOLE POINT OF THIS CHANGE. This used to jump
   * straight from the legacy portrait to the legacy header, so a title whose
   * legacy URLs both 404 - 2806050 - fell to the motif with a live, captured
   * header_image sitting unread in its own verdict JSON.
   *
   * Indexed walk rather than the old two-step, mirroring PosterCard: the number
   * of stages now varies with what the art block holds.
   */
  const onCoverError = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    const wrap = img.parentElement;
    if (!wrap) return;
    const next = Number(img.dataset.stage ?? "0") + 1;
    const stage = stages[next];
    if (!stage) {
      wrap.classList.remove("letterbox");
      wrap.classList.add("motif");
      return;
    }
    img.dataset.stage = String(next);
    wrap.classList.toggle("letterbox", stage.letterbox);
    // The blurred fill behind a letterboxed face is a scaled copy of the same
    // image (DESIGN.md:167), so it tracks the stage rather than being pinned to
    // one URL.
    const bg = wrap.querySelector<HTMLImageElement>(".art-bg");
    if (bg) bg.src = stage.src;
    img.src = stage.src;
  };

  /** Disc chain is independent: library_hero -> cover darkened -> motif. */
  const onDiscError = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.currentTarget;
    if (img.dataset.stage === "hero") {
      img.dataset.stage = "cover";
      img.classList.add("dim");
      img.src = `${CDN}/${appid}/library_600x900.jpg`;
    } else {
      img.style.display = "none"; // motif behind it shows through
    }
  };

  return (
    <div className="case-scene">
      <div className="case-wrap">
        <div className="case" id="case" ref={caseRef}>
          <div className="edge" aria-hidden="true" />
          <div className="panel tray" aria-hidden="true">
            <div className="disc">
              {motif}
              <img
                className="disc-art"
                data-stage="hero"
                src={`${CDN}/${appid}/library_hero.jpg`}
                alt=""
                aria-hidden="true"
                onError={onDiscError}
              />
              <div className="sheen" aria-hidden="true" />
            </div>
          </div>
          <div className="panel cover" id="cover" ref={coverRef}>
            <div className="face front">
              <div className="band display">PC</div>
              <div className={stages[0].letterbox ? "art-wrap letterbox" : "art-wrap"}>
                <img className="art-bg" alt="" aria-hidden="true" />
                <img
                  className="art"
                  data-stage="0"
                  src={stages[0].src}
                  alt={`${gameName} cover art`}
                  onError={onCoverError}
                />
                {motif}
              </div>
            </div>
            {/* inner-left panel: the cover seen from behind through frosted
                tinted plastic - mirrored, ghosted, blurred, tinted */}
            <div className="face inside" aria-hidden="true">
              {/* the same physical object as the front face (DESIGN.md:159),
                  so it starts from the same stage rather than a pinned URL */}
              <img
                className="ghost"
                src={stages[0].src}
                alt=""
                onError={(e) => { e.currentTarget.style.display = "none"; }}
              />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
