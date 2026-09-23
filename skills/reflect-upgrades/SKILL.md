---
name: reflect-upgrades
description: Use after substantial work or a real finding to decide where each lesson should act - reuse an existing tool, fix the code, add a check the project already runs, a shared guard, a path rule, a skill step or a note - and to build one per wrap. Fires on "did we learn anything that would help build or upgrade our tools", "reflect on upgrades", "/reflect-upgrades", at every update-context wrap, or proactively when a session produced durable learnings. A lesson stays in its own project unless it is a platform trap, a verified second bite, a fix to a shared artifact, or catastrophic-if-wrong.
---

<!-- canonical: ~/.claude/skills/reflect-upgrades/SKILL.md · version: 2026-09-23.1 -->
<!-- Version-stamped so cross-estate reconciliations diff against a stamp, not archaeology.
     Bump the date-tag on any substantive edit; a fork adds its own provenance line here. -->

# Reflect-upgrades — put each lesson where it can act

The question worth asking by hand every session: *did we learn anything that should change our
tools?* This skill answers it **by changing them**, not by writing a row about them. It runs three
ways: `update-context` invokes it at every wrap (the only automatic path, and the only one that
builds), the bundled `upgrade-reflection-nudge` hook suggests it mid-session after substantial work
(see *Companion hook*), and the user can invoke it by name.

**Every surviving lesson ends in exactly one outcome:** `reused` (an existing tool already does it),
`built` (this wrap's one build), `queued` (this project's `UPGRADE-QUEUE.md`), `filed-central` (a
committed inbox lesson, routes a-d below), `noted` (a project memory note — owner rulings and
preferences), `strengthened-existing` / `dedup-existing` (it is already somewhere), or `zero`.
"Surfaced in chat" is not an outcome: chat scrolls away.

## When to fire / not fire

Fire when the session produced substantive work — edits, commits, a debugged gotcha, a manual step
done more than once, friction hit more than once. Do NOT fire on pure Q&A or trivial sessions; return
the empty verdict rather than manufacturing lessons.

## Step 1 — Gather the session signal

List what the session actually produced: shipped artifacts, decisions, debugged gotchas, repeated
manual sequences, friction hit more than once, memory files written. If `update-context` already
computed shipped / learned / decided / deferred, reuse it.

The signal is **reactive**: what the session *hit*. That is two kinds of evidence — a **failure** it
ran into, and **work it repeated** (a sequence run twice by hand, the same fix applied across sites, a
check re-derived because nothing invokes it). A repeat needs no failure incident: say the count out
loud ("ran this 3x by hand this session"), because that number is the justification. A capability the
project ought to have but never needed here is the generative question — `/opportunity-scan`'s job,
not this one.

**Reasoning misses** (a blind spot, a wrong reading you corrected, an assumption that bit) are their
own stream: append one dated, transcript-verifiable line to the self-audit log in your central
upgrades repo (`SELF-AUDIT.md` at its root; create it on first use) with its two tags — `incident:`
(was this occurrence corrected?) and `system:` (`unmitigated` / `candidate-filed(<ref>)` /
`guard-deployed` / `recurrence-seen(<prior-date>; <ref>)`). Run the Step 2 search on the miss's
mechanism **before** appending: a hit on an entry already at `guard-deployed` means the guard failed —
the new entry ends `system: recurrence-seen(...)` and the recurrence is recorded (Step 6); a hit at
`candidate-filed` or `unmitigated` makes the new entry a recurrence of that one, strengthening it. The
log is append-only; never edit a prior entry.

## Step 2 — Look it up first: reuse, then de-dup

One pass per lesson, **before** designing anything:

```bash
python ~/.claude/skills/reflect-upgrades/scripts/capability-index.py query "<what the fix would do>"
python ~/.claude/skills/analyze-context/scripts/docket_corpus.py search -i '<term1>|<term2>' --scope all
```

- **Capability first, by what it does — never by filename.** The same capability has been built twice
  under two names by projects that did not know about each other; a same-name check found neither. A
  live hit that already does the job → **rung 0: adopt or port it** (outcome `reused`). A hit that is
  a sibling copy of the tool you are about to fix → the fix goes to its shared owner, once.
- **Then the corpus, by 2-3 terms naming the failure mechanism.** The helper searches every project's
  real docket files (including split-out row-body files, archives, pending `DOCKET-INBOX-*.md` filings
  and the self-audit log) and prints its denominator. A hit → `strengthened-existing` or
  `dedup-existing`: record the occurrence against the existing entry (a new date, project or wording
  does not make a new upgrade). A central hit is recorded from any project through the outcome record
  (Step 6), **never by editing the central docket or another session's pending inbox file** — that is
  the uncommitted-edit-to-a-live-central-doc class. A project hit is recorded in that project's own
  docket.

## Step 3 — Filter (the anti-noise gate)

1. **Load-bearing test — name all five, or it is an observation, not a lesson:** **current behaviour**
   (what happens today), **implementation target** (the file that changes), **expected improvement**
   (a step removed, a failure detected, a capability gained), **recurring cost** (context bytes, hook
   latency, maintenance — text loaded into every session of every project is the most expensive shape
   there is), and a **concrete acceptance check** (what you would run to see it work). *"A future
   session would act differently"* is necessary, never sufficient: reading one more rule qualifies and
   improves nothing. **The five fields are the build spec** — target = the file, acceptance check = the
   RED condition, current behaviour = the incident command and output.
2. **Target project alive** — a lesson whose remedy targets a discontinued project is dead work (check
   wherever you track project lifecycle status, if you do). Its platform kernel, if any, still routes
   (a).

## Step 4 — Pick the rung, then the route

**The ladder — first match wins:**

| Rung | Home | Use when |
|---|---|---|
| 0 | **Reuse** | Step 2 found something that already does it: a project's own script or test, a sibling's copy, the catalog, an installed skill |
| 1 | **Fix the code** | the defect lives in code this project owns |
| 2 | **A check the project already runs** | its tests / pre-commit / ship-check — enrolled so it actually executes (a network check cannot be a pre-commit gate; hook it to an `analyze-context`/`update-context` step keyed on project state instead) |
| 3 | **A shared guard hook** | an OS / shell / git / harness trap any project can hit |
| 4 | **A path rule** | `.claude/rules/*.md` with `paths:` — a file-type authoring rule that should load only when a matching file is read |
| 5 | **A step in a skill that measurably fires** | only `update-context`, `analyze-context`, `receiving-code-review`; or code/constants inside a Workflow runnable (never prose in `orchestrate`) |
| 6 | **A project memory note** | owner rulings and preferences; a technical lesson only as a holding pen that names its queued build item |
| 7 | **One line in the always-loaded core** | only behaviour that must fire everywhere with no trigger, and only through the bar below |
| 8 | **Reference** | searchable, never auto-loaded: incidents and worked examples |

**The route — a lesson stays in its project unless:** (a) it is a **platform / OS / harness trap**;
(b) a **second project** has the same mechanism — a **verified** row, checked with
`docket_corpus.py state <project> <id>` (it must not return `absent`), never a self-declared claim;
(c) the fix **edits a shared artifact** — a shared skill, hook, runnable, catalog entry or shared-toolkit
script; or (d) it is **catastrophic-if-wrong** (live external writes, regulated personal data such as
health records, credentials, pushes/deploys, data destruction) → shared on the **first** bite, written
at mechanism level only, with no incident detail.

**Route by the ownership of the remedy, not by what the incident touched.** Having *used* a shared skill
while hitting a problem does not make the remedy shared; a fix confined to this project's own code,
checks or instructions stays here. A fix that genuinely edits a shared artifact is route (c) even when
one project has felt it. Split into two lessons only when an independent project-local change also
exists.

**The global-rulebook bar.** Rung 7 — or any lesson whose target is the global `CLAUDE.md` /
`AGENTS.md` — needs one of two gates, named in the lesson: **second bite** (route b, verified) or
**structurally unscopeable** (a platform/toolchain/harness property no project can own; name the
layer). A once-measured kernel is not wrong — it belongs where one data point lives, with a
`promote-on: second bite` note. Enforce the bar mechanically where you can — at filing and again at
ingest — rather than by re-reading this paragraph.

**Central lessons (routes a-d) are filed as a new committed inbox file** at your central upgrades
repo's root (`DOCKET-INBOX-<date>-<project>.md`), never an uncommitted edit to a live central doc.
If the central repo is ever open in more than one session at a time, file through an **atomic
filer**: build the commit in a *temporary* index rather than the shared one (`git read-tree` →
`git update-index --add` the single file → `git write-tree` → `git commit-tree` → a compare-and-swap
`git update-ref`). That is sweep-immune in both directions, lands on the branch you name regardless
of what is checked out, and retries a concurrent tip move instead of losing it; plain `git add` plus
a pathspec `git commit -- <file>` of the one file is the fallback. The filer should refuse a lesson
without valid front matter:

```markdown
---
origin_project: <this project>
route: <a|b|c|d>
second_bite: <other project>:<row id>
mechanism: <one line naming the failure mechanism>
target: <the file or tool that would change>
---
<the lesson: the five fields from Step 3; for route d, mechanism only>
```

`second_bite` is required for route b and omitted otherwise.

Show the receipt (path + short sha): "filed" means a quotable commit. The next central session
processes the inbox under these same rules — builds it, queues it, or hands it back.

**Project lessons that do not fit this wrap's build go to the project's `UPGRADE-QUEUE.md`** at its
root: one `## YYYY-MM-DD · <title>` heading per item (oldest first), then `- **Lesson:**`,
`- **Target:**`, `- **RED:**`, `- **Source:**` bullets. **Cap 5.** A full queue shows as one briefing
line; it is never a question for the owner.

## Step 5 — Build one (wrap layer only)

`update-context` runs this step at every wrap; nudge and manual firings stop at Step 4 (queue or file)
and the next wrap builds. **Exactly one build per wrap:** the best new lesson on rungs 1-5 that fits
one wrap, else the **oldest** queued item, else nothing.

1. **Look again before building** — if the build edits a hook or script, query the capability index
   for other copies of it. Shared logic lives once; project differences live in per-project config;
   a fix to a shared tool goes to its shared owner.
2. **Write the spec on the main thread:** the incident command and output, the target file, the RED
   condition (Step 3's five fields).
3. **Hand it to a fresh small-context helper** (the Agent tool with worktree isolation, an agent type
   that has a shell) that builds the check in its own worktree **outside the project root** and returns
   the diff plus RED and GREEN evidence. The wrap's own context is too large to build in.
4. **Apply it on the main thread, run the test once, and commit** with a trailer:
   `git add <paths>` then `git commit -m "<subject>" -m "Upgrade: <one plain sentence>" -- <paths>`.
   The trailer is the record: a ledger can derive *built* from it, in the repo where it landed.
5. **Too big for one wrap** → queue it (cap 5).
6. **Projects with live external writes or regulated personal data:** the build may only add tests
   that import no write client, and must not touch the project's sensitive-data/secret guard, its git
   hooks, its harness settings, its config/override files or its live runners (the project's own
   `CLAUDE.md` names them). The RED proof uses an in-memory mutant or a synthetic fixture with the live
   gate forced off. The full suite must be green and the project's own reviewer must pass before the
   commit.
7. **Central lessons** are built by the next central session's wrap, oldest first, on a branch in a
   central worktree; `main` is fast-forwarded only when the shared checkout is clean and no other
   central session is live.

**Done means adopted, not built.** An upgrade moves **filed → built → adopted → observed**. *Built*:
the artifact exists with a RED/GREEN proof. *Adopted*: the project reaches it through its normal work
path — a hook, the runner, a lifecycle step — and it has run that way at least once. *Observed*: a later
session recorded it catching, removing or preventing something. **The owner-facing test:** start from
an ordinary request; if anyone has to name the upgrade or remember its command for the benefit to
appear, it is not adopted. The wrap records adoption in the handoff, not just the build.

## Step 6 — Report and record

One row per lesson:
`rung <0-8> | route <local|a|b|c|d> | <one-line what> | <evidence from this session> | <honesty-label> | <outcome>`

**Honesty labels are mandatory:** `proven-need` (this session hit it), `solid-extension` (real value,
no forcing incident), `speculative` (plausible, unproven). A session realistically yields 0-2 lessons;
at most one `speculative`, and 3+ rows means the load-bearing filter failed — re-run Step 3. Nothing
survives → one line: "No tooling upgrades warranted this session." That is a common, valid result.

**Record the verdict, whatever it is.** The *record* is required; *where* you keep it is yours — a log
line, a docket entry, your own tracking tool. Capture these fields:

```text
layer:     nudge | wrap | manual
status:    built | queued | reused | noted | filed-central | filed-project | filed-catalog |
           strengthened-existing | dedup-existing | zero | other
candidate: <ref>@<central|project|catalog>[,...]   (- when none)
reason:    <short>            (required when status is zero or other)
session:   <uuid>            (when the session id is visible)
```

`status` is the strongest outcome; list every ref, each tagged with where it **actually** landed
(`-` when none); `reason` is required for `zero`/`other`. `layer` is `wrap` from update-context,
`nudge` when prompted by `[upgrade-reflection]`, `manual` otherwise. If you keep the companion
`upgrade-ledger` machinery, that is `upgrade-ledger.py record --layer ... --status ... --candidate
"..." --reason "..." [--session <uuid>]`. A later **catch** or **recurrence** is an event, with a
repo-qualified id and an explicit owner (`upgrade-ledger.py event --candidate <project>:<id> --owner
<project> --event <confirmed|observed> --evidence-ref <where> --note "<what ran and what it caught>"`).
If you cannot record it in the moment, say so in the report — never silently skip.

**Never drop a surviving lesson.** Each named non-reason licensed a real near-drop: *"the docket is on
rotation-hold"* (a hold blocks structural rotation, never a queue line or an inbox filing); *"keep the
wrap diff small"*; *"context is high, wrap fast"*. Catching an unrecorded lesson in your own report
means going back and recording it before finishing — the user should never have to say "file it".

## Do NOT
- Build more than one upgrade per wrap, build on the main thread, or build from a nudge or manual firing.
- Edit a live-write project's forbidden files (Step 5 item 6).
- Manufacture lessons to seem productive — Step 3 is the gate.
- Emit an unlabeled row, or re-propose something Step 2 found.
- Convert a lesson into an offer ("say the word and I'll queue it") — record it, then report.

## Companion hook

`hooks/upgrade-reflection-nudge.py` is a `UserPromptSubmit` hook that suggests this reflection
mid-session: once per session, after a substantial-work signal (>= N file edits, a memory-file
write, or a `git commit`), it injects a one-line non-blocking nudge to run this skill. Wire it in
`~/.claude/settings.json` under `UserPromptSubmit` (env tunables: `UPGRADE_NUDGE_EDIT_THRESHOLD`
default 3; `UPGRADE_NUDGE_DISABLE=1` to silence). Pure stdlib, ASCII-only, fails open.

## Related
- `update-context` — invokes this at every wrap and runs Step 5; its shipped / learned / decided signal
  feeds Step 1.
- `hooks/upgrade-reflection-nudge.py` — the once-per-session `UserPromptSubmit` nudge (above).
- `analyze-context` — prints each project's pending inbox filings, upgrade queue and recent `Upgrade:`
  trailers in every briefing, so nothing here waits on anyone remembering it.
- `SELF-AUDIT.md` (central upgrades repo root) — the own-miss stream (Step 1).
- `/opportunity-scan` (ships in this repo's `project-scans/`) — the generative counterpart:
  capabilities a project should have but has never been hurt for lacking.
