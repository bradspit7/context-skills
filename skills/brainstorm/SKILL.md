---
name: brainstorm
description: "Use before any creative or feature work — new features, components, behavior changes, new projects — when requirements aren't fully pinned down. Drop-in replacement for superpowers:brainstorming (prose questions, one recommendation, no option menus, no choice-button UI). Fires on 'let's design', 'I want to build', 'how should we approach', or any build request that lacks an approved spec. Terminal state is an approved spec handed to write-plan."
---

# Brainstorm — idea to approved design

Turn an idea into an approved design through short, evidence-grounded dialogue. This is a drop-in replacement for `superpowers:brainstorming`; where the two conflict, this wins.

<HARD-GATE>
No implementation skill, no code, no scaffolding until a design has been presented and the user has approved it. Applies to every project regardless of perceived simplicity — "simple" work is where unexamined assumptions burn the most time. The design itself can be three sentences; the gate still applies.
</HARD-GATE>

## Step 1 — Evidence before questions

Read the project context FIRST: CLAUDE.md, the handoff/docket layer, relevant memory entries, the code area in question, recent commits. Every question you can answer from the repo is a question you don't ask. Most "requirements questions" have answers sitting in the context layer.

Scope check while reading: if the request spans multiple independent subsystems, say so immediately and decompose into sub-projects (each gets its own spec → plan → execution cycle) before refining details of any one piece.

## Step 2 — Interview, the short way

- **Prose questions only. Never the AskUserQuestion tool / choice-button UI.** If a choice is genuinely binary, ask it as a one-line prose question with your lean stated.
- **~2-4 questions total** before you synthesize. Default to one question per message — answers reshape later questions. Batch only when the evidence has already pinned scope and the remaining 2-3 unknowns are independent (no answer would change what you'd ask next); a batch is parallel one-line prose questions about different decisions, never alternatives for one decision — that's an option menu in disguise. If you're past four, you're interviewing instead of reading evidence.
- **Ask about scope, success criteria, preferences, naming, pacing — not deep internals.** When the user defers on technical detail ("trust you", "whatever you think"), that's a green light to decide, paired with a duty to self-verify — not a prompt to keep asking. Flag only the technical forks with real scope/cost consequences.
- Don't re-ask anything the context layer already answers.

## Step 3 — Converge to ONE design

- Explore alternatives privately; present **one recommended design** with the reasoning that makes it win. Name a runner-up in a single sentence only when it's genuinely close. Never present an A/B/C menu unless the user explicitly asked for options.
- Present the whole design in one message, sections scaled to their complexity (a few sentences when straightforward; more when nuanced). Cover: shape/architecture, components and boundaries, data flow, error handling, how it will be verified. Lead with the shape; internals expand on request.
- Design the **complete** approved scope. Sequencing by dependency is fine; "phase 2 later" framing is not — either it's in the design or it's cut.
- YAGNI ruthlessly. Units small enough to hold in context, boundaries clean enough that internals can change without breaking consumers.
- In existing codebases: follow established patterns; fold in targeted improvements only where existing problems touch this work. No drive-by refactors.

One approval round on the whole design — not per-section sign-off. Revise and re-present if the user redirects.

## Step 4 — Write the spec

On approval, write the design to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` (project conventions override the location). Then self-review it once, fixing inline:

1. **Placeholders** — no TBD/TODO/vague requirements.
2. **Internal consistency** — no section contradicts another; architecture matches feature claims.
3. **Scope** — one implementation plan's worth, or flag for decomposition.
4. **Ambiguity** — any requirement readable two ways gets pinned to one.

Commit per project law (commit yes; never push unprompted). Tell the user where the spec lives and ask them to flag anything they want changed — then proceed to Step 5 in the same message. The design approval in Step 3 is the authorization; the spec-flag ask is non-blocking, and you revise only if they actually flag something.

## Step 5 — Hand off

Multi-step work → invoke **write-plan**. Trivially small approved work (single edit, one file) → implement directly, citing the approved design — unless the edit decides what gets **written / filed / matched / registered**: write-path logic gets no size exemption; run the write-path review fleet (orchestrate's hardened contract) before committing, or take the plan route. No other skill is the successor to brainstorm.

## Self-checks (the historical failure modes)

- Asking the user something `grep` could answer — read first.
- Option menus / "three approaches" essays — converge, recommend, move.
- Batching questions whose answers interact — if one answer can moot another, they go one per message.
- Approval theater — one design gate, one spec gate, done.
- Designing only "phase 1" of an approved whole — design it all.
- Writing code mid-brainstorm — the hard gate is hard.
