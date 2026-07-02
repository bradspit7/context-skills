---
name: device-handoff
description: One-command cross-device departure. Fires on /device-handoff, "wrap up and prep for switching devices", "I'm leaving this machine", "end the session and push", or "handoff to my other device". Runs update-context, pushes memory out to the project's cross-device transport in the departure direction (local to bucket), and pushes the current repo plus any documented sibling repos with unpushed commits so the next machine receives the work. The departure counterpart to device-sync; pushes by default. Use plain update-context for a context save with no device switch.
---

# Device Handoff

One-command cross-device departure: persist the session (`update-context`), push memory OUT to the cross-device transport, and push every repo with unpushed commits — so the next machine you sit at receives your full local state. The departure counterpart to `device-sync`; it **wraps** `update-context` the way device-sync wraps `analyze-context`, and **pushes by default** because the push is the only way the other device gets the work (symmetric to device-sync's auto-pull).

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
2. **in-repo mirror + bootstrap script** → update-context already copied live→mirror (committed in Step 1). **Verify it landed** — `diff -rq <live-memory-dir> <in-repo-mirror-dir>` (or confirm this session's changed memory files are present in the mirror commit). Match → no-op. **Mismatch → the copy did not complete: run the copy-back (`cp <live-memory-dir>/*.md <in-repo-mirror-dir>/` then commit), or stop and tell the user.** Never push a departure that leaves newer live memory unmirrored — silently no-op'ing a failed copy is how cross-device state gets stranded.
3. **live dir is a junction to an out-of-band location** → OS auto-syncs; no-op.
4. **a sync-root bucket belongs to THIS project** (a **positive** `bucket-match` — `exact`/`declared`/`alias`; a `bucket-match-lowconf` substring hit needs user confirmation first) → run the project's recipe in the **departure direction (local → bucket)**, honoring its guard: `/XD` backup-dir exclusion for a `robocopy /MIR`; `MEMORY.md` superset-merge that preserves every lane for a snapshot-merge. The recipe file is authoritative for the exact command and bucket path.
5. **none** → no cross-device memory transport; nothing to push out.

## Step 4 — Push every repo with unpushed work

Push so the other machine receives your full local state — **all** unpushed commits, not only this session's (that is what "pushes by default" means). For the current repo, then each **sibling repo the project documents** (read the project CLAUDE.md repo map):

1. **Preflight before pushing.** Report what will go out: `git -C <repo> status -sb` and `git -C <repo> log --oneline @{u}..HEAD` — which repo, how many ahead commits, and whether the tree is dirty. Uncommitted changes are **not** pushed; if a documented sibling's tree is dirty, warn that those edits will be left behind on this machine.
2. **Push** any repo with ahead commits (`git -C <repo> rev-list --count @{u}..HEAD` > 0). Report each push result; a repo with no upstream → report it, do not fail.
3. **Project no-push rules are satisfied by this invocation.** Invoking device-handoff IS the explicit session push instruction (a trigger phrase is literally "end the session and push") — never re-litigate a "no push without explicit user instruction" rule or hold a repo silently. Only a repo whose project docs name a **per-push side effect** (auto-deploy to production, a limited build budget) earns a confirm: push every ungated repo first, then ask one final confirm as the **last act of the turn** covering EVERY gated repo — each named with its own consequence — and led by the stranded state: "HANDOFF INCOMPLETE until answered: <repo> ahead N, unpushed — the other machine will not have this work. Push (<named consequence>) or hold?" If the user says a documented side effect no longer exists, push — and get the stale doc fixed: in the current project, fix it this session; in a sibling repo you are only pushing, queue the fix for that repo's own next session (never edit-and-commit a sibling's docs mid-handoff) — otherwise it re-gates every future handoff.
4. **Incomplete-handoff invariant.** The handoff is complete ONLY when every documented repo with unpushed commits has been pushed. A repo with an upstream left unpushed — held, or its push failed — means the final message LEADS with "HANDOFF INCOMPLETE — <repo> ahead N unpushed; <what the arriving machine will miss>", never a completion claim with an ask buried beneath it. (A documented repo with NO configured upstream stays item 2's report — there is nothing to push to; flag it once as a possible setup gap, not as INCOMPLETE on every handoff.)

## Step 5 — Cross-device readiness

For an out-of-band (OneDrive/Dropbox) project, confirm the sync client process is running so the bucket actually uploads to the cloud — a local bucket write that never uploads silently strands the handoff. Warn if it is not running; do not block.

## Do NOT

- **Sync in the wrong direction.** Departure is always local → bucket. Arrival (bucket → local) is `device-sync`'s job.
- **Confirm-gate the bucket write.** Departure direction + the recipe's own guard = the safe operation; run it hands-off.
- **Reimplement update-context.** Delegate the entire write-side to it; this skill adds only departure-sync + multi-repo push + readiness check.
- **Push partial state.** If update-context stopped to ask, resolve it first.
- **Re-litigate project no-push rules.** The invocation is the push authorization; only a documented per-push side effect earns a confirm — one final ask, covering every gated repo, loud.
- **Claim completion over an unpushed repo.** Held or failed push ⇒ "HANDOFF INCOMPLETE" leads the final message; never "everything else is done" with the question buried beneath it.
- **Infer sync direction from conflicting timestamps.** Direction comes from the operation (sync = arrival/pull, handoff = departure/push), never from a guess about which copy is newer. On conflicting state, surface the evidence and stop.

## Related

- `device-sync` — the arrival half (pull + memory-in + analyze-context).
- `update-context` — the write-side this skill wraps.
- `analyze-context` — read-side (device-sync's final step).
