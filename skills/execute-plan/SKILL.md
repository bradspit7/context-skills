---
name: execute-plan
description: "Execute a written implementation plan task-by-task in the current session — per-task verification, evidence before completion claims, stop-on-blocker. Drop-in replacement for superpowers:executing-plans. Use when a plan exists (docs/superpowers/plans/) and its tasks are coupled or sequential; for mostly-independent tasks prefer orchestrate."
---

# Execute-plan — run a written plan with discipline

Load the plan, verify its assumptions, execute every task with its verification, report with evidence. This replaces `superpowers:executing-plans`; where they conflict, this wins.

## Step 1 — Load and currency-check

1. Read the plan file **in full** (chunk past any truncation).
2. Read the spec it cites if anything is ambiguous.
3. **Verify the plan's assumptions still hold before task 1:** the files it modifies exist at the cited paths, the branch state matches what it expects, the verify-loop commands it names actually run here. Plans go stale the same way handoffs do — a plan written three sessions ago describes a repo that may have moved.

   **Separate CURRENCY assumptions from BEHAVIORAL premises — they fail differently and only one of them is a defect-finding instrument.** Everything above is *currency*: do the paths still exist, does the branch match, do the commands run. A **behavioral premise** is different in kind — *"X is currently untested"*, *"deleting this branch leaves the suite green"*, *"nothing guards Y today"* — because it is a **claim about the code**, so verifying it is itself a measurement. **Measure it, and when it comes back FALSIFIED do not just record "premise stale, move on" — ask "what IS unguarded here, then?"** A stale premise means someone already closed the hole the plan was aimed at, and the interesting question is what *remains* open beside it. **Measured 2026-07-28:** a plan asserted *"deleting this branch currently leaves all tests green — verify that is still true."* It was stale; an intervening round already caught full deletion. Rather than write a test for an already-closed hole, the executor probed the *realistic* drift instead — widening the branch so a timed-out child ALSO releases the origin — which left the entire suite **green at 2780 passed / 0 failed**. That is a live duplicate-order path in a clinical system, and nothing pinned it. The falsified premise was the only thing that pointed at it.
4. Review critically: real concerns (wrong approach, missing dependency, contradicts project law) go to the user BEFORE execution starts. No concerns → create a task list (one entry per plan task) and go.
5. Branch discipline: never execute on main/master when project law forbids it — branch first.

## Step 2 — Execute, task by task

For each task, in order:

1. Mark in_progress.
2. Follow the steps **exactly as written** — the plan is the contract. The executor's judgment is for noticing problems, not for silently "improving" the plan.
3. Run every verification step and **read its output**. Expected-FAIL steps must actually fail; expected-PASS steps must actually pass. Never narrate a verification you didn't run.
4. Check the checkbox in the plan file, commit per the task's commit step, mark completed. One task at a time — never batch-complete.

**Continuous execution:** no "should I continue?" between tasks, no progress check-ins, no deferring approved tasks to "later". Stop only for: a real blocker, a verification failure that persists after the systematic-debugging route below, an instruction you genuinely can't interpret, or a discovered design-level problem.

**Deviation protocol:**
- *Minor* (path moved, rename, obvious typo in the plan): fix, note the deviation in the plan file next to the task, proceed.
- *Design-level* (task can't work as written, spec conflict, law conflict): STOP, surface to the user with what you found, don't improvise around the plan.

**Write-path safety gate (mandatory).** A task that decides what gets *written / filed / matched / registered* must run a **write-path review fleet** (orchestrate's hardened contract) before it can be marked complete. If the plan specifies the step, execute it. If the plan OMITS it for a write-path task, that is a plan defect, not a license to improvise: log it as a mandatory safety deviation in the plan (per the deviation protocol) and run the fleet, or STOP and surface it — never skip it silently, never bolt it on without recording the deviation.

**On failure:** verification fails twice on the same step → stop patching blind; route to `superpowers:systematic-debugging`, find the root cause, then resume the plan.

## Step 3 — Close out

1. Full-suite verification: run the project's whole verify loop once at the end, not just per-task checks — integration breaks live between tasks.
2. Update the plan file: all boxes checked, deviations noted.
3. On a feature branch with project-law integration steps → route to `superpowers:finishing-a-development-branch`, but ask its integration question as a one-line prose question with a single recommendation — never the choice-button UI or an option menu. Otherwise commit per project law (never push unprompted).
4. Session ending → suggest `/update-context`; the plan's outcome belongs in the handoff layer.

Report with evidence: what ran, what passed, exact failures if any, deviations made. "Done" claims come with the verification output that proves them.

## Self-checks

- Skipping a verify step "because it obviously passes" — run it.
- Batch-marking tasks complete at the end — per-task, in the moment.
- Quietly rewriting the plan mid-flight — deviations are logged or escalated, never silent.
- Pushing through a blocker with guesses — stop and ask; the plan author had context you may lack.
- Asking permission to continue between tasks — the approved plan IS the permission.
