---
name: device-handoff
description: One-command cross-device departure. Fires on /device-handoff, "wrap up and prep for switching devices", "I'm leaving this machine", "end the session and push", or "handoff to my other device". Runs update-context, pushes memory out to the project's cross-device transport in the departure direction (local to bucket), and pushes every touched repo so the next machine receives the work. The departure counterpart to device-sync; pushes by default. Use plain update-context for a context save with no device switch.
---

# Device Handoff

One-command cross-device departure: persist the session (`update-context`), push memory OUT to the cross-device transport, and push every touched repo — so the next machine you sit at receives the handoff. The departure counterpart to `device-sync`; it **wraps** `update-context` the way device-sync wraps `analyze-context`, and **pushes by default** because the push is the only way the other device gets the work (symmetric to device-sync's auto-pull).

## When to fire / not fire

Fire on `/device-handoff`, "wrap up and prep for switching devices", "I'm leaving this machine", "end the session and push", "handoff to my other device".

Do NOT fire mid-task, or when nothing substantive changed. For a context save with **no** device switch, plain `update-context` is enough — device-handoff is for when you want the work pushed out to the other machine.

## Step 1 — Persist + commit (delegate to update-context)

Invoke the `update-context` skill (Skill tool) **without** "and push" — this skill controls the push in Step 4. update-context persists HANDOFF/memory/docket, rotates history, and commits locally; for mirror+bootstrap projects it also copies live memory → the in-repo mirror per project convention. **If update-context stops to ask** (three-source conflict, uncertain triage), resolve it before Steps 2-5 — never push partial state.

## Step 2 — Probe

Run the bundled probe from the project root:

```bash
bash ~/.claude/skills/device-handoff/scripts/probe-sync.sh
```

Read the full structured output (same transport signals device-sync uses).

## Step 3 — Memory departure sync (reverse of device-sync; evaluate IN ORDER, first match wins)

1. **live dir is a junction/symlink INTO the repo** → no-op; update-context's commit already captured it.
2. **in-repo mirror + bootstrap script** → update-context already copied live→mirror (committed in Step 1); verify it happened, else no-op.
3. **live dir is a junction to an out-of-band location** → OS auto-syncs; no-op.
4. **a sync-root bucket belongs to THIS project** (`bucket-match` ≠ `none`) → run the project's recipe in the **departure direction (local → bucket)**, honoring its guard: `/XD` backup-dir exclusion for a `robocopy /MIR`; `MEMORY.md` superset-merge that preserves every lane for a snapshot-merge. The recipe file is authoritative for the exact command and bucket path.
5. **none** → no cross-device memory transport; nothing to push out.

## Step 4 — Push every touched repo

Push the current repo. Then push any **sibling repo the project documents** (read the project CLAUDE.md repo map) that has unpushed commits (`git -C <repo> rev-list --count @{u}..HEAD` > 0). Report each push result; a repo with no upstream → report it, do not fail.

## Step 5 — Cross-device readiness

For an out-of-band (OneDrive/Dropbox) project, confirm the sync client process is running so the bucket actually uploads to the cloud — a local bucket write that never uploads silently strands the handoff. Warn if it is not running; do not block.

## Do NOT

- **Sync in the wrong direction.** Departure is always local → bucket. Arrival (bucket → local) is `device-sync`'s job.
- **Confirm-gate the bucket write.** Departure direction + the recipe's own guard = the safe operation; run it hands-off.
- **Reimplement update-context.** Delegate the entire write-side to it; this skill adds only departure-sync + multi-repo push + readiness check.
- **Push partial state.** If update-context stopped to ask, resolve it first.

## Related

- `device-sync` — the arrival half (pull + memory-in + analyze-context).
- `update-context` — the write-side this skill wraps.
- `analyze-context` — read-side (device-sync's final step).
