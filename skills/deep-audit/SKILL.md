---
name: deep-audit
description: Use when auditing a whole project for bugs or quality issues while running on a scarce, expensive model (e.g. Fable 5) and you need to conserve usage — a directed "deep-audit this project" request, especially with several audits to fit in one premium window, where naively fanning premium agents across every file would blow the budget.
---

# Deep Audit

## Overview

A rationed deep audit of a whole project, run **from** a scarce premium model. Cheap models do all the breadth; the premium tier is spent only on a **capped** few high-value verifications. The hard budget lever is the verifier `cap` — premium spend is bounded by it, not by the size of the codebase.

**You are on the premium model to USE it — ration it, don't avoid it.** Two opposite failure modes to reject: (a) fanning premium agents across every file and blowing the window; (b) over-correcting into "route everything to a cheaper model and keep the premium tier idle," which wastes the window you're paying for. Neither is right: cheap models enumerate, the premium tier verifies a capped residue.

## When to use

- A directed "deep-audit this project" request while on a scarce/expensive model, **especially with multiple audits to fit one window**.
- You want the premium tier's judgment on real findings, bounded so one audit can't eat the budget.

## When NOT to use

- A quick single-file or single-function check — just read and review it.
- You're not on a scarce model — a normal review or `/code-review` is simpler and cheaper.
- Distinct from opportunity/orchestration scans (which find *directions* or *parallelizable work*) — this audits code for *defects*.

## The flow

Don't hand-roll a fleet. Route the rationed core through the tested runnable bundled with this skill.

1. **Scope** — turn the directed prompt into (a) the audit surface (which files/dirs) and (b) the focus (correctness / security / a specific concern). List the substantive files first (a quick glob or one Sonnet recon agent) so you size to reality, not to a guess.
2. **Enumerate cheaply** — fan out **Sonnet** finders over the surface to produce a discrete candidate list of findings (high-recall breadth). This is the cheap half, and it prices how much premium work exists before the premium tier spends a token. **REQUIRED SUB-SKILL:** use `orchestrate` for the fan-out discipline (contracts, verification quotes, count reconciliation).
3. **Ration the premium tier** — hand the candidate list to the bundled `scripts/scout-then-verify.workflow.js` with `verifyModel` set to your session's premium model (e.g. `'fable'`) and `cap` = your per-audit premium budget. Premium spend is bounded by `cap`; confirmed findings beyond it return as `overflow` (deferred, not dropped); citation-only findings return as `needsReverify`. **REQUIRED SUB-SKILL:** scout-then-verify carries the accounting, vacuity gate, and needsReverify safety — don't reinvent them.
4. **Synthesize** — read `survivors` (plus `needsReverify` and `overflow`) and write the audit report. One pass; no "let me double-check" loop unless a finding is genuinely ambiguous.

## Setting the budget (the whole point)

`cap` = the number of premium verifiers = the hard spend bound for the audit.

- Divide the window across your audits: N projects → `cap ≈ window / N`, kept small (a handful, e.g. 4–6).
- `cap: 0` is a **free dry run** — the Sonnet scout phase alone reports how many findings would need the premium tier, so you can size the real run before committing premium tokens.
- Prefer several small capped audits over one uncapped fan-out. Enumeration is cheap; premium verification is the scarce thing.

## Security caveat

Never route a security-focused `verifyTask` to a model with cyber-classifier refusal exposure — such a model false-positive-refuses even defensive prompts, and a refused verifier is a coverage hole, not a pass. Pin security verification to a model without that exposure (e.g. `verifyModel: 'opus'`) for that audit or lens.

## Common mistakes

| Mistake | Fix |
|---|---|
| Fan premium agents across every file | Cheap enumerate first; the premium tier verifies only the capped confirmed residue. |
| "Conserve the premium model" → keep it idle, route all to a cheaper tier | That wastes the window. Ration the premium tier via `cap`, don't avoid it. |
| Reinvent a review fleet | Route through the bundled `scripts/scout-then-verify.workflow.js`; it's tested. |
| No hard cap ("I'll be careful") | Set `cap` explicitly — it is the only real bound on premium spend. |
| One giant audit | Size `cap` so all N audits fit the window; dry-run with `cap: 0` first. |
| Security lens on a refusal-prone model | Pin it to a model without cyber-classifier refusal exposure. |
