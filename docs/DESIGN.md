# DESIGN — WorthIt.gg

**Audience:** PC gamers arriving from Reddit, mostly on mobile, mostly at
night, deciding whether to spend money. They live in dark UIs (Steam, Discord)
and are allergic to anything that smells like marketing.

**The page's single job:** deliver a verdict they trust in under two minutes.
Trust comes from showing the receipts, not from polish.

**Design thesis:** the product's core claim is that *disagreement is
information*. The UI's job is to make disagreement visible and delightful to
explore — not to hide it behind an average. Every signature element below
derives from that.

**Tone:** modern, a little playful, never corporate. Think "a sharp friend who
games" — not a SaaS dashboard, not an esports energy-drink site.

---

## Tokens

### Color — dark, gaming-native, semantic trio

Do NOT use: cream/terracotta editorial look, near-black + single acid-green
accent, or newspaper hairline-broadsheet styling. These are generic AI-design
defaults and this brief overrides them.

| Token | Hex | Use |
|---|---|---|
| `--bg` | `#10141C` | Page background (deep blue-ink, warmer than pure black) |
| `--surface` | `#1A2029` | Cards, panels |
| `--surface-2` | `#232B37` | Expanded citations, hover states |
| `--text` | `#E8ECF1` | Primary text |
| `--text-dim` | `#8B95A5` | Secondary text, metadata |
| `--buy` | `#4ADE80` | Buy verdict + positive segments |
| `--wait` | `#FBBF24` | Wait verdict + mixed segments |
| `--skip` | `#F87171` | Skip verdict + negative segments |
| `--link` | `#7DD3FC` | Interactive elements, links (soft cyan — NOT the verdict colors) |

Rules: verdict colors are **semantic only** — never decorative. Interactive
affordances always use `--link` so color never lies about meaning. Verdict
colors must also never be the only carrier of meaning (color-blind users):
always pair with the word Buy/Wait/Skip or an up/down glyph.

### Type — three roles, receipts feel

| Role | Face | Use |
|---|---|---|
| Display | **Space Grotesk** (Google Fonts) | Verdict word, game titles, section headers. Bold, tight tracking. |
| Body | **Inter** | Everything readable. |
| Data | **IBM Plex Mono** | Hours, counts, percentages, review IDs, timestamps — anything that is *evidence*. |

The mono-for-evidence rule is load-bearing: numbers set in mono read as
receipts, which is the brand. `142.5 hrs` in Plex Mono next to a citation does
more trust-work than any badge.

Scale: display 32/24/20, body 16, data 14. Line-height 1.6 body, 1.1 display.

### Spacing & shape

- 8px base grid. Cards `border-radius: 12px`, chips/badges `8px`, pills `999px`.
- No borders where elevation can do the job; where borders are needed,
  `1px solid rgba(255,255,255,0.06)`.
- Max content width 720px on desktop — this is a reading product, not a
  dashboard. Generous whitespace; the dark theme must feel airy, not dense.

---

## Signature element: the Split Bar

One element carries the identity — the **Split Bar**: a horizontal stacked bar
per playtime cohort showing % positive vs negative, cohort label left
(`<2h refund window`, `2–20h`, `20–100h`, `100h+`), sentiment split rendered
in `--buy`/`--skip` with the percentage in Plex Mono at the bar's end.

Stacked vertically, the four bars form the "spine" of every verdict page —
disagreement becomes a shape you can see before reading a word. A game where
the refund bar is red and the veteran bar is green *looks like* "steep learning
curve" at a glance. This is the product thesis as a visual.

**Data source (non-negotiable, CLAUDE.md invariant 13):** every bar reads
`pool.buckets[<cohort>].pct_positive` from the verdict JSON, and its cohort
label carries the matching `pool_n` in mono: `<2h refund window · pool_n 47`.
Never the post-quota or post-filter review counts — those are pipeline
diagnostics and describe our sampling, not the game. A bar whose percentage has
no `pool_n` beside it does not render at all.

Cohorts under the 20-review floor (invariant 12) render the bar at 30% opacity
with the label `n=12 · too few reviews to call` and carry no claims beneath
them. The bar still shows: an honest "we don't know" is worth more than a
missing row, and the gap is itself information about who bounced.

- On load, bars fill left-to-right with a 350ms staggered ease-out (the page's
  one orchestrated motion moment). Respect `prefers-reduced-motion`: render
  filled, no animation.
- A compact 4-stripe mini version of the Split Bar appears on home-grid cards
  and becomes the favicon/OG-image motif. One element, reused everywhere =
  identity.

Everything else stays quiet so this lands.

## Verdict stamp

The verdict itself: the word BUY / WAIT / SKIP in Space Grotesk bold, its
semantic color, inside a chip with a subtle 1px border of the same color at
20% opacity — followed by the for-whom qualifier in body type ("Buy — if you
want a story-first RPG and have patience for slow openings"). No stamp
rotation, no grunge texture, no gimmick: the qualifier sentence is what makes
it feel human, not decoration.

## Citations = receipts

- Claims render as one-line statements with a mono evidence tag:
  `▸ 6 reviews · 2 cohorts`. This is the **one sanctioned non-pool number** on
  the page (invariant 13): it counts the receipts attached to *this claim*, not
  how many players think it. Never render it as a share, a rate, or "6 players",
  and never let a claim's wording lean on it ("only a handful mention…").
- Tapping expands (`--surface-2`, 200ms height ease) to the verbatim review
  excerpts, each with `voted_up` glyph, `hours at review` in mono, and date.
- Collapsed by default ALWAYS (blast-radius rule from CLAUDE.md invariant 9).
- Microcopy on the expander: **"Show receipts"** / "Hide receipts". This is
  the product's catchphrase — use it consistently, never synonyms.

## Distortion flags

An inline callout strip, not an alarm: `--wait`-tinted background at 8%
opacity, mono label like `SCORE DISTORTION DETECTED`, one sentence of plain
explanation, expandable evidence. Factual voice — flags explain, never editorialize.

Any figure inside a flag — cohort rates, before/after splits, the gap between
cohorts — comes from the `pool` block with its `pool_n` (invariant 13). A flag
that cannot cite a pool figure does not ship; "this game looks review-bombed"
without a number attached is editorializing, which is the one thing flags may
never do.

---

## Page anatomy

### Home
1. Wordmark + one-line promise: "Should you buy it? The verdict, with
   receipts." (This exact line — it names both the product and the mechanism.)
2. Search box, autofocus on desktop, full-width. Placeholder: "Search a game…"
3. Grid of game cards: cover-art-free by default (capsule images from Steam CDN
   are allowed if trivially available; never block on them) — title, mini
   Split Bar, verdict chip. The grid should read as verdicts, not a store.
4. Footer: "Game not here? Request it" + methodology link.

### Verdict page (top to bottom)
1. Game title + verdict stamp + for-whom line — the answer first, always.
2. Split Bar block (the spine).
3. Distortion flags, if any.
4. Claims grouped by theme (performance / content / monetization / difficulty),
   each with receipts expander.
5. Hardware context section only when data density permits (F9) — omit
   silently otherwise, never show an empty section.
6. Footer: "Data: {pool_n} reviews across 4 cohorts · generated {date} · how
   this works →" in mono. `pool_n` is the swept pool (invariant 13) — not the
   quota sample, not the post-filter count, not "reviews read by the model".

### Methodology page
Written like a straight-talking README, not a legal page. Contains: the
segmentation logic in plain words, the live eval table (QR-1..4 with dates,
mono), the sample-vs-Steam distribution chart, and the Death Stranding
side-by-side (Steam's summary vs WorthIt's split). This page is the trust
artifact — link it from every verdict footer.

### Empty / request states
Empty search result: "Not in the catalog yet. Request it and it'll be here
within 48 hours." + single input + button labeled "Request verdict". After
submit: "Queued. Check back tomorrow." No email asked, ever.

---

## Motion budget (total)

1. Split Bar staggered fill (page load, once).
2. Receipts expand/collapse (200ms).
3. Hover: card lift 2px + shadow ease on desktop only.

Nothing else moves. Reduced-motion kills 1 and 3 entirely.

## Copy rules

Active voice, sentence case, plain verbs. Buttons say what they do ("Show
receipts", "Request verdict"). Numbers are specific and always carry their
denominator ("1,930 reviews across 4 cohorts", "47 in the refund window"),
never vague ("hundreds") and never bare percentages. Prevalence words — most,
majority, many players, half, few — are banned in generated copy; they are
rejected in code at 1.4, and the same rule applies to hand-written UI strings. No exclamation marks. The interface's personality
comes from precision + the one catchphrase, not from jokes.

## Quality floor (non-negotiable, ship silently)

Responsive to 360px; visible keyboard focus (`--link` 2px outline); WCAG AA
contrast on all text (check `--text-dim` on `--surface`); reduced-motion
respected; verdict pages statically generated with real `<title>`/OG tags per
game (Reddit unfurls matter for distribution).
