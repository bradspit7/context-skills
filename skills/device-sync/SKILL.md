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

- **Git repo** → run `git pull` first. Then, if the probe reported a `BOOTSTRAP SCRIPT` or a genuine session-start heading, open the project CLAUDE.md, find its documented session-start sequence, and run the rest verbatim (sibling-repo pulls, `bootstrap-laptop.sh`, etc.). The `SESSION-START HINT` is advisory, not authoritative — if it turns out to be incidental wording with no real commands, the `git pull` you already ran is the whole of Step 1. Never skip the pull because a heading did or didn't match.
- **Non-git** → skip; note "no git pull (not a git repo)".

## Step 2 — Memory transport (evaluate IN ORDER; take the FIRST branch that matches)

The order matters — several signals can be true at once (a shared sync root holds *other* projects' buckets; a transport-note file can sit next to git-mirrored memory). Take the first match top-down:

1. **live memory dir is a junction/symlink INTO the repo** (probe `live-dir-junction: yes` with an in-repo target) → git-in-repo; the `git pull` in Step 1 already synced it. No-op.
2. **in-repo memory mirror + a bootstrap script** (probe `IN-REPO MEMORY MIRROR` present **and** a `BOOTSTRAP SCRIPT`) → the bootstrap in Step 1 already copied mirror→live. If the pull output shows **deleted or renamed** mirror files, run the clean re-sync guard so stale live files do not linger: `rm <live-memory-dir>/*.md && cp <mirror-dir>/*.md <live-memory-dir>/`. No further sync.
3. **live memory dir is a junction/symlink to an out-of-band location** (target outside the repo) → OS auto-syncs. No-op.
4. **a sync-root bucket belongs to THIS project** (probe `bucket-match:` is **not** `none`) → out-of-band transport. Open the RECIPE FILE the probe named and execute its documented recipe **in the arrival direction (bucket → local)**, honoring its stated guard (`/XD` backup-dir exclusion for a `robocopy /MIR`; `MEMORY.md` superset-merge that preserves every lane for a snapshot-merge). The recipe file is authoritative for the exact command and bucket path.
5. **none of the above** → state "no cross-device memory sync configured for this project" and proceed.

**A sync root merely *existing* is NOT branch 4** — other projects' buckets sharing the root do not make this project an out-of-band project. Branch 4 requires a positive `bucket-match` for THIS project. The `RECIPE FILE` line is consulted **only inside branch 4**; if a project resolves to branch 1/2/3, any transport-description file the probe happened to surface is informational and must never be executed as a bucket recipe.

## Step 3 — Brief

Invoke the `analyze-context` skill (Skill tool) for the currency gate + full briefing. A device switch always warrants the full read, never the slim `analyze-handoff`. analyze-context re-runs its own currency gate, re-verifying the post-pull state.

## Do NOT

- **Confirm-gate the memory sync.** Arrival direction + the recipe's own guard = the same safe operation the user runs by hand. Run it hands-off.
- **Sync in the wrong direction.** Always remote/bucket → local. Local → bucket (the overwrite/purge direction) is `update-context`'s job and is never device-sync's action.
- **Push anything.** device-sync is arrival (pull) only; the departure half (push + copy-back) is `update-context`.
- **Re-implement a transport.** Execute what the project documents. If no recipe is documented and the family is ambiguous, say so rather than guessing a command.

## Related

- `analyze-context` — the read-only briefing this skill ends by invoking.
- `analyze-handoff` — slim same-machine resumption (no pull/sync).
- `update-context` — the departure half (session-end push + copy-back).
