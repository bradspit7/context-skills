---
description: Scan the current project's vision and research for high-leverage directions the docket is not yet tracking. Use when asked to recommend new directions or fresh ideas for a project — new features, content, pages, SEO/growth, conversion, or automation opportunities — to come at it from a novel angle, or "what should this project do next"
---

You are running an **opportunity scan** on the CURRENT project — the creative, vision-layer complement to `/ultracode-scan`. Where `/ultracode-scan` reads the **docket** ("of the work I've already decided to do, what's parallelizable right now?") and is anti-manufacture by design, this scan reads the **vision / research / half-built** layer and asks: *"what high-leverage directions does this project's own design and research point at that never became tasks?"* Output = a short, ranked, honestly-labeled list of directions — not a backlog, not a plan. Do **not** build, plan, or refactor in this pass. After the user confirms, you may record the one or two they pick into this project's docket as candidate directions; execution happens later, in this project's own session.

**Why this exists:** the docket is a *next-actionable-task* list. It does not carry "the subsystem we fully designed but never built," "the locked decision with zero code," or "the research finding nobody turned into a task." `/ultracode-scan` is structurally blind to all of that — which is correct for what it does, and exactly the gap this scan fills.

**Scope — this command's only side effect:** it reads freely, but its ONLY possible write is appending the user-chosen direction(s) to this project's *existing* docket/context file as clearly-marked **candidate directions** (not committed tasks), and only after the user confirms the exact text (Step 5). It never edits product code, never creates new files, never commits, never pushes, never dispatches a subagent. Report-only is the default; it writes nothing unless the user says to record a pick.

**Focus directive (optional user steering — works in any project type):** if the user supplies focus
areas with the invocation ("focus on the patient-conversion funnel" / "explore a new content series" /
"look at ops automation"), those areas **weight** lens selection and ranking — spend most of the scan
there. A focus never relaxes anything else in this contract: grounding in the project's own materials,
the guards, the honesty labels, and the ranked 3–5 cap apply unchanged inside the focus. Keep license
to surface ONE off-focus direction when it is genuinely higher-leverage than anything in-focus —
finding what the user didn't ask for is half this scan's value. No focus supplied = the default cold
read across all fitting lenses.

## What this is (and is not)

- **PROACTIVE + CREATIVE + product-focused:** "what should this project become, given its own stated vision and research?" You ARE allowed — encouraged — to propose net-new directions that are not in the docket.
- **NOT `/ultracode-scan`.** That scan routes *existing docket work* to orchestration recipes and is anti-manufacture (zero is its common, correct result). This one deliberately goes *beyond* the docket. Do not relax `/ultracode-scan`'s gates to do this job — they are two complementary passes.
- **NOT `brainstorm` (the skill).** `brainstorm` interactively designs a feature the user has *already named*. This scan reads a project cold and *surfaces* which directions are worth naming in the first place.
- **COMPLEMENTARY to `reflect-upgrades` — the boundary is REACTIVE vs GENERATIVE, not product vs tooling.** `reflect-upgrades` is session-bound: its Step 1 reads *what this session produced* and routes the friction the session actually hit, so it can only propose tooling whose absence already hurt. It has no step that can originate a capability nothing has forced yet. Therefore a **project-native tooling direction** — a skill, workflow, subagent, hook, command, or rule THIS project should have but has never been bitten for lacking — is **in scope here** and belongs in the ranked list like any other direction, judged by the work the project repeatedly does rather than by friction already logged. What still belongs to `reflect-upgrades` is a durable learning *this session generated* (a gotcha, a repeated manual step, a correction worth binding). **Do not hand a generative tooling direction back to it** — nothing there can receive one.

## Step 1 — Read the project's VISION cold (you have no memory of prior conversations)

Read for what the project is *trying to be*, not just its next task:
1. This project's `CLAUDE.md` — what it is, its reference titles / competitors, its hard guards (these are binding — bake them into every candidate).
2. The vision/design layer — design docs, decision docs, locked-but-unbuilt specs, roadmaps, vision artifacts, research/competitor/strategy files. **This is the primary fuel.** The best directions usually live here, not in the handoff.
3. The context layer — `HANDOFF.md` / `CONTEXT.md` / `continuation/context.md`, to learn current state and (critically) what is *already shipped* vs *still latent*.
4. The actual product — code structure, content folders, roster/data files, page lists, asset stubs. Look specifically for **half-built systems**: a subsystem with a full design and little/no code, a locked decision never implemented, an authored stub waiting for its loop, a research finding never turned into a task.

If the project's vision/research docs are **thin**, say so — and mark your ideas as more speculative. Do not manufacture confidence a thin context can't support. A direction grounded only in generic best-practice (not in this project's own materials) is the failure mode here, exactly as ungated docket work is `/ultracode-scan`'s.

## Step 2 — Ideate across creative lenses (be genuinely creative, not generic)

Generate candidate directions across the lenses that fit this project: **new mechanic/system · new content/series · audience-growth/distribution · retention/depth · monetization (only if apt) · novel use of tech you already have · cross-pollination from a reference title or sibling project · project-native tooling.**

**The project-native-tooling lens** (fires in any project type, and is the one lens no other pass generates): read what this project *repeatedly does by hand* and what its own shape implies it will keep doing — its verify loop, its release/deploy ritual, its review habits, the file conventions it re-derives, the multi-step judgment its docket keeps replaying — and propose the skill / workflow / subagent / hook / command / rule that would make that native. Ground it the same way as every other lens: in this project's own materials, not in generic best practice. The test is *"this project does X often enough that X should be a capability"*, **never** *"this session hit friction Y"* — that second one is `reflect-upgrades`' job and is out of scope here.

- Prefer the **non-obvious high-leverage** move over the safe one. Be a little contrarian.
- **No filler.** Reject generic SaaS-brain suggestions (leaderboards, achievements, "add social sharing," "start a newsletter") unless one is genuinely the single highest-leverage move for *this specific project*.
- Find the ideas a thoughtful collaborator who *knows this project* would pitch — not a consultant reading a category.

## Step 3 — Ground, rank, and label honestly (the anti-busywork guardrail)

This is the inverse of `/ultracode-scan`'s docket-grounding, not the absence of grounding:
- **Ground each idea in the project's OWN materials:** a vision/design doc, a research/competitor file, a half-built system, a named reference title, a named competitor, or an obvious structural gap in the product. An idea grounded only in generic best-practice is dropped or labeled `borderline-busywork`. Cite the specific source.
- **Rank ruthlessly, best-first. Cap 3–5.** Quality over volume.
- **Label every idea honestly:** `novel-high-value` (a real new direction the project's own design points at) · `solid-extension` (good, but an extension of existing work, not a new direction) · `borderline-busywork` (included for completeness; say so plainly — do not dress it up). A scan that labels everything `novel-high-value` has failed its honesty contract.
- **For a game under a proven-mechanics rule** (e.g. the project's CLAUDE.md says "use proven mechanics from <reference title>, don't invent"): every idea MUST name the reference title it is borrowed from. Inventing a novel mechanic there is a failure, not creativity.
- **Note `orchestratable` per idea** — whether a multi-agent build would accelerate it. This is the bridge back to `/ultracode-scan`: a direction the user adopts becomes docket work, and `/ultracode-scan` then routes its execution.

## Step 4 — Respect this project's guards (read them from its CLAUDE.md, do not assume)

Every direction must be expressible **without violating this project's codified rules.** Apply whichever it declares:
- **Hobby/game:** no process ceremony or infra/licensing; proven mechanics over invented features; human playtest is the gate. Bias to shipping gameplay/content.
- **PHI / privacy:** no external egress, no new write paths, read-only beyond sanctioned writes; green tests are necessary-not-sufficient for any filing/registration change.
- **YMYL / deploy-on-push:** never imply auto-deploy; visual changes are shown before shipping; clinical/legal scope is binding; flag any idea that intersects a live legal/date constraint.
- **Security / authorized-scope:** only the active in-scope target; presence-only; request-volume caps.

A direction that can't survive these guards is dropped or reframed until it can.

## Step 5 — Output contract

Produce a **short, ranked findings list** (not prose):

1. **Vision** — one sharp line: what this project is really trying to be (as you read it).
2. **Reference anchors** — the proven titles / competitors / works it draws from.
3. **Ranked directions (3–5, best-first).** For each: title · lens · pitch (1–2 concrete sentences) · why-this-project (why it fits THIS vision, not generic) · grounding (the project's-own-materials source you cite) · effort (S/M/L) · impact (why high-leverage) · orchestratable (would a multi-agent build help) · honesty (`novel-high-value` / `solid-extension` / `borderline-busywork`).
4. **Top pick** — the single highest-leverage direction and one line on why.
5. **Creative thesis** — 2–3 sentences on where this project's real upside lives.

If the project is mechanically/strategically complete or its vision is genuinely tapped, it is acceptable — though far less common than for `/ultracode-scan` — to report **"The strongest moves here are extensions, not new directions"** rather than inflate an extension into a novel direction.

**Report before you write.** Show the ranked list, then ask whether to record any picks — e.g. *"Record direction(s) #N to `<docket>` as candidate directions? — reply go / edit / skip."* Do not modify any file until the user confirms. On confirmation, append ONLY the chosen direction(s) to the docket Step 1 identified as this project's live entry point, **clearly marked as candidate directions (not committed tasks)**, using the project's own docket convention (if it uses a namespaced/numbered ID scheme — e.g. `#123` with a counter — allocate the next ID and bump the counter; a plain dated line otherwise). **Egress guard:** in a privacy/PHI project, never write to a git-tracked docket if a gitignored local one exists — use the local file. If the project has NO context-layer file, report the picks inline and tell the user no docket exists rather than creating one.

Do **not** create a standalone ideas document and do **not** dispatch any build. End your turn after reporting (and after recording only if the user confirmed). Directed project work is acted upon in that project's own session, never from another repo.
