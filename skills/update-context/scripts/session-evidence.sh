#!/usr/bin/env bash
# session-evidence.sh — consolidated end-of-session evidence gatherer for update-context.
# Read-only. Prints a structured report. TRIAGE lines must each be classified in the
# audit artifact; THRESHOLD lines trigger the rotation / memory-hygiene pass. Always exits 0.
#
# Usage: bash session-evidence.sh

set -u

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
  MAXLEN=$(awk '{ if (length > m) m = length } END { print m+0 }' "$f")
  [ "$MAXLEN" -gt 4000 ] && echo "THRESHOLD $f max line length ${MAXLEN} chars (>4000) — single-line accretion; rewrite that line to current state and archive the displaced history this run"
done

echo
echo "== MEMORY HEALTH =="
CANDIDATES=""
for d in continuation/memory context/memory; do [ -d "$d" ] && CANDIDATES="$CANDIDATES $d"; done
if git rev-parse --git-dir >/dev/null 2>&1; then
  MAIN_WT=$(git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}')
else
  MAIN_WT=$(pwd)
fi
if command -v cygpath >/dev/null 2>&1; then NATIVE=$(cygpath -w "$MAIN_WT"); else NATIVE="$MAIN_WT"; fi
SLUG=$(printf '%s' "$NATIVE" | sed 's/[^A-Za-z0-9]/-/g')
[ -d "$HOME/.claude/projects/$SLUG/memory" ] && CANDIDATES="$CANDIDATES $HOME/.claude/projects/$SLUG/memory"

if [ -z "$CANDIDATES" ]; then
  echo "(no memory directory found — in-repo or out-of-repo)"
fi
for MEMDIR in $CANDIDATES; do
  COUNT=$(ls "$MEMDIR"/*.md 2>/dev/null | wc -l | tr -d ' ')
  KB=$(ls -l "$MEMDIR"/*.md 2>/dev/null | awk '{s+=$5} END {printf "%d", s/1024}')
  echo "$MEMDIR: $COUNT md files, ${KB}KB of md"
  IDX="$MEMDIR/MEMORY.md"
  if [ -f "$IDX" ]; then
    # dead index links: [text](file.md) entries whose target doesn't exist next to the index
    grep -oE '\]\([^)]+\.md\)' "$IDX" 2>/dev/null | sed 's/^](//; s/)$//' | sort -u | while read -r tgt; do
      case "$tgt" in http*|/*) continue ;; esac
      [ -f "$MEMDIR/$tgt" ] || echo "THRESHOLD dead index link in MEMORY.md -> $tgt (fix or remove the index line this run)"
    done
    # Index lines are pointers + hooks, not content: >200 chars means detail belongs in the topic file
    LONG=$(awk 'length > 200' "$IDX" | wc -l | tr -d ' ')
    [ "${LONG:-0}" -gt 0 ] && echo "THRESHOLD $IDX has $LONG index line(s) over 200 chars — MOVE detail down into topic files this run (verify it lands there before shortening; a move, never a cut)"
  else
    [ "$COUNT" -gt 5 ] && echo "THRESHOLD $MEMDIR has $COUNT files but NO MEMORY.md index — create one this run"
  fi
  [ "${COUNT:-0}" -gt 40 ] && echo "THRESHOLD $MEMDIR file count > 40 — consolidation pass due"
  [ "${KB:-0}" -gt 150 ] && echo "THRESHOLD $MEMDIR md size > 150KB — consolidation pass due"
done

echo
echo "== VERDICT =="
echo "Every TRIAGE line needs a class (commit/delete/leave-untracked). Every THRESHOLD line triggers"
echo "the rotation or hygiene pass in THIS run. Porcelain paths missing from the audit artifact = incomplete wrap."
