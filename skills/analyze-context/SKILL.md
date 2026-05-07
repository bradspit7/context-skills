---
name: analyze-context
description: Triggered at the START of a new session to thoroughly read and synthesize the project's persistence layer (HANDOFF.md / context.md / project skill / memory files / roadmap.md / active specs and plans) into a coherent mental model before any work begins. Fires on phrases like "catch me up", "what's the state", "what were we working on", "give me the picture", "where did we leave off", "start the session", "analyze the context", "read the context files", "what's the current status", "brief me on this project". Proactively fire on the first substantive message of a session in a project with a context layer. Produces a structured briefing (shipped/in-flight/locked-decisions/open-docket/known-issues/next-step) rather than a regurgitation of file contents.
---

# Analyze Context

Thoroughly read and synthesize a project's persistence layer at session start. Produces a structured briefing that makes the project state legible in ~30 seconds of reading.

This is the **session-start** complement to `update-context` (which runs at session end).

## When to fire

Trigger phrases:
- "catch me up" / "catch up"
- "what's the state" / "what's the current state"
- "what were we working on" / "where did we leave off"
- "give me the picture" / "what's going on here"
- "brief me" / "brief me on this project"
- "start the session" / "begin"
- "analyze the context" / "read the context files"
- "what's the current status"

Proactively fire when:
- The first substantive user message of a session lands in a project with a detected context layer (HANDOFF.md, continuation/ directory, or CONTEXT.md + context/ variant)
- User asks about project state or history in any shape
- Claude would otherwise be guessing about project state

Do NOT fire when:
- User immediately gives a concrete task — they don't want a briefing, they want work done
- User is in the middle of a task and just asks a narrow question
- The project has no context layer (nothing to analyze)

## Source files (the reading set)

Read these in order, deeply. Don't skim — the context layer exists BECAUSE of past sessions that failed by skimming.

### Tier 1 — always read

1. **`<project-root>/CLAUDE.md`** (if exists) — session-start protocol, behavioral rules, conventions
2. **`<project-root>/HANDOFF.md`** — **current-state TL;DR, the authoritative source for "what's happening right now."** When `update-context` runs, it produces HANDOFF.md on every project regardless of pattern. If it's present, read it first among content files — it's the shortest path to current state and cites the other files you need. If it's absent (older project that hasn't been touched by the current update-context rules yet), fall through to the wiki doc below and note it in the briefing.
3. **Wiki / running-log doc** — supporting detail for depth when HANDOFF.md points you there. One of:
   - `<project>/continuation/context.md` (running-log style, in `continuation/` dir)
   - `<project-root>/CONTEXT.md` (CONTEXT-style, running log with variant filename; companion dir is `<project>/context/`)
   - In monolithic-handoff projects, HANDOFF.md doubles as wiki + handoff — there's no separate wiki doc. Read HANDOFF.md fully.
   - If the wiki doc exceeds the Read tool's default 2000-line return, **chunk procedurally**: `Read(file, offset=1, limit=2000)`, then `Read(file, offset=2001, limit=2000)`, continue until a Read returns < 2000 lines (= EOF). Do NOT stop after the first chunk because "the current pickup point is at the top" — the docket, locked decisions, and known issues live below it. Stopping early is the #1 historical failure mode of this skill (see Fail modes). Token cost of a full read IS the expected cost of starting a session — budget for it.
4. **Master index / roadmap** (if present) — `<project>/continuation/INDEX.md` (running-log) OR docket file in `<project>/context/` like `<topic>_docket.md` (CONTEXT-style). Look for explicit `roadmap.md` / `docket.md` / `INDEX.md` / `*_docket.md` filenames.

### Tier 2 — read if present

5. **Memory directory:**
   - In-repo: `<project>/continuation/memory/MEMORY.md` (or `<project>/context/memory/MEMORY.md` for CONTEXT-style) + linked topic files (all of them — they're small)
   - Out-of-repo: `~/.claude/projects/<hashed-project-path>/memory/MEMORY.md` + linked files
   - Read the index FIRST; only click into topic files that look relevant to recent work (don't exhaustively read every `feedback_*` file on every session)
6. **Roadmap:** `<project>/continuation/memory/roadmap.md` (running-log) — the docket
7. **Project-local skill:** `<project>/**/skills/<name>/SKILL.md` (if exists) — project conventions + gotchas
8. **Most recent spec/plan docs:** latest 2-3 files in `docs/**/specs/` and `docs/**/plans/` — ongoing design decisions

### Tier 3 — read on demand

Don't read upfront; read if the user asks about something specific:
- Older pickup points in context.md (below the current one, in the history section)
- `continuation/archive/` (old session logs moved out of rotation)
- Older spec/plan docs (more than ~a week old)
- `README.md` (usually high-level, not session-relevant)

## Workflow

### Step 1 — Detect pattern

(Same detection logic as `update-context`.)

- `HANDOFF.md` at root → **monolithic-handoff style**
- `continuation/` directory at root → **running-log style**
- `CONTEXT.md` at root + `context/` directory at root → **CONTEXT-style** (running-log variant — same shape as running-log but different filenames; treat as running-log for workflow purposes)
- Multiple patterns present → hybrid / migration-in-progress; note to user and ask which to treat as primary
- None of the above → no context layer to analyze; tell user

**CONTEXT-style specifics:**
- Primary running log: `CONTEXT.md` at root
- Supporting directory: `context/` at root (holds docket files, memory subtree, archive)
- Docket is typically `<topic>_docket.md` (e.g., `physics_docket.md`) rather than a fixed `roadmap.md` filename
- Memory lives at `<project>/context/memory/` in-repo (not out-of-repo)
- All other workflow steps (tier-2 reads, briefing synthesis, drill-down discipline) proceed identically to running-log style

### Step 1.5 — Verify worktree state (skip if not in a worktree-per-session workflow)

If the project uses git worktrees (multiple working directories sharing one `.git` directory), the lifecycle docs you're about to read may not reflect the project's actual current state — sibling worktrees can have newer commits with newer HANDOFF/context content. Run this check before reading content files:

```bash
# List all worktrees + their HEADs
git worktree list

# Identify newer siblings on the same .git
CURRENT_WT=$(git rev-parse --show-toplevel)
CURRENT_HEAD=$(git rev-parse HEAD)
CURRENT_TS=$(git log -1 --format=%ct HEAD)

git worktree list --porcelain | awk '/^worktree/ {wt=$2} /^HEAD/ {print wt, $2}' | \
while read wt head; do
  if [ "$wt" != "$CURRENT_WT" ]; then
    OTHER_TS=$(git -C "$wt" log -1 --format=%ct "$head" 2>/dev/null)
    if [ -n "$OTHER_TS" ] && [ "$OTHER_TS" -gt "$CURRENT_TS" ]; then
      echo "newer-sibling: $wt at $head (ts $OTHER_TS vs current $CURRENT_TS)"
    fi
  fi
done

# Also check origin for unpulled commits on the current branch
git fetch --all --quiet 2>/dev/null
git log HEAD..@{upstream} --oneline 2>/dev/null | head -5
```

**If the check surfaces a newer sibling worktree or unpulled origin commits**: STOP and ask the user before proceeding. Don't synthesize a briefing from files in a stale worktree. Sample message:

> *"I'm running in worktree `<name>` at HEAD `<hash>` (timestamp X). Sibling worktree `<name>` has a newer HEAD `<hash>` (timestamp Y, ~N hours newer). Should I read from there, or is this worktree authoritative? If the latest work is in the sibling, point me at that path before I synthesize."*

**If the check is clean**: proceed to Step 2. Mention nothing — silence is the success case.

**Why this matters**: in a worktree-per-session workflow, each session creates a fresh worktree from main. If a previous session's `update-context` commits stayed on its worktree's branch (not merged to main), the new session's worktree starts at the older main HEAD and reads outdated lifecycle docs. The skill's "current state" reads will be silently wrong. This is the **wrong-worktree failure mode** — fundamentally different from sparse-read or doc-drift, and undetectable without explicit worktree enumeration.

### Step 2 — Read the tier-1 set fully

Run file reads in parallel where possible. Respect the "read in full, not sparse chunks" rule — especially for running logs like `continuation/context.md` that accrete detail at the top.

If a file exceeds single-read limits, chunk it. Do not skip sections to fit context. The token cost of a full read IS the expected cost of starting a session.

### Step 3 — Index tier-2, read strategically

The default approach ("scan MEMORY.md, click into relevant files") works for small memory directories. For larger ones (50+ files), the index itself encodes navigation signals you must read carefully:

**Section structure**: if MEMORY.md uses heading-divided sections (e.g., `## Clinical & content rules`, `## Project infrastructure`, `## Behavioral rules`), identify which section maps to the user's task domain. Read **all** files in that section, not just files whose names obviously match. Section membership is the project's curated "what's relevant when" signal — trust it over filename heuristics.

**Priority markers**: if entries use markers like ⚡, ⚡⚡, ⭐, 🔴, 🟡, 🟢, etc., treat marked entries as must-read for any session in their domain. Single-marker = high priority; double-marker = critical / load-bearing for current work. Don't skip marked entries based on filename heuristics — markers exist precisely because the filename underspecifies the importance.

**Inline update patches**: index entries are NOT one-liners on mature memory dirs — they often contain embedded `**LATE+N UPDATE**`, `**Updated YYYY-MM-DD (N corrections)**`, or `**As of YYYY-MM-DD**` patches that supersede the linked file's body. **Read the FULL TEXT of each index entry, not just the first sentence.** The most recent state often lives in the index entry, not in the linked file.

**Sibling cross-references**: entries may link to related rules: *"Sibling: feedback_X.md"*, *"Sibling rules: clinic_X.md, project_Y.md, feedback_Z.md"*, or inline `[link](file)` references in body text. Follow these links transitively. Stop only when the cluster's domain coverage feels complete — don't stop at the first hop.

**Prefix-based reading discipline** — differentiate the read rule by file prefix:

| Prefix | Reading discipline |
|---|---|
| `clinic_*`, `business_*`, `scope_*`, `domain_*` | **Always read** when writing content in scope. Non-negotiable business rules; missing them produces compliance violations, not just imperfect output. |
| `feedback_*` | Read if the rule applies to current work (use prefix + filename + index entry to judge). |
| `research_*` | Read the **most-recent-dated** file in the relevant domain. Older research files are tier-3 (only if user asks). |
| `project_*` | Read when implementing patterns in the project's domain. |
| `memory_*` (verdicts) | Read for locked decisions; rarely re-read once locked, but check the index entry for any inline supersession note. |
| `plan_*`, `intake_*`, `page_intent_*` | Treat as project conventions; read at session start if relevant to the work. |

**Calibration**: don't pad to read every memory file every session (still wasteful). But don't under-read either — if the index has 50+ files and your heuristic produces 0 reads, something's wrong. **At minimum** read the section matching the user's task + all ⚡⚡ entries + any `clinic_*` / scope-prefix files for content-writing tasks.

### Step 4 — Build the briefing

Synthesize what you read into this structure (not a regurgitation — a mental model):

```markdown
## <Project name> — current state

**One-line status:** <what phase/plan/goal is active; one sentence>

### Recently shipped (last 1-2 sessions)
- <concrete deliverable + date>
- <another>

### In flight / known work-in-progress
- <what's started but not done>

### Locked decisions (DO NOT reopen)
- <design decisions the user has marked as settled>

### Open docket — next candidates
1. <highest-priority queued item + source>
2. <next>

### Known issues / blockers
- <anything that should not be surprised by>

### Behavioral rules currently in force
- <top 3-5 memory rules relevant to likely upcoming work>
- <link back to memory files for deep reading>

### Next step suggestion
<Given the above, what's the best next move? Usually: follow the "next session" entry point from the primary handoff doc. If user's first message suggests something else, note that and offer to redirect.>
```

**Size the briefing to the project's actual state — no hard word count.** A clean-docket fire might produce 200-300 words; a complex mid-migration or multi-workstream project might legitimately need 500-800. Discipline is **structural, not numeric**:
- **Synthesized, not regurgitated** — compress file contents into the 6 section slots; don't paste verbatim
- **Linked, not duplicated** — if detail lives in a memory file or context.md section, cite it rather than copy
- **Tier-1 + relevant tier-2 only** — don't drift into archive / older specs unless user asks
- **Scoped to the next session's needs** — "what does the resumer need to do first" drives what's surfaced

If the project has 50 load-bearing facts, surface the ones the next session needs most; if 5 facts are enough, use 5. **"Short" is not a virtue if it drops real state.** Size content to what it needs; stated word targets are calibration, not ceilings.

Failure modes aren't "too long" — they're regurgitation (pasting file contents verbatim) or tier-3 creep (reading every archive file). A tight 600-word briefing for a complex project beats a padded 300-word one that hid half the in-flight items.

### Step 5 — Wait for user direction

After delivering the briefing, the skill's job is done. The user now drives:
- "Continue with next step" → proceed to execute the next-session plan from the primary handoff
- "Actually I want to do X instead" → redirect; the analysis was context, not commitment
- "Tell me more about Y" → drill into a specific tier-2 or tier-3 file

## Pattern-specific notes

### monolithic-handoff style

- HANDOFF.md is a single doc; read all of it. Don't skip sections — "Pending user decisions" and "Known small issues" often hide key state.
- The "Ready signal" at the bottom of HANDOFF.md (if present) is a verification checklist for this skill — if test counts or branch state don't match, flag it.
- Project-local SKILL.md: skim for Plan N Learnings sections (they append over time); the newest section is most relevant for upcoming work.
- Memory dir is out-of-repo at `~/.claude/projects/C--CLAUDE-PROJECTS-<sanitized>/memory/`. You must know the path conversion (project path → hashed memory path).

### running-log style

- `context.md` grows large (can be 1500+ lines). **Read the full file in chunks**, do NOT sparse-search.
- Top pickup point = current state. Previous pickup points below `---` dividers are history; skim but don't treat as current.
- `CLAUDE.md` may have an explicit session-start protocol — this skill's workflow should match it, not duplicate.
- `roadmap.md` is the DOCKET — priority-ordered. Open items are typically 🔴🟡🟢 (unchecked); closed items are ✅.
- Memory files live in-repo at `continuation/memory/`. They can include domain-specific business rules, not just dev rules — surface business rules in the briefing if they're relevant.
- If the project has a never-auto-push rule, surface this if the user's first message sounds like "let's push/deploy/ship".

### Hybrid / neither

- If both patterns are present, note the ambiguity in the briefing: "Project has both HANDOFF.md and continuation/ — treating HANDOFF as primary unless you tell me otherwise."
- If neither is present, briefing is: "No context layer found. Recent git activity: <summary>. Want me to scaffold a context layer?"

## What the briefing should NOT do

- Do NOT paste whole sections verbatim from context.md or HANDOFF.md. Synthesize.
- Do NOT surface every memory file one-by-one — a listing of 20 rules is noise. Pick the load-bearing ones: rules relevant to current work or the next-step suggestion. If 3 files are enough, show 3; if 8 are needed, show 8. **Don't pad to hit a number; don't truncate to stay under one.**
- Do NOT list every test or every commit in history. Pick the session-level units (phases, plans).
- Do NOT claim "I don't see context" without actually reading the files — if something's missing from your briefing, it's because YOU skipped a file, not because it doesn't exist.
- Do NOT invent plans or decisions the files don't support. If a section is thin, say so.

## Fail modes to watch

- **Skimming context.md** → the #1 failure. The trap looks like this announcement: *"context.md is too large for one read. Reading the top entry (current pickup point) and the docket."* That sentence IS the violation — it sounds reasonable but it's the exact behavior the chunk-read rule was added to prevent. Read top-to-bottom procedurally (see Tier 1 reading instructions for the exact `Read` calls).
  - **Verification ritual before producing the briefing**: pick three concrete facts to quote — one from the file's top third (the latest pickup point), one from the middle third (older pickup points or wiki sections), one from the bottom third (oldest history or initial decisions). If you can only quote from the top, you only read the top — re-chunk before synthesizing. Files read in full (< 2000 lines) pass trivially. The check is hard to fake because the bottom-third fact has to come from text the model couldn't have inferred from the pickup-point summary alone.
- **HANDOFF references commits not in this worktree's git log** → strong signal of a worktree mismatch. If `HANDOFF.md` cites commit hashes that `git log` can't find from this worktree's HEAD, the file was authored in a sibling worktree at a different branch tip. STOP — don't synthesize a briefing from a worktree that's missing referenced commits. Run Step 1.5's worktree check, ask the user which worktree to read from, then restart.
- **Wrong-worktree silent staleness** → in worktree-per-session workflows, you may be reading lifecycle docs from a worktree whose branch never received a previous session's `update-context` commits. Step 1.5's check is the only reliable detection. Skipping Step 1.5 is the canonical way this failure mode reaches the briefing undetected.
- **Trusting one tier only** → HANDOFF.md's "next session" pointer can go stale if a memory file captures a more recent decision. Cross-check.
- **Regurgitation** → producing a briefing that's literally just concatenated file contents. Synthesis is the product. If you couldn't answer "what's the next concrete move" after reading, you didn't synthesize.
- **Tier-3 creep** → reading every archived pickup point to feel thorough. Wastes tokens and dilutes the briefing. Only dip into archive if the user asks.
- **Date drift (silent clock trust)** → when the system-provided date conflicts with evidence in the files (commit timestamps, pickup-point dates, memory-file dates), **anchor on the file/git evidence and flag the discrepancy explicitly** in the briefing. Don't silently trust either source. Example phrasing: *"Note: system currentDate says 2026-04-20 but commits + context.md pickup both confirm work through 2026-04-22. Treating 04-22 as the actual state."* This is symmetric to `update-context`'s three-source-triangle: the authoritative answer comes from the files when clock and files disagree.
- **HANDOFF.md contradicts git / context / memory** → if the HANDOFF claims "Plan 3A shipped, 242 tests passing" but `git log` shows the last test-related commit left the count at 216, OR if CONTEXT.md's wiki section on a system disagrees with the HANDOFF's recent-shipped claims, **flag the contradiction in the briefing rather than silently picking one.** The user needs to know which source is stale. Default heuristic: git evidence > memory-file evidence > HANDOFF.md evidence > CONTEXT.md wiki (most recent signal wins), but do NOT just auto-pick — surface the disagreement so the user can resolve it.

## Alternatives / related skills

- **`update-context`** (sibling) — run at session end to persist what this session's work produced. Read this skill first, work happens, update-context runs last.
- Existing project-level CLAUDE.md instructions — respect them. If the project's CLAUDE.md specifies a read order, follow it. This skill is the general version when no project-specific protocol exists.

## Do NOT

- Don't skip files "for token efficiency" — the briefing's quality depends on full reads
- Don't assume memory rules from other projects apply here — scope memory-file usage to the detected project's memory directory
- Don't write anything — this skill is read-only. Writes are `update-context`'s job.
- Don't invoke `update-context` at the same time — they're lifecycle bookends, not a compound action.
