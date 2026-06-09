# Context skills — session-lifecycle pair (+ slim sibling)

Three skills for keeping project context sane across Claude Code sessions, machines, and developers:

- **`analyze-context/`** — runs at session START. Verifies the persistence layer is *current* (worktree/branch/cross-machine drift check), reads it at the right depth, and produces a synthesized briefing.
- **`update-context/`** — runs at session END. Triages the session's facts into single homes, rotates history out of the hot path, runs memory hygiene, and leaves the tree provably clean (auto-commit, never push).
- **`analyze-handoff/`** — slim sibling for same-day resumption. Reads only the handoff doc, 3-line summary, ~5K tokens.

Together they form a session-bridging loop on top of the **persistent-markdown-vault-as-agent-context** pattern: each project keeps a structured file set (HANDOFF.md, wiki/running-log, memory/, docket) that survives session boundaries.

## v2 architecture (2026-06)

Rebuilt from a months-long audit of real projects (200K-token session starts, 75KB HANDOFF headers, 92%-history wikis, 103-file unindexed memory dirs). Key mechanisms:

- **Deterministic helper scripts** replace inline git improvisation:
  - `analyze-context/scripts/currency-check.sh` — one-run session-start gate: machine identity, worktree siblings, branch survey with handoff-hash drift, all-refs reachability, lag, memory-path resolution. Any `FINDING` line blocks synthesis until resolved.
  - `update-context/scripts/session-evidence.sh` — one-run wrap evidence: porcelain status, untracked triage list, rotation `THRESHOLD` signals (pickup-point counts, header accretion, oversized per-dev files), memory health (dead links, size/count gates).
- **Depth router with delegation** — core docs read directly (with a ~40KB size valve); heavy read sets (≥ ~60KB) are fully read inside parallel subagents that return structured extracts + top/middle/bottom verification quotes. Full coverage without the 200K-token cold start.
- **Single-home triage** — every session fact routes to exactly one file (status → HANDOFF, narrative → log entry, rule → memory, decision → decision doc, queue → docket); everything else cites by pointer. Facts failing the load-bearing test ("would the next session act differently without this?") are dropped.
- **Rotation rules** — HANDOFF headers may never accrete prior-session summaries; wikis keep the newest 3 pickup points inline (older → archive); per-dev files trim past ~600 lines. Archive moves are non-destructive and don't ask.
- **Memory hygiene gate** — dead-link sweeps, supersession archiving, consolidation thresholds (>40 files / >150KB / missing index).
- **Multi-developer pattern** — first-class support for per-dev `HANDOFF-<name>.md` narratives + a slim shared HANDOFF as live team contract + coordination-feed awareness, with GitHub-identity resolution and one-writer-per-file discipline. (Field-proven on a 3-developer game build.)
- **Currency before content** — header `Updated:` stamps are advisory, never proof; reachability of recent handoff commits from HEAD is the proof. Findings block the briefing; they are never demoted to FYIs.

## Project patterns supported

| Pattern | Detected by | Primary doc |
|---|---|---|
| **multi-dev** | `HANDOFF-<name>.md` files / `coordination/` dir | slim shared HANDOFF + your own per-dev file |
| **monolithic-handoff** | `HANDOFF.md` only | HANDOFF.md (wiki + bridge in one) |
| **running-log** | `continuation/` dir | HANDOFF.md snapshot + `continuation/context.md` wiki |
| **CONTEXT-style** | `CONTEXT.md` + `context/` dir | same as running-log, different filenames |
| **hub / no-git** | context files, no `.git` | as detected; staleness via file mtimes |

## Install

Copy each skill **directory** (SKILL.md *and* its `scripts/` subdir) to `~/.claude/skills/<name>/` on your machine:

```bash
cp -r skills/analyze-context skills/update-context skills/analyze-handoff ~/.claude/skills/
```

Claude Code auto-discovers them on session start. The scripts are plain bash and run on Windows git-bash and macOS alike; if a script is missing, each SKILL.md carries an inline fallback.

## Spec lineage

These skills evolved through real-use post-mortems (worktree staleness, wrong-branch drift, post-merge branch resurrection, untracked-artifact loss, speculative wraps, black-box-datamine false negatives). The v2 rewrite preserved every hardening rule from that lineage — three-source triangle, untracked-file triage with git as the ignore authority, porcelain-derived audit artifacts, append-only-with-corrections, no-unverified-negatives, date-drift flagging, machine/branch header stamps, auto-commit-never-push — stated once, enforced by script where possible, and verified by executing the skills against the real projects that produced the original failures.

## Modify freely

These are starting points. Adapt trigger phrases, thresholds (40/60/100KB, pickup-point counts), and pattern detection to your own projects.
