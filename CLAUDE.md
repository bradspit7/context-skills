# context-skills

Public repo (github.com/bradspit7/context-skills) publishing twelve Claude Code skills: the session-lifecycle set (`analyze-context`, `update-context`, `analyze-handoff`, `reflect-upgrades`), the cross-device pair (`device-sync`, `device-handoff`), the process suite (`brainstorm`, `write-plan`, `execute-plan`, `orchestrate` — drop-in replacements for the superpowers plugin's core development-loop skills), the standalone visual-iteration skill `design-variants`, and the rationed-audit skill `deep-audit`. The `skills/<name>/SKILL.md` files are both the spec and the product; `skills/<name>/scripts/*.sh` are the deterministic helpers the lifecycle skills shell out to (`currency-check.sh`, `session-evidence.sh`, and the device pair's shared `probe-sync.sh`); `analyze-handoff`, `reflect-upgrades`, the process suite, and `design-variants` carry no `scripts/` (`reflect-upgrades` bundles a `hooks/` nudge; `design-variants` bundles a `references/` taste rubric; `deep-audit` bundles its `scripts/scout-then-verify.workflow.js` rationing runnable). Two non-skill bundles also ship: `recall-layer/` (local memory recall — hooks + index builders + `/memory-search` `/recall` `/semantic-search`) and `project-scans/` (the `/opportunity-scan` + `/ultracode-scan` commands, generalized forks of the maintainer's private originals), each with its own README. Install/usage docs: `README.md`.

## Push hold

**HOLD — do not push `main`.** Recorded 2026-07-16. This is a durable hold: it takes this repo out of any automated push set (`device-handoff` Step 4 checks for exactly this section, and reports a held repo rather than skipping it silently) until the condition below is met.

`origin/main` (`97f54d2`) is the **pinned base** of an in-flight, gated apply. That apply's validated commit is pinned as `d87c07b`, was built on this exact base, and currently exists only on another machine — it has not been pushed here. Any new commit pushed to `main` is a **base move**, which by that gate's own rule invalidates the pin and forces a full re-run of its content gate (its most expensive leg) on that other machine.

Local `main` is ahead of `origin/main` and **would fast-forward cleanly** — no hook or other mechanism prevents it. That is precisely why this hold is written down rather than assumed.

**Lift only when** `git ls-remote origin refs/heads/main` reports a SHA *starting with* `d87c07b` (it prints the full 40-char hash, so match on the prefix — never string-equal the short form) — i.e. the pin has landed. After that a base move costs nothing: rebase local `main` onto the new tip, push normally, and delete this section.

**Carve-out — the pinned push itself is NOT held.** This hold blocks pushing *other* commits to `main`. The gated apply's own terminal act — pushing the pinned SHA by explicit refspec (`git push origin d87c07b:refs/heads/main`) from the machine that holds the pin, after its own G5/G6 asserts — is the act this hold exists to protect: `d87c07b`'s parent *is* `97f54d2`, so it fast-forwards the pin into place rather than moving the base out from under it. Do not read "do not push `main`" as blocking it, or the hold deadlocks the thing it is guarding.

Scope: `main` only. Other refs — feature/WIP branches tracking their own upstreams — are unaffected, since pushing those cannot move `main`.

## Sync discipline — read before editing anything

This repo is the **third copy** in a one-way chain. Skill edits originate in the live install and flow down:

1. Live (canonical): `~/.claude/skills/<name>/`
2. Private mirror: `claude-infra/skills/<name>/` in the maintainer's private upgrades repo
3. Here: `skills/<name>/`

- Never edit skill content here first — change the live copy, then propagate through the mirror to here, keeping all three byte-identical.
- This repo can also drift AHEAD via GitHub web edits: `git pull` before any work session here. If a pull lands skill-content changes, ahead-drift resolves UPWARD — back-port them to the live copy and mirror before any other skill edit; never overwrite this repo from live.
- `README.md` and `CLAUDE.md` are repo-native (authored here, not mirrored).

**Exception — deliberately generalized skills.** Some skills whose live copies carry maintainer-specific references (an example script path, personal tool/skill names, embedded project terms, an authorship note) ship here with those references stripped, so their public copies are *intentionally* NOT byte-identical to live/mirror (current cases: `design-variants`, `update-context`, `reflect-upgrades`, `deep-audit`). Each such divergence is recorded as adjudicated by the maintainer's sync tooling — do **NOT** resolve it by copying live → here, which would reintroduce the stripped references (a codename leak). To change a generalized skill's behavior, edit the live/mirror copy, then re-apply the generalization into this copy.

Sync check (silence = in sync — **except** any deliberately-generalized skill above, which shows an expected diff; the maintainer's sync tooling, not this snippet, is the authority on which divergences are sanctioned):

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
