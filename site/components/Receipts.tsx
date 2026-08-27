"use client";

/**
 * The citation expand - lifted out of VerdictPage so it can carry an event.
 *
 * PRD §3's headline metric is verdict → citation-expand rate ≥30%. That rate is
 * the direct test of the "claims with receipts" thesis, so this is the one
 * interaction on the site that HAS to be instrumented, and it had to be
 * instrumented before traffic: there is no way to recover a "before" number
 * afterwards.
 *
 * INVARIANT 9 IS UNCHANGED, and the markup below is a verbatim lift of what
 * VerdictPage rendered inline - proved, not asserted: the rendered HTML of all
 * 539 committed verdicts was diffed across the swap and is byte-identical
 * (evals/citation-expand-markup-diff-2026-08-26.txt). It is still a native
 * <details>, still closed on the server, still toggling with no JS. Review text
 * is still reachable only behind an expand, and still is with JavaScript
 * disabled - the handler adds an event, it does not become the mechanism.
 * VerdictPage stays a server component; this is the only client boundary in it.
 *
 * ONLY ON OPEN. `onToggle` fires in both directions and a close is not an
 * expand - counting both would roughly double the numerator of the one metric
 * this exists to measure.
 */

import { citationHours } from "../lib/verdict";
import type { Citation } from "../lib/verdict";
import { capture } from "../lib/analytics";

export function Receipts({
  appid,
  verdictWord,
  bucket,
  citations,
}: {
  appid: string;
  verdictWord: string;
  bucket: string;
  citations: Citation[];
}) {
  return (
    <details
      onToggle={(e) => {
        if (!e.currentTarget.open) return;
        capture("citation_expand", { appid, verdict: verdictWord });
      }}
    >
      <summary>
        <span className="tag mono">
          ▸ {citations.length}{" "}
          {citations.length === 1 ? "review" : "reviews"}
        </span>
        <span className="cta">Show receipts</span>
      </summary>
      {citations.map((cit) => (
        <div key={cit.recommendationid} className="citation">
          <div className="meta mono">
            {cit.voted_up ? "▲ recommends" : "▼ does not recommend"}{" "}
            · {citationHours(cit, bucket)} hrs ·{" "}
            {cit.date}
          </div>
          <div className="body">{cit.review_text}</div>
        </div>
      ))}
    </details>
  );
}
