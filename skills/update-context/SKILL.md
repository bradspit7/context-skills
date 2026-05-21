---
name: update-context
description: Triggered at the END of a substantive work session to comprehensively update the project's persistence layer (HANDOFF.md / context.md / project skill / memory files / roadmap.md). Fires on phrases like "update context", "update the handoff", "update context files", "end of session update", "refresh context files", "start a thorough update of context", "update context and handoff", "time to update the docs", "wrap up this session". Proactively fire when the user signals a session is ending and substantive changes occurred. Analyzes the active conversation, git state, and TodoWrite state as three corroborating sources. Detects per-project pattern (monolithic-handoff vs running-log vs CONTEXT-style). Always produces/updates `<project-root>/HANDOFF.md` regardless of pattern. Emits a file-list audit artifact, then writes without stopping for confirmation — invoking the skill IS the authorization. Stops to ask only when the three-source triangle detects a conflict or a destructive edit is needed. Auto-commits writes locally with a derived "Session update: ..." message at the end; never auto-pushes (push timing stays user-controlled).
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

### Step 0 — Machine identity check

Run `hostname` (or `echo $COMPUTERNAME` on Windows) and match it against a known-machines mapping you keep somewhere persistent (e.g., a section in your `~/.claude/CLAUDE.md`). The machine identity gets recorded in HANDOFF.md's header metadata so future sessions can see which machine wrote the latest update — useful for cross-machine handoff (alerts the resumer if the previous session ran on the OTHER machine, which means git state, tool availability, or local config may differ).

If hostname is unknown, **flag it and ask the user before proceeding** — don't write an "unknown" machine tag into HANDOFF.md silently. Cross-machine state assumptions are exactly the failure mode the tag is designed to catch.

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

### Step 2.5 — Untracked-file triage gate (mandatory)

**Every file returned by `git ls-files --others --exclude-standard` MUST be explicitly classified before Step 3.** No untracked file is allowed to be silently skipped. This is the gate the skill historically lacked — agent memory of Edit/Write tool calls is an incomplete view of the working tree because Bash-tool side effects (heredoc-redirected file writes, script output captures, `gh`/`curl` downloads, `>` redirects) create files that never appear in the Edit/Write audit trail. The post-mortem canonical incident: a wrap-up missed 3 `.superpowers_*`-prefixed research artifacts produced by an in-session Python extraction script, ~30-45 min of work + a tool-reinstall away from being unrecoverable.

For each untracked file, run:

```bash
git check-ignore -v <path>
```

…and classify into exactly one of:

| Class | Action | Audit-artifact line |
|---|---|---|
| **(a) Commit** — relevant work artifact | Stage + include in this session's commit | `<path>  [commit]  <one-line: what this file is, why it belongs in history>` |
| **(b) Delete** — intentional scratch, no future value | `rm <path>` before Step 3 | `<path>  [delete]  <one-line: why scratch, not session output>` |
| **(c) Leave untracked** — pre-existing project clutter, explicitly throwaway, or session-private debugging | Keep on disk, do not stage | `<path>  [leave-untracked]  <one-line justification>` |
| **(d) Already gitignored** — `git check-ignore` returned the matching rule | No action; surface the rule for verification | `<path>  [gitignored: <.gitignore:LINE: PATTERN>]` |

**Do not trust agent-side pattern-matching for gitignore decisions.** A file named `.superpowers_extract_ultratap.py` LOOKS gitignored if you scanned `.gitignore` and saw `.superpowers/` — but the directory pattern and the filename-prefix are different rules and the file is NOT ignored. Always defer to `git check-ignore -v`'s exit code: zero = ignored (and the rule + line number is printed), non-zero = NOT ignored, file must be triaged into (a)/(b)/(c).

**Symmetric trap to watch for: Bash-tool-created files in directories the agent doesn't think of as "this session's output."** Project root `.foo`-prefixed scratch, `/tmp` writes that got copied into the project dir, sibling-directory writes from a script run with the wrong CWD. Run `git ls-files --others --exclude-standard` from the project root; trust its output over any mental model of "where I wrote files."

The classified list flows into Step 4's audit artifact as additional rows beyond the obviously-edited HANDOFF / context / memory files. **The Step 4 audit artifact is incomplete if it does not enumerate Step 2.5's classifications.**

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

**Required header metadata** — include at the top of HANDOFF.md alongside the `Updated:` line:

- `**Last write from:** <machine-name>` — the machine that wrote this update, per Step 0's `hostname` check against the known-machines mapping. One line, near the top. Lets the next session immediately see if the previous session ran on a different machine (which means git state, tool availability, or local installs may differ).
- `**Branch:** <git rev-parse --abbrev-ref HEAD>` — the branch this HANDOFF was authored on (omit if writing on `main` / `master`). One line, near the top. Combined with `analyze-context`'s Step 1.5 Check B (branch-recency survey), this gives the next session a baseline to detect when a sibling branch's HANDOFF supersedes the current branch's — critical in branch-per-feature + cross-machine workflows where work alternates between machines and lands on different branches. Without this stamp, a session resuming on a different branch has no signal that the previous HANDOFF lives elsewhere unless Check B's diff fires.

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
- **No unverified negatives.** Never record a negative-availability claim — "X doesn't exist," "X is unavailable," "X is undocumented / a black box" — into a memory file when repo + local disk could confirm or deny it, and you only have a single web-search result. A web agent's "not publicly documented" means *not on the public internet*, NOT *unavailable to us* — privately-extracted datasets, local decompiles, and committed-but-unindexed files never surface in a web search. Before writing any "X is unavailable" memory: `grep -ri <X>` the repo and check any README-cited local extract dir. A false negative in memory is uniquely corrosive — it propagates the wrong belief to every future session and steers them away from data they actually have. If two session facts can't both be true ("the design is built on X" + "X is unavailable"), reconcile them by searching, don't record the convenient one.

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

**Build the audit artifact from `git status --porcelain` ground truth, NOT from agent memory of edits.** Memory of Edit/Write calls is an incomplete view because Bash-tool side effects (script output captures, heredoc writes, `gh`/`curl` downloads) create real files invisible to the Edit/Write audit trail. The canonical failure mode the audit artifact prevents: agent reports "wrap complete" with a HANDOFF entry mentioning some research, but the empirical data files that ground the research were left untracked on the working tree and lost on next `git clean`.

Concrete derivation:

```bash
git status --porcelain         # every staged, unstaged, untracked path
git diff --stat HEAD            # what changed vs last commit (line-counts)
# Plus Step 2.5's classified untracked-file list
```

Then emit a row-per-path artifact covering EVERY path the above returns. Format:

```
<path>  [<class>]  <one-line reason / what's changing>
```

Where `<class>` is one of: `commit-edit` (file changed via Edit/Write this session), `commit-new` (Step 2.5 class (a)), `delete` (Step 2.5 class (b)), `leave-untracked` (Step 2.5 class (c)), `gitignored: <rule>` (Step 2.5 class (d)), `pre-existing-unstaged` (modified before this session — flag, don't auto-stage; see Step 6 exception 3), `already-tracked-no-change` (in status but actually unchanged).

**Files don't get to escape this listing.** If `git status --porcelain` returns a path and the audit artifact doesn't, that's a bug — the wrap is incomplete and the report must NOT claim "wrap complete." This rule supersedes any temptation to summarize-as-narrative without enumerating the git state.

This file-list + classification lets the user verify post-hoc what was done without re-deriving from `git diff`. Then **apply the writes immediately** without waiting for further confirmation.

**Exceptions — STOP and ask before writing:**
1. **Three-source conflict detected** (per Step 2's triangulation rule): conversation, git, and TodoWrite disagree. Don't silently pick a side — ask the user to adjudicate.
2. **Destructive edit** outside the normal rewrite pattern: deleting a memory file, truncating HANDOFF.md's wiki-content sections, removing historical pickup points. Ask before executing.
3. **Uncertain ground truth** flagged by Step 2: e.g., test count where conversation says 210, git log shows 186, and no commit explains the jump. Ask rather than write a wrong number.
4. **Anything surprising or non-routine** — catch-all for edge cases the specific exceptions above don't cover. If the session's planned writes don't match the expected "persist what was discussed / built / decided" pattern — scope expanded beyond this project's root, file locations unusual, pattern detection seems wrong, memory file content feels speculative rather than grounded in the conversation — **stop and ask.** `/update-context` invocation authorizes routine context persistence; anything non-routine gets a pause. Default to caution when confidence is low.
5. **Untracked-file classification incomplete or uncertain** — Step 2.5 returned files the agent cannot confidently classify into (a)/(b)/(c)/(d). Surface the ambiguous paths to the user and ask. Common cause: scratch-prefixed files that LOOK gitignored but `git check-ignore` proves are not — the user is the authority on whether they're keepers or trash, and silently picking either is a data-loss-vs-noise hazard.

**Named anti-pattern — "narrative-summary persistence test."** If the agent thinks *"my HANDOFF entry mentions X, so X is preserved"* — that's WRONG unless X is committed-as-data, not just mentioned-as-prose. Persistence is a property of git state, not of narrative content. A HANDOFF.md paragraph naming a research artifact does NOT preserve the artifact; only a commit containing the artifact (or a `git add` then commit) does. The audit artifact's git-state derivation (above) is the antidote — it forces ground-truth enumeration rather than narrative-summary trust.

**Exceptions — do NOT stop to ask:**
- Routine file list, content summary, memory-index update
- Adding a new memory file when a new rule is clear from conversation
- Rewriting HANDOFF.md (the universal rule mandates this on every run)
- New pickup point prepend (running-log / CONTEXT-style pattern)

### Step 5 — Apply updates + verify

Write the planned changes. Verify each file is coherent after write (re-read the edited sections; check wiki-links and path references still resolve).

### Optional: Lifecycle direct-push exemption (per-project opt-in)

Some projects with multi-worktree workflows benefit from `HANDOFF.md` and the wiki doc (`continuation/context.md` or `CONTEXT.md`) landing directly on `main` rather than the current worktree's feature branch. This prevents **state fragmentation** — where lifecycle docs live in unmerged feature branches and a sibling worktree's `analyze-context` reads stale state from a worktree that never received the previous session's update.

**Per-project opt-in.** This is NOT default. A project opts in via either:

- A marker file at `<project>/.claude/lifecycle-direct-push.flag` (presence = opt-in)
- A `## Lifecycle direct-push exemption` subsection in CLAUDE.md naming `HANDOFF.md` and `context.md` / `CONTEXT.md` as the only files exempt from no-auto-push

**When opted in**: replace Step 5's commit step with the branch-switch-stash-commit-push-restore sequence — the same shape used by direct-push slash commands like `/tell-collaborator` writing to a coordination feed. The exemption applies to **only** the lifecycle docs (HANDOFF + context.md/CONTEXT.md). All other update-context writes (memory files, project skill SKILL.md, roadmap.md, decision docs) commit on the current branch per default Step 6.

Canonical bash flow:

```bash
ORIGINAL_BRANCH=$(git symbolic-ref --short HEAD)
STASH_CREATED=false
if ! git diff --quiet || ! git diff --cached --quiet; then
  git stash push -m "update-context-autostash" && STASH_CREATED=true
fi

git checkout main && git pull --ff-only origin main
# ... write/commit lifecycle docs ...
git push origin main || (git pull --rebase origin main && git push origin main)

git checkout "$ORIGINAL_BRANCH"
[ "$STASH_CREATED" = true ] && git stash pop
```

**Trade-off**: direct-push removes the worktree-fragmentation failure mode but requires the same atomic-stash discipline (`git stash push`, NOT `git stash create`/`store`) to handle dirty worktrees safely. Race-with-another-writer requires `git pull --rebase` + retry-once. Opt in only if the worktree-mismatch problem is actually biting in practice.

**When NOT opted in (default)**: fall through to Step 6's "stop before commit/push" rule as written.

### Step 6 — Commit, then stop before pushing

**Auto-commit is the default.** After writes complete, derive a one-line summary from Step 2's session signal (shipped + decided + learned), then run:

```bash
git add <each-file-listed-in-Step-4-audit-artifact>
git commit -m "Session update: <one-line summary>"
```

Local commit is non-destructive (reversible via `reset`, `revert`, amend) and the Step 4 audit artifact already enumerated every touched file pre-write. Reviewing the diff post-commit is identical in safety to reviewing pre-commit; the "show commit-message-template, wait for user to copy-paste into terminal" ritual is friction without proportionate safety gain.

If `git diff --cached` is empty after `git add` (writes produced no effective change), skip the commit and report *"No effective changes — nothing to commit."*

**Pre-report tree-cleanliness assertion.** Before printing the "Committed as <sha>" report, re-run `git status --porcelain` and confirm every remaining path is in one of: `leave-untracked` (Step 2.5 class (c)), `pre-existing-unstaged` (declared in Step 4 audit artifact and deliberately not staged), or empty (clean tree). If unexpected untracked or unstaged paths remain, **do NOT report wrap-complete.** Surface them: *"Tree still has unclassified paths after commit: `<path1>`, `<path2>`. The wrap is not complete — re-run Step 2.5 triage."* This is the last line of defense against the canonical failure mode (a real untracked artifact slipping past the audit artifact). It's cheap (one git command) and catches both Step 2.5 escapes and any Bash-side-effect file the session produced AFTER Step 2.5 ran.

**Do NOT run `git push` automatically.** Push timing is user-controlled per project no-auto-push rules and per user-global git-discipline conventions. After commit, report:

```
Committed as <sha>. N files changed. Push when ready.
```

**Exceptions — do NOT auto-commit, fall back to show-message-only:**

1. **Three-source-conflict / destructive-edit / uncertain-ground-truth flags fired during Step 4** — you should have stopped already, but if you somehow proceeded, don't compound the error with an auto-commit.
2. **User explicitly said "don't commit yet"** / "let me look first" / similar — explicit user veto wins.
3. **Working directory had pre-existing uncommitted changes overlapping with files this update touched** — `git add <touched-files>` would bundle unrelated content into the commit. Detect via `git status --porcelain` BEFORE write; if any file in the planned write set has pre-existing unstaged modifications, fall back to show-message-only and let the user resolve the overlap manually.
4. **Project CLAUDE.md or HANDOFF.md explicitly says "never auto-commit"** — per-project opt-out. Respect it. (Distinct from "no-auto-push" which is the default everywhere.)

**Fallback report when an exception fires:**

```
N files written. Skipping auto-commit because <exception reason>. Review with `git diff` and commit manually:

  git add <files> && git commit -m "Session update: <summary>"

Push only after explicit user approval.
```

## When the skill should refuse or scope down

- **No conversation signal** — if the session had only Q&A with no concrete changes, no commits, no new todos completed, tell the user: "I don't see substantive changes to persist. Did something happen I should know about, or is there nothing to update?"
- **Conflicting signals** — if git diff contradicts the conversation's claims, flag before writing. Example: conversation claims a bug is fixed but git shows no commit touching the relevant file.
- **User is mid-crisis** — if the user is frantically debugging, don't auto-fire. Wait for "okay, that's done" signals.
- **Bash-tool-side-effect files present and uninspected** — if the session created files via the Bash tool (script outputs written via `>` redirect, heredoc writes, `gh`/`curl` downloads, `cp`/`mv` from outside the project) those files are NOT in the Edit/Write tool's audit trail and the agent's mental model of "what I wrote this session" omits them. They MUST be re-discovered via `git status --porcelain` + Step 2.5 triage before the wrap can be considered complete. If Step 2.5 hasn't run and the conversation suggests Bash-side-effect writes occurred, refuse to proceed to Step 4 until Step 2.5 completes.

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
6. Auto-commits: `git add <4 files> && git commit -m "Session update: Plan 2 shipped, test count to N"`. Reports: *"Committed as `<sha>`. 4 files changed. Push when ready."*

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
6. Auto-commits the 3 files with a derived `"Session update: ..."` message. Reports: *"Committed as `<sha>`. 3 files changed. Push when ready."* Push stays explicit per the no-auto-push rule.

## Alternatives / related skills

- **`analyze-context`** (sibling skill) — run at session START to thoroughly ingest the project's state before doing any work. Complement to this skill.
- **`claude-md-management`** (Anthropic plugin) — narrower scope: only CLAUDE.md files, audit/dedup focus, not session-update focus
- **`session-report`** (Anthropic plugin) — reports about sessions but doesn't file updates

## Do NOT

- Don't push automatically (commit IS automatic per Step 6's default — push timing stays user-controlled)
- Don't rewrite historical pickup points (in running-log projects) — preserve them
- Don't rewrite the project-local SKILL.md's existing sections (monolithic-handoff projects) — append-only
- Don't invent gotchas or learnings not grounded in actual session evidence
- Don't update files outside the detected project root (no touching other projects)
- Don't write memory files about meta-projects/catalogs when working in a domain project
