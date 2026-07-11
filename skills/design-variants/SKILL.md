---
name: design-variants
description: Sandbox-to-selection visual iteration - build N labeled design variants of a visual surface in isolated sandboxes, present them as localhost links or screenshots, let the user pick with their eyes (mix-and-match allowed), apply the winner to production, and prove it landed with fresh post-apply evidence. Fires on /design-variants, "give me a few takes/versions/variants of", "make N designs and let me pick", "try some different looks", or any visual redesign request where the user wants to choose between directions. Not for single-direction edits (use your design tools directly) and not for non-visual changes.
---

# Design Variants

Sandbox → visual selection → rollout. The user asks for takes on a visual surface; each take is a real, inspectable artifact (a localhost page or a screenshot), the user picks with their eyes, and the winner ships to production with proof. The model proposes; the human's eye disposes.

Read `references/taste-rubric.md` (bundled) before Step 1 — it drives the variant theses (Step 1), the quality bar (Step 2), and the pre-present self-critique (Step 3).

## Step 1 — Scope + base pin

> **Commands below use shell variables you set first — never paste the angle-bracket forms literally.** Unquoted, `<surface>`/`<stacked-page>` parse as shell redirections; they are read-me-substitute, not paste-me. Set once, reuse the quoted expansions: `SURFACE=(path/to/file …)` (the surface file set) and `SURFACE_ROOT=path/to/surface-dir` (its containing dir), `STACKED_PAGE=path/to/stacked-comparison.html`, and the base pin — `PINNED_COMMIT=$(git rev-parse HEAD)` (clean base) **or** `SNAPSHOT_DIR=path/to/base-snapshot` (dirty base, item 3). `DV_DIR` = this skill's own directory (for the bundled checker in Step 2).

1. **Target surface:** name the exact files (web) or scene/nodes (game/native) the variants will change — this is `SURFACE`. Ask only if genuinely ambiguous.
2. **Count:** default 3 variants; honor an explicit N.
3. **Base pin (operational, not just a hash):** run `git status --short -- "${SURFACE[@]}"`.
   - Clean → pin = current commit hash: `PINNED_COMMIT=$(git rev-parse HEAD)`.
   - Dirty or untracked files inside the surface → they ARE the base, not noise: snapshot them into a recorded base dir (`SNAPSHOT_DIR`, copied into the sandbox base) so variants build on what the user actually sees, and record which files were dirty. If the dirty state looks half-finished or contradictory, stop and ask before building on it.
4. **Theses:** write one line per variant naming its **primary axis** from the taste rubric (structure/layout, hierarchy/emphasis, color/mood, typography/voice, density/breathing-room, motion/attention) and what it commits to on that axis. No two variants share a primary axis unless the user asked for close alternatives. At least one variant goes deliberately bolder than the brief — cheap to reject, high information.

## Step 2 — Build variants in isolation

- **Web mode** (static site / dev-server project): one sandbox copy of the surface per variant — sibling dirs or **separate `git worktree`s / clones (never an in-place branch checkout of the live tree — that edits production)** — served on separate localhost ports, or a single variants index page linking all of them. Never edit production files in this step.
- **Non-web mode** (Godot, native UI, images): one scene/asset copy per variant; capture a same-viewpoint screenshot of each.
- **Labels:** every variant carries a visible badge — its letter + thesis — built with a fixed greppable marker so stripping is mechanical: web wraps the badge in `<!-- dv-label -->…<!-- /dv-label -->` comments; Godot puts it in a node named `DVLabel`. "The second one" must never be ambiguous.
- **Generators:** your existing design tools — a design-system skill, a frontend-design plugin's verbs, or the project's own component library — are the generators inside this step. Orchestrate them; never duplicate their guidance here.
- **Preview fidelity — a hidden or isolated variant is not a faithful preview.** Two production-rendering conditions that isolation hides:
  - **Reveal/visibility JS (web).** A variant with visibility-triggered JS (IntersectionObserver reveal-on-scroll, an `opacity:0` base state) renders **blank** inside a `display:none` panel — the observer never fires, so the base state never resolves. When variants carry such JS, prefer **separate standalone pages/ports** (each variant genuinely visible and scrollable). If you use a **single stacked comparison page**, strip the *variant* `<script>`s from it (a case-insensitive scrub, or a project's own strip tool) — motion is then judged only in the standalone view. **Gate (do this before Step 3, not by trusting the strip):** the comparison page must contain **zero variant script tags**, except **at most one** switcher tag marked with a `data-dv-harness` attribute (mirrors the `dv-label` idiom). A substring/per-line grep cannot decide this — `data-dv-harness-disabled`, two switcher tags, or a leaked tag sharing a physical line all false-pass it. Use the bundled checker, which extracts each opening tag and checks the exact attribute + count:
    ```bash
    bash "$DV_DIR/references/check-harness-scripts.sh" "$STACKED_PAGE"   # silent + exit 0 = clean; prints offenders + exit 1 = fail
    ```
    (`--selftest` runs its fixture battery.) The checker sees `<script>` tags only — if a variant wires reveal/animation JS through **inline handler attributes** (`onload=`, `onscroll=`, `onanimationstart=`), strip those too; they execute with no `<script>` tag, so the gate can't see them.
  - **Host cascade (web, inlined variants).** A variant that will be **inlined into a host container** (not replace a standalone page) looks clean in isolation but repaints on apply — host text rules at `(0,1,1)` beat bare BEM at `(0,1,0)` (a real bite: navy-on-navy, invisible). If the winner will be inlined, build the sandbox variant *inside a copy of the real host container + its stylesheet* so the preview reproduces the true cascade. (Apply-time hardening is Step 4.)
- **Quality bar:** each variant must clear the rubric's bar (thesis legible in 3 seconds, internally consistent, craft floor met, design tokens respected unless the brief breaks them) before it earns a slot in the table.

## Step 3 — Self-critique, present, STOP

1. Critique each variant against the rubric in one line: where it commits, where it cheats. A variant whose critique reads "variant X with different colors" gets rebuilt or dropped — never presented as diversity.
2. Present the selection table: **ID → thesis → one-line self-critique → localhost URL or screenshot.** Tell the user what to look at per the rubric's selection guidance.
3. STOP. The user inspects and picks. **Mix-and-match is a first-class outcome** ("B, but with A's header") — compose named parts; push back only if the mix breaks a thesis (say why, then do what the user decides).

## Step 4 — Apply the winner to production

1. **Re-check the pin — working-tree AND committed drift** (`git status --short` alone can't see commits that landed after the pin, so it would green-light a blind overwrite of another session's committed interim edits):
   - Clean base: `git status --short -- "${SURFACE[@]}"` (uncommitted) **and** `git diff --name-only "$PINNED_COMMIT" HEAD -- "${SURFACE[@]}"` (committed since the pin). Either nonempty = drift.
   - Dirty base: compare the recorded snapshot against current bytes — `diff -r "$SNAPSHOT_DIR" "$SURFACE_ROOT"` (or per-file `diff` across `"${SURFACE[@]}"`); a commit range can't represent a snapshot base.
   Drift → rebase the winner onto current state deliberately, showing what changed; never blind-merge, never silently overwrite someone's interim edits.
2. **Strip all labels:** remove every `dv-label` marker/badge (and `DVLabel` nodes). Verify mechanically, scoped to the production surface only (never a recursive walk that reaches a still-present sandbox):
   - Web: `grep -rn "dv-label" "${SURFACE[@]}"` → zero hits.
   - Godot: `grep -rn "DVLabel" "${SURFACE[@]}"` → zero hits — the node name is `DVLabel`, not `dv-label`, so the web grep can't find it; `.tscn`/`.tres` are text, so this is a real mechanical check, not an eyeball.
3. Transplant the winner completely — a half-applied variant is worse than none. Mix-and-match composes the named parts, each completely.
4. **Inlining into a host container? Harden the fragment's cascade.** When the winner is inlined under a host with its own text/list/heading CSS (not replacing a standalone page), ancestor-prefix its selectors so host specificity can't repaint it — host `(0,1,1)` → prefixed `(0,2,0)+` — while preserving the designer's colors, and prepend structural neutralizers for the non-color host leaks (`li::before` dot, heading `border-top`, `li` padding). A blanket `color:inherit` is **wrong**: at the specificity needed to beat the host it also kills the module's own class colors. Reference impl to adapt: a small, parse-safe (brace/string/comment-aware) fragment-CSS hardener with its own self-test — build one per project rather than hand-editing selectors under pressure.

## Step 5 — Verify + clean up

1. **Fresh evidence from PRODUCTION post-apply:** serve/screenshot the production page or scene — never the sandbox as proof (the sandbox already looked right; that proves nothing about the apply).
2. Remove the sandboxes/ports/worktrees (unless the user asks to keep them for another round) **before** the no-label assertion — a still-present sandbox legitimately carries labels and would trip a surface-wide grep.
3. **No-label assertion (production surface only):** `grep -rn "dv-label" "${SURFACE[@]}"` and `grep -rn "DVLabel" "${SURFACE[@]}"` → zero hits. Scoped to `"${SURFACE[@]}"`, never a recursive walk that could reach a sandbox/worktree root.
4. Commit per project law. **Never push** — deploy-on-push projects burn build minutes; push is the user's call. And if a commit in this repo can itself trigger a push (a post-commit auto-push hook), that too is the user's call: don't commit — leave it staged for them.

## Do NOT

- Present variants that differ only in shades of one idea — that is an option menu wearing a costume, not diversity (rubric: distinct primary axes).
- Use the sandbox as post-apply proof. Production evidence only.
- Leave labels, badges, or sandbox files in production.
- Auto-pick a winner. The user's eye decides; your job is to make the choice easy and honest.
- Present a stacked variant whose live reveal-JS can't run in a hidden panel, or inline a fragment without reproducing the host cascade — **a hidden or isolated variant is not a faithful preview** (Step 2).
- Push, ever.

## Related

- `references/taste-rubric.md` — the judgment layer this workflow runs on.
- `references/check-harness-scripts.sh` — the Step 2 harness-gate checker (`--selftest` for its 9-fixture battery).
- Your design tools (a design-system skill, a frontend-design plugin, project component library) — per-verb generators used inside Step 2.
- `superpowers:verification-before-completion` — the evidence discipline Step 5 instantiates.
