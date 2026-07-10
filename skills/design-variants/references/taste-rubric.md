# Taste rubric — design-variants

The judgment layer for `design-variants`. Authored once as a stable rubric so the taste
survives model changes: use it to pick variant theses (Step 1), hold the quality bar
(Step 2), and self-critique before presenting (Step 3).

## 1. Axes of variation (the thesis menu)

A variant earns its slot by committing to ONE primary axis. Pick the axes that are live
for the brief — the axis where the current design is weakest is usually variant A.

- **Structure / layout** — what the page IS: grid vs single column, split vs stacked,
  where the eye enters. The highest-information axis; if the user is unhappy and can't
  say why, vary structure first.
- **Hierarchy / emphasis** — what wins the first 3 seconds: scale contrast, one hero
  element vs democratic blocks, how ruthlessly secondary content is demoted.
- **Color / mood** — temperature, saturation discipline, dark vs light ground, one-accent
  vs palette. Cheapest axis to vary, easiest to over-credit: color changes FEEL big but
  rarely fix a structural problem. Never let 2 of 3 variants be color-only.
- **Typography / voice** — type scale and pairing, editorial vs utilitarian, how much the
  words themselves are the design.
- **Density / breathing room** — information per viewport: compact-and-scannable vs
  spacious-and-sequential. Vary this when the audience is split between experts (want
  density) and newcomers (want air).
- **Motion / attention** — what moves and when. Only a primary axis when the surface is
  interactive; otherwise restraint IS the taste (motion that doesn't direct attention is
  decoration).

## 2. The quality bar (every variant, before it earns a table slot)

- **Thesis legibility:** the variant's one-line thesis is visible in the artifact within
  3 seconds, without the label. If you need the badge to tell variants apart, they are
  the same variant.
- **Commitment:** the thesis is carried through every element it touches. A "bold color"
  variant with one timid accent has not committed; go further or change the thesis.
- **Internal consistency:** every element serves the thesis or stays neutral. No element
  fights it (a dense-data thesis with a decorative hero image is fighting itself).
- **Craft floor (non-negotiable, all variants):** aligned edges, consistent spacing
  rhythm, readable contrast (WCAG AA as the floor), no broken states in the shown
  viewport. A variant below the craft floor is rebuilt, not presented — a sloppy bold
  take reads as "bold is sloppy" and poisons the axis.
- **Token discipline:** respect the project's existing design tokens/system unless the
  brief explicitly breaks them; a variant that ignores the system is proposing a
  redesign of the system — say so in its thesis or rein it in.
- **The bold slot:** exactly one variant per round goes past the brief's comfort zone on
  its axis. Rejected bold takes are cheap and calibrate the user's range faster than two
  safe ones.

## 3. Self-critique protocol (Step 3, one line per variant)

State where the variant commits and where it cheats. Honest examples:

- "A commits to a single-column editorial structure; cheats by keeping the old nav, which
  fights the linear flow."
- "B is C with a warmer palette — FAILS diversity, rebuild on a structure thesis."
- "C carries density all the way to the footer; bold slot; may read as cluttered on
  mobile — check 375px."

If any critique names another variant as its baseline ("X but warmer"), the round has a
diversity failure: rebuild before presenting. Never present a known-weak variant as
filler to make a count.

## 4. Selection guidance (what to point the user's eye at)

- Direct attention per axis, not per variant: "watch where your eye lands first on each"
  (hierarchy), "notice how much you scroll" (density), "which one still looks right at
  arm's length" (structure).
- Ask for a gut pick BEFORE reasons. Post-hoc reasons follow the pick anyway; the gut
  pick is the data.
- **Mix-and-match composes components, not midpoints.** "A's header on B" is a real
  outcome; "somewhere between A and B" is not — averaging two theses produces the
  committee design both were built to avoid. Offer the nearest committed version instead.
- If the user rejects all variants, the round still succeeded if it localized the axis
  ("structure was wrong in all three") — run round 2 varying THAT axis only.

## 5. Anti-patterns (the ways variant rounds actually fail)

- **Three shades of the same idea** — one thesis in three trench coats; the diversity
  failure the axes exist to prevent.
- **Decoration-as-taste** — gradients/shadows/animation added without a hierarchy change;
  reads as effort, changes nothing about what the eye does.
- **Novelty scoring** — picking or building the weird one because it is different, not
  because its thesis serves the brief. The bold slot explores range; it is not
  automatically the recommendation.
- **Form breaking function** — a variant that sacrifices a working element (nav, form,
  CTA) for looks; production surfaces earn their look around the job they already do.
- **Averaging on request** — see §4; hold the line politely and offer the nearest
  committed alternative.
