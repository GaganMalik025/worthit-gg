/**
 * The shared verdict renderer. Both loaders in lib/verdict.ts feed this exact
 * component - that is what makes the dual path safe, and what the contract test
 * pins.
 *
 * Data-faithful, not yet fully styled: the approved visual design lives in
 * mockups/kenshi-verdict.html and lands with 3.1. What matters here and is
 * already load-bearing:
 *
 *   - every rate ships with its evidence count in English (invariant 13),
 *     never a bare percentage and never the raw field name
 *   - citations render only inside the collapsed receipts element (invariant 9,
 *     blast-radius); <details> is closed by default with no JS involved
 *   - citation_verdict is carried in the data and never rendered as claim
 *     valence (invariant 13)
 */

import { CaseHero } from "./CaseHero";
import type { Sourcing, Verdict } from "../lib/verdict";

/**
 * The sourcing disclosure (B2). Tier 1 is unconditional on every cohort that
 * renders claims, because divergence between the pool rate and the cited
 * sample is the catalog's NORMAL state - measured 2026-08-17, 21.4% of cohort
 * sections diverge by more than 40 points and only 1 of 1,077 diverges the
 * other way. A note that appeared only on the tail would tell a reader, by its
 * silence, that every other claim list was drawn representatively.
 *
 * Deliberately numberless. The counts sit in the JSON as diagnostics and must
 * not reach this function - see the Sourcing type and invariant 13.
 *
 * "more negative" is safe to state unconditionally on the divergent trigger:
 * pipeline/sourcing.py tests the LOWER binomial tail only, so that rule cannot
 * fire in the other direction.
 *
 * THE REPETITION IS A DELIBERATE NON-FIX (owner, 2026-08-17). On a title whose
 * cohorts all escalate - Counter-Strike (10) is the example, 7 titles carry 3
 * or more - the same baseline sentence renders four times down the page. The
 * structural alternative (hoist the baseline sentence to the Split Bar, keep
 * only the escalation clause per cohort) was considered and declined: the note
 * is about the claim list directly beneath it, and moving it away from that
 * list to save words costs the thing it is for. Do not re-litigate unless an
 * audit read flags it as genuinely bad - that would be evidence, which is the
 * bar.
 */
export function sourcingNote(s: Sourcing | null): string | null {
  if (!s) return null;
  const base =
    "The rate above covers all reviews in this cohort. " +
    "The points below come from the reviews that described something specific";
  const thin = s.triggers.includes("thin");
  const divergent = s.triggers.includes("divergent");
  if (thin && divergent) {
    return `${base} — here, an unusually small set of them, leaning more negative than the cohort above.`;
  }
  if (thin) return `${base} — here, an unusually small set of them.`;
  if (divergent) {
    return `${base} — here, reviews leaning more negative than the cohort above.`;
  }
  return `${base}.`;
}

/** Must cover every value in pipeline/extract_claims.py THEMES - asserted by
 *  lib/__tests__/theme-labels.contract.test.ts, because the `?? t.theme`
 *  fallback below renders a missing one as a raw lowercase enum value rather
 *  than failing, which is the kind of thing that ships. */
export const THEME_LABEL: Record<string, string> = {
  performance: "Performance",
  content: "Content",
  difficulty: "Difficulty",
  access: "Access",
  monetization: "Monetization",
  other: "Other",
};

/**
 * One side of the fit split.
 *
 * Renders nothing at all for an empty list - which is what a pre-split verdict
 * coming off the `verdicts` branch normalizes to, so those pages keep the shape
 * they had rather than showing an empty box.
 *
 * The polarity is carried by the tint AND the glyph, never by colour alone
 * (DESIGN.md). Nothing here colours text: the heading stays --text-dim, because
 * a coloured word is the verdict stamp's job and the fit boxes must not be read
 * as a second verdict.
 */
function FitBox({ kind, title, clauses }: {
  kind: "yes" | "no";
  title: string;
  clauses: string[];
}) {
  if (!clauses.length) return null;
  return (
    <div className={`fit ${kind}`}>
      <h3>
        <span className="glyph" aria-hidden="true">{kind === "yes" ? "▲" : "▼"}</span>{" "}
        {title}
      </h3>
      <ul>
        {clauses.map((c) => <li key={c}>{c}</li>)}
      </ul>
    </div>
  );
}

export function VerdictPage({ verdict: v }: { verdict: Verdict }) {
  const fit = v.verdict.for_you_if.length || v.verdict.not_for_you_if.length;
  return (
    <div className="layout">
      <header className="hero-copy">
      <h1>{v.game_name}</h1>
      <div className="stamp-row">
        <span className={`stamp ${v.verdict.word.toLowerCase()}`}>
          {v.verdict.word.toUpperCase()}
        </span>
        <p className="tagline">{v.verdict.tagline}</p>
      </div>

      {fit ? (
        <div className="fit-grid">
          <FitBox kind="yes" title="For you if" clauses={v.verdict.for_you_if} />
          <FitBox kind="no" title="Not for you if" clauses={v.verdict.not_for_you_if} />
        </div>
      ) : null}

      <section className="spine" aria-label="Sentiment by playtime cohort">
        <h2>How satisfaction changes with playtime</h2>
        <p className="sub">
          Percent of reviewers who&rsquo;d recommend it, grouped by how long they
          played before reviewing.
        </p>
        {v.split_bar.map((b, i) => (
          <div key={b.bucket} className={b.muted ? "bar-row muted" : "bar-row"}>
            <span className="bar-label">
              {b.label}{" "}
              <span className="mono">
                {b.muted
                  ? `${b.pool_n} reviews · too few to call`
                  : `· based on ${b.pool_n} reviews`}
              </span>
            </span>
            <span className="bar-track">
              <span className="bar-fill" style={{ ["--delay" as string]: `${420 + 60 * i}ms` } as React.CSSProperties}>
                <span className="bar-pos" style={{ width: `${b.pct_positive}%` }} />
                <span className="bar-neg" style={{ width: `${100 - b.pct_positive}%` }} />
              </span>
            </span>
            <span className="bar-pct mono">{b.pct_positive.toFixed(1)}%</span>
          </div>
        ))}
      </section>
      </header>

      <div className="case-col">
        <CaseHero appid={v.appid} gameName={v.game_name} splitBar={v.split_bar} />
      </div>

      <main className="main-col">
      {v.cohorts.map((c) => (
        <section key={c.bucket} className="cohort">
          <h2>{c.label}</h2>
          <div className="stats mono">
            {c.hours_range} · {c.pct_positive.toFixed(1)}% positive, based on{" "}
            {c.pool_n} reviews
          </div>
          {c.summary ? <p className="summary">{c.summary}</p> : null}
          {/* Sits directly above the claim list because that is what it is
              about ("the points below"), and renders nothing when the cohort
              renders no claims. */}
          {sourcingNote(c.sourcing) ? (
            <p
              className={
                c.sourcing?.level === "escalated"
                  ? "sourcing escalated"
                  : "sourcing"
              }
            >
              {sourcingNote(c.sourcing)}
            </p>
          ) : null}
          {c.themes.map((t) => (
            <div key={t.theme} className="theme">
              <h3>{THEME_LABEL[t.theme] ?? t.theme}</h3>
              {t.claims.map((cl) => (
                <div key={cl.claim_id} className="claim">
                  <p className="text">{cl.claim}</p>
                  {/* invariant 9: review text only behind a citation expand */}
                  <details>
                    <summary>
                      <span className="tag mono">
                        ▸ {cl.citations.length}{" "}
                        {cl.citations.length === 1 ? "review" : "reviews"}
                      </span>
                      <span className="cta">Show receipts</span>
                    </summary>
                    {cl.citations.map((cit) => (
                      <div key={cit.recommendationid} className="citation">
                        <div className="meta mono">
                          {cit.voted_up ? "▲ recommends" : "▼ does not recommend"}{" "}
                          · {(cit.hours_at_review ?? 0).toFixed(1)} hrs ·{" "}
                          {cit.date}
                        </div>
                        <div className="body">{cit.review_text}</div>
                      </div>
                    ))}
                  </details>
                </div>
              ))}
            </div>
          ))}
        </section>
      ))}

      </main>
      <footer className="mono verdict-footer">
        Data: {v.footer.pool_n.toLocaleString("en-US")} reviews across{" "}
        {v.footer.cohort_count} cohorts · generated{" "}
        {v.generated_at.slice(0, 10)}
      </footer>
    </div>
  );
}
