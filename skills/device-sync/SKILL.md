---
name: device-sync
description: One-command cross-device arrival. Fires on /device-sync, "I switched machines", "pull and catch me up", "sync from my other device", or the first substantive message of a session right after a machine switch. Detects the project's documented session-start and memory-sync transport, executes the recipe in the arrival direction (remote to local), then hands off to analyze-context for the briefing. Use analyze-context or analyze-handoff directly for same-machine resumption where no pull or memory sync is needed.
---

# Device Sync

One-command cross-device arrival: detect the project's session-start + memory-sync recipe, execute it in the arrival direction, hand off to `analyze-context`. This is the **mutating** session-start pre-step; `analyze-context` (read-only) does the briefing. It runs the same operations the user would run by hand — just without the typing.

## When to fire / not fire

Fire on `/device-sync`, "I switched machines/devices", "pull and catch me up", "sync from my other machine", or the first substantive message of a session right after a machine switch.

Safe to use as a general session-start (a no-op pull + no-op sync still just briefs). Do NOT use it as a substitute for same-machine resumption where nothing needs pulling — route to `analyze-handoff` (same-day) or `analyze-context` (full brief) for those.

## Step 0 — Probe (never parse a guessed shape)

Run the bundled probe from the project root (Bash tool; works on Windows git-bash and macOS):

```bash
bash ~/.claude/skills/device-sync/scripts/probe-sync.sh
```

Read its full structured output. It reports: machine, project slug, git ahead/behind, whether CLAUDE.md documents a session-start block, whether a bootstrap script + in-repo memory mirror exist, the live memory dir (path / file count / junction + target), any conventional out-of-band sync root, and the project's memory-sync recipe file. **Reason over these facts — do not assume a transport.** If the probe script is missing (partial install), run the inline essentials: `hostname`; `git rev-parse --git-dir`; grep CLAUDE.md for a "Session start"/"bootstrap" heading; check for `claude-infra/memory` or `continuation/memory`; check `~/OneDrive/claude-memory/` for a matching bucket; `find` the live memory dir for a `*memory_sync*`/`*onedrive*`/`cross-machine*` file.

## Step 1 — Session-start / pull

For a git repo, **`git pull` always happens** — the `SESSION-START HINT` and `BOOTSTRAP SCRIPT` signals only tell you whether there is *more* to run on top of it.

- **Git repo** → run `git pull` first. Then, if the probe reported a `BOOTSTRAP SCRIPT` or a genuine session-start heading, open the project CLAUDE.md, find its documented session-start sequence, and run the rest verbatim (sibling-repo pulls, `bootstrap-laptop.sh`, etc.). The `SESSION-START HINT` is advisory, not authoritative — if it turns out to be incidental wording with no real commands, the `git pull` you already ran is the whole of Step 1. Never skip the pull because a heading did or didn't match. Then `git pull` each sibling repo the project CLAUDE.md repo map documents — the same set device-handoff pushes on departure — reporting each result (no upstream → report, don't fail); sibling pulls key off the repo map, not the session-start heading.
- **Non-git** → skip; note "no git pull (not a git repo)".

### Step 1a — The pull cannot fast-forward: merge it, do not stop to ask

Each machine commits locally and pushes on departure, so one missed push guarantees a divergence on the next arrival. A plain two-sided divergence is **expected work, not an ambiguous state**, and stopping to ask permission to merge is the defect. This applies to every repo Step 1 pulls, siblings included.

1. **Protect uncommitted work first.** If git refuses because local uncommitted changes would be overwritten, commit exactly those files with a pathspec (`git commit -m "WIP: uncommitted changes found at device-sync arrival (<host>)" -- <those files>`), then pull again. Never stash, reset or discard. Leave other dirty files alone; the merge does not touch them.
2. **Merge, never rebase:** `git pull --no-rebase --no-edit`. With no conflicts, git makes the merge commit itself; go to step 4.
3. **Resolve each conflicted file by what it is:**
   - **Code, including tests:** take whole functions and classes from each parent, never spliced line ranges. A conflict boundary can fall inside a function, and a line splice can leave a test that still passes while asserting nothing. Read the parents with `git show HEAD:<path>` and `git show MERGE_HEAD:<path>`. Staging a path destroys its `:2:`/`:3:` index stages, so do not rely on those.
   - **Append-only records** (HANDOFF, docket, logs, changelog, memory index): keep both sides' entries. If both sides allocated the same id, the entry that was pushed or is already cited keeps the number; renumber the other and say why in the row.
   - **Generated files:** re-run the generator the project documents; never line-merge generated output.
   - **The same logic changed two ways:** keep the side the project's tests support. If nothing in the code, tests or docs decides it, that is the one conflict to stop on (step 6).
4. **Check the merge before trusting it:** `python ~/.claude/skills/device-sync/scripts/merge-check.py`. It reports lost or shrunken tests, duplicated functions, duplicated registry ids and leftover conflict markers, and it runs on a clean merge too (duplicate ids arrive without any conflict). Fix every finding and re-run until it exits 0. If a lost or shrunken test is a deliberate drop that one side made on purpose (its own commit says so), pass `--accept <path>::<test>` and name the test and the reason in the merge commit message. Never accept a finding just to get a clean exit. Then commit the merge with `git commit --no-edit`. A merge commit cannot take a pathspec, so where a repo's guard blocks bare commits, use the guard's sanctioned override and say so.
5. **Run the project's own verify loop** (its CLAUDE.md names it). A failure that also fails on a parent is pre-existing: note it and continue. To check, run just that suite in a throwaway worktree (`git worktree add --detach <tmp> HEAD^1`, then remove it). A failure only the merge has is the merge's: fix it.
6. **Stop only when** a conflict needs a judgment that neither the code, the tests nor the docs can settle; the merge breaks the verify loop and you cannot fix it; or the direction is genuinely ambiguous (the remote branch was rewritten or force-pushed). If you stop mid-merge, run `git merge --abort` first so both machines' work stays intact, then say in one or two lines what blocked it.
7. **Report one line in the briefing:** "merged N local + M remote commits; K conflicts resolved (<files>); merge-check clean; verify green (or: pre-existing failures X)".

## Step 2 — Memory transport (evaluate IN ORDER; take the FIRST branch that matches)

The order matters — several signals can be true at once (a shared sync root holds *other* projects' buckets; a transport-note file can sit next to git-mirrored memory). Take the first match top-down:

1. **live memory dir is a junction/symlink INTO the repo** (probe `live-dir-junction: yes` with an in-repo target) → git-in-repo; the `git pull` in Step 1 already synced it. No-op.
2. **in-repo memory mirror + a bootstrap script** (probe `IN-REPO MEMORY MIRROR` present **and** a `BOOTSTRAP SCRIPT`) → the bootstrap in Step 1 already copied mirror→live. If the pull output shows **deleted or renamed** mirror files, run the clean re-sync guard so stale live files do not linger: delete from live exactly the files the pull reported deleted/renamed (`rm <live-memory-dir>/<each-named-file>`), then `cp <mirror-dir>/*.md <live-memory-dir>/`. Never `rm <live>/*.md` wholesale — live-only files (transport notes, un-mirrored session memory) are not the mirror's to delete. No further sync.
3. **live memory dir is a junction/symlink to an out-of-band location** (target outside the repo) → OS auto-syncs. No-op.
4. **a sync-root bucket belongs to THIS project** (probe reports a **positive** `bucket-match:` line — `exact`/`declared`/`alias` provenance) → out-of-band transport. Execute the recipe the probe named **in the arrival direction (bucket → local)**, honoring its stated guard (`/XD` backup-dir exclusion for a `robocopy /MIR`; `MEMORY.md` superset-merge that preserves every lane for a snapshot-merge). The recipe file is authoritative for the exact command and bucket path. A recipe note can carry a long dated log after the recipe; the probe prints its ranges under the `recipe:` line. Read the `body:` line range (Read with offset/limit) — it is short and it states the guard. **Never read the whole `history-log:` range.**
   - **The command:** the `sync-arrival:` line if the probe printed one; else the body; else the one `newest-arrival-entry:` the probe names; else grep the file for it (e.g. `grep -n robocopy <recipe>`). If that is still ambiguous, say so rather than guess a command.
   - **Check it before running it, wherever it came from:** the source is the bucket and the destination is the live memory dir; if it deletes at the destination (`/MIR`, `/PURGE`, `--delete`), the body says to; and the body's guard still happens (a `MEMORY.md` superset-merge that a copy command cannot do is still done). An entry can mention both directions, so check the command, not the entry's label. A command that fails a check is not run — say so.
   - If the probe printed the `-> add a line` hint, say once in the briefing that one `sync-arrival:` line in the recipe saves the next arrival the search.
5. **the in-repo memory dir is git-TRACKED** (probe `repo-is-transport: yes`) → **the repo IS the transport**; the `git pull` in Step 1 already brought the memory across. A **no-op for a stated reason** — say that, not "none". A bootstrap script is one project's implementation of a live→mirror **copy** step, i.e. evidence a copy is *needed*, never evidence a transport *exists*, so its absence is not a defect. (Branch 2 still owns the case where a copy step exists and must run.)
6. **none of the above** — and `repo-is-transport: no` → state "no cross-device memory sync configured for this project" and proceed. **This is the branch that means memory genuinely does not travel**, so it is the only one worth flagging; do not treat it as interchangeable with branch 5's stated no-op.

**Why branch 5 exists** (measured on a sibling project, 2026-08-26): requiring a bootstrap script to credit an in-repo mirror **inverts the test** — a project whose memory is simply tracked in the repo, with nothing to copy, has the cleanest possible arrangement and was classified as having no transport at all. **Probe a capability by its EFFECT, never by an implementation marker.**

**A sync root merely *existing* is NOT branch 4** — other projects' buckets sharing the root do not make this project an out-of-band project. Branch 4 requires a positive `bucket-match` for THIS project. The `RECIPE FILE` line is consulted **only inside branch 4**; if a project resolves to branch 1/2/3, any transport-description file the probe happened to surface is informational and must never be executed as a bucket recipe. A `bucket-match-lowconf` (substring) hit is not branch 4 either — surface the candidate(s) to the user and confirm before executing any bucket recipe; never silently execute, never silently ignore.

## Step 3 — Brief

Invoke the `analyze-context` skill (Skill tool) with args `arrival`. It re-runs its own currency gate on the post-pull state and, when the gate is clean, gives the short arrival briefing: where and when the handoff was written, the state lines, last done / next / blocked, the bounded docket. Put your one-line Step 1 summary (pulls, bootstrap, restart needed or not) in its header. The full briefing happens only when the user asks for it ("catch me up", "brief me", "full briefing") or when the gate itself forces it (a FINDING, a multi-dev project; the class line says why).

## Do NOT

- **Confirm-gate the memory sync.** Arrival direction + the recipe's own guard = the same safe operation the user runs by hand. Run it hands-off.
- **Sync in the wrong direction.** Always remote/bucket → local. Local → bucket (the overwrite/purge direction) is `device-handoff`'s departure step and is never device-sync's action.
- **Push anything.** device-sync is arrival (pull) only; the departure half (memory-out + multi-repo push) is `device-handoff`, which wraps `update-context`.
- **Re-implement a transport.** Execute what the project documents. If no recipe is documented and the family is ambiguous, say so rather than guessing a command.
- **Infer sync direction from conflicting timestamps.** Direction comes from the operation (sync = arrival/pull, handoff = departure/push), never from a guess about which copy is newer. When the direction is genuinely ambiguous, surface the evidence and stop. An ordinary two-sided git divergence is not ambiguous: merge it (Step 1a).
- **Ask permission to merge a divergence.** The merge is part of the command the user already gave.
- **Launch helper agents or subagents on arrival.** The pull, bootstrap, memory sync and the arrival briefing all run in the main thread.
- **Run test suites or the verify loop on arrival,** except the ones Step 1a's merge path requires (its step 5).
- **Re-verify the pull or bootstrap beyond their own output.** Their output is the evidence, and analyze-context's gate already re-checks the post-pull state.

## Related

- `analyze-context` — the read-only briefing this skill ends by invoking.
- `analyze-handoff` — slim same-machine resumption (no pull/sync).
- `device-handoff` — the departure counterpart (update-context + memory-out + push).
- `update-context` — the write-side save with no device switch (commits locally; never pushes).
