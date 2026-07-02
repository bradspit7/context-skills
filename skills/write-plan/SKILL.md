---
name: write-plan
description: "Turn an approved design or spec into an executable implementation plan at docs/superpowers/plans/. Drop-in replacement for superpowers:writing-plans. Use when a design is approved (usually via brainstorm) and the work is multi-step. Plans assume a zero-context executor — exact paths, complete code, and a per-task verify step drawn from the project's own verify loop."
---

# Write-plan — approved design to executable plan

Write plans a skilled developer with **zero context for this codebase** could execute: every file path exact, every code change shown, every task verified with a real command. The plan is the contract that lets a weaker model — or a future cold session — execute at full quality. This replaces `superpowers:writing-plans`; where they conflict, this wins.

**Save to:** `docs/superpowers/plans/YYYY-MM-DD-<feature-name>.md` (project conventions override).

## Before writing

1. **Spec in hand** — if there's no approved design, route to **brainstorm** first.
2. **Scope** — multiple independent subsystems = multiple plans; each plan ships working, verifiable software on its own.
3. **File map** — list every file created/modified and its single responsibility before cutting tasks. This locks decomposition. Follow the codebase's existing patterns; don't unilaterally restructure.
4. **Verify loop** — read the project's CLAUDE.md for the house verification commands. Plan steps verify with THE PROJECT'S loop, not a generic one: pytest-style TDD where that's house style; parse-validation + headless runs in Godot projects; the site's own pre-commit gate skill and link-the-changed-page habits in static-site work; `--verify` scripts where they exist. A plan whose verify steps don't match the project's reality will be skipped by its executor.
5. **Project law** — fold binding rules (branch discipline, no-push, ownership claims, PHI/scope guards, append-only files) into the tasks they constrain, restated inline. The executor must not need to discover them.

## Plan header (mandatory)

```markdown
# [Feature Name] Implementation Plan

> **For executors:** run this plan with the `execute-plan` skill (coupled tasks, inline)
> or `orchestrate` (independent tasks, parallel subagents). Steps use `- [ ]` checkboxes.

**Goal:** [one sentence]
**Architecture:** [2-3 sentences]
**Spec:** [path to the design doc]
**Verify loop:** [the project's commands, copied here]
```

## Task structure

Each task: 2-5 minute steps, one action per step, checkbox-tracked.

````markdown
### Task N: [Component]

**Files:**
- Create: `exact/path/file.py`
- Modify: `exact/path/existing.py:123-145`

- [ ] **Step 1: Write the failing test / define the expected behavior**
  (actual test code or exact expected-behavior description — not "write tests")
- [ ] **Step 2: Verify it fails** — `<command>` → expected: FAIL with <message>
- [ ] **Step 3: Implement** — (the actual code, shown)
- [ ] **Step 4: Verify it passes** — `<command>` → expected: <output>
- [ ] **Step 5: Commit** — `git add <paths> && git commit -m "<message>"`
````

Where the house style isn't test-first (e.g., scene/asset work), steps 1-4 become: make the change → run the project verify loop → check the observable result (named explicitly: which scene, which page, which output line).

**Write-path tasks carry a review-fleet step.** If a task decides what gets *written / filed / matched / registered* (a matcher, a registration/attribution gate, a foundational constant other code reads), add an explicit verification step before its commit step that dispatches the **write-path review fleet** (orchestrate's hardened contract). A green per-task test proves the data layer, not single-pass correctness — the fleet is the step that catches the mis-write. Run its adversarial pass on a different model than wrote the code where possible.

## No placeholders — these are plan failures

- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling / validation / edge cases"
- "Write tests for the above" without the actual tests
- "Similar to Task N" — repeat the content; tasks get read out of order
- Steps that say what without showing how
- References to types/functions no task defines

## Self-review (run on the finished plan, fix inline)

1. **Spec coverage** — every spec requirement maps to a task; gaps become tasks.
2. **Placeholder scan** — patterns above.
3. **Consistency** — names/signatures match across tasks; verify commands actually exist in this repo.
4. **Law check** — no task instructs something a project rule forbids.
5. **Write-path check** — every task that decides what gets *written / filed / matched / registered* carries its review-fleet step; a missing one is a plan failure.

## Hand off

Commit the plan per project law, add a docket/HANDOFF pointer if the project keeps one, then recommend ONE executor in one line: **orchestrate** when tasks are mostly independent (parallel subagents, per-task review), **execute-plan** when tasks are coupled or sequential. State which and why in a sentence — don't present it as a menu.
