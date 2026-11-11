---
name: reflect-upgrades
description: Use after substantial work or a real finding to decide where each lesson should act - reuse an existing tool, fix the code, add a check the project already runs, a shared guard, a path rule, a skill step or a note - and to build one per session, early (never at a wrap). Fires on "did we learn anything that would help build or upgrade our tools", "reflect on upgrades", "/reflect-upgrades", at every update-context wrap, or proactively when a session produced durable learnings. A lesson stays in its own project unless it is a platform trap, a verified second bite, a fix to a shared artifact, or catastrophic-if-wrong.
---

<!-- canonical: ~/.claude/skills/reflect-upgrades/SKILL.md · version: 2026-11-07.1 -->
<!-- Version-stamped so cross-estate reconciliations diff against a stamp, not archaeology.
     Bump the date-tag on any substantive edit; a fork adds its own provenance line here. -->

# Reflect-upgrades — put each lesson where it can act

The question worth asking by hand every session: *did we learn anything that should change our
tools?* This skill answers it **by changing them**, not by writing a row about them. It runs three
ways: `update-context` invokes it at every wrap (the only automatic path; a wrap never builds), the
bundled `upgrade-reflection-nudge` hook suggests it mid-session after substantial work (see *Companion
hook*), and the user can invoke it by name. A session's one build starts early -- after its briefing,
or at a mid-session firing (Step 5).

**Every surviving lesson ends in exactly one outcome:** `reused` (an existing tool already does it),
`built` (this session's one build), `queued` (on the list: this project's `UPGRADE-QUEUE.md` or
`UPGRADE-NEXT.md`), `filed-central` (a committed inbox lesson, routes a-d below), `noted` (recorded, not
owed a build: `UPGRADE-NOTES.md`, or a project memory note for owner rulings and preferences),
`strengthened-existing` / `dedup-existing` (it is already somewhere), or `zero`.
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
  real docket files (including split-out row-body files, archives, pending `DOCKET-INBOX-*.md` filings,
  the self-audit log and the three upgrade lists of Step 4) and prints its denominator. A hit → `strengthened-existing` or
  `dedup-existing`: record the occurrence against the existing entry (a new date, project or wording
  does not make a new upgrade). A central hit is recorded from any project through the outcome record
  (Step 6), **never by editing the central docket or another session's pending inbox file** — that is
  the uncommitted-edit-to-a-live-central-doc class. A project hit is recorded in that project's own
  docket.

## Step 3 — The rule: does it earn a build?

Finding something true does not mean owing it a build. This rule decides:

> **Build automatically when the change has a credible, worthwhile benefit to real work, the fix can actually deliver that benefit, and a simpler response wouldn't do the job better.**

Each candidate gets three short answers, in plain words, from evidence already in its entry:

1. **What real work improves, and what's the evidence?** Something the owner asked for, a step the owner repeats, a failure that happened, or a serious risk someone has actually shown is reachable.
2. **Why is this fix worth its full cost?** Building, testing, upkeep, and anything it adds to normal sessions. Could removing or simplifying something do it instead?
3. **How does an ordinary request get the benefit?** A result the owner or a session would see, not just a new warning, a passing test or a sentence in a skill.

**Machinery isn't banned.** It's judged the same way. A true lesson that doesn't pass is recorded, not
built (Step 4).

**Target project alive** — a lesson whose remedy targets a discontinued project is dead work (check wherever you track project lifecycle status, if you do). Its platform
kernel, if any, still routes (a).

**The five fields are the build spec, not the test.** Filling them in passes nothing; a lesson that
passes names them so it can be built: **current behaviour** (what happens today), **implementation
target** (the file that changes), **expected improvement** (a step removed, a failure detected, a
capability gained), **recurring cost** (context bytes, hook latency, maintenance — text loaded into every
session of every project is the most expensive shape there is), and a **concrete acceptance check** (what
you would run to see it work). Target = the file, acceptance check = the RED condition, current behaviour
= the incident command and output.

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
processes the inbox under these same rules — builds it, lists it, notes it, or hands it back.

**Recording is separate from queuing.** A project lesson that is not this session's build goes in one of
three files at the project root, all in one form: a `## YYYY-MM-DD · <title>` heading per item, then
`- **Lesson:**`, `- **Better because:**` (one line in plain words, no file names), `- **Target:**`,
`- **RED:**`, `- **Source:**` bullets (plus `- **Partial:**` once a stopped helper's work is parked, Step 5
item 4, and an optional `- **Needs own session:** <why>`, Step 5).

- **`UPGRADE-QUEUE.md`: Build next, about 10. File order is build order.** What the owner has chosen comes
  first, unless something is seriously broken right now. **The owner's picks go to the top.** Everything
  else competes on benefit, full cost and confidence; age only breaks ties.
- **`UPGRADE-NEXT.md`: Up next, in order.** A lesson that passes Step 3 goes in `UPGRADE-NEXT.md`, or in
  `UPGRADE-QUEUE.md` at its place in the order if it beats what's there.
- **`UPGRADE-NOTES.md`: recorded, not owed a build.** Anything else goes in `UPGRADE-NOTES.md`, findable by
  Step 2's search, with a one-line reason. Recording stays free. Another sighting adds a date and is a
  reason to look again, not automatic approval. A session that hits a problem held here is told it's
  already known.

A full list shows as one briefing line and is never a question for the owner: a full list sends a new
lesson to `UPGRADE-NEXT.md` or notes, unless it beats an entry there, which then moves down (Step 5 item 2).

## Step 5 — Build one per session, early (never at a wrap)

**A wrap never builds, and neither does a departure.** They record their lesson (Step 4) and end with
nothing left running. Measured 2026-09-29 (owner: *"30 MINUTE UPDATE CONTEXT??"*): the wrap itself
finished in 10.5 minutes, but the build it had started in the background kept the session looking busy
for 17 more, and its report promised to apply the build "when it returns", so the owner waited for it.
A build started at the wrap is one the owner waits for, however it runs.

**A session's build starts early** (one per session), so it lands while the owner is still working:
- **At session start:** when the briefing's `UPGRADES` line shows entries in `UPGRADE-QUEUE.md`,
  take its **first** entry and **check it against the rule (Step 3) right before building**. If it fails,
  move it to `UPGRADE-NOTES.md` with the reason and take the next. An empty `UPGRADE-QUEUE.md` with entries
  in `UPGRADE-NEXT.md` moves the top one up, then takes it through the same check. Commit any move with a
  pathspec before any helper starts. **No candidate means no build.** The builder has no duty to stay busy.
  Start the one that passes right after the briefing, in the background, and go on with the owner's
  request. **When that entry carries a `- **Partial:** <patch> at <base>` bullet** (an earlier helper's
  parked work, item 4), the build starts from it, not from scratch:
  `python ~/.claude/skills/reflect-upgrades/scripts/park-worktree.py --unpark <patch> --into <worktree dir> --branch build/<topic>`
  creates the helper's worktree at the patch's base with the partial applied (read from its committed
  blob); the helper commits that as its starting point, merges the local HEAD, then builds. Anything the
  partial recorded (a FAILED count, a passing run) is a **lead, not a result**: re-run it.
- **Mid-session:** a nudge or manual firing starts this session's build when none has started yet. File
  order is build order here too: a new lesson on rungs 1-5 is placed by Step 4's order, and the build is
  the first entry that passes Step 3, which is the new lesson only if it was placed first. On a full list,
  a lesson that would land last goes to `UPGRADE-NEXT.md` and is not this session's build.
- **An entry no helper may build:** one with a `- **Needs own session:**` bullet, or whose target item 6
  forbids, is not started by a helper, and "first" means the first entry a helper may build. The briefing
  names it and offers it as its own owner-started session (a session whose whole task it is), or it moves
  to the project's docket so it stops using a list slot.
- **Room on the list:** when `UPGRADE-QUEUE.md` holds fewer than about 10, move the top of `UPGRADE-NEXT.md`
  up. A docket row comes on only if it passes the rule (central: from `## Open — pick up here` in
  `roadmap.md`), its `- **Source:**` naming the row id; the row stays in the docket until the build that
  lands it closes it.
- **A small correction may not need a helper at all:** a misleading line can be fixed in passing, with no
  helper and no review.

1. **Look again before building** — if the build edits a hook or script, query the capability index
   for other copies of it. Shared logic lives once; project differences live in per-project config;
   a fix to a shared tool goes to its shared owner.
2. **Write the spec on the main thread:** the incident command and output, the target file, the RED
   condition (Step 3's five fields). **The lesson must be in `UPGRADE-QUEUE.md` before the helper
   starts** — a queued item already is; write a new lesson's entry now, at its place in the order, and on
   a full list move the last entry down to `UPGRADE-NEXT.md`: the entry moved down is never the one being
   built. The queue entry is what carries the lesson if the build never lands.
3. **Hand it to a fresh small-context helper in the background** that builds the check in its own
   worktree **outside the project root**, made by hand from the local HEAD:
   `git worktree add ../<repo>-<topic> -b build/<topic> <local HEAD sha>`, then the Agent tool with
   `run_in_background: true` and an agent type that has a shell and **no isolation flag**. A lean build
   agent that loads no instruction files is much cheaper to start, if you define one; it then knows only
   its brief, so the brief carries the project's rules (item 6's forbidden files included) and names the
   suites to run: the build's own and the project's cross-cutting lints, which scan every test file. It
   is told to work
   only in that worktree's absolute path, **never to use `cd ..` or a `../` path, and to put scratch
   files in a `mktemp -d` dir** (2 of 3 helpers told only "write nothing outside it" still wrote a
   scratch file one level up, into a parent no `git status` sees), and **never to edit `UPGRADE-QUEUE.md`:
   the landing removes the entry**. A battery or selftest it writes that copies the tree and runs git
   **copies no `.git`, file or directory, and runs its git with the variables
   `git rev-parse --local-env-vars` lists removed from the environment** (a git hook in a linked
   worktree exports `GIT_DIR` and `GIT_INDEX_FILE`, and a child that inherits them re-initialises or
   stages into the real repository). It returns the diff plus RED and
   GREEN evidence. (Not the
   Agent tool's `isolation` option: it creates `<project root>/.claude/worktrees/agent-<id>/`, inside
   the tree, and, unless the `worktree.baseRef` setting is `head`, cuts it from origin's default
   branch rather than the local HEAD. Measured once: while one existed, every `rglob` test in the main
   checkout saw each source file twice.) The session's own context is too large to build in.
4. **Never wait for it.** Go on with the owner's work. (Measured: most builds take 4 to 18 minutes,
   but one whose acceptance includes a serial mutation battery can take far longer -- one battery alone
   ran about 100 minutes -- so time its first rows before giving an ETA.) When the helper returns
   **outside closing mode**, **land it on the main thread with one command**, then run the propagation
   a wrap would run for those files (for a skill, `update-context`'s Step 7 probe):
   `python ~/.claude/skills/reflect-upgrades/scripts/land-build.py <worktree> --item "<queue title>" --subject "<subject>" --upgrade "<one plain sentence>" --verify "<the project's quick verify loop>"`
   (for example `--verify "bash run-tests.sh --quick"`, whatever the project's own quick test command
   is). It runs through the platform's default shell, `cmd.exe` on Windows, so a bash-form `VAR=x cmd`
   goes inside `bash -c '...'`. `--item` takes the title after `## YYYY-MM-DD · ` or that whole heading,
   `YYYY-MM-DD · <title>`; a landing with no queue entry (a fix-forward of a landed build, a design
   build) passes `--no-item "<why>"` instead: no queue edit and no `Upgrade:` trailer, every other
   check kept. **Pass the project's quick verify loop, not
   only the build's own test:** cross-cutting lints scan every test file, so a new test can turn a
   DIFFERENT suite red while its own stays green. The script brings the branch's paths over and removes
   the queue entry (and a Partial's `.patch` and `.base`) in one commit with the trailer and a pathspec,
   so a sibling session's staged work stays out. It refuses, changing nothing, a dirty worktree, a path
   main also changed since the branch's base, a main checkout dirty in a path it touches, or a title
   that is not exactly one queue heading. It warns, never refuses, about anything in the worktree's
   parent newer than the worktree. It byte-checks the COMMITTED tree (a check before `git add`
   reads an untracked new file as deleted and fails on identical bytes), and only then removes the
   worktree, before the gating verify run: `git worktree unlock <path>` first if the harness locked it,
   then `git worktree remove <path>` and `git branch -d build/<topic>` (as `-D`, since main gets the
   branch's bytes, not its commits; the byte check is what licenses it). A harness
   worktree left under `.claude/worktrees/` is a second copy of every file the main checkout's tests
   scan. A worktree it cannot remove (a shell or a test run still inside it) is a `LEFTOVER:` line with
   its cleanup command, and the verify still runs, unless that folder is inside the main checkout (exit
   72). It exits with the verify's code; `--dry-run` prints the plan and changes nothing.
   **If your setup has an external review script** (`~/.claude/codex-ask.py`; its contract is in
   land-build.py's docstring), the build also gets a review: before the commit land-build starts it on
   the branch's diff in the background (waiting out another call that holds the script's lock), and after
   the verify prints `CODEX REVIEW RETURNED <call-id> answer=<path>` with the range it reviewed. Returned
   is not adjudicated: check each point against the landed files, fix forward what holds and is
   worth fixing now (a point not fixed on the spot goes through Step 3 like any lesson, and a true one may
   earn only a note), tell the user
   one line per disagreement, then record the call's outcome. In closing mode that line, like any late
   event, is recorded only: its call id and answer path. A refusal is one line and never blocks the
   landing. Pass
   `--no-codex-review` only for a trivial or mechanical diff, a diff already reviewed this session, or
   content your project's rules keep out of an external prompt.
   The trailer is the record (a ledger can derive *built* from it, in the repo where it landed), so a
   delivered upgrade gets exactly one, on the commit that delivers it, and a test-only, review-fix or
   fix-up commit gets none. If the session ends first, the entry stays queued and the next session's
   start checks it and builds it. **In closing mode** (from a wrap or departure request on: `update-context`'s
   *Closing mode*, where the session finishes the wrap and starts no new work), **a returned helper is
   recorded only, never landed, and a wrap stops and parks a running build, as a departure does.** Its
   partial diff is parked, never left in a worktree no step names (stopped unreported, it sits there
   untracked and machine-local; measured once, a restart stranded a 9-file diff that was saved by
   hand): stop the helper and confirm the stop (its task notification reads stopped or killed);
   classify the worktree's ignored files
   (`git -C <worktree> ls-files --others --ignored --exclude-standard`; the patch leaves them out, so
   copy a valuable one out or name it in the handoff); then park it
   (`park-worktree.py <worktree> --item "<queue title>"`, update-context Step 5, device-handoff Step 1).
   A returned helper's worktree is parked the same way. Parking commits the patch, its base sha and the
   entry's `- **Partial:** <patch> at <base>` bullet, then removes the worktree; when the stop cannot be
   confirmed or an ignored file is unresolved, `--snapshot` commits the same and keeps the worktree,
   and the report names what is unresolved. It refuses a worktree holding a mutation battery's
   sentinel, an emptied one, or one with nothing to park.
   **Park only a worktree this session's helper used;** the briefing's and wrap's `WORKTREES` lines
   name every other one, and those are reported, never parked. When the build lands, its commit
   removes the queue entry **and** the partial's `.patch` and `.base` files (`land-build.py` does both).
5. **Too big for one session** → record it by Step 4's rules and take the next entry.
6. **Projects with live external writes or regulated personal data:** the build may only add tests
   that import no write client, and must not touch the project's sensitive-data/secret guard, its git
   hooks, its harness settings, its config/override files or its live runners (the project's own
   `CLAUDE.md` names them). The RED proof uses an in-memory mutant or a synthetic fixture with the live
   gate forced off. The full suite must be green and the project's own reviewer must pass before the
   commit.
7. **Central lessons** are built by a central session, in list order and early as above, on a branch in a
   central worktree; `main` is fast-forwarded only when the shared checkout is clean and no other
   central session is live.

**Done means adopted, not built.** An upgrade moves **filed → built → adopted → confirmed**. *Built*:
the artifact exists with a RED/GREEN proof. *Adopted*: the project reaches it through its normal work
path — a hook, the runner, a lifecycle step — and it has run that way at least once. *Confirmed*: a later
session recorded it catching, removing or preventing something, as a `confirmed` event (Step 6); the
defect coming back after it shipped is the opposite record, a `recurrence` event. **The owner-facing
test:** start from an ordinary request; if anyone has to name the upgrade or remember its command for
the benefit to appear, it is not adopted. The wrap records adoption in the handoff, not just the build.

## Step 6 — Report and record

One row per lesson:
`rung <0-8> | route <local|a|b|c|d> | <one-line what> | <evidence from this session> | <honesty-label> | <outcome>`

**Honesty labels are mandatory:** `proven-need` (this session hit it), `solid-extension` (real value,
no forcing incident), `speculative` (plausible, unproven). A session realistically yields 0-2 lessons;
at most one `speculative`, and 3+ rows means the rule was not applied — re-run Step 3. Nothing
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
repo-qualified id and an explicit owner — one name per meaning:

- it **caught, removed or prevented** something → `confirmed`, bound to the deploy it names
  (`upgrade-ledger.py event --candidate <project>:<id> --owner <project> --event confirmed
  --mechanism-key <key> --commit <sha> --evidence-ref <where> --note "<what ran and what it caught>"`;
  a trailer-built upgrade's key is `upgrade-trailer` and its sha is the one the report prints);
- the **defect came back** after it shipped → `recurrence`, which marks the mechanism ineffective
  (`--event recurrence --evidence-ref <where> --note "<how the defect came back>"`).

A row recorded under the wrong name is corrected append-only, never edited
(`--event retracted --supersedes <its exact first-field stamp> --note "<why>"`). The old name
`observed` is refused, because it was written for both meanings; existing rows still read as
recurrences. If you cannot record it in the moment, say so in the report — never silently skip.

**Never drop a surviving lesson.** `UPGRADE-NOTES.md` satisfies this: not owed a build is not lost. Each
named non-reason licensed a real near-drop: *"the docket is on
rotation-hold"* (a hold blocks structural rotation, never a queue line or an inbox filing); *"keep the
wrap diff small"*; *"context is high, wrap fast"*. Catching an unrecorded lesson in your own report
means going back and recording it before finishing — the user should never have to say "file it".

## Do NOT
- Build more than one upgrade per session, build on the main thread, or start a build at a wrap or a
  departure.
- Hold a wrap open for a build, leave one running at a wrap, or land one in closing mode: a wrap stops
  and parks a running build, as a departure does, and records a returned one (Step 5 item 4).
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
- `update-context` — invokes this at every wrap (Steps 1-4 and 6; a wrap starts no build, and stops
  and parks a running one per Step 5 item 4); its shipped / learned / decided signal feeds Step 1.
- `hooks/upgrade-reflection-nudge.py` — the once-per-session `UserPromptSubmit` nudge (above).
- `analyze-context` — prints each project's pending inbox filings, upgrade queue and recent `Upgrade:`
  trailers in every briefing, so nothing here waits on anyone remembering it; a non-empty queue there
  is where a session's build starts (Step 5).
- `SELF-AUDIT.md` (central upgrades repo root) — the own-miss stream (Step 1).
- `/opportunity-scan` (ships in this repo's `project-scans/`) — the generative counterpart:
  capabilities a project should have but has never been hurt for lacking.
