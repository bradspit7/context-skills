---
name: analyze-context
description: Use at the START of a session in a project with a context layer (HANDOFF.md, CONTEXT.md, continuation/, or per-dev HANDOFF-<name>.md files). Fires on "catch me up", "brief me", "what's the state", "what were we working on", "where did we leave off", "analyze the context", "read the context files", or the first substantive message after a multi-day gap, a machine switch, or in a multi-developer repo. Read-only. For same-day resumption on the same machine, route to the slim sibling analyze-handoff instead.
---

# Analyze Context

Session-start skill: **verify the persistence layer is current, read it at the right depth, synthesize a briefing.** The read-side complement to `update-context`.

Two laws, in priority order:

1. **Currency before content.** Never synthesize from files you haven't verified are the newest copy. Worktrees, sibling branches, other machines, and other developers can all hold newer state — every historical staleness incident traces to skipping or demoting this check.
2. **Full reads, never skims — delegated when heavy.** Lifecycle docs are read top-to-bottom. When the read set is large, the full read happens *inside subagents* that report back structured extracts — cost is controlled by delegation, never by dropping files.

If the project's own CLAUDE.md specifies a session-start protocol or a project-local analyze-context variant, that wins — this is the general version.

## When to fire / not fire

Fire on the trigger phrases above, or proactively when the first substantive message of a session lands in a project with a context layer and the user hasn't given a concrete task.

Do NOT fire when:
- The user immediately gives a concrete task (they want work, not a briefing)
- Mid-session narrow questions
- Same-day continuation on the same machine → route to `analyze-handoff` (~5K tokens vs this skill's full run). Already inside this skill (user typed `/analyze-context` by habit)? Don't abort — Step 1's `RESUME CLASS` signal downgrades the run to the slim path mechanically.
- No context layer exists → say so, offer to scaffold via `update-context`

## Step 1 — Currency gate (before reading ANY content file)

Run the bundled script from the project root (Bash tool; works on Windows git-bash and macOS):

```bash
bash ~/.claude/skills/analyze-context/scripts/currency-check.sh
```

One run replaces the old Step 0 + Step 1.5 + pre-briefing checkpoint. It reports: machine identity, pattern markers, fetch + new remote branches, newer sibling worktrees, unpulled upstream, a branch survey (10 most recent refs ∪ last-24h refs) comparing the handoff doc's blob hash, all-refs handoff commits from the last 7 days with HEAD-reachability, lag (days + commits since the doc was last touched), header stamps, and the out-of-repo memory path (with a linked-worktree warning when memory must key off the main checkout).

**Handling the output:**
- **Any `FINDING` line → STOP and ask the user which source is authoritative.** Never auto-switch sources. Never demote a finding to the briefing's "Known issues" section — that demotion is itself the historical failure mode. Synthesis blocks until resolved.
- **Clean → proceed silently.** Note the machine + lag values for the briefing header.
- **`SAME-DAY RESUME CANDIDATE` (RESUME CLASS section) + zero FINDINGs → take the slim path.** Unless the user explicitly asked for a full briefing ("catch me up", "brief me", "what's the state") or their message implies new scope: read the primary doc fully and deliver `analyze-handoff`'s 3-line summary (last completed / next intended / blocker) **plus the docket** (open items by ID, one line each, preserving each row's status marker so a parked/deprioritized row is never shown as actionable; skip only rows moved to the handoff's Resolved/✅ section; source it from the doc's own next-tasks/open-items section — or the separate docket file the handoff points to, if any) with a one-line "full briefing on request" offer — do NOT run Steps 2–4's deep reads. This in-skill downgrade IS the analyze-context↔analyze-handoff routing; invocation-time routing measurably never happens (2026-07-04 audit: 0 slim-path uses in 204 sessions while 20+ same-day resumes paid the full read). A `FULL BRIEFING` class, any FINDING, or an explicit full-picture request proceeds normally — the class line's stated reasons say which.
- **Re-run gate:** any `git switch` / `checkout` / `pull` / `reset` / worktree change between now and the briefing invalidates the pass — re-run the script. Findings from the old source do not transfer to the new one.
- **Header stamps are advisory, never proof.** `Updated:` / `wave-N` headers say when *that paragraph* was written, not whether a newer one exists elsewhere. Reachability of recent doc commits from HEAD (the script's RECENT section) is the only currency proof. Catching yourself thinking "the header says wave-41, so we're on wave-41" means the trap is firing.
- **Hook/feed signals are a separate channel.** A SessionStart hook reporting "no new feed entries" says nothing about HANDOFF.md commits. Never substitute one channel for the other.
- **Merged-looking branches still count.** A branch whose PR was squash-merged can keep receiving commits afterward (post-merge resurrection); the survey compares doc hashes regardless of merge status — trust it over the "that branch is done" intuition.
- **No-git projects:** the script falls back to file mtimes. Doc >7 days old → flag staleness in the briefing header; in-content dates become the staleness evidence.

If `~/.claude/skills/analyze-context/scripts/currency-check.sh` is missing (partial install — don't confuse it with a project-level `scripts/` dir), run the essentials inline: `hostname`; `git fetch --all` (watch for `[new branch]`); `git worktree list`; `git for-each-ref --sort=-committerdate refs/heads refs/remotes --format='%(refname:short) %(committerdate:iso)' | head -15`; `git log --all --since='7 days ago' --format='%h %ai %s' -- HANDOFF.md` and check each hash with `git merge-base --is-ancestor <sha> HEAD`.

## Step 2 — Detect the pattern

| Pattern | Markers | Primary doc |
|---|---|---|
| **multi-dev** | `HANDOFF-<name>.md` files and/or `coordination/` dir | slim shared `HANDOFF.md` (team contract) + your own `HANDOFF-<dev>.md` (narrative) |
| **monolithic-handoff** | `HANDOFF.md` only (doubles as wiki + bridge) | `HANDOFF.md` |
| **running-log** | `continuation/` dir | `HANDOFF.md` (snapshot) + `continuation/context.md` (wiki) |
| **CONTEXT-style** | `CONTEXT.md` + `context/` dir | same as running-log; substitute filenames (docket may be `<topic>_docket.md`) |
| **hub / no-git** | context files but no `.git` | as detected; staleness via mtimes |
| **hybrid** | multiple of the above | ask the user which is primary |
| **none** | — | "No context layer found. Recent activity: <git summary>. Scaffold one?" |

`HANDOFF.md` may live at root or in `context/` — check both. **Multi-dev adds an identity check:** resolve the developer via `gh api user --jq .login` mapped through the project's CLAUDE.md identity table; fall back to `git config user.name`; if still ambiguous, ask. The identity picks which `HANDOFF-<dev>.md` is *yours*.

## Step 3 — Core read (direct, main thread)

Read these yourself, in parallel where possible:

1. Project `CLAUDE.md` — rules, conventions, session protocol. (Grepping it earlier for the multi-dev identity table is fine — that's a lookup, not a synthesis read.)
2. The handoff doc(s) — `HANDOFF.md`; in multi-dev also your own `HANDOFF-<dev>.md`
3. Memory index `MEMORY.md` — **the full text of every entry, not just first sentences.** Index entries on mature projects carry inline `UPDATE`/`As of <date>` patches that supersede the linked file's body.
4. Docket/roadmap — `roadmap.md` / `*_docket.md` / `INDEX.md`
5. Latest decision doc (`docs/**/decisions/`, newest) — **in full, not via the HANDOFF's one-line summary of it.** Grounding references (datasets, extracts, research) live in the doc body and the HANDOFF one-liner routinely drops them. No decisions dir → skip; note nothing.
6. Multi-dev: your own per-dev file's newest entry FIRST (it dates your last session), then `coordination/feed.md` entries newer than that date (or the project's feed cursor). Feeds and per-dev logs are append-only: for session purposes, **entries since your last session ARE the full read**; older entries are tier-3 history, not skipped content.

**Protected workflow docs — read them fully BEFORE assuming the pipeline shape.** Any root file matching `*WORKFLOW*` / `*PIPELINE*` / `*RUNBOOK*` / `*PLAYBOOK*.md` is the canonical description of how the project's process actually runs, and it routinely supersedes an older flow sketched in the HANDOFF or README. Read each such doc top-to-bottom before you state (or act on) the pipeline in the briefing — inferring the shape from the handoff summary is how a stale or superseded flow gets asserted as current. If one carries a LOCKED / DO-NOT-EDIT section, treat that section as canon, not as prose to paraphrase past.

**Size valve — core docs are read fully when ≤ ~40KB.** A core doc over ~40KB (a bloated docket, a 400KB per-dev narrative, an accreted HANDOFF) gets a split read: read its *current-state* portion directly (header, newest entries back to your last session, open-item/priority sections, contract tables) and push the remainder into Step 4's delegated set so coverage still happens — via extracts, not silence. An oversized core doc is also a finding in its own right: surface "rotation overdue — update-context should trim this" in the briefing's Known issues.

## Step 4 — Depth read (direct or delegated)

Compute the remaining read set, per pattern:
- **running-log / CONTEXT-style:** the wiki doc (`continuation/context.md` / `CONTEXT.md`) + in-scope memory topic files + active specs/plans
- **monolithic:** in-scope memory topic files + active specs/plans (+ any oversized-core remainder from Step 3)
- **multi-dev:** other devs' **newest 1-2 entries each** (scan for cross-lane context — never their full histories), active specs/plans (check the dirs the project CLAUDE.md names; planning often migrates, e.g. `docs/superpowers/plans/`), in-scope memory topic files, oversized-core remainders

"Active" specs/plans = work the docket/handoff still shows open. **Specs whose work shipped are tier-3, not "dropped"** — tier-classification with a stated reason satisfies Law 2; silently omitting an active doc violates it. When the user gave no task, in-scope = whatever the handoff's next-step entry point implies.

Check total size (`wc -c`), then:

- **< ~60KB → read directly**, in parallel. **Chunk rule: whenever a Read returns a truncated/partial view (line-capped OR token-capped — the tool reports where it stopped), continue from the reported offset until EOF.** *"Reading just the top entry since the pickup point is at the top"* is the #1 historical failure mode, and that announcement IS the violation.
- **≥ ~60KB → delegate.** Dispatch parallel read-only subagents (Explore type), each assigned a slice of the read set, with this contract in the prompt:
  - Read every assigned file **fully**, chunking past every truncation; never sparse-search.
  - Return a structured extract: current-state claims (with dates), locked decisions, open items/blockers, gotchas/rules relevant to upcoming work, contradictions against the HANDOFF summary you supply in the prompt.
  - Include **verification quotes**: one short verbatim quote from the top, middle, and bottom third of each assigned file, with line numbers.
  Synthesize from the extracts. An extract missing its bottom-third quote means the file wasn't fully read — re-dispatch. This keeps a 200K-token corpus out of the main context (~15-25K after delegation) without re-enabling the skim failure.
- **No subagent support available** (rare) → direct reads in descending relevance order; if ingest approaches ~100KB, stop, and **list what was deferred and why in the briefing's Known issues** — explicit deferral the user can override, never silent omission.

**Search first, then read the hits.** Before hand-walking the memory index, run `/memory-search` (and `/recall` where available) on the topics the context layer surfaced — the entry point in the handoff, the open docket items, any subsystem the next step touches — and open only the few load-bearing hits it returns. The index eyeball is the fallback for what search can't phrase, not the default: an index of 50+ files is exactly where keyword search earns its keep. If the search index is stale or unavailable, degrade to reading the index and the in-scope files directly — a zero-hit search over a stale index proves nothing, so never treat it as "no memory on this."

**Memory navigation** (both modes) — precedence order when signals conflict: **(1) MEMORY.md section assignment** ("top of stack" / "read first" / domain sections — the index always wins) → **(2) priority markers** (⚡/⚡⚡/🔴 are must-reads in their domain) → **(3) prefix heuristics**: `domain_*`/`scope_*` non-negotiable for in-scope content work; `feedback_*` if applicable; `research_*` newest-dated only *unless the index pins an older one*; `memory_*` verdicts are locked decisions. Follow sibling cross-references transitively. Don't read every file every session — but an index of 50+ files producing zero reads means the heuristic is broken.

**Tier-3 (on demand only):** archives, historical pickup points, feed/log entries older than your last session, shipped specs, older decisions, README. Reading them to "feel thorough" wastes tokens and dilutes the briefing.

## Step 4.5 — Verify from live source, then refute the reading

Step 1 proved you have the newest *files*. This step proves the briefing's *claims* are true. It runs after the reads and before the briefing; skip it on the slim path (a `SAME-DAY RESUME CANDIDATE` run — the 3-line summary makes no current-state assertions worth re-deriving).

**Live-source verify pass.** Memory files and handoff prose age; a current-state claim the briefing is about to assert can silently be stale. For any such claim that could have drifted, re-derive it from live source before asserting it — pick the probe by claim type:

| Claim type | Live source to probe |
|---|---|
| running processes / a service is "up" | `ps` / the platform's process or job list (`launchctl list`, `systemctl`, Task Manager) |
| commit / branch / ahead-behind counts | `git log` / `git status` / `git rev-list --count` — not the header stamp |
| config values, flags, thresholds | the actual config file on disk, read now |
| test / file / row counts | run the count command; don't quote the handoff's number |
| balances, positions, prices, external state | the live state file or API, not a memory note |

If the project's CLAUDE.md declares session-start or liveness probes, run those verbatim — declared probes beat guessed equivalents. When a memory file and the live probe disagree, the briefing reports the **live** state and flags the stale source; never silently trust either. Trust order for surfacing a conflict (surface, never auto-pick): **live > git > recent memory > older memory > older HANDOFF > wiki.**

**Refutation cross-check.** The currency gate checks *sources*; nothing yet checks the *synthesis*. Before delivering a non-trivial briefing, hand the draft's **claims only** — one-line status, in-flight items, the counts/branch/process facts, the next-step pointer, never your reasoning or source list — to one independent re-derivation and get back, per claim, `AGREE / DISAGREE (evidence) / UNVERIFIABLE (what's missing)`. Where subagents are available, dispatch one read-only Explore agent carrying the claims; otherwise re-probe each claim yourself in a distinct second pass. A `DISAGREE` resolves per the trust order above **before** delivery; anything unresolved or `UNVERIFIABLE` ships only under the briefing's "Known issues / blockers" as a flagged mismatch, never silently in the body. A cross-check that errors, times out, or skips claims does not waive the check — re-probe those claims yourself before delivery. **Fire it when** the briefing is multi-workstream, any staleness NOTE survived Step 1, a memory file supplied a current-state claim, or the project is money-adjacent; **skip it** for a trivial briefing (and on the slim path, which never reaches this step). This verifies the reading — it never replaces Step 1 or the live probes above.

## Step 5 — The briefing

Mandatory header, from Step 1's verified values — never from header stamps:

```markdown
## <Project> — current state
**Machine:** <name> · **HANDOFF:** updated <date> (<N> days, <M> commits behind HEAD) · **Currency:** verified clean | FINDINGS resolved: <how>
```

Then synthesize — a mental model, not a regurgitation:

```markdown
**One-line status:** <active phase/goal>

### Recently shipped (last 1-2 sessions)
### In flight / work-in-progress
### Locked decisions (DO NOT reopen)
### Empirical foundation  ← only when the design rests on external/extracted data:
    what dataset/extract grounds it, where it lives (in-repo path + local extract dir), one line on how to query it
### Open docket — next candidates (open items by `G#` ID + source pointer)
### Known issues / blockers
### Behavioral rules in force (the 3-8 memory rules relevant to likely next work, linked)
### Next step suggestion (usually the handoff's "next session entry point"; note if the user's first message points elsewhere)
```

**Surface open goals by their `G#` ID** where the docket uses them, so the resumer can reference a goal by stable ID across sessions; a docket on a legacy bare-`#N` system is shown as-is.

Multi-dev briefings add: open PRs by author, lane allocation, and unanswered feed entries.

**Sizing is structural, not numeric.** Clean docket ≈ 200-300 words; complex multi-workstream state may need 600-800. Compress, link instead of copying, scope to what the resumer needs first. "Short" is not a virtue if it drops real state; a padded-thin briefing that hid half the in-flight items is the actual failure.

## Step 6 — Stop. The user drives.

Deliver the briefing, then wait. Drill-downs, redirects, and "continue with next step" are all user calls.

**Dispute rules — in order:**
1. **User contests current-state or next-step ("we moved past this", "that's not where we are")** → re-run the Step 1 script FIRST. Currency drift the gate missed is the most common cause of a wrong briefing — not a missing file. Static-file deepening comes second.
2. **User questions a source/approach choice ("why are you using X?") — especially twice** → search for the alternative they're implying exists (`grep -ri` the repo, check README-cited local extract dirs, read the decision doc in full) BEFORE defending the choice. A web search answering "not public" never proves "not available locally" — private extracts and committed-but-unindexed files don't surface online.

## Fail modes (one line each — all are live traps)

| Trap | Counter |
|---|---|
| "File too large, reading just the top" | That sentence is the violation. Chunk-read, delegate, or split per the size valve — silent truncation is never sanctioned. |
| Oversized core doc treated as normal | A 100KB+ HANDOFF/docket is a rotation failure — split-read it AND flag "rotation overdue" in Known issues. |
| HANDOFF cites commits absent from `git log` | Authored in another worktree/branch. STOP, re-run Step 1, ask. |
| Findings demoted to "Known issues" FYI | Findings block synthesis. Pre-briefing resolution only. |
| Trusting `Updated:`/wave headers as currency | Headers date the paragraph, not the project. Reachability is proof. |
| Feed/hook silence read as HANDOFF silence | Independent channels; check both. |
| "That branch was merged, skip it" | Post-merge commits happen. The hash survey decides, not the intuition. |
| HANDOFF contradicts git/memory/wiki | Flag the contradiction in the briefing; default trust order live > git > recent memory > older memory > older HANDOFF > wiki, but surface, don't silently pick. |
| System date contradicts file/commit dates | Anchor on file/git evidence, flag the discrepancy explicitly. |
| Briefing = pasted file contents | Synthesis is the product. If you can't state the next concrete move, you didn't synthesize. |
| Claiming "no context" without checking root AND `context/` AND `continuation/` | The files exist; you skipped them. |
| Applying another project's memory rules | Memory is scoped to the detected project's memory dir. |
| Inventing decisions thin files don't support | Say the section is thin instead. |

## Do NOT

- Write anything — read-only skill; writes are `update-context`'s job
- Invoke `update-context` in the same action — lifecycle bookends, not a compound
- Skip files "for token efficiency" — delegate instead
- Read other devs' per-dev files in depth by default (multi-dev) — scan for cross-lane context only

## Related

- **`analyze-handoff`** — slim sibling: same-day resumption, reads only the handoff doc, 3-line summary. Escalates to `device-sync` on machine switch (arrival pull + memory sync first, then this skill); here on >24h gap or any cross-branch signal.
- **`update-context`** — session-end write-side. Keeps this skill's read cost low via rotation + hygiene; the leaner the layer, the cheaper every session start.
