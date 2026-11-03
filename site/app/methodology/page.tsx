import type { Metadata } from "next";

/**
 * The trust page (PRD F8). Figures are hand-set from committed evidence and pinned to
 * that evidence by methodology.contract.test.tsx, so a page that goes stale fails CI
 * rather than quietly overclaiming. Copy rules are DESIGN.md's: no prevalence language,
 * and no rate without what it rests on.
 */
export const metadata: Metadata = {
  title: "How it works — WorthIt.gg",
  description:
    "How WorthIt.gg makes a verdict from Steam reviews, how good it is, and what it cannot tell you.",
};

const COHORTS = [
  ["Refund window", "under 2 hours, Steam's refund limit"],
  ["Early", "2 to 20 hours"],
  ["Mid", "20 to 100 hours"],
  ["Veteran", "over 100 hours"],
];

const CHECKS = [
  ["Do the cited reviews say what the claim says?",
   "47 of 70 fully, 23 partly, 0 unsupported", "2026-07-31"],
  ["Do the cited reviews belong to that cohort?",
   "70 of 70, guaranteed by how they are chosen, so this only guards against bugs",
   "2026-07-31"],
  ["Do at least two reviews back a claim and frame it the same way?",
   "59 of 70", "2026-11-03"],
  ["Any slurs or explicit content in a citation?",
   "0 in 28,331 citations by wordlist, plus a person reading samples", "2026-11-03"],
];

export default function Methodology() {
  return (
    <main className="method">
      <a className="site-home" href="/">WorthIt.gg</a>
      <h1 className="wordmark">How WorthIt.gg works</h1>
      <p>
        Reviews disagree because players are describing different experiences. Someone
        who refunded at two hours and someone at 100 hours played different games, in
        effect. A single score averages them away, so we show them apart.
      </p>

      <h2>How a verdict is made</h2>
      <p>
        <strong>We sweep recent reviews from Steam.</strong> Up to about 2,400 per game,
        in English: the newest, plus the ones Steam ranks highest for helpfulness from
        recent weeks. That sweep is the pool. It is a sample of Steam, not all of it.
      </p>
      <p><strong>We split the pool by playtime at the moment of review.</strong></p>
      <table>
        <thead><tr><th>Cohort</th><th>Played</th></tr></thead>
        <tbody>
          {COHORTS.map(([name, hours]) => (
            <tr key={name}><td>{name}</td><td className="mono">{hours}</td></tr>
          ))}
        </tbody>
      </table>
      <p>
        <strong>The word is arithmetic, not an AI&rsquo;s opinion.</strong> We take the
        share of recommending reviews across the early, mid and veteran cohorts, weighted
        by how many reviews each holds. <span className="mono">89%</span> or above is Buy,
        under <span className="mono">64%</span> is Skip, and anything between is Wait. The
        refund window is left out, because it is by definition the group that bounced, and
        it is shown separately. A cohort with fewer than 20 usable reviews is greyed out
        and makes no claims.
      </p>
      <p>
        <strong>An AI writes the rest, on a short lead.</strong> It reads each cohort and
        lists claims, each of which must cite at least two reviews. Code checks that those
        reviews exist, belong to that cohort and share words with the claim. A second pass
        writes the summary and may only use those claims. Reviews containing slurs or
        explicit content are filtered out first, and every citation is checked again
        before anything is published.
      </p>
      <p>Every number on a page comes from the pool and shows how many reviews it rests on.</p>

      <h2>How good it is</h2>
      <table>
        <thead><tr><th>Check</th><th>Result</th><th>Measured</th></tr></thead>
        <tbody>
          {CHECKS.map(([check, result, date]) => (
            <tr key={check}>
              <td>{check}</td><td className="mono">{result}</td><td className="mono">{date}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        These claim checks cover 70 claims from five games, written in July and scored by
        an AI judge. So we checked the judge against a person. On 6 randomly chosen claims
        they agreed on all 6 for the first check, and on 5 of 6 for the third. An earlier
        round agreed on only 3 of 10, mainly because the person was asking a different
        question: whether a claim captures the reviewer&rsquo;s main point, which the first
        check does not ask. Six claims is a small test, and these results describe those
        five games, not the whole catalog.
      </p>

      <h2>What this cannot tell you</h2>
      <p>
        <strong>Claims lean negative, and we have not fixed that.</strong> In 491 of 533
        games we measured, the reviews behind the claims were less positive than the
        reviews available, by about 21 points on average. Complaints are specific, and
        praise like &ldquo;10/10&rdquo; gives us nothing to check. So read a cohort&rsquo;s
        percentage as how it felt and its claims as what it talked about. Death
        Stranding&rsquo;s veterans read <span className="mono">95.3%</span> positive, based
        on <span className="mono">169</span> reviews, with three claims beneath them, all
        complaints.
      </p>
      <p>
        <strong>Some claims are thinner than they look.</strong> In those 70 claims, 11 had
        one review really supporting them even though they cite two. Our check matches
        words, so it cannot always tell.
      </p>
      <p>
        <strong>The sample is built, not random.</strong> We deliberately keep more of the
        small cohorts, so nothing here says what share of players feel a certain way. Our
        pool also leans on recent reviews and on what Steam ranks helpful, which can run
        harsher than recent reviews alone.
      </p>
      <p>
        <strong>Verdicts age.</strong> Each page shows when it was generated, and we do not
        refresh them on a schedule. A game that has changed since then may read differently
        today.
      </p>
    </main>
  );
}
