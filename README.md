# Context skills — session lifecycle + process suite

Twelve skills in four families, plus a standalone [memory recall layer](recall-layer/README.md).

**Session lifecycle** — keeping project context sane across Claude Code sessions, machines, and developers:

- **`analyze-context/`** — runs at session START. Verifies the persistence layer is *current* (worktree/branch/cross-machine drift check), reads it at the right depth, and produces a synthesized briefing.
- **`update-context/`** — runs at session END. Triages the session's facts into single homes, rotates history out of the hot path, runs memory hygiene, and leaves the tree provably clean (auto-commit, never push).
- **`analyze-handoff/`** — slim sibling for same-day resumption. Reads only the handoff doc, 3-line summary, ~5K tokens.
- **`reflect-upgrades/`** — after substantial work, turns session learnings into tooling-upgrade candidates (a new/upgraded skill, hook, subagent, command, MCP, or rule). Invoked by every `update-context` wrap and by a once-per-session `UserPromptSubmit` nudge hook bundled under the skill (`hooks/upgrade-reflection-nudge.py`). Surfaces and files candidates; it does not build them.
- **`device-sync/`** — one-command cross-device **arrival**. Detects the project's documented session-start + memory-sync transport (git-in-repo, in-repo mirror, OS-synced junction, or an out-of-band bucket), runs it in the arrival direction (remote → local), then hands off to `analyze-context` for the briefing. For when you sit down at a different machine. Bundles `scripts/probe-sync.sh`.
- **`device-handoff/`** — the **departure** counterpart. Runs `update-context`, pushes memory out in the departure direction (local → remote), and pushes every repo with unpushed commits, so the next machine you use receives the work. Shares the same `scripts/probe-sync.sh`.

**Process suite** — the development loop from idea to integrated code, designed as drop-in replacements for the superpowers plugin's brainstorming / writing-plans / executing-plans / subagent-driven-development / dispatching-parallel-agents:

- **`brainstorm/`** — idea → approved design. Evidence before questions (read the repo first), prose questions only (no choice-button UI), convergence to ONE recommended design, spec written to `docs/superpowers/specs/`. Hard gate: no code before an approved design.
- **`write-plan/`** — approved design → executable plan at `docs/superpowers/plans/`. Zero-context-executor standard: exact paths, complete code in every step, per-task verification drawn from *the project's own verify loop*, project law folded inline.
- **`execute-plan/`** — runs a plan task-by-task inline: plan currency check before task 1, per-task verification with evidence, continuous execution (no "should I continue?" gates), explicit deviation protocol.
- **`orchestrate/`** — parallel-subagent fan-out under explicit contract: read fan-outs with top/middle/bottom-third verification quotes, implementer-per-task with two-stage review (spec compliance, then quality), adversarial refutation of review findings, background tasks for long commands.

The process suite is deliberately mechanical — judgment is moved into explicit recipes, gates, and status protocols so quality holds up on smaller models, not just frontier ones. It encodes opinions (single recommendation over option menus, continuous execution over check-in theater) — edit them if your taste differs.

**Visual iteration** — one standalone skill for the "give me a few takes and let me pick" workflow (no superpowers equivalent):

- **`design-variants/`** — sandbox-to-selection visual iteration: build N labeled design variants of a surface in isolated sandboxes, present them as localhost links or screenshots, let the user pick by eye (mix-and-match allowed), apply the winner to production, and prove it landed with fresh post-apply evidence. Bundles `references/taste-rubric.md` — a model-independent taste rubric (axes of variation, quality bar, anti-patterns) that drives the variant theses and the pre-present self-critique. Carries two hard-won preview-fidelity gotchas (reveal-JS renders blank in hidden panels; host-cascade repaints on inlining) and apply-time CSS-specificity hardening. It orchestrates whatever design tools you already have — it does not replace them.

**Rationed audit** — one skill for auditing a whole project *from* a scarce, expensive model without blowing the usage window:

- **`deep-audit/`** — cheap Sonnet finders enumerate candidate defects across the surface; a **capped** few premium verifiers (refute-by-default) confirm only the high-value residue. The hard budget lever is the verifier `cap` — premium spend is bounded by it, not by codebase size (`cap: 0` is a free dry run that prices the audit before you commit premium tokens). Bundles `scripts/scout-then-verify.workflow.js`, the tested rationing engine (per-key accounting, a vacuity gate, overflow-deferred-not-dropped, and needsReverify safety). Uses `orchestrate` for the cheap fan-out.

**Also ships: `recall-layer/`** — a standalone local memory recall layer over your memory/notes markdown: SQLite FTS5 keyword search plus an optional semantic half (local Ollama embeddings + sqlite-vec), with the hooks, index builders, and `/memory-search` / `/recall` / `/semantic-search` commands that wire it up. Not a skill — install and usage docs live in [`recall-layer/README.md`](recall-layer/README.md).

**Also ships: `project-scans/`** — two complementary "what should this project do next?" slash commands: `/ultracode-scan` reads the **docket** and matches already-chosen work to `orchestrate`'s parallelization recipes (anti-manufacture — zero picks is a valid result), while `/opportunity-scan` reads the **vision / research / half-built** layer and surfaces high-leverage directions the docket never captured. Report-only by default. Install and usage docs live in [`project-scans/README.md`](project-scans/README.md).

**Superpowers interop:** the process suite references a few superpowers skills it does NOT replace (`systematic-debugging`, `finishing-a-development-branch`). With the plugin installed, those route normally; without it, treat each reference as "do that discipline manually" — nothing breaks. If you run the plugin alongside this suite, add one line to your `~/.claude/CLAUDE.md`: *"Prefer brainstorm / write-plan / execute-plan / orchestrate over their superpowers equivalents."*

Together they form a session-bridging loop on top of the **persistent-markdown-vault-as-agent-context** pattern: each project keeps a structured file set (HANDOFF.md, wiki/running-log, memory/, docket) that survives session boundaries.

## v2 architecture (2026-06)

Rebuilt from a months-long audit of real projects (200K-token session starts, 75KB HANDOFF headers, 92%-history wikis, 103-file unindexed memory dirs). Key mechanisms:

- **Deterministic helper scripts** replace inline git improvisation:
  - `analyze-context/scripts/currency-check.sh` — one-run session-start gate: machine identity, worktree siblings, branch survey with handoff-hash drift, all-refs reachability, lag, memory-path resolution. Any `FINDING` line blocks synthesis until resolved.
  - `update-context/scripts/session-evidence.sh` — one-run wrap evidence: porcelain status, untracked triage list, rotation `THRESHOLD` signals (pickup-point counts, header accretion, oversized per-dev files), memory health (dead links, size/count gates).
- **Depth router with delegation** — core docs read directly (with a ~40KB size valve); heavy read sets (≥ ~60KB) are fully read inside parallel subagents that return structured extracts + top/middle/bottom verification quotes. Full coverage without the 200K-token cold start.
- **Single-home triage** — every session fact routes to exactly one file (status → HANDOFF, narrative → log entry, rule → memory, decision → decision doc, queue → docket); everything else cites by pointer. Facts failing the load-bearing test ("would the next session act differently without this?") are dropped.
- **Rotation rules** — HANDOFF headers may never accrete prior-session summaries; wikis keep the newest 3 pickup points inline (older → archive); per-dev files trim past ~600 lines. Archive moves are non-destructive and don't ask.
- **Memory hygiene gate** — dead-link sweeps, supersession archiving, consolidation thresholds (dead links / oversized index lines / session-start read-path >50KB [index + docket only, not on-demand topic bulk] / missing index).
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

Copy each skill **directory** (SKILL.md *and* its `scripts/` subdir where present) to `~/.claude/skills/<name>/` on your machine:

```bash
cp -r skills/analyze-context skills/update-context skills/analyze-handoff skills/reflect-upgrades \
      skills/device-sync skills/device-handoff \
      skills/brainstorm skills/write-plan skills/execute-plan skills/orchestrate \
      skills/design-variants skills/deep-audit \
      ~/.claude/skills/
```

Or install individual skills with the [skills CLI](https://skills.sh):

```bash
npx skills add bradspit7/context-skills -s brainstorm -a claude-code -g -y
```

Claude Code auto-discovers **skills** on session start. The lifecycle scripts are plain bash and run on Windows git-bash and macOS alike; if a script is missing, each SKILL.md carries an inline fallback. The process-suite skills are SKILL.md-only.

**Hooks are NOT auto-discovered — copying is not installing.** `reflect-upgrades` bundles a once-per-session `UserPromptSubmit` nudge at `skills/reflect-upgrades/hooks/upgrade-reflection-nudge.py`. The `cp -r` above puts the file on disk and nothing else: until it is registered in `settings.json` it never fires, and the failure is silent — the skill still works when invoked by name, so the only symptom is a nudge that never arrives. Register it explicitly:

```json
"hooks": { "UserPromptSubmit": [ { "hooks": [ {
  "type": "command", "shell": "bash",
  "command": "python \"$HOME/.claude/skills/reflect-upgrades/hooks/upgrade-reflection-nudge.py\""
} ] } ] }
```

On Windows use a real `python` and prefer absolute paths for both interpreter and script — bare `python3` resolves to a Microsoft Store alias stub that opens the Store rather than running the hook, and `%USERPROFILE%` does not expand under `"shell": "bash"`. The same applies to the recall layer, whose hooks and index builders need their own wiring — see [`recall-layer/README.md`](recall-layer/README.md), and read its corpus-scope warning before enabling always-on recall.

## Spec lineage

These skills evolved through real-use post-mortems (worktree staleness, wrong-branch drift, post-merge branch resurrection, untracked-artifact loss, speculative wraps, black-box-datamine false negatives). The v2 rewrite preserved every hardening rule from that lineage — three-source triangle, untracked-file triage with git as the ignore authority, porcelain-derived audit artifacts, append-only-with-corrections, no-unverified-negatives, date-drift flagging, machine/branch header stamps, auto-commit-never-push — stated once, enforced by script where possible, and verified by executing the skills against the real projects that produced the original failures.

## Modify freely

These are starting points. Adapt trigger phrases, thresholds (40/60/100KB, pickup-point counts), and pattern detection to your own projects.

## License

[MIT](LICENSE) — copy, modify, redistribute, and use commercially; keep the copyright notice. Provided as is, without warranty.
