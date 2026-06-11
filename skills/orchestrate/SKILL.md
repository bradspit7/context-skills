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

For audits/reviews: one agent per dimension (correctness, security, conventions, staleness…), dispatched concurrently. Before acting on findings that would drive real changes, run an **adversarial pass**: a skeptic agent per finding, prompted to REFUTE it against the actual code. Findings that survive get acted on; "plausible but wrong" dies here instead of in your diff.

## Recipe 4 — Long-running commands

Any command expected to run >2 minutes (sweeps, builds, full suites, recon): launch as a background task and keep orchestrating; collect on completion. Never sit idle behind a long command, and never poll in a sleep loop. When a project skill *wraps* such a command, write this discipline into that skill's own text ("background launch, never poll, keep working or end the turn") — the instruction living in the skill is what makes every future session do it unprompted.

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
