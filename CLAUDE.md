# context-skills

Public repo (github.com/bradspit7/context-skills) publishing ten Claude Code skills: the session-lifecycle set (`analyze-context`, `update-context`, `analyze-handoff`, `reflect-upgrades`), the cross-device pair (`device-sync`, `device-handoff`), and the process suite (`brainstorm`, `write-plan`, `execute-plan`, `orchestrate` — drop-in replacements for the superpowers plugin's core development-loop skills). The `skills/<name>/SKILL.md` files are both the spec and the product; `skills/<name>/scripts/*.sh` are the deterministic helpers the lifecycle skills shell out to (`currency-check.sh`, `session-evidence.sh`, and the device pair's shared `probe-sync.sh`); `analyze-handoff`, `reflect-upgrades`, and the process suite carry no `scripts/` (`reflect-upgrades` bundles a `hooks/` nudge instead). Install/usage docs: `README.md`.

## Sync discipline — read before editing anything

This repo is the **third copy** in a one-way chain. Skill edits originate in the live install and flow down:

1. Live (canonical): `~/.claude/skills/<name>/`
2. Private mirror: `claude-infra/skills/<name>/` in the maintainer's private upgrades repo
3. Here: `skills/<name>/`

- Never edit skill content here first — change the live copy, then propagate through the mirror to here, keeping all three byte-identical.
- This repo can also drift AHEAD via GitHub web edits: `git pull` before any work session here. If a pull lands skill-content changes, ahead-drift resolves UPWARD — back-port them to the live copy and mirror before any other skill edit; never overwrite this repo from live.
- `README.md` and `CLAUDE.md` are repo-native (authored here, not mirrored).

Sync check (silence = in sync):

```bash
for d in skills/*/; do s=$(basename "$d"); diff -rq "skills/$s" ~/.claude/skills/"$s"; done
```

## Verify loop

```bash
# Script syntax check
for f in skills/*/scripts/*.sh; do bash -n "$f" && echo "OK $f"; done

# Smoke test: scripts operate on cwd, so run the repo copy from inside any real git project
cd <any-git-project> && bash <path-to-this-repo>/skills/analyze-context/scripts/currency-check.sh
```

Scripts always exit 0 — pass/fail lives in the output lines (`FINDING` / `THRESHOLD` / `TRIAGE`), never in the exit code. Don't treat exit 0 as a green light.

## Public-content rules

- Generic terminology only: no personal project codenames, developer/machine/studio names in any committed content, including commit messages. Scan diffs for these before committing, and periodically grep the existing tree too — the baseline is not guaranteed clean.
- LF line endings everywhere; CRLF in the bash scripts breaks them when run in place.

## When editing SKILL.md content

Every hardening rule listed under README "Spec lineage" (three-source triangle, untracked-file triage, append-only-with-corrections, no-unverified-negatives, auto-commit-never-push, ...) encodes a real post-mortem — never drop or weaken one while restructuring. Threshold values are field-tuned — treat them as deliberate; the numbers live in the SKILL.md files and README "Modify freely".

## Lifecycle overrides

No context layer here by design — `update-context` must not scaffold HANDOFF.md/memory/ in this public repo. Skill-development session state lives in the Claude-upgrades project.
