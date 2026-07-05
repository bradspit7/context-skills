#!/usr/bin/env bash
# session-evidence.sh — consolidated end-of-session evidence gatherer for update-context.
# Read-only. Prints a structured report. TRIAGE lines must each be classified in the
# audit artifact; THRESHOLD lines trigger the rotation / memory-hygiene pass. Always exits 0.
#
# Usage: bash session-evidence.sh

set -u

# Echo the hold expiry date if an UNEXPIRED rotation-hold marker exists in any given file,
# else echo nothing. Marker (HTML comment): <!-- rotation-hold: until YYYY-MM-DD reason -->
_rotation_hold() {
  local today f d
  today=$(date +%Y-%m-%d 2>/dev/null) || return 0
  for f in "$@"; do
    [ -f "$f" ] || continue
    d=$(grep -oE 'rotation-hold:[[:space:]]*until[[:space:]]+[0-9]{4}-[0-9]{2}-[0-9]{2}' "$f" 2>/dev/null \
        | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | head -1)
    [ -n "$d" ] || continue
    [[ "$d" < "$today" ]] && continue   # expired marker — ignore
    printf '%s' "$d"; return 0
  done
  return 0
}

echo "== MACHINE =="
hostname

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo
  echo "== NO-GIT =="
  echo "Not a git repo. Evidence = conversation + file mtimes. Commit steps will be skipped."
  echo "Recently modified files (7 days, top 25):"
  find . -type f -mtime -7 -not -path '*/node_modules/*' -not -path '*/.git/*' 2>/dev/null | head -25
else
  echo
  echo "== BRANCH / LAST COMMIT =="
  echo "branch: $(git rev-parse --abbrev-ref HEAD)"
  echo "last:   $(git log -1 --format='%h %ai %s' 2>/dev/null || echo 'no commits yet')"

  echo
  echo "== STATUS (porcelain — EVERY path here must appear in the audit artifact) =="
  git status --porcelain
  [ -z "$(git status --porcelain)" ] && echo "(clean tree)"

  echo
  echo "== DIFFSTAT vs HEAD =="
  git diff --stat HEAD 2>/dev/null | tail -20

  echo
  echo "== UNTRACKED TRIAGE (already filtered by git's own ignore rules — every line needs a class) =="
  UNTRACKED=$(git ls-files --others --exclude-standard)
  if [ -n "$UNTRACKED" ]; then
    printf '%s\n' "$UNTRACKED" | sed 's/^/TRIAGE  /'
  else
    echo "(none)"
  fi

  echo
  echo "== HYGIENE (conflict markers + frontmatter trailing whitespace in the about-to-commit set) =="
  # Change set this wrap will commit = tracked-modified UNION untracked. `git diff --check` alone
  # misses untracked NEW files (the exact class that shipped a `metadata:`-trailing-space memory file
  # uncaught), so we union both. Trailing-whitespace is scoped to YAML frontmatter (between the leading
  # `---` fences) on purpose: markdown BODY may legitimately end a line in two spaces (a hard break),
  # so a blanket trailing-ws check would false-positive in prose-heavy projects — frontmatter never
  # wants a trailing space, so this stays zero-false-positive across every project the mirror reaches.
  HYG_OUT=$( { git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | sort -u | while IFS= read -r f; do
    [ -f "$f" ] || continue
    # conflict markers: <<<<<<< / >>>>>>> are never markdown; skip lone ======= (setext underline)
    if grep -InE '^(<{7}|>{7})' "$f" >/dev/null 2>&1; then
      echo "THRESHOLD $f has a merge-conflict marker (<<<<<<< / >>>>>>>) — resolve before committing"
    fi
    if [ "$(sed -n '1p' "$f" 2>/dev/null | tr -d '\r')" = "---" ]; then
      L=$(awk 'NR==1{infm=1;next} infm&&$0=="---"{exit} infm&&/[ \t]$/{printf "%s ",NR}' "$f" 2>/dev/null)
      [ -n "$L" ] && echo "THRESHOLD $f frontmatter trailing whitespace (line(s): $L) — strip it; fails git diff --check (the 'metadata: ' class)"
    fi
  done )
  if [ -n "$HYG_OUT" ]; then printf '%s\n' "$HYG_OUT"; else echo "(clean — no conflict markers or frontmatter trailing whitespace in the change set)"; fi
fi

echo
echo "== ROTATION SIGNALS =="
for w in continuation/context.md CONTEXT.md; do
  [ -f "$w" ] || continue
  P=$(grep -c 'PICKUP POINT' "$w" 2>/dev/null); P=${P:-0}
  L=$(wc -l < "$w" | tr -d ' ')
  echo "$w: $L lines, $P pickup points"
  [ "$P" -gt 3 ] && echo "THRESHOLD $w holds $P pickup points (keep newest 3 inline) — rotate older to archive this run"
done
if [ -f HANDOFF.md ]; then
  L=$(wc -l < HANDOFF.md | tr -d ' ')
  # -o counts occurrences (accretion happens on ONE physical header line); the colon excludes archive-pointer lines
  PS=$(grep -o 'Prior summary:' HANDOFF.md 2>/dev/null | wc -l | tr -d ' ')
  echo "HANDOFF.md: $L lines, $PS 'Prior summary:' occurrence(s)"
  [ "$PS" -gt 0 ] && echo "THRESHOLD HANDOFF.md header has accreted $PS prior-session summary block(s) — rotate ALL of them into the log/archive this run"
  if [ ! -d continuation ]; then   # running-log root HANDOFF is a deliberately-slim snapshot — skip
    HB=$(wc -c < HANDOFF.md | tr -d ' '); HKB=$(( HB / 1024 )); HLIMIT=${HANDOFF_STRUCT_KB_LIMIT:-40}
    if [ "$HKB" -gt "$HLIMIT" ]; then
      HOLD=$(_rotation_hold HANDOFF.md)
      if [ -n "$HOLD" ]; then
        echo "INFO HANDOFF.md ${HKB}KB — structural rotation on HOLD until ${HOLD}; no action this run"
      else
        echo "THRESHOLD HANDOFF.md ${HKB}KB (>${HLIMIT}KB) — structural rotation assessment due (extract durable wiki/setup tail to docs/, Step 5)"
      fi
    fi
  fi
fi
for pd in HANDOFF-*.md; do
  [ -e "$pd" ] || continue
  L=$(wc -l < "$pd" | tr -d ' ')
  echo "$pd: $L lines"
  [ "$L" -gt 600 ] && echo "THRESHOLD $pd exceeds 600 lines — archive-trim due (respect the project's trim convention)"
done
# Single-line accretion: rolling digests / SUPERSEDED chains hide tens of KB inside ONE
# physical line, evading every line-count check above. Max-line-length is the detector.
for f in continuation/context.md CONTEXT.md HANDOFF.md context/HANDOFF.md HANDOFF-*.md; do
  [ -f "$f" ] || continue
  MAXLEN=$(LC_ALL=en_US.UTF-8 awk '{ if (length > m) m = length } END { print m+0 }' "$f")
  [ "$MAXLEN" -gt 4000 ] && echo "THRESHOLD $f max line length ${MAXLEN} chars (>4000) — single-line accretion; rewrite that line to current state and archive the displaced history this run"
done

echo
echo "== MEMORY HEALTH =="
CANDIDATES=()
for d in continuation/memory context/memory; do [ -d "$d" ] && CANDIDATES+=("$d"); done
if git rev-parse --git-dir >/dev/null 2>&1; then
  MAIN_WT=$(git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}')
else
  MAIN_WT=$(pwd)
fi
if command -v cygpath >/dev/null 2>&1; then NATIVE=$(cygpath -w "$MAIN_WT"); else NATIVE="$MAIN_WT"; fi
SLUG=$(printf '%s' "$NATIVE" | sed 's/[^A-Za-z0-9]/-/g')
[ -d "$HOME/.claude/projects/$SLUG/memory" ] && CANDIDATES+=("$HOME/.claude/projects/$SLUG/memory")

# Dedupe by canonical path: the out-of-repo ~/.claude/projects/<slug>/memory is commonly a
# junction to in-repo continuation/memory; realpath collapses them (MSYS inodes do NOT).
# Arrays keep every candidate a single token even when the path carries spaces (a spaced
# $HOME word-split the old string version and silently skipped the memory-hygiene pass).
# The `${arr[@]+"${arr[@]}"}` idiom guards empty-array expansion under `set -u` (macOS bash 3.2).
DEDUP=(); SEEN=""
for d in ${CANDIDATES[@]+"${CANDIDATES[@]}"}; do
  rp=$(realpath "$d" 2>/dev/null || printf '%s' "$d")
  key=$(printf '%s' "$rp" | tr ' ' '\001')   # squash spaces so the key is a single token
  case " $SEEN " in
    *" $key "*) : ;;
    *) SEEN="$SEEN $key"; DEDUP+=("$d") ;;
  esac
done
CANDIDATES=(${DEDUP[@]+"${DEDUP[@]}"})

if [ "${#CANDIDATES[@]}" -eq 0 ]; then
  echo "(no memory directory found — in-repo or out-of-repo)"
fi
# Session-start read-path = the files analyze-context loads EVERY session start (index + docket/roadmap).
# On-demand topic files are deliberately EXCLUDED: a large topic library is not a session-start cost and
# must NOT trigger a consolidation nag. (The old blunt total-bytes trigger re-fired right after a valid
# consolidation, because trimming the read-path barely moves a sum dominated by on-demand topic files.)
# env-overridable (like HANDOFF_STRUCT_KB_LIMIT): a project whose index+docket is inherently
# large-but-legitimate can raise its own ceiling instead of re-holding a rotation marker each expiry.
READPATH_KB_LIMIT=${READPATH_KB_LIMIT:-50}
for MEMDIR in ${CANDIDATES[@]+"${CANDIDATES[@]}"}; do
  COUNT=$(ls "$MEMDIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
  KB=$(ls -l "$MEMDIR"/*.md 2>/dev/null | awk '{s+=$5} END {printf "%d", s/1024}')
  RP_BYTES=0
  for f in "$MEMDIR/MEMORY.md" "$MEMDIR"/roadmap.md "$MEMDIR"/*docket*.md; do
    [ -f "$f" ] && RP_BYTES=$(( RP_BYTES + $(wc -c < "$f" 2>/dev/null || echo 0) ))
  done
  READPATH_KB=$(( RP_BYTES / 1024 ))
  echo "$MEMDIR: $COUNT md files, ${KB}KB total (${READPATH_KB}KB session-start read-path: index+docket)"
  IDX="$MEMDIR/MEMORY.md"
  if [ -f "$IDX" ]; then
    # Dead index links. Detector covers the three forms a plain `](x.md)` grep misses —
    # [text](file.md#anchor), URL-encoded targets (%20), and Obsidian [[wiki-links]] —
    # ported 2026-07-05 from a delivered cross-estate session-evidence variant. Decode is
    # perl (ships with git-bash + macOS); a printf-%b route was rejected in review — %b
    # interprets stray backslashes in targets, and bash-3.2/BSD behavior is ambiguous.
    # No perl -> the raw target is checked undecoded (encoded links may false-flag; rare).
    grep -oE '\]\([^)]+\)' "$IDX" 2>/dev/null | sed 's/^](//; s/)$//' | sort -u | while IFS= read -r tgt; do
      case "$tgt" in http*|mailto:*|/*) continue ;; esac
      tgt=${tgt%%#*}                        # strip #anchor
      [ -n "$tgt" ] || continue             # pure-anchor link — same-file, never dead
      case "$tgt" in *%[0-9A-Fa-f][0-9A-Fa-f]*)
        tgt=$(printf '%s' "$tgt" | perl -pe 's/%([0-9A-Fa-f]{2})/chr(hex($1))/ge' 2>/dev/null || printf '%s' "$tgt") ;;
      esac                                  # decode %20 etc. only when %XX present
      case "$tgt" in *.md) ;; *) continue ;; esac
      [ -f "$MEMDIR/$tgt" ] || echo "THRESHOLD dead index link in MEMORY.md -> $tgt (fix or remove the index line this run)"
    done
    # Obsidian wiki-links: [[target]], [[target|alias]], [[target#anchor]]
    grep -oE '\[\[[^]|#]+' "$IDX" 2>/dev/null | sed 's/^\[\[//' | sort -u | while IFS= read -r tgt; do
      [ -n "$tgt" ] || continue
      if [ ! -f "$MEMDIR/$tgt" ] && [ ! -f "$MEMDIR/$tgt.md" ]; then
        echo "THRESHOLD dead index wiki-link in MEMORY.md -> [[$tgt]] (fix or remove the index line this run)"
      fi
    done
    # Index lines are pointers + hooks, not content: >200 chars means detail belongs in the topic file
    LONG=$(LC_ALL=en_US.UTF-8 awk 'length > 200' "$IDX" | wc -l | tr -d ' ')
    [ "${LONG:-0}" -gt 0 ] && echo "THRESHOLD $IDX has $LONG index line(s) over 200 chars — MOVE detail down into topic files this run (verify it lands there before shortening; a move, never a cut)"
  else
    [ "$COUNT" -gt 5 ] && echo "THRESHOLD $MEMDIR has $COUNT files but NO MEMORY.md index — create one this run"
  fi
  # Trigger on session-start READ-PATH bloat ONLY (index + docket/roadmap loaded every start) — never on
  # on-demand topic-file bulk. Clearable by design: trimming the named files clears it; topic files don't.
  if [ "${READPATH_KB:-0}" -gt "$READPATH_KB_LIMIT" ]; then
    HOLD=$(_rotation_hold "$MEMDIR"/roadmap.md "$MEMDIR"/*docket*.md)
    if [ -n "$HOLD" ]; then
      echo "INFO $MEMDIR session-start read-path ${READPATH_KB}KB — docket rotation on HOLD until ${HOLD}; no action this run"
    else
      echo "THRESHOLD $MEMDIR session-start read-path ${READPATH_KB}KB (>${READPATH_KB_LIMIT}KB: MEMORY.md + docket/roadmap, loaded every session start) — trim/rotate the index + docket this run; if the bloat is closed/resolved docket rows or durable wiki/reference content, apply structural rotation (Step 5: archive closed rows / extract durable reference to docs/), not just trimming. On-demand topic files are NOT the cause"
    fi
  fi
done

echo
echo "== VERDICT =="
echo "Every TRIAGE line needs a class (commit/delete/leave-untracked). Every THRESHOLD line triggers"
echo "the rotation or hygiene pass in THIS run. Porcelain paths missing from the audit artifact = incomplete wrap."
echo "INFO lines are visibility-only (held or assessment); no mandatory action this run."
