---
name: orchestrate
description: "Fan independent work out to parallel subagents with explicit contracts — read fan-outs with verification quotes, implementer-per-task with two-stage review, dimension-split review fleets, background tasks for long commands. Drop-in replacement for superpowers:subagent-driven-development AND superpowers:dispatching-parallel-agents. Use for 2+ independent tasks, heavy read sets, multi-file audits/sweeps, or executing a plan whose tasks are mostly independent."
---

# Orchestrate — parallel subagents under explicit contract

Delegate to fresh subagents with precisely constructed context, run independent work concurrently, verify everything that comes back. Replaces `superpowers:subagent-driven-development` and `superpowers:dispatching-parallel-agents`; where they conflict, this wins.

The contracts below are deliberately mechanical. Follow them as written — they encode failures already paid for (skimmed reads, rubber-stamped findings, parallel agents colliding on shared files). Do not relax them because the work "seems simple."

## When / when not

**Use:** 2+ tasks with no shared mutable state; read sets too large for one context; multi-file audits, sweeps, migrations; plan execution where tasks are independent; review passes split by dimension.
**Don't use:** tightly coupled or sequential tasks (→ `execute-plan`); exploratory debugging where you don't yet know what's broken (→ `superpowers:systematic-debugging`); work small enough that dispatch overhead exceeds the work.

**Independence test before dispatching:** would any two agents read state another agent mutates, or edit the same file? If yes, serialize those two or isolate via worktrees — never "probably fine."

## The prompt contract (every dispatch, no exceptions)

Subagents inherit NOTHING from this conversation. Every prompt must carry:

1. **Scope** — the one problem domain, named files/areas, and explicitly what NOT to touch.
2. **Context** — everything needed to act cold: error text, task text from the plan (paste it — never "read the plan file"), relevant project-law excerpts (no-push, append-only files, ownership, PHI/scope rules).
3. **Verification duty** — the exact command(s) the agent must run before reporting, with expected outcome.
4. **Output format** — structured: what it found/changed, evidence (command output), files touched, and a status from: `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`.
5. **Model** — typed agents never inherit the session model: an omitted `model` resolves to the agent-type's default (measured: `Explore` → Haiku). Pass it explicitly wherever judgment quality is load-bearing — all reviewers/verifiers, and readers when extraction is subtle.

## Recipe 1 — Read/scout fan-out (read-only, Explore-type agents)

For large read sets (context layers, audits, research):
- Slice the read set; one agent per slice; dispatch in a single message so they run concurrently.
- Contract: read every assigned file FULLY, chunking past every truncation — never sparse-search; return a structured extract (current-state claims with dates, locked decisions, open items, contradictions vs the summary you supply).
- **Verification quotes:** for every file over ~100 lines, the extract includes one short verbatim quote from its top, middle, and bottom third, with line numbers. A missing bottom-third quote for a file over that threshold means the file wasn't fully read — re-dispatch that slice.

## Recipe 2 — Implementer per task, two-stage review

For plan execution with independent tasks:
- One fresh implementer per task, given the full task text + scene-setting context. Same-model default; drop to a cheaper model only for mechanical 1-2-file tasks with complete specs; keep the most capable model for review and integration judgment.
- **Never run two implementers concurrently whose file sets overlap.** Disjoint sets may run in parallel; overlap = serialize or worktree-isolate.
- After each implementer: **spec-compliance review first** (does the diff match the task — nothing missing, nothing extra), **then code-quality review**. Fresh reviewer agents; findings go back to the implementer to fix; re-review after fixes. Never start quality review before spec review passes; never advance a task with open findings.
- Status handling: `NEEDS_CONTEXT` → supply it, re-dispatch. `BLOCKED` → change something (context, model, task size) or escalate; never re-dispatch unchanged. `DONE_WITH_CONCERNS` → read the concerns before proceeding.

## Recipe 3 — Review fleet + adversarial verify

For audits/reviews: one agent per dimension (correctness, security, conventions, staleness…), dispatched concurrently. Before acting on findings that would drive real changes, run an **adversarial pass**: a skeptic agent per finding, prompted to REFUTE it against the actual code. Findings that survive get acted on; "plausible but wrong" dies here instead of in your diff. Adjudicating a pasted NUMBERED review: first prove the parse covers its own numbering ({1..N} exactly once — a bare count passes on drop+duplicate, observed live); an unproven parse is a logged coverage hole, never a silent drop.

**Spawn every reviewing lens read-only** — reviewers, verifiers, critics, synthesizers, and any parse/transform helper that feeds them (every fleet agent that is not the orchestrator). A reviewing agent needs no write tools — give it a read-only `agentType` (`Explore`, or a tools-restricted reviewer) so a lens cannot edit the artifact it is judging. Prompt-level "review only" is NOT a guard when the agent still holds `Write`/`Edit`: default the tools off, and let the **orchestrator** (not the lens) apply fixes, deliberately, after reading the findings. This is paid-for — a completeness-critic running on the default write-capable agent once autonomously edited a live production file mid-gate when the pass was meant to be advisory-only. A read-only type like `Explore` still retains `Bash`, so seal the gate at the prompt level too: tell each lens in its prompt to use read-only inspection only (no mutating shell commands).

**Validate the fleet itself before trusting its verdicts.** A zero-finding run is ambiguous — clean code, a too-lenient gate, and a fleet that never read its target all look identical. Seed a *known* bug into a throwaway copy and confirm the fleet flags it — and make the seed exercise the verify-gate edge paths (a 1-1 tie, a crashed verifier), not just an obvious bug every verifier agrees on. An obvious-bug-only seed leaves the threshold logic unexercised and passes even when the gate is wrong (real case: a gate that confirmed 1-1 ties passed its obvious-bug seed because the verifiers happened to agree). A green review run is necessary, not sufficient — green-tests-not-sufficient, applied to the reviewer.

**Write-path fleet — the hardened gate (use when the change decides what gets *written / filed / matched / registered*).** The generic pass above is not enough for write-path logic; this gate has already paid for real silent-data-loss bugs. A correct write-path fleet MUST hold all of:
- **Named dimensions** including a *reproduce-the-specific-mis-write* lens (not just generic correctness) and reachability of the new state, alongside the standard lenses.
- **Strict majority of the *expected* votes** (default 3 skeptics/finding); a missing or crashed vote counts as **refute**, never a silent confirm.
- **`needsReverify` bucket** — a crashed/timed-out verifier surfaces for hand-adjudication; it is never silently folded into refuted.
- **Exactly-one source coverage** — every finding maps to exactly one input; a missing / duplicated / invented mapping forces the fallback (no silent drop, no double-count). For the receive-mode parse of a pasted numbered review, Recipe 3's parse-coverage proof applies.
- **One shared concurrency pool** below the runtime's ~14 cap (default ~6) + retry of crashed slots, so the verifier burst can't trip the rate-limit into false-refutes.
- **Read-only lenses** — every non-orchestrator agent in the fleet (reviewers, verifiers, critics, synthesizers, parse/transform helpers) runs under a read-only `agentType` (e.g. `Explore`) AND is told in-prompt to avoid mutating shell commands (`Explore` keeps `Bash`); a gate that can mutate the artifact under review is not a gate. The orchestrator applies confirmed fixes itself, after adjudication. Model pins per the prompt contract (item 5): every lens/verifier call passes its model explicitly (the fleet's role defaults or a per-lens pin).
- **Different-model verifiers (ratified 2026-07-01; canonical form assumes single-model access)** — when a second strong model is available (a different lineage such as Codex, or a second strong Claude tier), run verifiers on a **different model** than the reviewer/judge lenses, so no finding is confirmed by the model that raised it. With single-model access, a same-model fleet is the validated baseline — but the model that AUTHORED the change is never its *sole* certifier (angle-diverse refute-by-default verifiers + the orchestrator's human-adjudicated apply step carry the gate). Pin any security-adjacent lens AND its verifiers to a model without cyber-classifier refusal exposure (Opus 4.8 today — Fable 5 false-positive-refuses security-lens prompts even on defensive review, and a refused lens agent returns null, which otherwise masquerades as a clean zero-findings pass: surface it as a coverage hole, never a clean zero).

Run the project's validated review-fleet workflow when it provides one (generate mode for a diff; receive mode to adjudicate an external review's claims); reproduce every guarantee above from scratch only when it doesn't. A from-prose re-derivation that drops any of these is the exact failure this contract prevents.

## Recipe 4 — Long-running commands

Any command expected to run >2 minutes (sweeps, builds, full suites, recon): launch as a background task and keep orchestrating; collect on completion. Never sit idle behind a long command, and never poll in a sleep loop. When a project skill *wraps* such a command, write this discipline into that skill's own text ("background launch, never poll, keep working or end the turn") — the instruction living in the skill is what makes every future session do it unprompted.

## Recipe 5 — Big fan-outs via the Workflow tool (when the harness offers it)

Prefer a Workflow script over hand-rolled Agent batches once the fan-out has structure: ~10+ agents, multi-stage pipelines (mine → verify → synthesize), loops/conditionals, or wherever validated structured outputs matter. The prompt contract above carries over verbatim — every workflow agent prompt still needs scope, cold-start context, verification duty, and output format. Workflow-specific contracts (proven on a 25-agent corpus-mining run, 2026-06-10):

- **Schema-enforce every agent output** (the `schema` option) — validated JSON beats parsing prose, and mismatches retry at the tool layer instead of corrupting the pipeline.
- **`args` may arrive as a JSON string, not the object you passed** — parse defensively at the top: `let A = typeof args === 'string' ? JSON.parse(args) : (args || {})`. Skipping this does not error: a truthy string makes `args.foo` silently `undefined`, so every option falls back to its default — the symptom is a script that ignores its inputs (e.g. a review fleet that reviews the *default* target and reports nothing).
- **Join stage-N verdicts back to stage-N−1 findings mechanically** (normalize + fuzzy-match on the key field) and **count coverage per kind**. Verifiers skip findings silently — the reference run's first wave covered only ~53% of findings. Dispatch a top-up wave over the measured gap; never average over it.
- **Authenticate claims against sources in the verify stage:** the verifier greps the source material for a distinctive substring of each claim's quote; `quote_found=false` kills the finding regardless of plausibility (8/200 died this way in the reference run).
- Launch in the background and keep orchestrating (Recipe 4 discipline applies); collect on the completion notification.
- No Workflow tool on the current surface → run the same structure as sequenced Agent-tool batches. The contracts, not the tool, carry the quality.

## Integration (the orchestrator's own duties)

- **Continuous execution:** no "should I continue?" between tasks. Stop only for an unresolvable `BLOCKED`, genuine ambiguity, or completion.
- **When executing a written plan:** first run execute-plan's Step 1 yourself (full plan read, assumption/currency check, branch discipline), and as tasks complete, check off their `- [ ]` boxes in the plan file and log deviations there — orchestrated execution gets the same plan integrity as inline execution.
- Read every summary; spot-check claims against the actual diff/files — agents can be systematically wrong with full confidence.
- Check for cross-agent conflicts (same file edited twice, contradictory extracts) before accepting results.
- **Run the project's full verify loop yourself once at the end.** Per-agent verification doesn't cover integration.
- **No silent truncation:** failed, skipped, or dropped agents are reported with what they covered — a partial fan-out that reads as complete is worse than a smaller honest one.
- Wrap-up: commit per project law (never push unprompted); on a feature branch route to `superpowers:finishing-a-development-branch` — asking its integration question as a one-line prose question with a single recommendation, never the choice-button UI; suggest `/update-context` if the session is ending.

## Red flags

- Dispatching an agent that must "read the plan/handoff first" — paste the content; the file read costs more than the paste and the agent may read the wrong version.
- Accepting an extract missing its bottom-third quote (for a file over the ~100-line threshold), or a "DONE" with no verification output — contract violation, re-dispatch.
- Fixing an agent's half-done work by hand in the orchestrator context — dispatch a fix agent with specific instructions instead.
- Two implementers in flight on overlapping files "because they're quick."
- Relaxing review order (quality before spec) or skipping the re-review after fixes.
- Trusting a verifier's verdict label without reading its evidence fields — schema-enforced labels still drift semantically ("confirmed" can mean "the pattern is real" rather than "the claim survives"; a verifier whose *reason* refuted a claim was measured setting `refuted=false` — it answered "is the code fine?" instead of "does the claim survive?"). Pin the question mechanically where the tool allows it (per-field schema `description`s), AND classify from the cited evidence; mechanically join verdicts back to findings and count coverage — re-dispatch the gap, never average over it.
