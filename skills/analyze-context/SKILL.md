---
name: analyze-context
description: Triggered at the START of a new session to thoroughly read and synthesize the project's persistence layer (HANDOFF.md / context.md / project skill / memory files / roadmap.md / active specs and plans) into a coherent mental model before any work begins. Fires on phrases like "catch me up", "what's the state", "what were we working on", "give me the picture", "where did we leave off", "start the session", "analyze the context", "read the context files", "what's the current status", "brief me on this project". Proactively fire on the first substantive message of a session in a project with a context layer. Produces a structured briefing (shipped/in-flight/locked-decisions/open-docket/known-issues/next-step) rather than a regurgitation of file contents. For same-day session resumption (continuing recent work, no machine switch), prefer the slim sibling `analyze-handoff` — it reads only HANDOFF.md and produces a 3-line summary at much lower token cost.
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
- User invoked `/analyze-handoff` or signaled same-day continuation — that slim sibling reads only HANDOFF.md and produces a 3-line summary, sufficient when state hasn't shifted much since the last session. Use this full skill only for multi-day gaps, machine switches, or first-session-of-the-week briefings.

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

### Step 0 — Machine identity check

Run `hostname` (or `echo $COMPUTERNAME` on Windows) and match it against a known-machines mapping kept somewhere persistent (e.g., a section in your `~/.claude/CLAUDE.md`). Surface the result in the briefing header: `**Machine:** <machine-name>`. If the hostname doesn't match any known machine, flag it before proceeding:

> *"Unknown hostname `<x>` — verify cross-machine setup before trusting current state."*

Cost: 1 bash command, ~50 tokens. Cheap insurance against cross-machine state confusion (e.g., trusting a HANDOFF reference to a tool not installed locally, or assuming git auth credentials present on one machine are configured on another).

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

### Step 1.5 — Verify the lifecycle docs aren't being read from a stale source

The skill's whole product is "synthesize current state from the persistence layer." But the persistence layer can live in multiple places that don't always agree:
- Different **worktrees** on the same `.git` (worktree-per-session workflows)
- Different **branches** on the same worktree (branch-per-feature + cross-machine workflows)
- Unpulled commits on the current branch's upstream

Before reading any content files, verify the current location is authoritative. Two checks, both cheap. Check B is **always required**; Check A is required when multiple worktrees exist.

**Check A — worktree enumeration** (skip if single worktree):

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
      echo "newer-sibling-worktree: $wt at $head (ts $OTHER_TS vs current $CURRENT_TS)"
    fi
  fi
done
```

**Check B — branch-recency survey + HANDOFF.md hash comparison** (always run; this is the wrong-branch silent-staleness check):

```bash
# Fetch all remotes — capture output, new branches print as "[new branch]"
git fetch --all 2>&1 | tee /tmp/lifecycle-fetch.txt
grep '\[new branch\]' /tmp/lifecycle-fetch.txt   # surfaces new remote-tracking refs since last fetch

# Unpulled commits on the current branch's upstream
git log HEAD..@{upstream} --oneline 2>/dev/null | head -5

# 10 most recently-committed branches across local heads + origin
git for-each-ref \
  --sort=-committerdate \
  --format='%(refname:short) %(committerdate:iso) %(committerdate:unix)' \
  refs/heads refs/remotes/origin \
  | head -15

# Compare HANDOFF.md across branches more recently committed than current HEAD
CURRENT_HASH=$(git ls-tree HEAD -- HANDOFF.md 2>/dev/null | awk '{print $3}')
CUR_TS=$(git log -1 --format=%ct HEAD -- HANDOFF.md 2>/dev/null)
NOW=$(date +%s); THRESHOLD=$((NOW - 86400))
git for-each-ref --sort=-committerdate refs/heads refs/remotes/origin \
  --format='%(refname:short) %(committerdate:unix)' \
  | awk -v t="$THRESHOLD" 'NR<=10 || $2 > t {print $1}' \
  | sort -u \
  | while read branch; do
  OTHER_HASH=$(git ls-tree "$branch" -- HANDOFF.md 2>/dev/null | awk '{print $3}')
  if [ -n "$OTHER_HASH" ] && [ "$OTHER_HASH" != "$CURRENT_HASH" ]; then
    OTHER_TS=$(git log -1 --format=%ct "$branch" -- HANDOFF.md 2>/dev/null)
    if [ -n "$CUR_TS" ] && [ "$OTHER_TS" -gt "$CUR_TS" ]; then
      echo "newer-branch-handoff: $branch (HANDOFF.md ts $OTHER_TS vs current $CUR_TS)"
    elif [ -z "$CUR_TS" ] && [ -n "$OTHER_TS" ]; then
      echo "newer-branch-handoff: $branch has HANDOFF.md, current branch does not"
    fi
  fi
done
```

Do **not** filter the branch survey by author email — devs commit under multiple emails (work, personal, `noreply@github.com` from web edits), and filtering loses commits. Filter by HANDOFF.md presence + recency instead.

**Cross-machine escalation**: if HANDOFF.md on the current branch contains a `**Last write from:** <other-machine>` line and the current `hostname` is a different machine, treat Check B as **mandatory and high-severity**. Cross-machine alternation is a strong prior for branch-per-feature drift — work that continued on the other machine likely landed on a branch this machine has never had locally. Even if Check B returns no rows, surface the machine mismatch in the briefing header so the next reader knows to verify.

**If any check returns rows: STOP and ask. Do not auto-switch sources. Do not relegate the finding to the briefing's Known Issues section.** Both demotions are how this failure mode reaches the briefing undetected. The canonical incident: a real-use session synthesized off wave-N from the currently-checked-out feature branch, while wave-N+1 HANDOFF lived on a sibling feature branch pushed from another machine. The session surfaced the uninspected sibling branches in the briefing's Known Issues as "worth checking before parallel work" — a demotion from "verify before synthesis" to "FYI in briefing output" — instead of inspecting them pre-synthesis. The synthesis itself must block until the user resolves the ambiguity. Sample messages:

> *"Worktree mismatch: I'm in `<current>` (HEAD ts X), sibling `<other>` has newer HEAD (ts Y). Should I read from there?"*

> *"Branch `<other>` has a newer HANDOFF.md than the current branch `<current>` (~N hours newer). In branch-per-feature workflows the newest HANDOFF is usually authoritative even when it's not on the current branch. Should I read from there, or is the current branch authoritative?"*

> *"`git fetch` surfaced new remote branches I haven't inspected: `<branch1>`, `<branch2>`. Their HANDOFF.md differs from the current branch's. Inspect before I synthesize?"*

**If all checks are clean**: proceed to Step 2. Mention nothing — silence is the success case.

**Re-run trigger — Step 1.5 is not a one-shot pre-flight.** Any operation between Step 0 and Step 4 that changes the synthesis source (`git switch`, `git checkout`, `git reset`, `git pull`, `git fetch` that surfaced new branches, deleting/restoring a worktree, etc.) **invalidates the prior pass and requires re-running Check B before continuing.** The canonical incident this rule prevents: the skill ran Check B on the originally-checked-out (stale) branch, found drift, the user resolved by `git switch main && git reset --hard origin/main`, the skill proceeded to synthesis without re-checking — and missed a sibling branch's newer HANDOFF.md that had been pushed in the intervening hours. The first Check B's findings do **not** transfer to the new source. Treat each source-shift as a fresh session entry for Step 1.5 purposes.

**Branches whose names suggest lifecycle work get extra scrutiny.** Names like `*-handoff-refresh`, `wave-N`, `wave-N-handoff`, `*-context-update`, `*-update-handoff` are HIGH-PRIORITY for re-checking even when their PR has already been squash-merged. The merge intuition ("that branch is done") is wrong in workflows where the dev keeps pushing to the branch as a working surface after the PR lands. The branch tip can diverge from the squash-merge commit by hours-to-days of additional commits. Check B's HANDOFF.md hash comparison catches this if run, but the intuition "that branch was merged, skip it" suppresses the urge to re-check. Override the intuition for lifecycle-named branches.

**Why this matters**:
- **Wrong-worktree failure** (worktree-per-session workflows like superpowers' `using-git-worktrees`): each session creates a fresh worktree from main. If a previous session's `update-context` commits stayed on its worktree's branch and never merged to main, the new session reads outdated docs silently.
- **Wrong-branch failure** (branch-per-feature + cross-machine workflows): each feature gets a branch; work alternates between machines; HANDOFF.md updates land on whichever branch the session was working on. The current branch's HANDOFF can be wave-N while a sibling branch's is wave-N+1. Reading from the current branch silently returns the older wave with no signal — unless Check B's HANDOFF-hash comparison fires.

Both failure modes share a root: the skill historically assumed "HANDOFF.md at the current path" was authoritative. Step 1.5 lifts that assumption by inspecting siblings (worktree AND branch) before trusting the local copy.

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

**Pre-briefing currency checkpoint (cheap, mandatory).** Before writing the briefing — especially the "Next step suggestion" line — run a final 200ms sanity check that the synthesis source is still authoritative:

```bash
# Any commit touching HANDOFF.md (or your project's wiki doc) in the last 24h,
# across ALL refs — local + origin — regardless of which branch
git log --all --since='24 hours ago' --pretty=format:'%h %ai %d %s' -- HANDOFF.md
# (substitute CONTEXT.md or continuation/context.md as appropriate)
```

If any commit returns that is NOT reachable from the current HEAD's view of HANDOFF.md, STOP and re-run Step 1.5. The check is cheap enough to be unconditional. It catches: (a) the post-merge branch-resurrection variant of wrong-branch staleness (a merged branch keeps receiving commits after its PR landed); (b) commits pushed to other branches by another machine in the window between Step 0's machine check and now; (c) edits made via web UI / standalone clone that bypass the local sync flow. This is the cheapest single safeguard against the canonical "skill produced a briefing pointing at the wrong next step because a newer HANDOFF paragraph existed on a sibling branch" failure.

**Surface the design's empirical foundation, and don't trust the HANDOFF's one-line summary of it.** When a project's current direction rests on an external/extracted/datamined source (a decompiled game's data, a research corpus, a scraped dataset, a benchmark), that source is usually committed in-repo (e.g. under `docs/**/research/`, `data/`, `*.json`/`*.tsv` dumps) and/or sits in a local-disk extraction dir the repo's README points at. **The decision/ADR doc that locks the direction references this source; the HANDOFF's one-liner about that decision routinely drops the reference.** Reading only the HANDOFF summary leaves you believing the design is a black box. Two rules: (1) read the latest `docs/**/decisions/` (or ADR) doc *in full*, not via the HANDOFF's summary of it — the grounding/source references live in the doc body; (2) if the design rests on data, locate it (`grep -ri <source-name>` across the repo + check any README-cited local extract dir) and surface it in the briefing's "Empirical foundation" section. A session that can't answer "where's the data this design is built on" hasn't finished Step 2.

**Header-as-currency-proof is forbidden.** HANDOFF.md often opens with `Updated: <date>` / `Last write from: <machine>` / `wave-N closeout` style header metadata. **Treat these as advisory only.** They tell you when *this paragraph* was authored, not whether *a newer paragraph exists elsewhere*. The only proof of currency is the Pre-briefing checkpoint above plus Step 1.5's Check B. A briefing's "Next step suggestion" section must be grounded in *verified currency* (latest commit touching HANDOFF.md across all refs is reachable from current HEAD), not in *header-claimed currency*. If you find yourself thinking "the header says wave-41 so we're on wave-41," that's the trap — re-run Check B.

**Hook-surfaced signals are independent currency channels.** SessionStart / UserPromptSubmit hooks that surface external activity (coordination feeds, chat-room messages, ticket updates) tell you what's happening in *those channels* — not what's happening in HANDOFF.md. They can diverge by hours. A hook reporting "0 new feed entries since X" is NOT proof that HANDOFF.md hasn't been touched since X. Cross-reference hook signals with the Pre-briefing checkpoint; don't substitute one for the other.

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

### Empirical foundation (only if the design rests on external/extracted data)
- <what dataset / datamine / extract / research corpus grounds the current direction>
- <where it lives: in-repo path AND any local-disk extract dir — e.g. `docs/.../research/upgrades.json` + `C:/Users/.../extracted/`>
- <one-line on how to query it, so the resumer treats it as a live source not a black box>

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

**User-dispute re-grounding rule.** If the user contests the briefing's current-state claim or next-step suggestion — explicitly ("we moved on from this," "that's not where we are") or implicitly ("search again, it's gotta be in there") — the FIRST response is to **re-run Step 1.5 Check B + the Pre-briefing currency checkpoint**, NOT to search more static files. The most common reason a fresh briefing is wrong is currency drift the skill missed, not a missing memory file. Static-file deepening (memory dir, specs, plans, archive) is the SECOND response, after currency has been re-verified. Treat user dispute as the strongest signal of a missed Step 1.5 finding and act accordingly.

**Source/approach-dispute rule (broader than currency).** If the user questions a *source or approach choice* — "why are you using X?", "why fall back on Y?", asked once and especially asked **twice** — the FIRST action is to **search for the alternative they're implying exists**, NOT to defend the current choice. Repeated questioning of a source is the strongest signal that something findable is being missed: a dataset on local disk, an extract dir, a committed file the briefing didn't surface, a decision doc you read only in summary. Defending the current choice when the user is pointing at a better one is the failure. Concretely: `grep -ri <implied-source>` the repo, check README-cited local extract dirs, read the relevant decision doc in full — *before* arguing for the status quo. A privately-extracted dataset never appears in a web search, so "I searched the web and found nothing" is the wrong instrument for "does our own source data exist" — it answers *not public*, not *not available*. Reach for repo + local disk first.

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
- **Wrong-worktree silent staleness** → in worktree-per-session workflows, you may be reading lifecycle docs from a worktree whose branch never received a previous session's `update-context` commits. Step 1.5 Check A is the only reliable detection. Skipping Step 1.5 is the canonical way this failure mode reaches the briefing undetected.
- **Wrong-branch silent staleness** → in branch-per-feature workflows (especially with cross-machine alternation), HANDOFF.md is committed to whichever branch the session was working on, not centralized on main. The current branch can be wave-N while a sibling branch is wave-N+1. Same `.git`, same worktree, different branch tip — Step 1.5 Check A's worktree enumeration won't catch it; Step 1.5 Check B's branch-recency + HANDOFF-hash comparison is the only reliable detection. Symptom: HANDOFF reads as self-consistent (SHAs all resolve from current HEAD), but `git for-each-ref --sort=-committerdate` surfaces another branch with a newer HANDOFF.md commit. **A particularly insidious variant**: the briefing's Known Issues section names other branches as "worth checking before parallel work" — that demotion from "verify before synthesis" to "FYI in briefing output" IS the bug, not a mitigation. Branches surfaced by Check B must be inspected pre-synthesis, not handed to the user as a post-briefing TODO.
  - **Post-merge branch resurrection sub-variant**: a branch was squash-merged into main (PR closed, commit landed on main), but the dev kept pushing additional commits to the branch as a working surface AFTER the merge. From git's view the branch tip is no longer an ancestor of main — it diverges from the squash-merge commit by 1-to-N extra commits, often containing HANDOFF.md updates from continued work. The trap is the intuition "this branch is merged, its work is integrated, skip it." Override by running Check B unconditionally regardless of merge status; detection is the same HANDOFF.md hash comparison. Auxiliary detection: `git for-each-ref refs/remotes/origin --format='%(refname:short)' | while read b; do git merge-base --is-ancestor "$b" main 2>/dev/null || echo "non-ancestor: $b"; done` — non-ancestor branches whose names suggest lifecycle work (handoff-refresh / wave-N / context-update) deserve mandatory HANDOFF.md inspection.
- **Trusting wave/date headers as proof of currency** → HANDOFF.md often opens with `Updated: <date>` / `Last write from: <machine>` / `wave-N closeout — <summary>` style header metadata. These tell you when *this paragraph* was authored, not whether *a newer paragraph exists elsewhere*. Reading a wave-41 header as proof of "we're on wave-41" suppresses the urge to run Check B and the Pre-briefing checkpoint. The only proof of currency is verified reachability of every recent HANDOFF-touching commit from the current synthesis source. If you catch yourself trusting a header line as state-of-the-project, that's the trap firing.
- **Feed/hook activity ≠ HANDOFF activity** → SessionStart and UserPromptSubmit hooks that surface external channels (coordination feeds, chat threads, ticket updates) report activity in *those channels*, not in HANDOFF.md. The two can diverge by hours: a HANDOFF.md commit can land directly without a feed entry. A hook reporting "no new feed activity since X" is not proof HANDOFF.md hasn't moved since X. Treat them as independent currency channels; never substitute hook signals for the Pre-briefing checkpoint.
- **Trusting one tier only** → HANDOFF.md's "next session" pointer can go stale if a memory file captures a more recent decision. Cross-check.
- **Regurgitation** → producing a briefing that's literally just concatenated file contents. Synthesis is the product. If you couldn't answer "what's the next concrete move" after reading, you didn't synthesize.
- **Tier-3 creep** → reading every archived pickup point to feel thorough. Wastes tokens and dilutes the briefing. Only dip into archive if the user asks.
- **Date drift (silent clock trust)** → when the system-provided date conflicts with evidence in the files (commit timestamps, pickup-point dates, memory-file dates), **anchor on the file/git evidence and flag the discrepancy explicitly** in the briefing. Don't silently trust either source. Example phrasing: *"Note: system currentDate says 2026-04-20 but commits + context.md pickup both confirm work through 2026-04-22. Treating 04-22 as the actual state."* This is symmetric to `update-context`'s three-source-triangle: the authoritative answer comes from the files when clock and files disagree.
- **HANDOFF.md contradicts git / context / memory** → if the HANDOFF claims "Plan 3A shipped, 242 tests passing" but `git log` shows the last test-related commit left the count at 216, OR if CONTEXT.md's wiki section on a system disagrees with the HANDOFF's recent-shipped claims, **flag the contradiction in the briefing rather than silently picking one.** The user needs to know which source is stale. Default heuristic: git evidence > memory-file evidence > HANDOFF.md evidence > CONTEXT.md wiki (most recent signal wins), but do NOT just auto-pick — surface the disagreement so the user can resolve it.

## Alternatives / related skills

- **`analyze-handoff`** (slim sibling) — for same-day session resumption. Reads only HANDOFF.md, produces a 3-line summary (last completed / next intended / blocker). Much cheaper than this skill on big projects (~5K tokens vs 50K+). Pick this for cheap resumption; pick `analyze-context` for full cold-start briefing after multi-day gaps or machine switches.
- **`update-context`** (sibling) — run at session end to persist what this session's work produced. Read this skill first, work happens, update-context runs last.
- Existing project-level CLAUDE.md instructions — respect them. If the project's CLAUDE.md specifies a read order, follow it. This skill is the general version when no project-specific protocol exists.

## Do NOT

- Don't skip files "for token efficiency" — the briefing's quality depends on full reads
- Don't assume memory rules from other projects apply here — scope memory-file usage to the detected project's memory directory
- Don't write anything — this skill is read-only. Writes are `update-context`'s job.
- Don't invoke `update-context` at the same time — they're lifecycle bookends, not a compound action.
