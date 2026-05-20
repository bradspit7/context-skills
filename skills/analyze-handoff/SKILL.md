---
name: analyze-handoff
description: Slim same-day session resumption — reads ONLY the project's HANDOFF.md (or top pickup point of CONTEXT.md / continuation/context.md if HANDOFF absent) and produces a 3-line summary (last completed / next intended / blocker). Skips memory dir, archive, wiki body, and docket. Costs ~5K tokens vs analyze-context's 50K+. Fires on explicit `/analyze-handoff`, `/handoff`, "quick resume", "where was I", or "what's next" — but ONLY when same-day continuation is clear. Do NOT fire when the user asks for a full briefing ("catch me up", "brief me", "what's the state"), when more than ~24h have passed, when the user just switched machines, or when no HANDOFF/CONTEXT file is present — route to `analyze-context` for those cases instead.
---

# Analyze Handoff

Slim session resumption for same-day continuation. The cheap sibling to `analyze-context`. Reads one file, produces a 3-line summary, stops.

**Why this exists:** large projects accrete heavy context layers — it's not unusual for a mature project's HANDOFF + memory + context.md to sum to 100K+ tokens. Paying that cold-start cost on same-day continuation is wasteful — the user almost always just needs "where am I, what's next." This skill does that for ~5K tokens. Use `analyze-context` when you actually need the full briefing (multi-day gaps, new machines, first session in a project).

## When to fire

**Trigger phrases (explicit):**
- `/analyze-handoff`
- `/handoff`
- "quick resume"
- "where was I"
- "what's next" (when context indicates same-day continuation)

**Proactively fire when:**
- User has explicitly invoked the slash command — that's the only proactive case.
- All other proactive triggers deliberately omitted to avoid stomping `analyze-context`.

**Do NOT fire when:**
- User asks for a full briefing ("catch me up", "brief me on this project", "what's the state", "give me the picture", "what were we working on") — those are full-briefing phrases, route to `analyze-context`
- More than ~24 hours since the last activity in this project — full briefing is safer when state may have shifted
- User just switched machines — cross-machine handoff needs the full memory + rules set AND `analyze-context` Step 1.5 Check B (branch-recency survey) to catch wrong-branch staleness on branches this machine never checked out
- No `HANDOFF.md` / `CONTEXT.md` / `continuation/context.md` present at all → tell user "no handoff present; want full /analyze-context?" and stop
- User signaled a concrete first task — they don't want a briefing at all, just go

## Workflow

### Step 0 — Machine identity check

Run `hostname` (or `echo $COMPUTERNAME` on Windows) and match it against a known-machines mapping kept somewhere persistent (e.g., a section in your `~/.claude/CLAUDE.md`). Surface the result in the summary header: `**Machine:** <machine-name>`. If unknown, flag it: *"Unknown hostname `<x>` — verify cross-machine setup."*

Cost: 1 bash command. Trivial.

### Step 1 — Locate the handoff doc

Look in this order, stop at first match:
1. `<project-root>/HANDOFF.md`
2. `<project-root>/CONTEXT.md` (top section to first `---` divider only)
3. `<project>/continuation/context.md` (top pickup point to first `---` only)

If none found: tell the user *"No HANDOFF/CONTEXT file present. Want me to run /analyze-context for a full briefing instead?"* Stop.

### Step 2 — Read just enough

- HANDOFF.md present → read it fully. (It's supposed to be slim per `update-context` discipline. If it's grown to 1000+ lines, surface that as a hint that an `update-context` cleanup is overdue.)
- CONTEXT.md / context.md only → read top section only, stopping at the first `---` divider (= the current pickup point). Do NOT chunk-read the whole file. That's `analyze-context`'s territory.
- Do NOT read memory dir, archive, docket, plans, or specs.
- Do NOT run `git pull` / `git fetch` unless the user asked.

### Step 3 — Stale-check

Before producing the summary, check the handoff's freshness:
- Look for an `Updated: YYYY-MM-DD` line near the top, OR
- Use `git log -1 --format=%ci HANDOFF.md` to find last modification

If last-modified is more than ~3 days ago, flag it before summarizing:

> *"HANDOFF.md was last updated YYYY-MM-DD (X days ago). May be stale — want full briefing via `/analyze-context` instead?"*

Then wait for direction. **Don't produce the slim summary on stale data** — the user may make decisions based on it.

### Step 4 — Produce the 3-line summary

```
**Last completed:** <one line — most recent shipped work>
**Next intended:** <one line — what's queued, from "next session entry point" or top of docket>
**Blocker:** <one line if any open blocker / pending decision; otherwise "none">
```

Optionally append: *"Want full briefing? `/analyze-context`."*

### Step 5 — Stop

Wait for user direction. Do NOT drift into reading memory, archive, or specs on speculation. The summary is the deliverable; the user already knows what they want next.

## What NOT to do

- **Don't read the memory directory** — tier-2/3 reading is `analyze-context`'s territory.
- **Don't read archive or older pickup points** — same.
- **Don't produce the 6-section structured briefing** — that's `analyze-context`'s output shape.
- **Don't auto-escalate to `analyze-context`** if the slim summary feels thin. Tell the user; let them decide.
- **Don't write anything** — read-only skill, like `analyze-context`.
- **Don't `git pull`** unless user asked.
- **Don't try to be `analyze-context`-lite.** Be intentionally narrow. The cost savings ARE the point.

## Fail modes

- **HANDOFF stale (>3 days)** → flag and ask before summarizing. Slim summary on stale state misleads.
- **HANDOFF references commits not in this worktree's git log** → strong signal of worktree mismatch. Stop, ask user which worktree is authoritative. Same rule as `analyze-context` Step 1.5; the slim version doesn't exempt you.
- **Wrong-branch silent staleness (cross-machine indicator)** → if HANDOFF.md's `**Last write from:**` line names a different machine than the current `hostname`, the previous session ran on the other machine and may have continued work on a feature branch this machine has never checked out. The slim skill deliberately does NOT run `analyze-context`'s full branch-recency survey (Step 1.5 Check B) — that's the cost line the slim skill exists to avoid. So it cannot resolve this case safely. Escalate instead: *"HANDOFF's `Last write from:` is `<other-machine>`. Cross-machine handoff means recent work may live on a branch this machine doesn't have. Recommend `/analyze-context` for a full survey before trusting the slim summary."* Then stop. Same goes for any other signal of branch-per-feature drift (e.g., a recent `git pull` output the user shares showed `[new branch]` lines).
- **Multi-day gap detected** (per JSONL transcript timestamps or git activity gap) → don't produce a slim summary. Recommend `/analyze-context` instead.
- **Project has no HANDOFF.md but has `continuation/context.md`** → fall through to top-pickup-only read. Still slim. Note the missing HANDOFF in the summary so user knows to run `/update-context` later.
- **User invoked `/analyze-handoff` after a >1-week gap** → flag explicitly: *"Long gap since last activity — full briefing recommended."* Don't produce slim summary on stale state.
- **User immediately follows up with a question that needs full-briefing context** → run `/analyze-context` now; the slim was insufficient. Note this so the user calibrates which skill to invoke next time.
- **Wave-N / date headers are not currency proof** → HANDOFF.md often opens with `Updated: <date>` / `wave-N closeout — <summary>` headers. They tell you when *this paragraph* was written, not whether a newer one exists on a sibling branch. The slim skill cannot verify currency across branches by design (that's `analyze-context` Step 1.5 Check B's job). So any signal that branches-other-than-current may carry newer HANDOFF.md commits — recent `git fetch` output showed `[new branch]` lines, the project's commit history shows multiple lifecycle-named branches (`wave-N`, `*-handoff-refresh`, `*-context-update`) committed in the last 24h, or `Last write from:` ≠ current hostname — means the slim skill **cannot trust the header alone**. Escalate to `/analyze-context` and stop. The slim skill's currency confidence is bounded by what one branch-local HANDOFF.md can prove; when the workflow uses branch-per-feature, that's not enough.
- **User disputes the slim summary's claim** → immediately escalate to `/analyze-context`. Do not search more files. The most common reason a slim summary is wrong is currency drift across branches, which the slim skill cannot detect.

## Alternatives / related skills

- **`analyze-context`** (full sibling) — full briefing for multi-day gaps, new machines, or first session in a project. Use when you need the structured 6-section output (recently shipped / in-flight / locked decisions / open docket / known issues / behavioral rules / next-step suggestion). Costs significantly more depending on project size.
- **`update-context`** — session-end persistence. Keeps HANDOFF.md current so this skill stays useful. The slimmer your HANDOFF, the cheaper this skill is.

## Do NOT

- Don't claim "no context" without checking all three locations (HANDOFF.md / CONTEXT.md / continuation/context.md).
- Don't invoke this AND `analyze-context` in the same session — alternatives, not stages.
- Don't omit the stale-check — slim summary on stale data is a trap.
