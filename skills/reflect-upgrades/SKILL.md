---
name: reflect-upgrades
description: Use after substantial work or a real finding to reflect on whether the session warrants a new or upgraded tool, hook, subagent, skill, slash command, MCP, catalog entry, or rule. Fires on "did we learn anything that would help build or upgrade our tools", "reflect on upgrades", "/reflect-upgrades", or proactively when a work session produced durable learnings. Routes generalizable upgrades to a central upgrades repo or catalog and project-specific ones to the current project. Surfaces and files candidates; it does not build them.
---

# Reflect-upgrades — turn session learnings into tooling upgrades

The reflection worth running every session: *did we learn anything that would help build or upgrade
our tools, subagents, hooks, skills, commands, or rules?* This skill is its single canonical home. It
is invoked three ways — manually (trigger phrases above), by `update-context` at every wrap (Layer 1),
and by the `upgrade-reflection-nudge` hook once per session after substantial work (Layer 2).

This is a read-only judgment pass: it **surfaces and files candidates**, it does not build them.
Building a surfaced upgrade is separate, approved work.

## When to fire / not fire

Fire when a session produced substantive work — edits, commits, a captured learning, a debugged
gotcha, a manual step done more than once, friction hit more than once — and you are reflecting on
whether tooling should change.

Do NOT fire on pure Q&A or trivial sessions with no durable signal. Return the empty verdict
(Step 5) rather than manufacturing candidates.

## Step 1 — Gather the session signal

From the conversation plus git state, list what this session actually produced: shipped artifacts,
decisions, debugged gotchas, repeated manual sequences, friction hit more than once, and any memory
files written. If `update-context` already computed shipped / learned / decided / deferred, reuse it
— do not recompute.

## Step 2 — Scan against the upgrade surface

For each signal item, ask whether it warrants a new or upgraded:

| Surface | A candidate looks like |
|---|---|
| **skill** | a multi-step judgment procedure done by hand that would repeat across sessions |
| **hook** | a deterministic check / guard / nudge that should fire automatically on an event |
| **subagent / agent** | a self-contained delegated task done inline a specialized agent would do better |
| **slash command** | a fixed prompt or recipe typed more than once |
| **MCP / connector** | a manual external-service interaction a tool could automate |
| **catalog entry** | a tool / plugin / skill discovered or used that is worth recording for reuse |
| **CLAUDE.md rule** | a correction or convention that should bind future sessions (project or global) |
| **memory promotion** | a rule that has now bitten 2+ projects belongs in a skill or global CLAUDE.md |

## Step 3 — Filter (the anti-noise gate)

Every candidate must pass two filters:
1. **Load-bearing test** — *would a future session act differently if this tool existed?* No -> drop
   it. Do not invent work to look productive.
2. **De-dup** — check your central upgrades repo's docket and your catalog (if you keep one). Already
   queued -> do not re-propose; point at the existing entry instead.

## Step 4 — Route and file

Apply the routing rule:
- **Generalizable** (helps many projects, or is about your tooling itself) -> file to your **central
  upgrades repo or catalog** — a docket / "next candidates" item, or a catalog stub.
- **Project-specific** (only helps the current project) -> the current project's own docket / memory.

File the surviving candidates to the right home — do not merely mention them. Filing means a docket
line, a handoff entry, or a catalog stub. It does not mean implementing.

## Step 5 — Report

Emit an **Upgrade candidates** block, one row each:
`<surface> | <one-line what> | <evidence from this session> | routes-to <central|project> | ~<effort>`

If nothing survives the filters, say so in one line: "No tooling upgrades warranted this session."
That is a valid and common result.

## Do NOT
- Build the upgrades — surface and file only (a trivial single-edit the user approves on the spot is
  the only exception).
- Manufacture candidates to seem productive — the load-bearing test is the gate.
- Re-propose something already on the docket or in the catalog.

## Companion hook

`hooks/upgrade-reflection-nudge.py` is a `UserPromptSubmit` hook that fires this reflection
automatically: once per session, after a substantial-work signal (>= N file edits, a memory-file
write, or a `git commit`), it injects a one-line non-blocking nudge to run this skill. Wire it in
`~/.claude/settings.json` under `UserPromptSubmit` (env tunables: `UPGRADE_NUDGE_EDIT_THRESHOLD`
default 3; `UPGRADE_NUDGE_DISABLE=1` to silence). Pure stdlib, ASCII-only, fails open.

## Related
- `update-context` — invokes this at every wrap (Layer 1); its shipped / learned / decided signal
  feeds Step 1.
- `hooks/upgrade-reflection-nudge.py` — the once-per-session `UserPromptSubmit` nudge (Layer 2).
