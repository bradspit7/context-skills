---
description: Scan the current project for open work that multi-agent orchestration can accelerate right now
---

You are running an **orchestration opportunity scan** on the CURRENT project — the do-now analogue of a heavier whole-project audit. Scan **this** project for work that is materially faster or safer **right now** with multi-agent orchestration (a capable model + `orchestrate`). Do **not** plan, build, or refactor in this pass — produce a short ranked list of do-now moves and, only after the user confirms, record them in this project's own docket. Execution happens afterward, when the user says to dispatch.

**Scope — this command's only side effect:** it reads freely, but its ONLY possible write is appending 0–2 lines to this project's *existing* docket/context file, and only after the user confirms the exact text (Step 5). It never edits product code, never creates new files, never commits, never pushes, never dispatches a subagent. A scan that ends with zero picks writes nothing at all.

## What this is (and is not)

- **PROACTIVE + WORK-focused:** "does the upcoming work in this project contain parallelizable / fan-out-suitable tasks `orchestrate` already knows how to handle?" Output = specific work items matched to specific orchestrate recipes.
- **NOT `reflect-upgrades`.** That skill is reactive + **session-bound** (did *this session* teach us something that should become a hook/skill/rule?) and routes durable learnings to the upgrades pipeline; this scan is proactive + work-focused and routes existing open work to orchestrate. They can co-exist in a session — but if you surface a tooling/upgrade idea here, **route it by its KIND, never to `reflect-upgrades` by default:** a durable learning *this session produced* (a gotcha, a repeated manual step, a correction worth binding) goes to `reflect-upgrades`; a **generative** direction — a capability the project should have but has never been bitten for lacking — goes to **`/opportunity-scan`**, which owns that lane. `reflect-upgrades` is session-bound and has no step that can receive a generative one.
- **Capability is already in hand.** No "when X lands" escape hatch. If a move's value depends on a capability you cannot show has worked in *this project's own session history*, drop it.
- **Zero DO-NOW picks is a valid and common result.** A scan that ships a move on a clean, fully-gated docket has failed exactly as a 20-item backlog has. If nothing qualifies, say exactly **"No do-now orchestration moves warranted right now"** and record nothing.

## Step 1 — Read the project cold (you have no memory of prior conversations)

Read, in order:
1. This project's `CLAUDE.md` — hard rules, invariants, verify loop, any push/merge/egress/scope constraints. **These are binding guards; bake them into every candidate.**
2. The context layer it points to — `HANDOFF.md` / `CONTEXT.md` / `continuation/context.md` / per-dev `HANDOFF-<name>.md`, open docket, "next session entry point," in-flight WIP, deferred-not-blocking items. Note which file is the live docket — Step 5 writes there.
3. Memory index, plus any spec/plan/roadmap files the handoff cites for the live track.

If this project has **no** HANDOFF/CONTEXT/docket file, that is a valid shape — ground candidates in code shape, grep results, README/spec files, and memory rules, and (per Step 5) report picks inline rather than to a docket. You are looking for **the project's real open work**: the live track, named-but-unbuilt items, deferred PRs, known issues, recurring manual rituals, large read/audit surfaces.

## Step 2 — Match real work to orchestration patterns (do not invent work)

Run two gates BEFORE recipe-matching:
- **Gate 0 — trigger-ready right now?** If the docket marks it gated (model-gated, when-X-lands, blocked-on-user, scheduled-for-a-date), it is NOT a do-now candidate however cleanly it matches — route to GATE/NOT-WORTH-IT and do not score it. Recipe fit on gated work is the single most seductive manufactured-work trap: the work is real but you cannot run it yet.
- **Gate 0b — this project, this session?** A docket item assigned to another project or another session ("in its own project session", a different repo) is OUT OF SCOPE — neither DO-NOW nor gate. Do not record other-projects work in this project's docket.

For each surviving candidate the work item MUST already exist in the docket / code shape. **Every candidate cites its grounding or it is dropped.** A grep counts as grounding ONLY when it quantifies work the docket/handoff already commits to doing — a grep that discovers a surface nobody had decided to act on is discovery, not grounding (route it to **`/opportunity-scan`** — or to `reflect-upgrades` if this session's own friction is what surfaced it — or a NOT-WORTH-IT decline). The work must pre-exist the scan in the human's own intent. The bar: "I'd have done this anyway; orchestration only parallelizes/de-risks it."

Name the orchestration pattern by **recipe name + number** from the loaded `orchestrate` skill (`~/.claude/skills/orchestrate/SKILL.md`). Cite by name — do not re-describe recipe contracts:
- **Recipe 1 — Read/Scout Fan-Out** (read-only): large read sets, audit sweeps, completeness maps, repo navigation. Verification-quote contract applies.
- **Recipe 2 — Implementer-Per-Task, Two-Stage Review**: executing an approved plan with disjoint file sets. Overlapping files serialize or worktree-isolate.
- **Recipe 3 — Review Fleet + Adversarial Verify**: code audits, multi-dimension reviews, adjudicating pasted external review output. For any change that decides what gets **written / filed / matched / registered**, the **write-path hardened gate** applies — cite it by name; do not restate its clauses (they live in orchestrate Recipe 3).
- **Recipe 4 — Background Long-Running Command**: builds, full suites, sweeps, recon — anything >2 min.
- **Recipe 5 — Workflow-Tool Structured Fan-Out**: ~10+ agents, multi-stage pipelines, loops/conditionals, schema-enforced outputs.

For any **review/audit** candidate, prefer a ready-made review-fleet runnable over hand-rolling it: if the project ships one under `.claude/workflows/`, use it (GENERATE mode for fresh reviews; RECEIVE-REVIEW for adjudicating pasted findings) and say so. If none exists, reproduce the Recipe-3 guarantees from the loaded orchestrate skill — do not block on a runnable's absence.

Per-candidate output is a **match row**: `work-item -> recipe name (#) -> project-specific tuning` (dimension overrides, concurrency cap, write-path gate vs generic, worktree isolation, which files NOT to touch).

## Step 3 — Disposition every candidate (shipping-biased)

Each candidate resolves to exactly one — a list that just accumulates has failed:
- **DO NOW** — a do-now move grounded in the live, in-this-project, trigger-ready docket. **Cap: at most 1–2, often zero.** Pick the highest-leverage; these are queued for dispatch this session or next.
- **GENUINE GATE** — a human sign-off, legal/compliance constraint, vendor limit, or safety rule orchestration cannot route around (playtest balance call, attorney review, supervised-credential access). Name it and move on.
- **NOT WORTH IT** — orchestration overhead exceeds benefit, OR the deliverable already exists, OR (this covers two cases) the work is real but **worth doing inline, not orchestrating** — do it when you get to it, don't inflate it to DO-NOW to honor it. Decline **explicitly with one-line reasoning**.

**Hard cap on speculation: at most 2 items total flagged speculative/`shipNow:false`.** Beyond that, force each into GATE or NOT-WORTH-IT.

## Step 4 — Respect this project's guards (read them from its CLAUDE.md, do not assume)

Every candidate must be expressible **without violating this project's codified rules.** Apply whichever it declares:
- **Hobby/game:** no process ceremony or infra/licensing; proven mechanics over invented features; human playtest is the gate.
- **PHI / privacy:** no external egress, read-only beyond sanctioned writes, no new write paths, gate verdicts before push; green tests are necessary-not-sufficient for any filing/registration change — an adversarial mis-write pass is the real net.
- **YMYL / deploy-on-push:** never push/deploy without explicit per-session say-so; visual changes shown before shipping; clinical/legal scope is binding.
- **Security / authorized-scope:** only the active in-scope target; neutral framing; presence-only; request-volume caps.

If a candidate can't survive these guards, it's a GENUINE GATE or it's dropped.

## Step 5 — Output contract

Produce a **short ranked findings list** (not prose):

1. **DO-NOW picks (0–2):** for each — title, pattern (recipe name + #), cited grounding, one-line payoff, and the **first concrete dispatch** ("these N targets are a clean Recipe-1 fan-out; dispatch in one message"). If none qualify, state **"No do-now orchestration moves warranted right now"** and skip the recording step.
2. **GENUINE GATES:** one line each.
3. **NOT WORTH IT:** one line each with the decline reason.

**Report before you write.** If there are DO-NOW picks, show the **exact docket line(s) you propose adding** and ask the user to confirm before writing anything — e.g. *"Record these to `<docket>`? — reply go / edit / skip."* Do not modify any file until they confirm. (Zero picks → report the verdict and write nothing.)

On confirmation, **record the DO-NOW picks in the docket Step 1 identified as this project's live next-session entry point** — not a literal filename. Use the project's OWN docket convention: read existing entries first and mirror their format; if it uses namespaced/numbered IDs (e.g. a numbered scheme like `#123` with a `<!-- next-id: N -->` counter), allocate the next ID and bump the counter, never hand-number; if it has no ID convention, add a plain dated line and leave ID assignment to the next `update-context` wrap. **Egress guard:** in a privacy/PHI project, never write to a git-tracked docket if a gitignored local one (e.g. `HANDOFF.local.md`) exists — use the local file. If the project has NO context-layer file, report the picks inline and tell the user no docket exists rather than creating one.

Do **not** create a standalone audit document and do **not** spawn a parallel review queue — a finding that produces a new deferred queue has failed this scan's purpose. End your turn after reporting (and after recording only if the user confirmed). Do not begin dispatching until the user says go.
