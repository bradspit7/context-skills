---
name: update-context
description: Triggered at the END of a substantive work session to comprehensively update the project's persistence layer (HANDOFF.md / context.md / project skill / memory files / roadmap.md). Fires on phrases like "update context", "update the handoff", "update context files", "end of session update", "refresh context files", "start a thorough update of context", "update context and handoff", "time to update the docs", "wrap up this session". Proactively fire when the user signals a session is ending and substantive changes occurred. Analyzes the active conversation, git state, and TodoWrite state as three corroborating sources. Detects per-project pattern (monolithic-handoff vs running-log vs CONTEXT-style). Always produces/updates `<project-root>/HANDOFF.md` regardless of pattern. Emits a file-list audit artifact, then writes without stopping for confirmation — invoking the skill IS the authorization. Stops to ask only when the three-source triangle detects a conflict or a destructive edit is needed. Always stops before git commit/push.
---

# Update Context

Comprehensively update a project's persistence layer at session end. Prevents loss of context when the session closes.

## When to fire

Trigger phrases (not exhaustive):
- "update the context" / "update context files"
- "update the handoff" / "update handoff"
- "refresh context files" / "refresh the docs"
- "end of session update"
- "start a thorough and comprehensive update of context files and handoff files"
- "wrap up this session" / "commit the session"
- "update the project docs" / "update the session docs"

Proactively fire when:
- The user signals session closure ("I'm done for now", "let's wrap") AND substantive work happened this session
- A plan/phase completes and a "Plan N Learnings" append is overdue (monolithic-handoff style)
- A session introduced a new convention, gotcha, or design decision worth persisting

Do NOT fire when:
- Nothing substantive changed (no git diff, no new decisions, no completed todos)
- User is still mid-task and just asking a question
- The task was pure exploration with no deliverables

## Source inputs (the three-source triangle)

Every update is grounded in three sources, in decreasing authority:

1. **Active conversation** — *primary*. What was discussed, decided, built, debugged, or learned in this session. The conversation IS the source; files on disk are where decisions land.
2. **Filesystem changes** — `git status`, `git diff` (working tree + staged + last commit), new files, modified files. Corroborates the conversation's claims with ground truth.
3. **TodoWrite state** — what was completed, what's still in-flight, what's queued for next session.

If the three sources disagree, flag the mismatch to the user rather than silently picking one. ("The conversation says test count is 210, but `git log` shows the last test-related commit left it at 186. Which is right?")

## Workflow

### Step 1 — Detect the project's context pattern

Look at the project root and the first two subdirectory levels. Match against known patterns:

| Pattern | Detected by |
|---|---|
| **monolithic-handoff style** | `HANDOFF.md` exists at project root, doubles as both wiki + session-bridge |
| **running-log style** | `continuation/` directory exists at project root, or `continuation/context.md` exists |
| **CONTEXT-style** (running-log variant) | `CONTEXT.md` at project root AND `context/` directory at project root. Functionally the same as running-log style — just different filenames. Treat as running-log for workflow purposes. |
| **Hybrid** (multiple patterns present) | More than one pattern's markers exist — treat as a migration-in-progress; ask user which to update |
| **None / new project** | None of the above exist — offer to scaffold one; ask which style |

Also inventory secondary surface regardless of pattern:
- Project-local SKILL.md files: find via `find <project> -name "SKILL.md" -not -path "*/addons/*"`
- Memory directories:
  - In-repo: `<project>/continuation/memory/` (running-log style) or `<project>/context/memory/` (CONTEXT-style)
  - Out-of-repo: `~/.claude/projects/<hashed-project-path>/memory/` where the hash follows Claude Code's `C--CLAUDE-PROJECTS-<sanitized>` convention
- Active spec/plan docs: `docs/**/specs/*.md`, `docs/**/plans/*.md`
- Root `README.md` and root `CLAUDE.md`

### Step 2 — Gather the session's signal

Run these in parallel:

```bash
# What's changed on disk
git status
git diff HEAD~1 HEAD              # last commit
git diff --stat                   # working-tree + staged summary

# What was in the todo pipeline
# (read TodoWrite state from the current tool state)

# Any new files unstaged?
git ls-files --others --exclude-standard
```

Combine with the conversation's narrative. Build a session summary:
- **Shipped** — concrete deliverables (files created/modified, tests added, features landed)
- **Learned** — new conventions, gotchas, anti-patterns surfaced
- **Decided** — locked decisions that should not be re-opened
- **Deferred** — acknowledged-but-not-done; belongs in next-session docket
- **Pending user** — things that need user input (API keys, push approvals, scope decisions)

### Step 3 — Plan updates per file

#### Universal rule — always produce/update `<project-root>/HANDOFF.md`

**Every run of update-context, regardless of project pattern, produces or rewrites `HANDOFF.md` at the project root.** This is the session-bridging current-state TL;DR that lets the next session (on any machine) pick up seamlessly.

**Key distinction — do NOT conflate HANDOFF.md with the project wiki:**
- **HANDOFF.md = current-state snapshot.** Rewritten each session. Skimmable and action-oriented — bullet-structured so a resumer can glance-read even when the file is long. Answers: "what's the state right now, what should the next session do first, what's blocked?"
- **CONTEXT.md / continuation/context.md / (in monolithic-handoff projects, the HANDOFF.md *itself* — see exception below) = durable knowledge.** Architecture, systems, locked decisions, conventions, long-term narrative. Accretes slowly.

**HANDOFF.md should LINK to context + memory files, not duplicate them.** If architecture detail belongs in CONTEXT.md, HANDOFF.md says "See CONTEXT.md §X for architecture" rather than copying the content.

**No hard line count.** HANDOFF.md should be sized to the project's actual current state — no ceiling, no floor beyond the 8 required sections below. A clean-docket project might need 40-60 lines; a complex migration, multi-workstream, or multi-agent project can legitimately run 150-300 lines. **"Short" is not a virtue if it drops real state.** Size content to what it needs; stated line/word targets are calibration, not ceilings.

The discipline is **structural, not numeric**:
- **Link, don't duplicate** — if information lives in roadmap.md or context.md, HANDOFF cites it with a pointer + short summary, not a copy
- **Session-compressed** — "Recently shipped" covers the current + last 1-2 sessions, not all-time history
- **All 8 required sections present and accurate** — that's the floor
- **Stay fresh** — drop stale content from prior sessions; don't accrete
- **Bullet-structured** — short prefixes (dates, commits, filenames) stay consistent so a resumer can glance-read even at 300 lines

Failure modes aren't "too long" — they're **redundancy** (copying roadmap content into HANDOFF) or **drift** (leaving stale info from 3 sessions ago lingering). A tight 200-line HANDOFF for a complex project is better than a padded 50-line one that dropped half the in-flight items to stay short.

**Required sections in HANDOFF.md:**
1. **One-line current status** — single sentence. What phase/plan is active; what just shipped; what's next.
2. **Recently shipped (this session + last 1-2 if relevant)** — concrete deliverables with dates/commits.
3. **In flight / known work-in-progress** — what's started but not done; who's blocking what.
4. **Next session entry point** — ordered steps for resuming. Cite specific files to touch first.
5. **Pending user decisions** — things that need user input (API keys, scope calls, push approvals).
6. **Known issues / blockers** — anything the next session should not be surprised by.
7. **Files to read first when resuming** — ordered list. HANDOFF.md + CONTEXT.md + memory index at minimum.
8. **Pointers to deeper context/memory files** — link to the wiki + specific memory files relevant to the next moves.

**Pattern-specific HANDOFF.md interaction:**
- **monolithic-handoff projects** (where `HANDOFF.md` was already the project's primary doc with legacy section names like "Where you are in the process" / "Ready signal"): those sections are the project's current-state AND wiki content mixed together. Preserve the legacy section names, update them in place per the monolithic-handoff workflow below, AND ensure the universal required sections above are present (add any missing).
- **running-log + CONTEXT-style + new projects**: HANDOFF.md is an additive artifact separate from the running-log wiki (context.md / CONTEXT.md). Rewrite the full HANDOFF.md each session — don't accrete historical content there.

#### monolithic-handoff style (`HANDOFF.md` doubles as wiki + handoff)

In monolithic-handoff projects, `HANDOFF.md` was authored before the CONTEXT/HANDOFF split convention existed, so it holds both wiki-ish content (locked decisions, critical conventions) AND current-state content. Treat this as a pre-existing hybrid and update in place — do not force a migration.

`HANDOFF.md` updates **in place** (rewrite affected sections, don't append new pickup points):

- **"Last updated"** / top summary → rewrite to reflect current state
- **"Where you are in the process"** → update `✅` / `⏳` markers; add completed phases, set the new next phase
- **"Current code state"** → add new autoloads / entities / systems / UI pieces introduced this session
- **"Locked design decisions"** → add anything the user explicitly locked; never remove
- **"Critical conventions"** → add new conventions surfaced; update if existing ones changed
- **"Test count"** → update to current passing count
- **"Next session entry point"** → rewrite to describe the next planned work (typically the newly-queued Plan)
- **"Known small issues"** → add new minor issues, remove ones that got fixed
- **"Pending user decisions"** → add new decisions the user must make
- **"Ready signal"** at the bottom → update the test-count target and next-plan pointer

Ensure the 8 universal required sections above map to existing legacy sections (most already do: "Where you are" ≈ Recently shipped + In flight; "Next session entry point" = same; "Pending user decisions" = same; "Known small issues" = Known issues). Add a "Files to read first" bullet list if missing.

Project-local SKILL.md (e.g., `<project>/skills/<name>/SKILL.md`): **append-only with correction mechanism**:
- At the bottom, add a new section `## Plan N — <name> Learnings` (or equivalent)
- Fill with session's new gotchas, conventions, patterns — the things that would save time if encountered again
- **Do NOT rewrite existing sections; they're history.** If a past Plan N Learning was wrong or has been superseded, add a correction section (e.g., `## Plan 7 — Retrospective correction for Plan 3 Learning #2`) — reference the original by Plan + bullet, state what changed and why, but **never delete or silently edit the original**. Same revision discipline as memory files: append + reference, don't erase. Preserves the learning path while keeping the current truth findable.

Memory files (`~/.claude/projects/<hashed>/memory/`):
- For each distinct new fact/feedback/rule, create a new file following naming conventions: `feedback_*.md`, `project_*.md`, `reference_*.md`, `user_*.md`
- Update `MEMORY.md` index with a one-liner link to each new file
- Never rewrite existing memory files to erase history — add revision notes in-file if facts change

#### running-log style (`continuation/context.md` primary) — also applies to CONTEXT-style

**CONTEXT-style note:** CONTEXT-style projects use the same workflow as running-log style but with different filenames. Substitute:
- `CONTEXT.md` for `continuation/context.md`
- `context/` for `continuation/`
- `context/memory/` for `continuation/memory/`
- Docket may be a domain-specific filename (e.g., `<topic>_docket.md`) rather than `roadmap.md` — look for `*_docket.md` / `roadmap.md` / `docket.md` shapes
- `CLAUDE.md` at root handled same way

Everything else (pickup-point prepend pattern, memory file naming, no-auto-push rule) is identical.

`continuation/context.md` — **prepend a new pickup point**, preserve the old one:

1. At the top of the file (after the `# Title` and `**Last Updated**` header), demote the existing `## 🔖 PICKUP POINT FOR NEXT SESSION — <old-date>` heading by inserting a new pickup point above it
2. New pickup point format:
   ```markdown
   ## 🔖 PICKUP POINT FOR NEXT SESSION — <YYYY-MM-DD> <time-of-day context>

   **<One-line summary of the session's big shift.>**

   ### What shipped after the previous pickup below (most recent first)
   <detail per deliverable>

   ### New memory files established today
   <list>

   ### <Any other relevant sections: Cache state, Infrastructure added, etc.>

   ### Open docket (see `continuation/memory/roadmap.md` for full detail)
   <numbered list of queued items>

   ### What to do first when resuming
   <ordered list of read-first files + first actions>

   ---
   ```
3. The old pickup point stays in place below the `---` divider — DO NOT delete

`continuation/memory/roadmap.md` — update the docket:
- Mark completed items `✅ <DATE>` with brief commit/completion note
- Add newly-surfaced items in the appropriate priority section (🔴🟡🟢)
- If an item got superseded or obsolete, strike it rather than delete

`continuation/memory/MEMORY.md` + topic files:
- For each distinct new rule/fact, create a new topic file in `continuation/memory/`
- Add a one-liner to `MEMORY.md` linking the new file
- Use existing prefix conventions (`feedback_*`, `project_*`, etc.)

`CLAUDE.md` at root:
- Update ONLY if a new behavioral rule emerged that should be loaded every session
- Rare update — most new rules go in memory files, not CLAUDE.md

Do NOT touch `continuation/archive/` unless specifically asked to prune

#### Neither pattern detected (new project)

Don't guess. Ask the user:
- "No HANDOFF.md or continuation/ directory found. Want me to scaffold one?"
- Offer: (a) monolithic-handoff style HANDOFF.md, (b) running-log style continuation/ directory, (c) custom — describe what you want

Then build the chosen scaffold at minimum: HANDOFF.md with placeholder sections, OR continuation/INDEX.md + context.md + memory/MEMORY.md + memory/roadmap.md.

### Step 4 — Emit plan, then apply

**Invoking the skill IS the authorization.** Do NOT stop to ask for per-run confirmation before writing. The user already expressed intent by triggering the skill; asking again is friction without safety gain.

For each file about to be updated, emit an **audit artifact** in the response:
```
**<path>** — <one-line summary of what's changing>
```

This file-list + summary lets the user verify post-hoc what was done without re-deriving from `git diff`. Then **apply the writes immediately** without waiting for further confirmation.

**Exceptions — STOP and ask before writing:**
1. **Three-source conflict detected** (per Step 2's triangulation rule): conversation, git, and TodoWrite disagree. Don't silently pick a side — ask the user to adjudicate.
2. **Destructive edit** outside the normal rewrite pattern: deleting a memory file, truncating HANDOFF.md's wiki-content sections, removing historical pickup points. Ask before executing.
3. **Uncertain ground truth** flagged by Step 2: e.g., test count where conversation says 210, git log shows 186, and no commit explains the jump. Ask rather than write a wrong number.
4. **Anything surprising or non-routine** — catch-all for edge cases the specific exceptions above don't cover. If the session's planned writes don't match the expected "persist what was discussed / built / decided" pattern — scope expanded beyond this project's root, file locations unusual, pattern detection seems wrong, memory file content feels speculative rather than grounded in the conversation — **stop and ask.** `/update-context` invocation authorizes routine context persistence; anything non-routine gets a pause. Default to caution when confidence is low.

**Exceptions — do NOT stop to ask:**
- Routine file list, content summary, memory-index update
- Adding a new memory file when a new rule is clear from conversation
- Rewriting HANDOFF.md (the universal rule mandates this on every run)
- New pickup point prepend (running-log / CONTEXT-style pattern)

### Step 5 — Apply updates + verify

Write the planned changes. Verify each file is coherent after write (re-read the edited sections; check wiki-links and path references still resolve).

### Step 6 — Stop before committing

Do NOT run `git commit` or `git push` automatically. Default to no-auto-push. Report:

```
Updated N files. Review with `git diff` before committing. When ready, commit with a message like:

  "Session update: <brief summary of what was shipped>"

Push only after explicit user approval.
```

## When the skill should refuse or scope down

- **No conversation signal** — if the session had only Q&A with no concrete changes, no commits, no new todos completed, tell the user: "I don't see substantive changes to persist. Did something happen I should know about, or is there nothing to update?"
- **Conflicting signals** — if git diff contradicts the conversation's claims, flag before writing. Example: conversation claims a bug is fixed but git shows no commit touching the relevant file.
- **User is mid-crisis** — if the user is frantically debugging, don't auto-fire. Wait for "okay, that's done" signals.

## Examples

### Example 1 — monolithic-handoff project, Plan 2 just shipped

**User:** "alright now start a thorough and comprehensive update of context files and handoff files"

**Claude (this skill):**
1. Detects `HANDOFF.md` → monolithic-handoff style
2. Reads HANDOFF.md, project-local SKILL.md (if exists), scans `~/.claude/projects/<hashed>/memory/`
3. Gathers session signal: runs git log/diff; checks TodoWrite; scans conversation for new gotchas
4. Proposes:
   - HANDOFF.md: change status from "⏳ Plan 2 queued" → "✅ Plan 2 shipped; ⏳ Plan 3 queued"; bump test count to actual; update next-session entry point for Plan 3
   - SKILL.md: append `## Plan 2 — <name> Learnings` with new gotchas
   - memory: new `project_plan_2_outcomes.md` (if notable); update existing project status memory
5. Emits file-list + one-liner audit artifact. Applies without waiting (invoking the skill = authorization).
6. "Updated 4 files. Review `git diff` before committing."

### Example 2 — running-log project, end of content batch

**User:** "wrap up this session and update the context"

**Claude (this skill):**
1. Detects `continuation/` → running-log style
2. Reads `CLAUDE.md`, `continuation/INDEX.md`, top of `continuation/context.md`, `continuation/memory/roadmap.md`, `continuation/memory/MEMORY.md`
3. Gathers session signal: git log/diff; new files in changed directories; conversation narrative
4. Proposes:
   - `continuation/context.md`: prepend new pickup point with today's date; preserve old pickup below `---`
   - `continuation/memory/roadmap.md`: mark items ✅ with today's date + brief note; add new deferred items
   - `continuation/memory/`: new `feedback_<topic>.md` if a new rule emerged
   - `continuation/memory/MEMORY.md`: add link to new feedback file
5. Emits file-list + one-liner audit artifact. Applies without waiting.
6. "Updated 3 files. Commit when ready; then `git push` explicitly per the no-auto-push rule."

## Alternatives / related skills

- **`analyze-context`** (sibling skill) — run at session START to thoroughly ingest the project's state before doing any work. Complement to this skill.
- **`claude-md-management`** (Anthropic plugin) — narrower scope: only CLAUDE.md files, audit/dedup focus, not session-update focus
- **`session-report`** (Anthropic plugin) — reports about sessions but doesn't file updates

## Do NOT

- Don't commit or push automatically
- Don't rewrite historical pickup points (in running-log projects) — preserve them
- Don't rewrite the project-local SKILL.md's existing sections (monolithic-handoff projects) — append-only
- Don't invent gotchas or learnings not grounded in actual session evidence
- Don't update files outside the detected project root (no touching other projects)
- Don't write memory files about meta-projects/catalogs when working in a domain project
