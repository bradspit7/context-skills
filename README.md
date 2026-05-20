# Lifecycle skills — shareable copies

Three skills for managing project context across Claude Code sessions:

- **`update-context/SKILL.md`** — runs at session END. Persists what just happened to the project's HANDOFF / context / memory layer.
- **`analyze-context/SKILL.md`** — runs at session START. Reads the persistence layer and produces a synthesized briefing.
- **`analyze-handoff/SKILL.md`** — slim same-day-resumption sibling to `analyze-context`. Reads only HANDOFF.md, produces a 3-line summary, ~5K tokens vs `analyze-context`'s 50K+. For when you're resuming work you just left, not cold-starting.

Together they form a session-bridging loop: `analyze-context` (or `analyze-handoff` for cheap resumption) brings you up to speed when a session opens, then `update-context` writes the day's work back to disk before the session closes.

## What they do

These skills sit on top of the **persistent-markdown-vault-as-agent-context** pattern. Each project keeps a structured set of files (HANDOFF.md, context.md, memory/) that persist state across sessions. The skills enforce discipline on how those files get written and read so:

- Project state survives session boundaries
- The same project can be picked up on a different machine without losing context
- A future session understands what locked decisions exist, what's in flight, and what to read first

## Three project patterns supported

| Pattern | Detected by | Primary file |
|---|---|---|
| **monolithic-handoff** | `HANDOFF.md` at root | `HANDOFF.md` doubles as both wiki and session-bridge |
| **running-log** | `continuation/` directory | `continuation/context.md` is wiki; `HANDOFF.md` is added on top as session-bridge TL;DR |
| **CONTEXT-style** | `CONTEXT.md` + `context/` dir | Same as running-log, different filenames |

The skills detect which pattern a project uses and adapt their behavior.

## Install

Copy each `SKILL.md` to `~/.claude/skills/<name>/SKILL.md` on your machine. Claude Code auto-discovers them on session start.

## Spec history (high-level)

These skills evolved through real-use validation. Notable rules:

- **Universal HANDOFF.md** — every `/update-context` run produces/updates `<project-root>/HANDOFF.md` regardless of project pattern
- **No hard line counts** — file sizes match project complexity, not arbitrary targets
- **Three-source triangle** — conversation + git + TodoWrite must agree; mismatches are flagged not silently resolved
- **Append-only with correction mechanism** — past learnings are never silently rewritten; superseded items get explicit "retrospective correction" sections
- **Auto-apply default** — invoking the skill IS authorization to write; only stops to ask on conflicts, destructive edits, or surprising scope expansions
- **Date-drift flagging** — when system clock disagrees with file evidence, anchor on file evidence and surface the discrepancy
- **No mid-session push prompts** — git pushes are user-controlled; skill stops before commit/push
- **Machine-identity awareness** — both skills run a `hostname` check at Step 0 and surface the machine in their output; `update-context` stamps `**Last write from:**` and `**Branch:**` in HANDOFF.md's header so the next session can detect cross-machine handoffs and branch-per-feature drift
- **Worktree + branch staleness checks** — `analyze-context` Step 1.5 has two cheap sub-checks before reading any content files: Check A enumerates sibling git worktrees, Check B surveys branches and compares HANDOFF.md hashes across them. Both stop-and-ask on a newer-elsewhere finding rather than silently synthesizing from stale state. Critical for cross-machine workflows where work alternates between branches that live on different machines.

## Modify freely

These are starting points. Adapt the trigger phrases, section names, and pattern detection to match your own projects.
