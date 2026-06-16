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

- **SESSION-START BLOCK present** → open the project CLAUDE.md and execute its documented session-start commands verbatim (covers `git pull`, sibling-repo pulls, `bootstrap-laptop.sh`, etc.).
- **Else, git repo** → run `git pull`.
- **Else (non-git)** → skip; note "no git pull (not a git repo)".

## Step 2 — Memory transport (pick ONE branch from the probe signals)

- **in-repo git-tracked + live dir junctions into the repo** → already synced by the pull; no-op.
- **mirror + bootstrap script** → the bootstrap in Step 1 already copied mirror→live. If the pull output shows **deleted or renamed** mirror files, run the project's clean re-sync guard so stale live files do not linger: `rm <live-memory-dir>/*.md && cp <mirror-dir>/*.md <live-memory-dir>/`.
- **out-of-band sync root present** → open the RECIPE FILE the probe named and execute its documented recipe **in the arrival direction (bucket → local)**, honoring its stated guard (`/XD` backup-dir exclusion for a `robocopy /MIR`; `MEMORY.md` superset-merge that preserves every lane for a snapshot-merge). The recipe file is authoritative for the exact command and bucket path; the probe only told you which family you are in.
- **live dir junctions to an out-of-band location** → OS auto-syncs; no-op.
- **none of the above** → state "no cross-device memory sync configured for this project" and proceed.

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
