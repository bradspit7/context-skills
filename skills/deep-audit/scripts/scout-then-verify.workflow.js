/**
 * scout-then-verify.workflow.js — the rationing engine for the deep-audit skill.
 *
 * Rations a scarce premium tier across a candidate list: cheap Sonnet scouts ground-truth and
 * triage EVERY candidate; only the confirmed, benefit-ranked, CAP-limited residue reaches the
 * premium refute-by-default verifier. Premium spend is bounded by `cap`, never by candidate count.
 *
 * Usage (Workflow tool):
 *   Workflow({ scriptPath: '<this file>', args: {
 *     candidates: [{ key: 'c1', claim: '...' }, ...],   // required; each needs a unique `key`
 *     scoutTask:  'Ground-truth this against <source>. Cite file:line.',   // required
 *     verifyTask: 'Refute that this finding is real.',                     // required
 *     cap: 4,                    // premium verifiers; 0 = triage-only dry run (priced for free)
 *     verifyModel: 'opus',       // e.g. a scarce premium model during an open window; see below
 *   }})
 *
 * Model routing. `verifyModel` defaults to 'opus' — the durable default for a verifier role (a
 * top-tier model). Pass a scarce premium model (e.g. verifyModel:'fable') to spend an open premium
 * window; the structure is unchanged and degrades cleanly when the window closes. Never route a
 * security-flavored verifyTask to a model with cyber-classifier refusal exposure — a false-positive
 * refusal (stop_reason 'refusal') on a defensive prompt is a coverage hole, not a pass; pin the
 * security lens to a model without that exposure (e.g. verifyModel:'opus').
 *
 * An agentType carries its own default-model pin (e.g. a read-only Explore agent defaults to a cheap
 * model), so an omitted `model` resolves to the AGENT-TYPE's default, never the session model. Every
 * pin here is explicit.
 *
 * Premium is DIRECTED to judge on the scout's inline evidence -- but the default agent() is NOT
 * tool-free (measured: default-type verifiers read/grepped the filesystem despite an inline-only
 * prompt, and one false-refuted a real finding off its own empty grep). "Premium never does file
 * I/O" is achieved by SELF-CONTAINED EVIDENCE (locator + verbatim excerpt leaves it no reason to
 * re-read), never by omitting agentType. Set verifyAgentType:'Explore' only if it SHOULD
 * independently re-read source.
 */

export const meta = {
  name: 'scout-then-verify',
  description: 'Cheap Sonnet scouts triage every candidate; a capped premium tier verifies only the confirmed residue',
  phases: [
    { title: 'Scout', detail: 'one cheap scout per candidate: ground-truth + provisional triage' },
    { title: 'Verify', detail: 'capped premium refute-by-default verifiers on the confirmed residue only' },
  ],
}

// The Workflow tool delivers `args` as a JSON string across the tool boundary. Skipping this
// re-parse silently defaults every option.
let A = args || {}
if (typeof A === 'string') { try { A = JSON.parse(A) } catch (e) { A = {} } }

const CANDIDATES = Array.isArray(A.candidates) ? A.candidates : []
const SCOUT_TASK = A.scoutTask || ''
const VERIFY_TASK = A.verifyTask || ''
// `== null` guard, not `||`: cap:0 is a legitimate triage-only dry run.
const CAP = A.cap == null ? 4 : A.cap
const SCOUT_MODEL = A.scoutModel || 'sonnet'
const VERIFY_MODEL = A.verifyModel || 'opus'
const VERIFY_EFFORT = A.verifyEffort || 'high'
const SCOUT_AGENT_TYPE = A.scoutAgentType || 'Explore'
const VERIFY_AGENT_TYPE = A.verifyAgentType || undefined
const REDISPATCH = A.redispatch == null ? true : !!A.redispatch

if (!CANDIDATES.length) return { error: 'args.candidates must be a non-empty array of {key, ...} objects' }
if (!SCOUT_TASK || !VERIFY_TASK) return { error: 'args.scoutTask and args.verifyTask are both required' }
// cap:-1 would make confirmed.slice(0, -1) verify ALL BUT ONE candidate on the premium tier —
// the exact inversion of the rationing invariant. cap:'all' would slice(0, NaN) -> [] and log
// the misleading "nothing confirmed". Reject both; cap:0 (triage-only dry run) stays legal.
if (!Number.isInteger(CAP) || CAP < 0) return { error: `args.cap must be a non-negative integer (got ${JSON.stringify(A.cap)})` }
const missingKey = CANDIDATES.findIndex(c => !c || typeof c.key !== 'string' || !c.key)
if (missingKey !== -1) return { error: `args.candidates[${missingKey}] is missing a string \`key\`` }
const dupe = CANDIDATES.map(c => c.key).find((k, i, a) => a.indexOf(k) !== i)
if (dupe) return { error: `duplicate candidate key '${dupe}' — keys are the accounting identity` }

// The verifier is judged against the ORIGINAL candidate, not just the scout's compressed result —
// so the binding refutation has the claim in hand, not an opaque pointer.
const candidateByKey = {}
CANDIDATES.forEach(c => { candidateByKey[c.key] = c })

const SCOUT_SCHEMA = {
  type: 'object',
  required: ['key', 'verdict', 'benefit', 'evidence', 'confidence'],
  properties: {
    key: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'already-satisfied', 'contradicts-a-rule', 'absorbed', 'low-value'] },
    benefit: { type: 'string', enum: ['high', 'medium', 'low'] },
    evidence: { type: 'string', description: 'a locator (file:line) AND the verbatim source excerpt or command output at it that proves the verdict — never a bare citation, never prose alone' },
    confidence: { type: 'string', enum: ['high', 'medium', 'low'] },
  },
}
const VERIFY_SCHEMA = {
  type: 'object',
  required: ['key', 'survives', 'final_verdict', 'reasoning'],
  properties: {
    key: { type: 'string' },
    survives: { type: 'boolean', description: 'true ONLY if it withstands your strongest refutation' },
    refutation_attempt: { type: 'string' },
    final_verdict: { type: 'string' },
    reasoning: { type: 'string' },
  },
}

const scoutPrompt = c => `You are a cheap read-only reconnaissance scout. EVIDENCE-GATHERING + TRIAGE ONLY — do not make the final call; ground-truth this candidate from source and give a provisional verdict with an exact citation.

TASK: ${SCOUT_TASK}

Return evidence as a locator (file:line) PLUS the verbatim source excerpt or command output at that locator — a bare citation the verifier cannot open is not enough. Never prose alone. Do not redirect shell output to an absolute path.

CANDIDATE: ${JSON.stringify(c)}`

const verifyPrompt = (candidate, scout) => `You are the rationed premium refute-by-default verifier. DEFAULT TO REFUTE. Build the strongest case that this is NOT real; only survives=true if it withstands every attack.

TASK: ${VERIFY_TASK}

Judge the ORIGINAL CANDIDATE against the scout's inline evidence below. The scout's verdict is PROVISIONAL; you produce the binding one. Re-derive independently — do not re-read files unless you have been given tools; if the evidence is only a citation you cannot open, you cannot confirm it, so return survives=false.

ORIGINAL CANDIDATE: ${JSON.stringify(candidate)}
SCOUT RESULT: ${JSON.stringify(scout)}`

// --- GATE:BEGIN --- (extracted verbatim by the accompanying test — keep the sentinels)
// A bare `.filter(Boolean)` silently conflates a dropped/errored agent with a candidate that
// triaged clean, and a schema-valid object can still be vacuous ("shape-valid garbage"). Account
// for EVERY agent BY KEY and reject empty results BEFORE they reach the rationed premium phase.
// Conservative by design: every rejection is logged, so a false-drop is visible, never silent.
const MIN_EVIDENCE = 8
const PLACEHOLDER = /^(test|todo|tbd|n\/?a|none|null|example|sample|foo|bar|baz|xxx|placeholder|lorem|[a-z]|\d+)$/i
const SHORT_CITATION = /^[\w./-]+:\d+(?::\d+)?\b/   // e.g. x.py:1 — a real terse citation, exempt from the length floor
function isVacuous(r) {
  if (!r) return true
  const ev = String(r.evidence == null ? '' : r.evidence).trim()
  // Citation SHAPE is itself the evidence. Short-circuit before the token sweep, which would
  // otherwise false-drop 'a.c:10' / 'x.h:5' / 'test.c:1' (every token a single letter, a digit,
  // or the literal word "test"). A false-drop is silent and unrecoverable; a false-pass merely
  // spends one premium verifier, and premium spend is already bounded by CAP.
  if (SHORT_CITATION.test(ev)) return false
  if (ev.length < MIN_EVIDENCE) return true
  const tokens = ev.match(/[A-Za-z]+|\d+/g) || []
  if (!tokens.length) return true
  if (tokens.every(w => PLACEHOLDER.test(w))) return true   // every token is a placeholder
  return false
}
// N in -> ok / null(dropped) / vacuous, all accounted BY KEY. `raw` is index-aligned with `keys`;
// the positional key is authoritative because an agent can report the wrong one.
function reconcile(raw, keys, label, logFn) {
  const emit = logFn || log
  const rows = Array.isArray(raw) ? raw : []
  const ok = [], droppedKeys = [], vacuousKeys = []
  rows.forEach((r, i) => {
    const key = keys[i] || (r && r.key) || `#${i}`
    if (!r) droppedKeys.push(key)
    else if (isVacuous(r)) vacuousKeys.push(key)
    // Overwrite the forgeable agent-reported key with the authoritative positional one, on a COPY.
    // Otherwise a mis-keyed substantive scout leaves its real candidate in no bucket at all, and
    // the forged key can double-spend the premium tier downstream.
    else ok.push(Object.assign({}, r, { key }))
  })
  emit(`${label}: ${rows.length} in -> ${ok.length} ok / ${droppedKeys.length} null(dropped) / ${vacuousKeys.length} vacuous`)
  if (droppedKeys.length) emit(`  ${label} DROPPED (agent errored/null — never scouted): ${droppedKeys.join(', ')}`)
  if (vacuousKeys.length) emit(`  ${label} VACUOUS (shape-valid, no real evidence — do NOT treat as clean): ${vacuousKeys.join(', ')}`)
  return { ok, droppedKeys, vacuousKeys }
}
// An inline-only verdict can only bind on inline content (the verifier is INSTRUCTED not to re-read,
// though a default-type agent still could). `hasExcerpt` is true when evidence carries substantive
// content BEYOND a bare locator: strip one leading file:line and require a real remainder.
// 'x.py:1' -> '' (citation-only, NOT bindable); 'x.py:1 returns null on empty input' and
// 'grep found 3 matches in orchestrate/SKILL.md' -> substantive (bindable).
function hasExcerpt(r) {
  if (!r) return false
  const ev = String(r.evidence == null ? '' : r.evidence).trim()
  return ev.replace(SHORT_CITATION, '').trim().length >= MIN_EVIDENCE
}
// --- GATE:END ---

log(`scout-then-verify: ${CANDIDATES.length} candidate(s), cap=${CAP}, scoutModel=${SCOUT_MODEL} (agentType=${SCOUT_AGENT_TYPE}), verifyModel=${VERIFY_MODEL} (effort=${VERIFY_EFFORT}${VERIFY_AGENT_TYPE ? `, agentType=${VERIFY_AGENT_TYPE}` : ', default agent'}), redispatch=${REDISPATCH}`)

const runScouts = list => parallel(list.map(c => () =>
  agent(scoutPrompt(c), { label: `scout:${c.key}`, phase: 'Scout', agentType: SCOUT_AGENT_TYPE, model: SCOUT_MODEL, schema: SCOUT_SCHEMA })))

phase('Scout')
const keys = CANDIDATES.map(c => c.key)
const recon = reconcile(await runScouts(CANDIDATES), keys, 'Scout')

// Re-dispatch null/vacuous scouts exactly ONCE; a second failure is a LOGGED hole, never a silent drop.
let redispatched = { attempted: [], recovered: [] }
if (REDISPATCH && (recon.droppedKeys.length || recon.vacuousKeys.length)) {
  const retryKeys = recon.droppedKeys.concat(recon.vacuousKeys)
  const retryCands = CANDIDATES.filter(c => retryKeys.indexOf(c.key) !== -1)
  log(`Scout: re-dispatching ${retryCands.length} failed scout(s) once: ${retryKeys.join(', ')}`)
  const recon2 = reconcile(await runScouts(retryCands), retryCands.map(c => c.key), 'Scout(retry)')
  redispatched = { attempted: retryKeys, recovered: recon2.ok.map(r => r.key) }
  recon.ok = recon.ok.concat(recon2.ok)
  recon.droppedKeys = recon2.droppedKeys
  recon.vacuousKeys = recon2.vacuousKeys
}
const holes = recon.droppedKeys.concat(recon.vacuousKeys)
if (holes.length) log(`Scout: ${holes.length} UNRECOVERED coverage hole(s) after retry: ${holes.join(', ')} — these were never triaged`)

const scouts = recon.ok
const confirmed = scouts.filter(s => s.verdict === 'confirmed')
const rank = { high: 0, medium: 1, low: 2 }
confirmed.sort((a, b) => (rank[a.benefit] == null ? 3 : rank[a.benefit]) - (rank[b.benefit] == null ? 3 : rank[b.benefit]))

// A verifier judging inline-only can't bind on a bare citation it is not meant to open (and must
// not be ASSUMED able to open — never assume it can re-read, never assume it can't). Unless the
// caller opted into a file-reading verifier (verifyAgentType, e.g. 'Explore'), citation-only
// findings are diverted to needsReverify — never a binding survivor, and they don't burn a cap slot.
const useReader = !!VERIFY_AGENT_TYPE
const bindable = useReader ? confirmed : confirmed.filter(hasExcerpt)
const needsReverify = useReader ? [] : confirmed.filter(c => !hasExcerpt(c)).map(c => c.key)
const toVerify = bindable.slice(0, CAP)
const overflow = bindable.slice(CAP)
log(`Scout done: ${scouts.length} usable, ${confirmed.length} confirmed → premium will verify ${toVerify.length}` +
    (needsReverify.length ? ` (${needsReverify.length} citation-only → needsReverify: ${needsReverify.join(', ')})` : '') +
    (overflow.length ? ` (CAPPED; ${overflow.length} overflow deferred, NOT dropped: ${overflow.map(o => o.key).join(', ')})` : ''))

phase('Verify')
// `adjudicated` = every item that reached a BINDING verdict (survived OR refuted). It is NOT the
// clean set (that is `survivors`, survives===true only). Never NAME this `verified` — the value is
// "the verify stage produced a verdict payload," which READS to a consumer as "is clean" while it
// still holds refuted findings; a downstream keying on such a field misreads a flagged item as
// real. Name it for what it checks.
let adjudicated = [], verifyDropped = []
if (toVerify.length > 0) {
  const opts = { phase: 'Verify', model: VERIFY_MODEL, effort: VERIFY_EFFORT, schema: VERIFY_SCHEMA }
  if (VERIFY_AGENT_TYPE) opts.agentType = VERIFY_AGENT_TYPE
  const rawVerify = await parallel(toVerify.map(c => () =>
    agent(verifyPrompt(candidateByKey[c.key], c), Object.assign({ label: `verify:${c.key}` }, opts))
      .then(v => v ? { scout: c, verify: v } : null)   // a null agent must STAY null — never wrap it into a truthy row
  ))
  adjudicated = rawVerify.filter(r => r && r.verify)
  verifyDropped = toVerify.filter((c, i) => !(rawVerify[i] && rawVerify[i].verify)).map(c => c.key)
  log(`Verify: ${toVerify.length} in -> ${adjudicated.length} returned / ${verifyDropped.length} null(dropped): ${verifyDropped.join(', ') || '—'}`)
} else {
  log(`Verify: skipped (cap=${CAP}${CAP === 0 ? ' — triage-only dry run' : ', nothing confirmed'})`)
}

const survivors = adjudicated.filter(r => r.verify.survives === true)
log(`scout-then-verify: ${survivors.length} survivor(s) of ${adjudicated.length} adjudicated; ${needsReverify.length} needsReverify; ${overflow.length} overflow; ${holes.length} hole(s)`)

return {
  survivors,       // survives===true ONLY — THE confirmed-real / clean set (what a consumer should act on)
  adjudicated,     // reached a binding verdict (survived OR refuted); NOT clean — never read this as the real set
  needsReverify,
  triage: scouts,
  confirmed_count: confirmed.length,
  overflow,
  reconciliation: {
    scout_dropped: recon.droppedKeys,
    scout_vacuous: recon.vacuousKeys,
    scout_redispatched: redispatched,
    verify_dropped: verifyDropped,
    unrecovered_holes: holes,
  },
}
