---
name: update-context
description: Use at the END of a substantive work session to persist state to the project's context layer (HANDOFF.md, per-dev HANDOFF-<name>.md, wiki/running-log, memory files, docket). Fires on "update context", "update the handoff", "wrap up this session", "end of session update", "refresh context files", or proactively when the user signals the session is ending and substantive work happened. Does not fire when nothing substantive changed or the user is mid-task. Writes without per-run confirmation; auto-commits locally; never pushes.
---

# Update Context

Session-end skill: **triage what this session produced, write each fact to its single home, rotate history out of the hot path, and leave the tree provably clean.** The write-side complement to `analyze-context`.

Two laws:

1. **Persistence is a property of git state, not narrative.** A HANDOFF paragraph *mentioning* an artifact does not preserve it; only a commit containing it does. Every claim of "wrap complete" must be derivable from `git status --porcelain`, not from memory of what was edited.
2. **The layer must stay readable in one sitting.** Every write that adds must be matched by rotation that removes-to-archive. Bloat compounds: an unrotated wiki and an unconsolidated memory dir are why session starts cost 200K tokens. The next session's read cost is THIS run's responsibility.

Invoking the skill IS the write authorization — no per-run confirmation. Stop to ask only on the exceptions in Step 6. Project CLAUDE.md conventions (e.g. PR-flow for docs, never-auto-commit) override this skill's defaults.

## Three-source triangle

Ground every update in: **(1) the conversation** (what was discussed/decided/built — primary), **(2) git state** (corroborating ground truth), **(3) the task/todo state** (done vs in-flight vs queued). If they disagree — conversation says the bug is fixed, git shows no commit touching the file — flag the mismatch and ask; never silently pick a side. Same for date conflicts: when the system clock contradicts file/commit dates, anchor on file evidence and surface the discrepancy.

### Verify-from-live-source before writing

Before any current-state claim lands in a file, **re-derive it from live source** — not from the conversation's memory of it, another memory file, or stale handoff content. Perishable facts drift silently between when they were observed and when the wrap writes them (a HANDOFF once shipped an ahead-count that was already wrong the moment the wrap commit landed). **This also covers a claim you carry forward verbatim into a rewrite/compression, not only a freshly-authored one** — a preserved current-state line ("left untracked," "edits uncommitted," an ahead-count) can be stale even though you didn't re-type it, so re-probe it before it survives the rewrite. Re-probe the perishable ones:

| Claim type | Live probe |
|---|---|
| Test / assertion count | the test runner's collect/count (`pytest --collect-only`, the suite's own count command) |
| Branch / commit / ahead-count | `git status`, `git log`, `git rev-list --count @{u}..HEAD` |
| Running process / PID | `ps`, the process manager's list, a PID file |
| Config value / threshold | read the actual config file, not a doc describing it |
| External / API / dashboard state | the live endpoint or dashboard, not a cached figure |

If a declared liveness-probe convention exists in the project's CLAUDE.md, run it **verbatim** over any guessed equivalent. A probe that disagrees with the conversation/git/memory → trust the probe, write the verified value, note the discrepancy. A fact that stays **unverifiable** after probing is uncertain ground truth — route it through the existing Step-6 STOP rather than writing a guessed value.

**Optional parallelization (capable model only):** this verify pass and Step 3's memory-lesson scan are read-only, so on a capable model dispatch them as advisory read-only subagents via `orchestrate` while the main thread plans writes — a verify agent that re-derives each perishable claim per the table above, and a lesson agent that runs the Step-3 scan. Both are **advisory evidence with a barrier**: their results must land before the Step-6 audit artifact; a disagreement routes through the same Step-6 STOP (nothing is auto-resolved). **Writes, commits, and every STOP gate stay on the main thread and sequential.** A dispatched agent that errors, times out, or returns partial results → rerun that scan serially in the main thread before Step 6; no fan-out available → serial single-pass as normal, and say so in the report.

## Step 1 — Gather evidence

```bash
bash ~/.claude/skills/update-context/scripts/session-evidence.sh
```

One run returns: machine, branch, last commit, full porcelain status, diffstat, untracked **TRIAGE** lines, rotation **THRESHOLD** signals (pickup-point counts, HANDOFF prior-summary accretion, oversized per-dev files), memory health (file counts, sizes, dead index links, missing index), and **coherence** THRESHOLDs (a resolved `G#` ID still shown as an open row in the HANDOFF's forward sections, a duplicated ready-signal block, a mis-stated open-count). No-git projects get an mtime-based fallback. If the script is missing, run the essentials inline: `hostname`, `git status --porcelain`, `git diff --stat HEAD`, `git ls-files --others --exclude-standard`.

Combine with the conversation + todo state into the session signal: **shipped / learned / decided / deferred / pending-user**.

**Untracked triage is mandatory.** Every `TRIAGE` line gets exactly one class — `commit` (work artifact) / `delete` (scratch — confirm first) / `leave-untracked` (pre-existing clutter or session-private). No silent skips: Bash side effects (`>` redirects, heredocs, `gh`/`curl` downloads, scripts run with odd CWDs) create real files invisible to the Edit/Write audit trail, and an unclassified artifact is one `git clean` from gone. Trust git's output over any mental model of "where I wrote files"; the script's list is already filtered by git's own ignore rules, so a file appearing there is NOT gitignored no matter what its name resembles. Can't confidently classify a path → ask; the user is the authority on keeper-vs-trash.

## Step 2 — Detect the pattern

Same table as `analyze-context`: **multi-dev** (`HANDOFF-<name>.md` / `coordination/`), **monolithic-handoff**, **running-log** (`continuation/`), **CONTEXT-style** (`CONTEXT.md` + `context/`), **hub/no-git**, **hybrid → ask**, **none → offer to scaffold** (HANDOFF.md + memory/MEMORY.md + docket at minimum; ask which style).

Multi-dev adds the identity check: `gh api user --jq .login` → project CLAUDE.md identity table → fallback `git config user.name` → else ask. **You write only your own `HANDOFF-<dev>.md`** (plus the shared slim HANDOFF) — never another dev's file unless the user explicitly directs cross-coverage.

## Step 3 — Triage: every fact gets ONE home

The anti-bloat core. For each item in the session signal, route it to exactly one destination; everything else cites that home by pointer, never by copy:

| Fact type | Single home |
|---|---|
| Current status / next entry point / blockers | `HANDOFF.md` (or your per-dev file in multi-dev) |
| Session narrative ("what happened and why") | Wiki pickup point / per-dev dated entry / in monolithic projects: a dated entry in HANDOFF's progress-log section — compressed, not a transcript |
| Durable rule, gotcha, convention | Memory file (`feedback_*` / `project_*` / `reference_*` / domain prefix) + one index line |
| Locked decision with rationale | Decision doc (`docs/**/decisions/`) or the locked-decisions section; HANDOFF links it |
| Queued/deferred work | Docket (`roadmap.md` / `*_docket.md`) — HANDOFF shows only the top ~3 as pointers. No docket file yet → creating one (`memory/roadmap.md` or a root docket) is routine, not scaffolding. Open items get stable `G#` IDs (see *Docket goal IDs*, end of Step 4) |
| Cross-dev announcement (multi-dev) | Coordination feed entry (via the project's feed command), BEFORE the handoff refresh so the refresh can cite it |
| Everything failing the test below | Nowhere — drop it |

**The load-bearing test:** *would the next session — possibly another developer on another machine — act differently if this line were missing?* No → it doesn't get persisted. Verbose capture is not fidelity; it's the bloat that buries the load-bearing lines.

**Memory-specific rules:**
- Before creating a memory file, run the estate's memory keyword search (e.g. `/memory-search`) on the fact's key terms — an eyeballed MEMORY.md scan misses the same fact worded differently. A hit that reads as the same rule gets a dated revision note appended, not a duplicate file. No search tool available → fall back to reading the MEMORY.md index directly (a zero index-scan there proves nothing about same-fact-different-wording).
- Never rewrite memory history to erase it; corrections append and reference what they supersede.
- **No unverified negatives.** Never record "X doesn't exist / is unavailable / is a black box" on the strength of a web search alone — `grep -ri` the repo and check README-cited local dirs first. A false negative in memory steers every future session away from data that exists.

## Step 4 — Write, per pattern

**Universal: every run produces/updates `HANDOFF.md`** with this machine-readable header:

```markdown
**Updated:** YYYY-MM-DD (<short context>)
**Machine:** <name> · **Branch:** <branch> · **Author:** <dev — multi-dev only>
**Summary:** <ONE sentence for this session. Prior-session summaries NEVER accrete here — history lives in the wiki/log.>
```

…and the eight sections (compressed to what's real): one-line status / recently shipped (this + last session only) / in flight / next session entry point / pending user decisions / known issues / files to read first / pointers to deeper context+memory. HANDOFF is a **snapshot, rewritten each run** — link to the wiki, docket, and memory instead of duplicating them (the duplicated-table read-cost is paid by every future session). No line-count floor or ceiling: a complex project may need 200 tight lines; what's forbidden is redundancy and stale residue, not length.

**Rotate, don't append — rewrite the whole doc, not just the top.** Because the HANDOFF is rewritten each run, a status change must propagate through EVERY forward-looking section, not just a new block bolted above a stale one. The recurring failure: newer status written at the top while an operationally-false block survives below the fold — a resolved `G#` ID still listed as an **open row** in the Docket / Pick-up / Ready-signal sections, two ready-signal blocks, or an "N open" count carried forward instead of recomputed. Before reporting, resolve every `== COHERENCE ==` THRESHOLD the evidence script raised: a resolved ID belongs only in the backward-looking "Recently shipped" narrative, never in a forward section; there is exactly one current ready signal, naming this session's actual latest state; the open-count is recomputed from the docket. A **narrative mention** of a resolved ID in prose is fine — an open *row* claiming it is the incoherence.

**Perishable git-state prose: anchor it or make it derivable — never bare absolutes.** A git-state fact written as a bare present-tense absolute ("nothing pushed", "ahead 16", "tests 34/34", "tree is clean") falsifies silently the moment the next commit, push, or test run happens — a repeat external-review finding (3 P2s, 2026-07-04 audit). Every such fact in a file that outlives the session takes one of two durable forms: **(1) anchored** — tied to the event that produced it ("ahead 16 *after this wrap*", "34/34 *at commit `<sha>`*"), so the sentence stays historically true no matter what happens next; or **(2) derivable** — the command that recomputes it (`git rev-list --count @{u}..HEAD`) named instead of, or beside, today's value. The verify-from-live-source pass above makes the value true *at write time*; this rule keeps the sentence from becoming a lie *afterward* — both are required. (Step 7's "ahead <K> after this wrap" wording is the canonical instance.)

**running-log / CONTEXT-style:** prepend a new dated pickup point to `continuation/context.md` (or `CONTEXT.md`) above the previous one — what shipped / new memory files / open docket pointer / what to do first when resuming. Entry shape is load-bearing: the header line carries the literal `PICKUP POINT` + the ISO date, and the entry ends with a `---` divider — the evidence script's rotation counter and analyze-handoff's top-section read both parse this shape. Prior pickups are preserved (then rotated — Step 5). Update the docket: `✅ <date>` completions, new items in priority sections, strike (don't delete) superseded items. Each open item carries its stable `G#` ID (see *Docket goal IDs* below); completions flip the marker, the ID stays.

**monolithic-handoff:** update the legacy sections in place (status markers, code state, locked decisions — add-only, test counts, next entry point, known issues). Keep wiki-ish content intact UNTIL the structural size threshold fires (Step 5) — then extract the durable wiki/setup tail to docs/ leaving pointers; ensure the universal header + sections exist. Project-local SKILL.md gets append-only `## Plan N Learnings`; corrections reference, never silently edit.

**multi-dev:** prepend a dated entry to **your own** `HANDOFF-<dev>.md` — ISO date header, one dense paragraph (headline, PRs merged/opened/closed-without-merge, decisions, cross-dev state, ending with `NEXT-SESSION ENTRY POINT: <pointer>`), stamped `**Machine:** · **Branch:**`. Append-only: never edit prior entries; corrections go in the new entry. Then refresh the slim shared `HANDOFF.md` only where shared state changed (owner table, open-PR list, carry-forwards, kill/pivot rules) — it's a live contract kept current in place, not a log; no narrative there.

**hub/no-git:** same content flow; date stamps carry the staleness burden; skip commit steps.

### Docket goal IDs — the `G#` convention

Open goals carry **stable, namespaced IDs** so they survive status changes, reordering, and rotation instead of being silently dropped between sessions.

- **Format:** `G#<n>` — a positive integer, allocated monotonically per project, **never reused, never renumbered**. `G#` is collision-free against GitHub `#N` PR/issue refs and `[N]` step refs.
- **Allocation (never a bare-number scan):** the authoritative counter is a `<!-- next-goal-id: N -->` marker in the docket. Allocate `G#N`, then bump the marker to `N+1`. First adoption with no marker: seed `N = max(G#\d+ tokens across live + resolved + archive) + 1` (or `1`), then write the marker — the seed scan matches the **namespaced** `G#\d+` only, never bare `#\d+`, so it cannot grab a PR/issue number.
- **Row grammar:** a goal row begins with `G#<n>` (after any bullet, or in a dedicated table cell), then a status marker, then the text. E.g. `- **G#7** 🟡 Split the combat module — owner: me · ~2h`.
- **Status markers:** `✅` done · `🟢` ready · `🟡` in progress · `🔴` high · `⏸` deferred · `⛔` dropped · `📅` scheduled. Completion flips the marker; the **ID never changes**. Rotation retires the ID (never reused); a `⛔` keeps its ID + a one-line reason.
- **Tiers (scale by backlog; propose graduation, never force):** T1 inline numbered docket (default, every project) -> T2 workstream-grouped (~15+ open items or genuinely separate streams) -> T3 dedicated `roadmap.md` + dated resolved-ledger + rotation (when the docket outgrows the HANDOFF; uses the Step-5 structural-rotation machinery).
- **Preserve existing shape:** layer `G#` IDs + markers onto whatever docket shape a project already has (a table stays a table — add a `G#` column; multi-dev per-dev files keep their structure under one per-project counter). Never rewrite a working docket into a different format.
- **Grandfather legacy systems:** a docket already using a *consistent* bare-`#N` system with no `G#` markers (cross-references keyed off it) is a sanctioned legacy dialect — **do not renumber it**. `G#` adoption is for dockets that lack a stable-ID system.

## Step 5 — Rotation + memory hygiene (every THRESHOLD fires this run)

Rotation is how read-cost stays flat. All moves are **non-destructive** (content relocates to an archive file with a pointer left behind) — they don't require asking. Actual deletion always asks.

- **HANDOFF coherence** (`== COHERENCE ==` THRESHOLD): a resolved `G#` ID still shown as an open row in a forward section, a duplicated ready-signal block, or a stale open-count. Unlike history rotation (a move-to-archive), this is a same-doc **rewrite** to current state — the Step-4 rotate-don't-append rule; fix the offending section this run.
- **HANDOFF header accretion** (`Prior summary:` chains): move ALL prior-session summaries — however many are packed into the header line — into the wiki/log (or `archive/HANDOFF-history-<YYYY-MM>.md` for monolithic projects; `<YYYY-MM>` = the month of this run), leaving only the current header. Mandatory on first contact with a legacy blob. Word the pointer line left behind WITHOUT the literal string `Prior summary:` (e.g. *"Session history pre-<date> archived → <file>"*) so the evidence script's detector doesn't re-fire forever.
- **Wiki pickup points:** keep the newest **3** inline; move older ones verbatim to `continuation/archive/pickup-points-<YYYY-MM>.md` (create as needed), leave one pointer line.
- **Per-dev files > ~600 lines:** move entries older than ~2-3 weeks to the project's archive per its trim convention (in PR-flow projects, a separate trim PR — don't mix with the refresh).
- **Single-line accretion** (max-line THRESHOLD): a "slim" file can hide tens of KB inside ONE physical line — rolling-digest lines, multi-generation `SUPERSEDED` chains. Line counts never catch it (a 112-line file once hid 73KB this way). Rewrite the offending line to current state only; the displaced history goes to the archive like any other rotation.
- **Structural rotation** (size THRESHOLD on `HANDOFF.md` or the read-path docket — durable *structure*, not history): fires when a bridge doc exceeds its byte ceiling (`session-evidence.sh`: monolithic `HANDOFF.md` >~40KB, or a read-path THRESHOLD whose bloat is closed rows / durable reference). Unlike history rotation this relocates durable **live** content, so it is two-phase with the second phase gated:
  - **Protected-doc + foundational-root guards (OVERRIDE rotation — neither phase touches these):** a canonical operational doc — filename matching `*WORKFLOW*` / `*PIPELINE*` / `*RUNBOOK*` / `*PLAYBOOK*.md`, or any doc opening with a LOCKED-section / brand-bible-style preamble — is **never extracted, flattened, or overwritten** by rotation; the only permitted edits are a dated one-line "last updated" note and cross-reference pointers from the bridge doc. Likewise a **foundational root HANDOFF** (a substantive base-context file — "what this project is", file map, persona/character profiles, pipeline architecture, locked-decision content — not a slim pointer) is **never flattened into the slim snapshot form**: preserve its foundational content verbatim and update only a delimited current-session block at the top (or STOP-and-ask if a marker block is awkward for its structure). These guards beat the byte-ceiling THRESHOLD — a doc's size never licenses stripping it.
  - **Phase A — safe-collapse (always inline):** closed / ✅-done items → one-liners; cut duplicate paragraphs; compress verbose closed sections. Mechanical and safe like history rotation — do it this run.
  - **Phase B — structural extraction (GATED):** classify each remaining section *keep-in-bridge* (one-line status, next entry point, in-flight, open-docket pointers, locked decisions) vs *move-to-wiki* (fresh-clone/setup, tool inventory, stable how-it-works, deeper-context reference). Classify by section *content*, not its name — a "Known issues" section of stable behaviors is durable reference (move), but one listing open action items stays. Move the wiki set to `docs/` — `docs/SETUP.md` (setup/fresh-clone) + `docs/<status-or-wiki>.md` (durable reference) — **refreshing the destination FIRST if it is stale** (a move into a stale target strands content), leave one-line pointers, verify every moved section is pointer-reachable. Run Phase B inline ONLY when the destination is fresh (or trivially refreshable this run) AND classification is unambiguous; otherwise STOP-and-surface (Step 6) and record the residual as a next-session / docket flag — never a silent drop. A misclassification strands real state, so never auto-bundle Phase B into an unrelated feature wrap unreviewed.
  - **Running-log docket:** the structural target is the docket (`roadmap.md`) — archive closed/resolved rows to `continuation/memory/archive/roadmap-closed-<YYYY-MM>.md` (pointer left behind); extract durable reference to `docs/` as above. Respect inline "keep — baseline" row markers.
  - **HOLD:** an `INFO ... on HOLD until <date>` line from the evidence script (a dated `<!-- rotation-hold: until YYYY-MM-DD reason -->` marker in the doc) is acknowledged and NOT acted on — neither phase runs for a held doc.
- **Memory consolidation** (fires on: dead index links, oversized index lines, session-start read-path >50KB [MEMORY.md + docket/roadmap — NOT on-demand topic-file bulk], or no index over 5 files):
  - **Mechanical legs run via the bundled fixer — never hand-typed:** `bash ~/.claude/skills/update-context/scripts/memory-hygiene.sh <memory_dir> [mirror_dir]` strips frontmatter trailing whitespace in place (idempotent), lists >200-char index lines, and (with a mirror dir) syncs live→mirror + verifies parity. One command replaces the strip/copy/verify rounds that were being re-derived at nearly every wrap (2026-07-04 audit). The >200-char listing is report-only — the trim itself stays a judgment MOVE (next bullet).
  - Fix/remove dead MEMORY.md lines (index lines are not history; safe to correct).
  - Index lines stay **≤200 chars at write time** — an index line is a pointer + hook, not the content. Detail (including inline `UPDATE` patches) merges down into the topic file the moment it appears; indexes re-bloat by line-growth, not entry-count, so write-time discipline beats periodic sweeps. **Trimming an existing long line is a MOVE, never a cut:** verify the topic file already holds the detail (add it there first if not, deferring to the topic file where the two disagree) before shortening the index line. Topic files themselves have no size cap — size them to what the content needs.
  - Merge near-duplicate files into the newest canonical one; archive the superseded with a pointer.
  - Archive `research_*` superseded by newer same-domain research, and `project_*` snapshots about long-shipped work, to `memory/archive/`.
  - Entries deferred past a known future date get parked in archive with a `revisit: <date>` line.
  - **After any archive/merge, grep `.claude/` for the moved filenames** (skills, agents, hooks, commands) and repoint hits. Memory-internal cross-refs get audited by the dead-link check; the `.claude/`→memory direction is the one nothing checks by default — reviewer agents and skills cite memory files by name and break silently when consolidation moves them.
  - Build MEMORY.md if missing.
- **Upgrade reflection (run every wrap):** beyond memory promotion, scan the session signal for anything warranting a new or upgraded **tool / hook / subagent / slash command / MCP / catalog entry / CLAUDE.md rule** — invoke the `reflect-upgrades` skill (or inline its checklist: load-bearing test + de-dup, then route). Surface surviving candidates in the wrap report and FILE them — generalizables to your central upgrades repo or catalog, project-specific ones to the current project's docket. Filing is unconditional — no permission-seeking, no "next session" deferral; a `rotation-hold` blocks structural rotation, never a one-line docket add (canonical rule + named non-reasons: reflect-upgrades Step 4). A memory rule that has now bitten 2+ projects is one such candidate (promote it to a skill or global CLAUDE.md). Empty is a valid result — do not manufacture candidates.

## Step 6 — Audit artifact, then apply

Emit the audit artifact **derived from porcelain ground truth** — one row per path the script reported plus every file this run will write:

```
<path>  [commit-edit|commit-new|delete|leave-untracked|rotate-archive|pre-existing-unstaged|memory-write]  <one-line reason>
```

`memory-write` covers out-of-repo paths (`~/.claude/projects/<slug>/memory/...`) — outside porcelain's scope but still mandatory rows, so no write escapes the listing. A porcelain path missing from the artifact = the wrap is incomplete and must not claim completion. Then apply the writes immediately and verify each written file is coherent (re-read edited sections; links resolve).

**STOP and ask instead of writing when:** the three-source triangle conflicts · a destructive edit is needed (deleting memory files, truncating wiki history — rotation-to-archive excluded) · ground truth is uncertain (test counts that no commit explains) · untracked classification is uncertain · anything non-routine (scope outside the project root, speculative memory content, pattern detection looks wrong). Default to caution when confidence is low. **A stop suspends all writes until the user resolves it — it does not cancel them:** once resolved, the full plan including any mandatory THRESHOLD rotations still executes in this run. Stop ≠ skip.

## Step 7 — Commit, never push

**Hygiene re-check first:** Step 1's HYGIENE scan predates this wrap's own writes — and the auto-memory normalizer re-adds frontmatter trailing whitespace after every memory write — so re-run the evidence script's `== HYGIENE ==` scan now (after all writes and copy-backs) and strip anything flagged before adding. The strip is `scripts/memory-hygiene.sh <memory_dir> [mirror_dir]` (also re-syncs the mirror in projects that keep one) — one idempotent command, not hand-typed sed rounds. This is the once-per-wrap strip point; never strip at write time (the normalizer re-adds it).

Auto-commit is the default:

```bash
git add <each-path-classified-commit-*-or-rotate-archive>
git commit -m "Session update: <one-line from the session signal>"
```

**Pre-report cleanliness assertion:** re-run `git status --porcelain`; every remaining path must be `leave-untracked` or `pre-existing-unstaged` per the artifact. Anything else → *"Tree still has unclassified paths — wrap is NOT complete"* and back to Step 1's triage. Only then report: `Committed as <sha>. N files. <branch> ahead <K> of origin.` — ahead-count via `git rev-list --count @{u}..HEAD` (no upstream configured → say that instead). **The push-state line is visibility, not a push prompt** (mined 2026-06-10: "did you push this to git?" recurred across projects) — push timing stays with the user; don't append "want me to push?". If the project's handoff tracks pending-push counts, refresh them as the **post-wrap number** — at-write ahead-count plus the wrap commit(s) this run will still make, worded "ahead <K> after this wrap." The at-write count goes stale the moment the wrap commit lands (it can never include the commit that contains it); never chase it with a correction commit — the next session's currency gate recomputes anyway. (Field-learned on the line's first fire, 2026-06-11.)

**Cross-repo state table — mandatory whenever the session wrote to more than one repo.** The report's push-state line covers the project root; every OTHER repo the session wrote to (a catalog, a public mirror, a sibling repo, a central tooling repo) gets one table row, or the owner is left asking "so what do we need to push?" for exactly the repos the wrap didn't name. Per row: **repo · ahead-count · dirty/untracked · what gates its push** (a documented publish gate / owner call / freely pushable). Values are measured at wrap time — `git rev-list --count @{u}..HEAD` and `git status --porcelain` per repo, commands named per the anchored-git-state rule above — never carried forward from an earlier report. One repo written → the existing push-state line already is the table.

**Fall back to show-the-commands-only when:** a Step 6 stop-condition fired · the user said "don't commit yet" · planned writes overlap files with pre-existing unstaged modifications (committing would bundle unrelated work — a project with dozens of pre-existing dirty pages is the canonical case) · project convention says PR-flow or never-auto-commit (multi-dev repos commonly route handoff changes through PRs — follow the project's CLAUDE.md, including its branch-naming for `<dev>/handoff-refresh-<date>` branches).

**Never `git push` — a push requires a QUOTABLE authorization.** Push timing is user-controlled everywhere. A wrap may push only when the wrap report can quote the authorization verbatim, from exactly one of three sources: **(1)** the user's own words this session ("and push", "push it", "wrap and ship"); **(2)** the user invoking a push-by-design command (e.g. `/device-handoff` — the push is its purpose); **(3)** a documented standing exemption — `.claude/lifecycle-direct-push.flag` or a CLAUDE.md `## Lifecycle direct-push exemption` section — then HANDOFF + wiki (only those) land on main via the stash → checkout main → pull --ff-only → commit → push → restore sequence. No quotable source → no push (and per the visibility line above, no "want me to push?" either). **A "do not push" vetoes all three sources, the standing exemption included, until the user explicitly lifts it — and it binds in two forms, both of which the pre-push check reads:** stated this session (by the user, or by an external review gate the user has adopted), or recorded as a durable hold in the project's CLAUDE.md / handoff (a `push-hold` marker or `## Push hold` section — where a hold meant to outlive the session belongs, because conversation memory does not survive a resume or machine switch; a recorded hold you can no longer quote from the live conversation still binds). (A session audit caught unprompted wrap-pushes — one over an explicit external-review "do not push" gate.)

## Refuse / scope down

- **No substantive signal** (pure Q&A, no diffs, no decisions) → "I don't see substantive changes to persist — did something happen I should record?"
- **Mid-crisis** → don't fire while the user is actively debugging; wait for a "done" signal.
- **Conversation suggests Bash-side-effect files exist but triage hasn't run** → refuse to proceed to writes until it has.

**Wrap-completeness calibration — the missed-wrap and double-wrap boundaries (both are confirmed field failures, 2026-07-04 audit):**

- **Missed wrap:** substantive work + a session-ending signal ("that's it for today", "heading out", a machine-switch announcement) and no wrap invoked → offer it in ONE line ("Substantive work this session — wrap before you go?") rather than letting the session end silently. One missed wrap on real work cost a 3-day forensic recovery; the offer costs a line. Offer, never auto-fire — the user may be ending abruptly on purpose.
- **Double wrap:** before firing *proactively*, check whether this session already produced a wrap commit — detect by **content, not message string**: any commit since session start (any branch, including a `<dev>/handoff-refresh-*` PR branch) touching the paths this skill's Step 4 writes (`git log --oneline --all --since="<session start>" -- HANDOFF*.md` plus the project's wiki/log, memory-mirror, and docket paths). A message grep ("Session update:") misses PR-flow projects' own commit conventions. One exists → a second proactive wrap needs NEW substantive work landed since that commit, and mid-task is never wrap time regardless (a proactive mid-task double-wrap is a confirmed failure mode, not thoroughness). A user-invoked re-wrap always proceeds — invocation is authorization — scoped to the delta since the last wrap commit.

## Fail modes (one line each)

| Trap | Counter |
|---|---|
| "My HANDOFF entry mentions X, so X is preserved" | Mention ≠ commit. Only committed data persists. |
| Audit artifact built from memory of edits | Build it from porcelain. Bash side effects don't appear in Edit/Write history. |
| "That file LOOKS gitignored" | The triage list is already ignore-filtered by git; a listed file is not ignored. |
| Skipping rotation "to keep the diff small" | Skipped rotation is how 75KB headers and 92%-history wikis happened. THRESHOLD = this run. |
| Prepending a pickup point without archiving old ones | Growth without rotation = unbounded wiki. |
| Recording a negative-availability claim from a web search | Grep repo + local dirs first; "not public" ≠ "not available". |
| Writing memory about other projects / meta-observations | Memory scopes to this project; the load-bearing test gates entry. |
| Editing another dev's per-dev file or prior entries | One writer per file; append-only; corrections reference. |
| Speculative wrap ("fixes queued for next session") | Wrap records what verifiably happened, not narrative intention. |
| "Wrap complete" with unclassified tree paths | The cleanliness assertion is the gate; re-triage. |
| Pushing at wrap "to be helpful" / "while we're at it" | A push needs a quotable in-session authorization; an in-session "do not push" vetoes even the standing exemption. |
| "Nothing pushed" / "ahead N" written as bare fact | Perishable prose falsifies on the next push. Anchor it ("after this wrap", "at `<sha>`") or name the deriving command. |
| Session ends with real work and no wrap | Offer the one-line wrap on any session-ending signal — a missed wrap is a forensic recovery later. |
| Proactive second wrap mid-task | Check for a same-session wrap commit first; re-wrap only on new substantive work, never mid-task. |
| Newer status appended above a stale block | The `== COHERENCE ==` check flags a resolved ID in a forward section / a duplicated ready signal / a carried count; rewrite the section, don't append. |

## Related

- **`analyze-context`** — session-start read-side. This skill's rotation discipline is what keeps that skill affordable.
- **`analyze-handoff`** — slim resumption; only works if the HANDOFF header stays current and slim — another reason header accretion is forbidden.
