#!/usr/bin/env bash
# session-evidence.sh — consolidated end-of-session evidence gatherer for update-context.
# Read-only. Prints a structured report. TRIAGE lines must each be classified in the
# audit artifact; THRESHOLD lines trigger the rotation / memory-hygiene pass. Always exits 0.
#
# Usage: bash session-evidence.sh

set -u

# Emit the HEAD 'until' date of every ACTIVE rotation-hold marker in a file, one per line.
# Marker (HTML comment): <!-- rotation-hold: until YYYY-MM-DD reason -->
#
# FAIL-SAFE bias (the design axis this function turns on): the dangerous failure is a
# MISSED real marker -> a doc the author held gets rotated/archived = data loss. Over-holding
# (dropping a documented example) is merely a deferred rotation the operator can see and undo.
# So the marker match is PERMISSIVE (never miss a real one) and only HIGH-CONFIDENCE quotes are
# rejected:
#   - the comment body may contain '>' (only '-->' closes an HTML comment) and stray formatting
#     backticks -> both tolerated, so an '-> arrow' or a code-formatted date never drops a marker;
#   - only the HEAD 'until' date is read, so a date in the free-text reason cannot forge/mask a hold;
#   - a marker is treated as QUOTED (ignored) only when it sits in a fenced code block (CommonMark
#     rule: a CLOSING fence carries NO info string, so ```lang is content, not a close), a
#     blockquote, an indented code block (>=4 spaces or a tab -- the writer emits markers at the
#     top level, never indented), or is wrapped whole in inline-code backticks.
_active_hold_dates() {
  awk '
    # Collect the head "until" date of each ACTIVE marker on a line: print it directly when
    # buffer==0 (outside any fence), or hold it in buf[] when buffer==1 (inside a fence that has
    # not yet closed) so it can be dropped on a real close or flushed if the fence never closes.
    function scan(line, buffer,   rest, s, after, e, cmt, before, aft, d) {
      rest = line
      while ((s = index(rest, "<!--")) > 0) {
        after = substr(rest, s + 4)
        e = index(after, "-->")
        if (e == 0) break                         # no closing --> : not a complete comment
        cmt = substr(after, 1, e - 1)             # body (may contain > and backticks)
        before = (s > 1) ? substr(rest, s - 1, 1) : ""
        aft = substr(rest, s + 4 + e + 2, 1)      # char immediately after -->
        if (before != "`" || aft != "`") {        # NOT wrapped whole in inline code
          gsub(/`/, "", cmt)                       # drop formatting backticks inside the comment
          if (match(cmt, /rotation-hold:[ \t]*until[ \t]+[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) {
            d = substr(cmt, RSTART, RLENGTH); sub(/.*until[ \t]+/, "", d)
            if (buffer) buf[++bn] = d; else print d
          }
        }
        rest = substr(rest, s + 4 + e + 2)        # continue scanning after this comment
      }
    }
    {
      raw = $0
      if (match(raw, /^ {0,3}(`{3,}|~{3,})/)) {    # a fence line (open or close)
        m = substr(raw, RSTART, RLENGTH); sub(/^ +/, "", m)
        mc = substr(m, 1, 1); ml = length(m)
        if (!infence) { infence = 1; ofc = mc; ofl = ml; bn = 0; next }   # open: start buffering
        rest2 = substr(raw, RSTART + RLENGTH)
        if (mc == ofc && ml >= ofl && rest2 ~ /^[[:space:]]*$/) { infence = 0; bn = 0; next }  # bare CLOSE: buffered markers were truly fenced -> drop
        next                                       # info-string / mismatched line: still fenced
      }
      if (infence)                 { scan(raw, 1); next }   # inside an as-yet-unclosed fence: buffer
      if (raw ~ /^ {0,3}>/)        next            # blockquote  -> quoted
      if (raw ~ /^(    |\t)/)      next            # indented code block -> quoted
      scan(raw, 0)                                 # outside any fence: emit directly
    }
    END { if (infence) for (i = 1; i <= bn; i++) print buf[i] }  # UNCLOSED fence never really quotes -> flush (fail-safe: never miss a real marker)
  ' "$1" 2>/dev/null
}

# Echo the expiry date of the first UNEXPIRED active rotation-hold marker across the given
# files, else echo nothing. EVERY active marker's head date is evaluated, so an expired marker
# never hides a later active one.
_rotation_hold() {
  local today f d
  today=$(date +%Y-%m-%d 2>/dev/null) || return 0
  for f in "$@"; do
    [ -f "$f" ] || continue
    while IFS= read -r d; do
      [ -n "$d" ] || continue
      [[ "$d" < "$today" ]] && continue   # expired marker — check the next one
      printf '%s' "$d"; return 0          # first unexpired marker holds
    done < <(_active_hold_dates "$f")
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
echo "== COHERENCE (HANDOFF forward sections vs the resolved ledger -- G#84) =="
# A wrap that APPENDS newer status above stale operational blocks (instead of REWRITING the
# whole doc) leaves resolved IDs listed as open in the HANDOFF's forward-looking sections and
# lets a stale ready-signal block survive below the fold -- three consecutive external reviews
# caught this same class. Deterministic backstop; a THRESHOLD here means "rewrite the stale
# section THIS run", like any rotation. Read-only. Degrades to a clean skip on any docket that
# lacks a G# resolved-ledger, so it is safe on every project the mirror reaches.
COH_HANDOFF=""
for f in HANDOFF.md context/HANDOFF.md; do [ -f "$f" ] && { COH_HANDOFF="$f"; break; }; done
if [ -z "$COH_HANDOFF" ]; then
  echo "(no HANDOFF.md -- coherence check n/a)"
else
  # Ledger + open-row sources (files that may carry resolved/retired rows AND open rows). An ARRAY,
  # so a docket filename containing a space is ONE element, not word-split into broken paths (P2-4).
  # Sources cover the in-repo homes AND the running-log (continuation/) + out-of-repo memory-dir
  # homes the old flat globs missed (NEW-6).
  COH_DOCKETS=()
  for f in roadmap.md "$COH_HANDOFF" ./*docket*.md ./*_docket.md context/roadmap.md context/*docket*.md \
           continuation/roadmap.md continuation/*docket*.md; do
    [ -f "$f" ] && COH_DOCKETS+=("$f")
  done
  # memory-dir docket homes (a project whose docket lives in its out-of-repo memory dir). CANDIDATES
  # was resolved by the MEMORY HEALTH pass above; guard empty-array expansion under set -u (bash 3.2).
  for d in ${CANDIDATES[@]+"${CANDIDATES[@]}"}; do
    for f in "$d/roadmap.md" "$d"/*docket*.md; do [ -f "$f" ] && COH_DOCKETS+=("$f"); done
  done
  # CLOSED = leading-ID rows that are resolved/retired -- detected by EITHER a dedicated resolved-
  # LEDGER section heading (Resolved/Retired/Archived/Closed/Dropped/Completed/Done) OR the row's
  # own leading status glyph (U+2705 check / U+274C cross / U+26D4 no-entry "dropped", matched as
  # UTF-8 octal so this script stays ASCII-clean). Leading-ID only: a narrative mention of a
  # resolved ID inside another row's prose is deliberately NOT counted (only an OPEN-ROW claim is
  # incoherent). closedsec resets per file (FNR==1) so a Resolved section in one file can't bleed
  # into the next.
  CLOSED=$(awk '
    # NEW-7: a table row subject is any dedicated cell whose TRIMMED content LEADS with a (bolded)
    # G# id -- returns the space-separated ids from every such cell (handles a non-first G# column
    # and a grouped "**G#a / G#b**" cell) while ignoring a G# mentioned mid-prose in a note cell.
    function tabsubj(line,   n,i,parts,cell,c2,out) {
      n=split(line,parts,"|"); out=""
      for(i=1;i<=n;i++){ cell=parts[i]; sub(/^[[:space:]]+/,"",cell); sub(/[[:space:]]+$/,"",cell); sub(/^\*\*/,"",cell)
        if(cell ~ /^G#[0-9]+/){ c2=cell; while(match(c2,/G#[0-9]+/)){ out=out" " (substr(c2,RSTART+2,RLENGTH-2)+0); c2=substr(c2,RSTART+RLENGTH) } } }
      return out
    }
    FNR==1 { closedsec=0 }
    /^#{1,6}[[:space:]]/ {
      h=tolower($0)
      # A dedicated resolved-LEDGER heading closes its rows by membership; an OPEN-keyword heading
      # ends it; a NEW top-level (##) heading also ends it. NEW-5: a backward-looking "## Recently
      # shipped" NARRATIVE is NOT a ledger -- a bullet there whose leading bold names a just-FILED
      # OPEN id ("- **... G#88 filed**") must NOT be mis-closed; it closes only via a leading glyph.
      # But a DEDICATED "## Shipped" ledger IS a closer, so match "recently shipped" FIRST (exclude),
      # then plain "shipped" (close). Deeper (###/####) descriptive sub-headings KEEP closedsec so
      # resolved rows nested beneath them are not lost (P2-3).
      if (h ~ /recently shipped/) closedsec=0
      else if (h ~ /resolved|retired|archived|closed|dropped|completed|done|shipped/) closedsec=1
      else if (h ~ /open candidate|open work|open item|pick[ -]?up|next task|next step|next session|entry point/) closedsec=0
      else if ($0 ~ /^##[[:space:]]/) closedsec=0
      next
    }
    match($0, /^[[:space:]]*-[[:space:]]*\*\*[^*]+\*\*/) {
      bold=substr($0,RSTART,RLENGTH); rest=substr($0,RSTART+RLENGTH); sub(/^[[:space:]]+/,"",rest)
      # A close glyph counts ONLY when it is the row LEADING status token (immediately after the
      # bold ID, per the documented marker convention) -- index()==1. A glyph deep in a row prose
      # ("...work done. done sub-step") is a sub-step note, not the row status, so it never closes
      # the row. The leading [^*]+ bold span carries the row subject id(s) -- iterating every G#
      # token in it catches a grouped **G#a / G#b / G#c** row while ignoring a prose mention (which
      # sits OUTSIDE the leading bold).
      if (closedsec || index(rest,"\342\234\205")==1 || index(rest,"\342\235\214")==1 || index(rest,"\342\233\224")==1) {
        tmp=bold; while (match(tmp,/G#[0-9]+/)) { print substr(tmp,RSTART+2,RLENGTH-2)+0; tmp=substr(tmp,RSTART+RLENGTH) }
      }
    }
    match($0, /^[[:space:]]*\|/) {
      # NEW-7: sanctioned TABLE docket row. The "G# column" may be ANY dedicated cell (tabsubj), not
      # only the first. A close glyph anywhere in the row also closes it (status lives in a cell).
      subj=tabsubj($0)
      if (subj!="" && (closedsec || index($0,"\342\234\205")>0 || index($0,"\342\235\214")>0 || index($0,"\342\233\224")>0)) {
        m=split(subj,arr," "); for(k=1;k<=m;k++) print arr[k]
      }
    }
  ' ${COH_DOCKETS[@]+"${COH_DOCKETS[@]}"} 2>/dev/null | sort -un | tr "\n" " ")

  # (a)+(b): scan the HANDOFF's FORWARD-looking sections ONLY (a resolved ID appearing as an
  # open row there is the recurring failure -- backward-looking "Recently shipped" legitimately
  # lists resolved IDs, so it is excluded by header); detect DUPLICATE ready-signal sections
  # (the portable detector proves at-most-one; update-context's authoring contract still asks for
  # exactly one -- SKILL.md -- but a missing section is an omission, not an incoherence to fire on).
  # The heading match is EXACT (anchored), not a substring: an arbitrary project's "## READY signal
  # timing fix" must NOT count, or it false-THRESHOLDs any non-convention HANDOFF (P1-1b).
  COH_OUT=$(awk -v CLOSEDLIST="$CLOSED" '
    function tabsubj(line,   n,i,parts,cell,c2,out) {
      n=split(line,parts,"|"); out=""
      for(i=1;i<=n;i++){ cell=parts[i]; sub(/^[[:space:]]+/,"",cell); sub(/[[:space:]]+$/,"",cell); sub(/^\*\*/,"",cell)
        if(cell ~ /^G#[0-9]+/){ c2=cell; while(match(c2,/G#[0-9]+/)){ out=out" " (substr(c2,RSTART+2,RLENGTH-2)+0); c2=substr(c2,RSTART+RLENGTH) } } }
      return out
    }
    BEGIN { nc=split(CLOSEDLIST,a," "); for(i=1;i<=nc;i++) if(a[i]!="") closed[a[i]+0]=1 }
    /^#{1,6}[[:space:]]/ {
      h=tolower($0)
      forward=(h ~ /docket|ready signal|pick[ -]?up|open work|open candidate|open item|next task|next step|next session|entry point|pending user decision|pending decision|files to read/)?1:0
      if (h ~ /^#{1,6}[[:space:]]+ready signal([[:space:]]+#+)?[[:space:]]*$/) rs++
      next
    }
    # P2-5 (accepted limitation, by design): the top "**One-line status:**" / "**Summary:**" PREAMBLE
    # prose (before any forward heading) is NOT scanned. It is prose, not a "- **G#N**" bullet / table
    # row, so scanning it would need to distinguish an open-claim from a backward-looking "Resolved
    # G#N" recap -- an unbounded heuristic the row grammar deliberately avoids (only an OPEN-ROW claim
    # is an incoherence; a narrative mention is permitted). A resolved id claimed as top item ONLY in
    # the status prose is an accepted false-negative; the operational docket stays authoritative.
    forward && match($0, /^[[:space:]]*-[[:space:]]*\*\*[^*]+\*\*/) {
      tmp=substr($0,RSTART,RLENGTH)   # leading bold span = the row subject (handles a grouped **G#a / G#b / G#c** row)
      while (match(tmp,/G#[0-9]+/)) { n=substr(tmp,RSTART+2,RLENGTH-2)+0; if ((n in closed) && !(n in seen)) { seen[n]=1; print "STALE " n } tmp=substr(tmp,RSTART+RLENGTH) }
    }
    forward && match($0, /^[[:space:]]*\|/) {
      subj=tabsubj($0); m=split(subj,arr," ")   # NEW-7: G# subject from ANY dedicated cell, not only the first
      for(k=1;k<=m;k++){ n=arr[k]+0; if ((n in closed) && !(n in seen)) { seen[n]=1; print "STALE " n } }
    }
    END { if (rs>1) print "RS " rs }
  ' "$COH_HANDOFF")

  COH_FINDINGS=$(printf '%s\n' "$COH_OUT" | while IFS= read -r ln; do
    case "$ln" in
      "STALE "*) echo "THRESHOLD HANDOFF forward section lists G#${ln#STALE } as an OPEN row, but it is resolved/retired in the docket ledger -- REWRITE the stale section (rotate, don't append) this run" ;;
      "RS "*)    echo "THRESHOLD HANDOFF has ${ln#RS } 'Ready signal' section(s) -- more than one current signal found; a stale block survived below the fold. Rewrite to one." ;;
    esac
  done)

  # (c): open-count recompute -- ONLY when a DEDICATED docket file exists (each open item is its
  # own row there; an inline HANDOFF docket groups IDs on one row and would mis-count), and only
  # on a confident numeric mismatch. Clearable: recomputing the stated count clears it.
  COH_PRIMARY=""
  for f in roadmap.md ./*docket*.md ./*_docket.md context/roadmap.md context/*docket*.md continuation/roadmap.md continuation/*docket*.md; do
    [ -f "$f" ] && { COH_PRIMARY="$f"; break; }
  done
  # NEW-6: a memory-dir-only docket home must reach the COUNT recompute too, not just the CLOSED scan
  # -- else a memory-dir docket misses the stale-count + self-contradiction checks. In-repo wins
  # (precedence above); fall back to the same CANDIDATES memory dirs COH_DOCKETS uses.
  if [ -z "$COH_PRIMARY" ]; then
    for d in ${CANDIDATES[@]+"${CANDIDATES[@]}"}; do
      for f in "$d/roadmap.md" "$d"/*docket*.md; do [ -f "$f" ] && { COH_PRIMARY="$f"; break 2; }; done
    done
  fi
  if [ -n "$COH_PRIMARY" ]; then
    # NEW-2 (member-of-set): the DISTINCT stated open-counts (identical repeats collapse via sort -un).
    # A comparative phrase ("from 9 ... to 2 open candidates") yields multiple values; head -1 would
    # pick the stale first one and false-fire, so we compare the recompute against the whole SET.
    COH_COUNTS=$(grep -oE '[0-9]+ open (candidate|item|goal|task)' "$COH_HANDOFF" 2>/dev/null | grep -oE '^[0-9]+' | sort -un)
    if [ -n "$COH_COUNTS" ]; then
      # RECOMP = genuinely-open G# rows in the docket's open section. Emits three space-separated
      # fields: <recomp> <valid> <contradictions>.
      #  - NEW-1a: a resolved id parked under the open heading is SUBTRACTED (it is in CLOSED), so the
      #    recompute counts only genuinely-open ids.
      #  - NEW-1b: such an id is ALSO reported as the docket's own open-vs-resolved self-contradiction.
      #  - P1-2: valid=1 marks that a recognized open section WAS parsed even when it holds zero rows,
      #    so a valid-but-EMPTY docket (recomp 0) is still compared against a stale nonzero claim
      #    instead of being skipped as if no section existed (the live docket-exhaustion risk).
      COH_CRES=$(awk -v CLOSEDLIST="$CLOSED" '
        function tabsubj(line,   n,i,parts,cell,c2,out) {
          n=split(line,parts,"|"); out=""
          for(i=1;i<=n;i++){ cell=parts[i]; sub(/^[[:space:]]+/,"",cell); sub(/[[:space:]]+$/,"",cell); sub(/^\*\*/,"",cell)
            if(cell ~ /^G#[0-9]+/){ c2=cell; while(match(c2,/G#[0-9]+/)){ out=out" " (substr(c2,RSTART+2,RLENGTH-2)+0); c2=substr(c2,RSTART+RLENGTH) } } }
          return out
        }
        BEGIN { nc=split(CLOSEDLIST,a," "); for(i=1;i<=nc;i++) if(a[i]!="") closed[a[i]+0]=1 }
        FNR==1 { opensec=0 }
        /^#{1,6}[[:space:]]/ {
          h=tolower($0)
          # a resolved/retired heading ends the open block; an open-keyword heading starts it (and
          # marks the section VALID); a NEW top-level (##) section ends it -- but deeper (###/####)
          # descriptive sub-headings (In progress / Blocked / High) keep opensec, so their rows count.
          if (h ~ /resolved|retired|archived|closed|dropped|shipped/) opensec=0
          else if (h ~ /open candidate|open work|open item|pick up here|next task|next step/) { opensec=1; valid=1 }
          else if ($0 ~ /^##[[:space:]]/) opensec=0
          next
        }
        opensec && match($0, /^[[:space:]]*-[[:space:]]*\*\*[^*]+\*\*/) {
          tmp=substr($0,RSTART,RLENGTH)
          while (match(tmp,/G#[0-9]+/)) {
            n=substr(tmp,RSTART+2,RLENGTH-2)+0
            if (n in closed) contra[n]=1; else ids[n]=1
            tmp=substr(tmp,RSTART+RLENGTH)
          }
        }
        opensec && match($0, /^[[:space:]]*\|/) {
          # NEW-7: count table docket rows too (any dedicated G# cell), else P1-2 (valid open section,
          # recompute 0) false-fires the count check on a sanctioned table docket.
          subj=tabsubj($0); m=split(subj,arr," ")
          for(k=1;k<=m;k++){ n=arr[k]+0; if (n in closed) contra[n]=1; else ids[n]=1 }
        }
        END { c=0; for(k in ids) c++; cc=0; for(k in contra) cc++; print c, valid+0, cc }
      ' "$COH_PRIMARY")
      read -r RECOMP RECOMP_VALID CONTRA <<EOF2
$COH_CRES
EOF2
      RECOMP="${RECOMP:-0}"; RECOMP_VALID="${RECOMP_VALID:-0}"; CONTRA="${CONTRA:-0}"
      # P1-2 + NEW-2: fire the count mismatch only when a valid open section was parsed AND the
      # recomputed genuine-open count matches NONE of the stated counts. grep -qx: single pattern,
      # no -i/-F (git-bash grep-3.0 SIGABRT-safe), whole-line numeric match ('1' never matches '10').
      # Blind spot (documented, accepted): member-of-set clears whenever RECOMP equals ANY stated
      # number, so a current-vs-historical count swap ("now 2, was 9" while the docket still holds 9)
      # is NOT caught -- the alternative (head -1 / tail -1) false-fires on the ordinary comparative.
      if [ "$RECOMP_VALID" = "1" ] && ! printf '%s\n' "$COH_COUNTS" | grep -qx "$RECOMP"; then
        COH_FINDINGS="${COH_FINDINGS:+$COH_FINDINGS
}THRESHOLD HANDOFF's stated open-count(s) [$(echo $COH_COUNTS)] match NONE of the docket's recomputed $RECOMP genuine-open G# row(s) in $COH_PRIMARY -- recompute the open-count from the docket this run (do not carry it)"
      fi
      # NEW-1b: the docket itself lists an id as OPEN that its own resolved/retired ledger marks closed.
      if [ "$CONTRA" -ge 1 ] 2>/dev/null; then
        COH_FINDINGS="${COH_FINDINGS:+$COH_FINDINGS
}THRESHOLD the docket ($COH_PRIMARY) lists $CONTRA G# id(s) as OPEN that its own resolved/retired ledger also marks closed -- an open-vs-resolved self-contradiction; resolve it this run"
      fi
    fi
  fi

  [ -z "${CLOSED// /}" ] && echo "(no resolved-ledger G# rows detected -- open/closed ID cross-check skipped; ready-signal + count checks still ran)"
  if [ -n "$COH_FINDINGS" ]; then
    printf '%s\n' "$COH_FINDINGS"
  else
    echo "(coherence clean -- no resolved ID in a HANDOFF forward section; no duplicate ready signal; stated open-count consistent)"
  fi
fi

echo
echo "== VERDICT =="
echo "Every TRIAGE line needs a class (commit/delete/leave-untracked). Every THRESHOLD line triggers"
echo "the rotation or hygiene pass in THIS run. Porcelain paths missing from the audit artifact = incomplete wrap."
echo "INFO lines are visibility-only (held or assessment); no mandatory action this run."
