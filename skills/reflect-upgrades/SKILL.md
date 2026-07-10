---
name: reflect-upgrades
description: Use after substantial work or a real finding to reflect on whether the session warrants a new or upgraded tool, hook, subagent, skill, slash command, MCP, catalog entry, or rule. Fires on "did we learn anything that would help build or upgrade our tools", "reflect on upgrades", "/reflect-upgrades", or proactively when a work session produced durable learnings. Routes generalizable upgrades to a central upgrades repo or catalog and project-specific ones to the current project. Surfaces and files candidates; it does not build them.
---

<!-- canonical: ~/.claude/skills/reflect-upgrades/SKILL.md · version: 2026-07-09.2 -->
<!-- Version-stamped so cross-estate reconciliations diff against a stamp, not archaeology.
     Bump the date-tag on any substantive edit; a fork adds its own provenance line here. -->

# Reflect-upgrades — turn session learnings into tooling upgrades

The reflection worth running every session: *did we learn anything that would help build or upgrade
our tools, subagents, hooks, skills, commands, or rules?* This skill is its single canonical home. It
is invoked three ways — manually (trigger phrases above), by `update-context` at every wrap (Layer 1),
and by the `upgrade-reflection-nudge` hook once per session after substantial work (Layer 2).

This is a judgment-and-filing pass: it **surfaces and files candidates** — to the sanctioned
filing targets in Step 4 (docket lines, handoff entries, the catalog, the self-audit log) — it
does not build them. Building a surfaced upgrade is separate, approved work.

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

**Self-audit feeder (own-miss stream, paired reader built in):** separately from the tool-gap
scan above, ask — did this session contain a *reasoning miss* no existing tool would have caught
(a blind spot, a wrong reading you corrected, an assumption that bit)? That is a different signal
class from a tool-gap candidate: it needs a captured lesson, not a new tool. Append it as one
dated line to the **self-audit log** in the central upgrades repo (`SELF-AUDIT.md` at its root;
create it on first use) — a transcript-verifiable one-liner naming the miss and its mechanism.
The reader is this same skill: **whenever it fires, first read the self-audit log's still-open
entries** — any recurring or now-fixable miss becomes a Step-2 tooling candidate on this pass
(mark the entry resolved when it does). That closed loop is what earns the capture; never open a
write-only backlog.

## Step 3 — Filter (the anti-noise gate)

Every candidate must pass three filters:
1. **Load-bearing test** — *would a future session act differently if this tool existed?* No -> drop
   it. Do not invent work to look productive.
2. **De-dup** — check your central upgrades repo's docket and your catalog (if you keep one). Already
   queued -> do not re-propose; point at the existing entry instead.
3. **Target-project-alive** — if the candidate's remediation *target* is a specific project, confirm
   that project is still active before filing (if you track project lifecycle status). A candidate
   targeting a discontinued or abandoned project is **dead work — do not file it**. (A dead project's
   *machine-level* kernels — shell/tooling traps that bite anywhere — stay valid and generalize as
   usual; only project-*targeted* work dies with it.)

## Step 4 — Route and file

Apply the routing rule:
- **Generalizable** (helps many projects, or is about your tooling itself) -> file to your **central
  upgrades repo or catalog** — a docket / "next candidates" item, or a catalog stub.
- **Project-specific** (only helps the current project) -> the current project's own docket / memory.

**Dual-surface candidates — split, don't bury.** When a candidate touches *named shared machinery* —
a lifecycle or process skill (`update-context`, `analyze-context`, `orchestrate`, ...), a global
instruction file (e.g. `CLAUDE.md`), your catalog, a global hook, or the upgrade pipeline itself — it
has a generalizable kernel even when its concrete instance is project-local. File the kernel
**centrally** (and the project-local instance, if any, in the project). The project-local surface
must not keep the kernel trapped in the project docket — that is exactly how a real
`update-context`-rotation kernel once got stranded as a single project's roadmap item. Anti-over-filing
gate: it must touch the *named* shared machinery above, not merely "feel like it could generalize" —
Step 3's load-bearing test still applies.

**Filing from another project's session — durable + receipt-bearing.** Your central upgrades repo is
reachable by its local path even when the session is rooted elsewhere. File as a **new committed inbox
file**, never an uncommitted edit to a live central doc: write `DOCKET-INBOX-<date>-<project>.md` at
the central repo root (rows in docket style, unnumbered — ids are allocated at ingest, which also
removes counter contention between concurrent filers), **commit it immediately**, and **show the user
the receipt (path + short sha) in this session's report** — "filed" means a quotable commit, never
"it's in a working tree." A new file bundles no unrelated work and cannot be clobbered by a concurrent
session or a snapshot rewrite of the doc it would otherwise have edited. Your next central session
ingests the inbox: allocate ids, merge into the docket, delete the file (content survives in the
creating commit).

File the surviving candidates to the right home — do not merely mention them. Filing means a docket
line, a handoff entry, or a catalog stub. It does not mean implementing.

**Filing is unconditional — a duty, never an offer.** A surviving candidate has exactly three valid
terminal states: filed, strengthened into an existing row, or deduped against one. "Surfaced in
chat" is not a state — chat scrolls away; the docket doesn't. Never ask permission to file, and
never park a candidate behind "say the word next session and I'll fold it in" — that converts the
duty into an offer whose survival depends on the user remembering chat. Named non-reasons (each
licensed a real near-drop at a live project wrap — the candidate became a docket row only because
the user challenged the deferral):
- **"The docket/roadmap is on rotation-hold / doc-freeze"** — a hold blocks *structural rotation
  and archiving* (update-context scopes it to exactly that), never a one-line docket add.
- **"Keep the wrap diff small / avoid another commit"** — diff economy is never a reason to drop a
  learning; the docket line IS the wrap's product.
- **"Context is high / wrap fast"** — filing is one line; it is never the thing to cut.
Catching an unfiled surviving candidate in your own report means going back and filing it before
finishing — the user should never have to say "file it."

## Step 5 — Report

Emit an **Upgrade candidates** block, one row each:
`<surface> | <one-line what> | <evidence from this session> | <honesty-label> | routes-to <central|project> | ~<effort>`

**Honesty labels are mandatory**: `proven-need` (this session concretely hit the gap),
`solid-extension` (real value, no forcing incident), `speculative` (plausible, unproven).
**Cap:** a session realistically yields 0-2 candidates; at most ONE may be `speculative`, and 3+ rows
means the load-bearing filter failed — re-run Step 3 instead of emitting the list. A candidates list
that just accumulates across sessions has failed: if a new candidate shares the spirit of an open
docket row, strengthen that row instead of filing a sibling.

If nothing survives the filters, say so in one line: "No tooling upgrades warranted this session."
That is a valid and common result.

**Log the verdict (required, deterministic — the response side of the fires->outcome ledger):**
whatever the outcome — filed, strengthened, deduped, or zero — record it:

```bash
python ~/.claude/upgrade-ledger.py record --layer <nudge|wrap|manual> \
  --status <filed-central|filed-project|filed-catalog|strengthened-existing|dedup-existing|zero|other> \
  --candidate "<ref>[,...]" --reason "<short>" [--session <uuid>]
```

`--status` is the strongest outcome (`filed-central` > `filed-project`/`filed-catalog` >
`strengthened-existing`/`dedup-existing` > `zero`); list every ref in `--candidate` (`-` when none);
`--reason` is required for `zero`/`other`. `--layer`: `nudge` when this reflection was prompted by the
`[upgrade-reflection]` nudge, `wrap` when by update-context, `manual` otherwise. Add `--session` when
the session id is visible (the UUID in the scratchpad path). If the tool is missing or the command
fails, say so in the report — never silently skip. A fire with no recorded response reads as a
dismissal in the ledger. For a SURVIVING candidate the only valid outcomes are `filed-*`,
`strengthened-existing`, or `dedup-existing` — "surfaced-but-not-filed" is deliberately not a
status, and `other` is not a parking lot for skipped filing; a report row without one of those
outcomes means go back, file, then record.

## Do NOT
- Build the upgrades — surface and file only (a trivial single-edit the user approves on the spot is
  the only exception).
- Manufacture candidates to seem productive — the load-bearing test is the gate.
- Emit an unlabeled candidate — every row carries `proven-need` / `solid-extension` / `speculative`.
- Re-propose something already on the docket or in the catalog.
- Defer filing to a future session or convert it into an offer ("say the word and I'll file it") —
  file first, then report. Project holds (rotation-hold / doc-freeze) block rotation, never filing.

## Companion hook

`hooks/upgrade-reflection-nudge.py` is a `UserPromptSubmit` hook that fires this reflection
automatically: once per session, after a substantial-work signal (>= N file edits, a memory-file
write, or a `git commit`), it injects a one-line non-blocking nudge to run this skill. Wire it in
`~/.claude/settings.json` under `UserPromptSubmit` (env tunables: `UPGRADE_NUDGE_EDIT_THRESHOLD`
default 3; `UPGRADE_NUDGE_DISABLE=1` to silence). Pure stdlib, ASCII-only, fails open.

## Related
- `SELF-AUDIT.md` (central upgrades repo root) — the self-audit log the Step-2 feeder writes and
  this skill re-reads on every firing; the own-miss stream, paired with its reader.
- `update-context` — invokes this at every wrap (Layer 1); its shipped / learned / decided signal
  feeds Step 1.
- `hooks/upgrade-reflection-nudge.py` — the once-per-session `UserPromptSubmit` nudge (Layer 2).
