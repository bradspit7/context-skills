# project-scans — two complementary "what should this project do next?" commands

Two slash commands that scan the CURRENT project and return a short, ranked, honestly-labeled
list of directions — **report-only by default**, writing at most a line or two to the project's
own docket and only after you confirm the exact text. Neither builds, plans, refactors, commits,
pushes, or dispatches anything.

They read two *different* layers, and that difference is the whole point:

- **`/ultracode-scan`** reads the **docket** — the work you have already decided to do — and asks
  *"which of these open items would a multi-agent build (via the `orchestrate` skill) materially
  accelerate right now?"* It is **anti-manufacture by design**: zero do-now picks is a common,
  correct result, and it caps speculation hard. It matches real, already-committed work to named
  orchestration recipes; it never invents work.

- **`/opportunity-scan`** reads the **vision / research / half-built** layer — design docs, locked
  decisions with no code, research findings nobody turned into a task — and asks *"what
  high-leverage directions does this project's own materials point at that never became tasks?"*
  It deliberately goes **beyond** the docket, staying grounded in the project's own artifacts (an
  idea grounded only in generic best-practice is dropped or labeled `borderline-busywork`).

The docket scan is structurally blind to the vision layer, and the vision scan deliberately ignores
the "is it already committed?" gate — so they are two passes, not one. Run `/ultracode-scan` to
parallelize work you've already chosen; run `/opportunity-scan` to find work worth choosing.

## Install

Copy the command files to your Claude Code commands dir:

```bash
cp project-scans/commands/opportunity-scan.md project-scans/commands/ultracode-scan.md ~/.claude/commands/
```

Claude Code exposes them as `/opportunity-scan` and `/ultracode-scan`.

## Dependencies

- **`orchestrate`** (in this repo's `skills/`) — `/ultracode-scan` names its Recipe 1–5 patterns.
  Install the process suite (see the top-level README) so the recipe references resolve.
- **`brainstorm`, `reflect-upgrades`** (also in `skills/`) — the scans reference these to stay in
  their lane: `/opportunity-scan` is *not* `brainstorm` (which designs a feature you've already
  named) and *not* `reflect-upgrades` (which routes tooling learnings, not product directions).
  Nothing breaks if they're absent — the references simply describe boundaries.

## Generalized from a private original

These are de-personalized forks of the maintainer's private global commands — an example workflow
path, an internal audit codename, and a specific model name were replaced with generic phrasing.
Behavior is identical. Both degrade gracefully: they work in any project type, with or without a
docket, and with or without a numbered-ID docket convention.

## Modify freely

Adapt the trigger phrases, the 3–5 direction cap, the speculation cap, the guard families
(hobby/game, PHI/privacy, YMYL/deploy-on-push, security), and the honesty labels to your projects.
The anti-manufacture gates in `/ultracode-scan` and the grounding requirement in `/opportunity-scan`
are the load-bearing parts — keep those.
