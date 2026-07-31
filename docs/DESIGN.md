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

**Framing:** the stack is introduced once, above the bars — heading
**"How satisfaction changes with playtime"** with one line beneath it:
*"Percent of reviewers who'd recommend it, grouped by how long they played
before reviewing."* Once above the stack, never repeated per bar. A
first-time viewer must not need prior context to read the spine.

**Data source (non-negotiable, CLAUDE.md invariant 13):** every bar reads
`pool.buckets[<cohort>].pct_positive` from the verdict JSON, and its cohort
label carries the matching evidence count in mono, phrased as English:
`<2h refund window · based on 47 reviews`. `pool_n` is the JSON field, not
UI copy — raw field names never render. Never the post-quota or post-filter
review counts — those are pipeline diagnostics and describe our sampling,
not the game. A bar whose percentage has no evidence count beside it does
not render at all.

Cohorts under the 20-review floor (invariant 12) render the bar at 30% opacity
with the label `12 reviews · too few to call` and carry no claims beneath
them. The bar still shows: an honest "we don't know" is worth more than a
missing row, and the gap is itself information about who bounced.

- On load, bars fill left-to-right with a 350ms staggered ease-out (60ms per
  bar, beginning ~420ms — after the verdict stamp has landed) — the second
  half of the page's two-beat entrance sequence. Respect
  `prefers-reduced-motion`: render filled, no animation.
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

The verdict stamp is the page's single highest-impact element — worth
spending the "first two seconds" budget on. Everything else on the page can
be calm; this can be confident.

## The case hero (desktop)

A PC game case — PS5 case proportions, but the top spine band reads "PC" —
sits in the hero, with the wave backdrop (next section) flowing behind the
entire page. Cover art is the game's real Steam library art (see fallback
chain below).

Scroll choreography, desktop only (>=768px):
- At rest: case closed, front cover facing the viewer.
- On scroll: the case opens sideways like a book (CSS rotateY on the cover
  panel inside a perspective container), revealing the interior.
- On further scroll: the opened case settles into the left column and pins
  there. Claims, receipts, and flags flow into the right column with fluid
  entrance motion, progressively as the user continues scrolling.

Interior anatomy — the open case must read as a physical object, not two
posters side by side:

- **Disc (right side):** faced with the game's `library_hero.jpg` — a
  different, wider, more atmospheric asset than the box cover — darkened
  (brightness ~.5, contrast up, slight desaturation) under a sheen overlay:
  off-center radial highlight, faint conic light streaks, edge vignette.
  It should read as etched, reflective disc art, with the hub hole painted
  on top. Fallback when `library_hero` is missing: reuse the cover art
  heavily desaturated and darkened (still visually distinct from the case
  front) under the same sheen; if all art fails, the Split Bar motif shows
  through.
- **Inner-left panel:** the case's translucent plastic backing. It shows
  the back of the SAME front-cover art — mirrored (`scaleX(-1)`, viewed
  from behind), ~25% opacity, frosted blur, desaturated, tinted toward the
  panel's own surface color — a ghost of the cover seen through tinted
  plastic, never a second poster. It follows the cover's fallback chain
  (it is the same physical object) and hides entirely at the motif stage.

Cover art source, with fallback — library_600x900 is not present for every
title and WILL have gaps at 150-game catalog scale:
1. https://cdn.cloudflare.steamstatic.com/steam/apps/<appid>/library_600x900.jpg
   (2:3 portrait, correct aspect for a case face)
2. header.jpg (460x215 landscape) — letterboxed onto the case face with a
   blurred scaled copy of itself filling the remainder
3. Split Bar motif on a solid --surface face
Fallback must degrade silently and never break the case layout.

Mobile (<768px): the case renders as a static hero image. No scroll
choreography, no pinning, no 3D. Progressive enhancement, not a degraded
desktop layout.

prefers-reduced-motion: render the case already open and settled, the wave
as a single static frame (no loop), no scroll-linked motion, content
present without entrance animation.

## The wave backdrop

A continuously flowing, PS3-XMB-style wave behind the whole page — an
ambient field the page scrolls over, not a hero decoration. Locked by the
approved mockup:

- **Full-bleed, fixed, unclipped:** a canvas in a `position: fixed;
  inset: 0` layer, 100vw × 100vh, a direct child of `<body>` — never
  inside a content wrapper. No `overflow: hidden` ancestor, no mask, no
  fixed pixel height: nothing may create a visible boundary.
- **Stacking:** the page background lives on `html`, `body` stays
  transparent, the wave sits at `z-index: 0` with `pointer-events: none`,
  and content wrappers are lifted above it (`z-index: 1`). Do not reach
  for `z-index: -1` — a negative-z child of a painted body disappears
  behind the body's own background.
- **Always flowing:** three layered sine ribbons (two superimposed
  frequencies each, drifting vertical centers) in `--link` cyan only
  (verdict colors are semantic, never decorative) — gradient fills at
  5–15% alpha plus a 1.5px luminous crest line per layer, which is what
  makes it read as a wave rather than a texture. The rAF loop starts at
  load and never waits for interaction.
- **Scroll is a lean, not a trigger:** scroll progress eases (~5%/frame)
  into a factor that raises amplitude ~+40% and flow speed ~+60% at full
  scroll. The wave breathes on its own AND answers scrolling — alive and
  responsive, not just responsive.
- **prefers-reduced-motion: exactly one static frame.** Draw once, never
  start the loop. No slow mode, no reduced loop.

## The first two seconds

This is the wow moment, and it's the one thing in this brief that gets an
explicit exception to the "quiet" rule elsewhere in this doc. On landing on a
verdict page:

1. The verdict stamp (BUY/WAIT/SKIP) lands first — a stamp landing, not a
   fade: it scales down from 150% and settles to 100% over ~260ms with a
   slight overshoot (starting ~100ms after load), the color arriving at
   the same moment as the shape, and a one-shot ring rippling outward from
   the chip border as it settles (~450ms). The word and its meaning land
   as one beat — and it must be visibly perceptible, the first thing the
   eye catches, clearly ahead of the Split Bar starting.
2. Split Bar fills after the stamp has landed (bars begin ~420ms), each
   bar easing left-to-right over ~350ms, offset ~60ms per bar.
3. Below the fold, desktop only: the flag and each cohort section enter
   with a single fluid rise-and-fade (~450ms) the first time scrolling
   reveals them — the case-hero choreography — then are simply present.
   Mobile: present, no entrance. Don't animate anything else; the two hero
   beats above ARE the wow moment.

This sequence should read as: verdict lands → the shape of the disagreement
draws itself → then the page goes quiet and lets you read. Confident, fast,
over in about a second. Respect prefers-reduced-motion by presenting the
final state immediately, no exceptions.


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
3. Grid of game cards: title, mini Split Bar, verdict chip — and capsule art
   from the Steam CDN, consistent with the verdict-page case hero (same
   fallback chain, degrading silently; never block on it). Art is welcome on
   cards but verdict data leads: the grid should read as verdicts, not a
   store.
4. Footer: "Game not here? Request it" + methodology link.

Desktop only: card lift 2px + shadow ease on hover, ~150ms. No equivalent on
touch — don't fake a hover state with a tap.

### Verdict page (top to bottom)
1. Hero: the game's PC case, with the full-bleed wave backdrop (see "The
   wave backdrop") flowing behind the entire page. Alongside the case —
   visible immediately on load, never gated by scroll — the game title,
   verdict stamp, for-whom line, and Split Bar. The answer comes first;
   the case is atmosphere around it, not a gate in front of it.
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

### Cache-miss / generating / request states

Search is selection-only, so there is no free-text empty state — every
selection resolves to a real appid. What varies is whether we already hold a
verdict.

**Generating (the normal miss).** "We don't have this one yet — reading the
reviews now." Then a legible per-stage progress list, never a bare spinner
(CLAUDE.md guard 3): *Reading Steam reviews → Filtering out junk and unsafe
reviews → Reading each playtime cohort → Writing the verdict → Safety check.*
Completed stages tick; the current one is live. The Split Bar skeleton holds
its four rows so the page does not jump when the verdict lands.

The stated wait is **set from a measured round trip, never estimated**.
Generation alone measured **122s** on 2026-07-31 (`generate_one.py --report`);
the user-facing number must come from the full dispatch → commit → deploy
round trip, which is longer. Until that has been measured once on a real
deploy, the copy stays deliberately vague ("This takes a few minutes") rather
than precise-and-wrong. Never "under a minute."

**Queue fallback** — shown when the global reserve is spent or the QR-4 gate
fails. Same copy for both, because the distinction is ours, not the user's, and
"we found something unsafe in this game's reviews" is not information a buyer
asked for: "Not in the catalog yet. Request it and it'll be here within 48
hours." + button labeled "Request verdict". After submit: "Queued. Check back
tomorrow." No email asked, ever.

---

## Copy rules

Active voice, sentence case, plain verbs. Buttons say what they do ("Show
receipts", "Request verdict"). Numbers are specific and always carry their
denominator ("1,930 reviews across 4 cohorts", "47 in the refund window"),
never vague ("hundreds") and never bare percentages. Denominators read as
English — "92.9% positive, based on 47 reviews" — never as field names:
`pool_n` is a JSON key, not UI copy. Prevalence words — most,
majority, many players, half, few — are banned in generated copy; they are
rejected in code at 1.4, and the same rule applies to hand-written UI strings. No exclamation marks. The interface's personality
comes from precision + the one catchphrase, not from jokes.

## Quality floor (non-negotiable, ship silently)

Responsive to 360px; visible keyboard focus (`--link` 2px outline); WCAG AA
contrast on all text (check `--text-dim` on `--surface`); reduced-motion
respected; verdict pages statically generated with real `<title>`/OG tags per
game (Reddit unfurls matter for distribution).
