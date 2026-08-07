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
        if (!infence) {
          # CommonMark: a BACKTICK fence info string may not contain a backtick, so ```lang`x is
          # a paragraph, not a fence. Rejecting it as an opener keeps a marker below it LIVE
          # (fail-safe: never fence-suppress a real hold). Tilde fences allow ~ and ` in the info
          # string, so this check is scoped to backtick openers only. (no apostrophes in this awk.)
          if (mc == "`" && index(substr(raw, RSTART + RLENGTH), "`") > 0) { scan(raw, 0); next }
          infence = 1; ofc = mc; ofl = ml; bn = 0; next                    # open: start buffering
        }
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
# A project's pickup-point HEADER SHAPE and inline KEEP CEILING are both declarable.
# A running log that uses its own header format (e.g. '**Last Updated:**' /
# '**Prior:**' headers) counts 0 against the literal 'PICKUP POINT' forever, so the rotation
# THRESHOLD can never fire and the miss reports as a clean zero. Declaring the ceiling
# matters too: a project that legitimately keeps ~24 entries inline would otherwise trade
# a permanent false zero for a permanent false alarm. Both defaults reproduce the generic
# contract byte-for-byte. Siblings: READPATH_KB_LIMIT, MAXLINE_LIMIT.
PICKUP_RE=${PICKUP_HEADER_RE:-PICKUP POINT}
PICKUP_KEEP=${PICKUP_KEEP_LIMIT:-3}
for w in continuation/context.md CONTEXT.md; do
  [ -f "$w" ] || continue
  P=$(grep -cE "$PICKUP_RE" "$w" 2>/dev/null); P=${P:-0}
  L=$(wc -l < "$w" | tr -d ' ')
  echo "$w: $L lines, $P pickup points"
  [ "$P" -gt "$PICKUP_KEEP" ] && echo "THRESHOLD $w holds $P pickup points (keep newest $PICKUP_KEEP inline) — rotate older to archive this run"
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
# Overridable for parity with its two sibling size checks (HANDOFF_STRUCT_KB_LIMIT,
# READPATH_KB_LIMIT): a project whose log format is deliberately one dense entry per
# physical line trips the literal every wrap with "acknowledge, do not act" as the only
# correct response — a THRESHOLD that can only ever be ignored trains the wrap to ignore
# THRESHOLDs. Declare a real ceiling in .claude/settings.json -> env instead.
MAXLINE_LIMIT=${MAXLINE_LIMIT:-4000}
for f in continuation/context.md CONTEXT.md HANDOFF.md context/HANDOFF.md HANDOFF-*.md; do
  [ -f "$f" ] || continue
  MAXLEN=$(LC_ALL=en_US.UTF-8 awk '{ if (length > m) m = length } END { print m+0 }' "$f")
  [ "$MAXLEN" -gt "$MAXLINE_LIMIT" ] && echo "THRESHOLD $f max line length ${MAXLEN} chars (>${MAXLINE_LIMIT}) — single-line accretion; rewrite that line to current state and archive the displaced history this run"
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

  # (d) G#208: a commit that CLAIMS to have shipped/closed a G# row whose row marker is still OPEN.
  # Measured origin: a docket's own shipment log recorded 3 rows as shipped ("Phase 3a (68bcc23): #194
  # + #200-t1 + #201 ... ship-check clean") while all 3 ROWS stayed open in the SAME file; the
  # contradiction survived multiple sessions and two external-review passes, then sent a fresh
  # 25-agent session at work already done.
  #
  # ADVISORY (INFO), never THRESHOLD and never auto-flipping -- both constraints come from the row and
  # both are load-bearing: commits legitimately reference rows they do not close, and a row can be
  # RIGHT to stay open (a tier-1 fix shipping does not close a row whose tier-2 is pending; one of the
  # four measured fixes was genuinely incomplete). Auto-flipping here would reproduce the false-closure
  # mechanism G#460 was built to stop.
  #
  # PRECISION, deliberately, and it took two cuts: a BARE mention of an id is NOT a claim. An ingest
  # commit legitimately names every id it files (this repo's own ingest commits name 20+ open ids
  # each), so firing on bare mentions would make this a permanently-noisy line that gets ignored --
  # the disabled-gate failure this estate already documents.
  #
  # SAME-LINE co-occurrence of a verb and an id is ALSO too weak -- measured on this repo's own
  # history, it produced 22 findings of which the large majority were prose ("...unreferenced URL
  # (G#491); G#455 shipped the re-derivation..." puts `shipped` and G#491 on one physical line while
  # asserting nothing about G#491). The predicate is therefore ADJACENCY: a closure verb and the id
  # separated only by other ids, list separators, or a small filler set. That accepts the real
  # shapes -- "close G#459, G#412, G#234" (one verb, a list) and "G#123 RESOLVED" (verb after) --
  # and rejects prose where an unrelated clause sits between them.
  # Accepted false-negatives, stated rather than discovered later: a claim whose verb is on a
  # different line from the id, and one whose verb is separated from it by unlisted filler.
  # Verb matching runs in awk (tolower + punctuation-folded, so "closes:" and "(fixed)" both match),
  # never `grep -i`, which SIGABRTs on git-bash grep 3.0 with -F or 2+ patterns.
  #
  # SCOPE IS PRINTED, NOT IMPLIED (G#493): this reads COMMITTED history only (G#432 -- an uncommitted
  # fix is invisible to it) and only the most recent SE_COMMIT_WINDOW commits. The complement is
  # DERIVED and printed beside the verdict, and prints UNKNOWN rather than 0 if it cannot be derived,
  # because 0 is the one value meaning "nothing was skipped".
  SE_COMMIT_WINDOW="${SE_COMMIT_WINDOW:-200}"
  if git rev-parse --git-dir >/dev/null 2>&1; then
    # Every id that EXISTS as a docket row (leading-bold row subject or dedicated table cell). An id
    # named by a commit but absent from the docket is NOT reported: it is an unknown/foreign id
    # (another repo's numbering, a PR ref), not a stale row.
    COH_ALLROWS=$(awk '
      function tabsubj(line,   n,i,parts,cell,c2,out) {
        n=split(line,parts,"|"); out=""
        for(i=1;i<=n;i++){ cell=parts[i]; sub(/^[[:space:]]+/,"",cell); sub(/[[:space:]]+$/,"",cell); sub(/^\*\*/,"",cell)
          if(cell ~ /^G#[0-9]+/){ c2=cell; while(match(c2,/G#[0-9]+/)){ out=out" " (substr(c2,RSTART+2,RLENGTH-2)+0); c2=substr(c2,RSTART+RLENGTH) } } }
        return out
      }
      match($0, /^[[:space:]]*-[[:space:]]*\*\*[^*]+\*\*/) {
        tmp=substr($0,RSTART,RLENGTH)
        while (match(tmp,/G#[0-9]+/)) { print substr(tmp,RSTART+2,RLENGTH-2)+0; tmp=substr(tmp,RSTART+RLENGTH) }
      }
      match($0, /^[[:space:]]*\|/) { subj=tabsubj($0); m=split(subj,arr," "); for(k=1;k<=m;k++) print arr[k] }
    ' ${COH_DOCKETS[@]+"${COH_DOCKETS[@]}"} 2>/dev/null | sort -un | tr "\n" " ")

    COH_TOTALC=$(git rev-list --count HEAD 2>/dev/null || echo "")
    if [ -z "$COH_TOTALC" ]; then
      COH_SCANNED="UNKNOWN"; COH_SKIPPED="UNKNOWN"
    else
      COH_SCANNED="$COH_TOTALC"
      [ "$COH_TOTALC" -gt "$SE_COMMIT_WINDOW" ] && COH_SCANNED="$SE_COMMIT_WINDOW"
      COH_SKIPPED=$((COH_TOTALC - COH_SCANNED))
    fi
    COH_DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
    echo "INFO commit-vs-open-row scope: HEAD $(git rev-parse --short HEAD 2>/dev/null || echo '?'), scanned $COH_SCANNED of ${COH_TOTALC:-UNKNOWN} commit(s), $COH_SKIPPED NOT scanned; ${COH_DIRTY:-0} uncommitted change(s) NOT included (committed history only)"

    COH_SHIPCLAIMS=$(git log -n "$SE_COMMIT_WINDOW" --format='%x01%h %s%n%b' 2>/dev/null | awk -v CLOSEDLIST="$CLOSED" -v ALLLIST="$COH_ALLROWS" '
      BEGIN {
        nc=split(CLOSEDLIST,a," "); for(i=1;i<=nc;i++) if(a[i]!="") closed[a[i]+0]=1
        na=split(ALLLIST,b," ");    for(i=1;i<=na;i++) if(b[i]!="") known[b[i]+0]=1
        nv=split("close closes closed closing fix fixes fixed resolve resolves resolved ship ships shipped land lands landed complete completes completed done",v," ")
        for(i=1;i<=nv;i++) isverb[v[i]]=1
        nf=split("the this that and plus also both all now row rows item items id ids docket",f," ")
        for(i=1;i<=nf;i++) isfill[f[i]]=1
      }
      # A token chain is CLAIMED when a verb reaches the id through nothing but other ids or filler.
      # "|" is a CLAUSE BREAK (";", ":", ".", "!", "?") and always disarms -- without it, prose like
      # "...(G#491); G#455 shipped..." chains across the semicolon and reports G#491, which is the
      # single largest false-positive source measured on the history of this repo.
      #
      # The two directions get DIFFERENT id-passthrough budgets, and the asymmetry is the point:
      #   backward (verb BEFORE id) -- "close G#459, G#412, G#234, G#142, G#143" -- a list after a
      #     verb is idiomatic and unambiguous, so an unlimited run of ids is allowed.
      #   forward  (verb AFTER id)  -- "G#295/G#296 RESOLVED" -- is far likelier to be prose that
      #     merely ends in a verb, so at most ONE intervening id is allowed. Measured: this is what
      #     rejects "(G#411-G#412) and G#412 shipped" (2 intervening ids) while keeping the real
      #     "G#295/G#296 RESOLVED" claim.
      function reaches(t, n, from, step, maxids,   j, tok, ids) {
        ids=0
        for (j=from+step; j>=1 && j<=n; j+=step) {
          tok=t[j]
          if (tok=="") continue
          if (tok=="|") return 0
          if (isverb[tok]) return 1
          if (isfill[tok]) continue
          if (tok ~ /^g#[0-9]+$/) { ids++; if (maxids>=0 && ids>maxids) return 0; continue }
          return 0
        }
        return 0
      }
      {
        line=$0
        # A record emitted by --format begins with \001<hash>; every other line is a body line
        # belonging to the most recent header seen, so a multi-line body attributes correctly.
        if (substr(line,1,1)=="\001") { line=substr(line,2); cur=line; sub(/ .*/,"",cur) }
        # Clause terminators become an explicit break token FIRST, then the rest folds to spaces.
        # "#" is kept so a G# id survives as one token, and "_" is kept so an identifier such as
        # resolve_ref_repo() stays whole instead of shedding a bare "resolve" that reads as a verb
        # (measured: that split alone produced two false positives on this repo).
        vt=tolower(line); gsub(/[;:.!?]/," | ",vt); gsub(/[^a-z0-9#_|]+/," ",vt)
        ntok=split(vt,tk," ")
        for (i=1;i<=ntok;i++) {
          if (tk[i] !~ /^g#[0-9]+$/) continue
          n=substr(tk[i],3)+0
          if (!(n in known) || (n in closed) || (n in seen)) continue
          if (reaches(tk,ntok,i,-1,-1) || reaches(tk,ntok,i,1,1)) { seen[n]=1; print cur " G#" n }
        }
      }')
    if [ -n "$COH_SHIPCLAIMS" ]; then
      printf '%s\n' "$COH_SHIPCLAIMS" | while IFS=' ' read -r ch cid; do
        [ -n "$cid" ] || continue
        echo "INFO commit $ch claims to have shipped/closed $cid, but its row marker is still OPEN -- verify, then either close the row or record why it stays open. ADVISORY: do NOT auto-flip; a commit may legitimately reference a row it does not close, and a tier-1 fix shipping does not close a row whose tier-2 is pending"
      done
    else
      echo "(no commit in the scanned window claims to have shipped/closed a still-open G# row)"
    fi
  fi

  [ -z "${CLOSED// /}" ] && echo "(no resolved-ledger G# rows detected -- open/closed ID cross-check skipped; ready-signal + count checks still ran)"
  if [ -n "$COH_FINDINGS" ]; then
    printf '%s\n' "$COH_FINDINGS"
  else
    echo "(coherence clean -- no resolved ID in a HANDOFF forward section; no duplicate ready signal; stated open-count consistent)"
  fi
fi

# == PLAN-DOC COHERENCE (G#211): a plan doc's TOP status header vs its own per-task execution records ==
# The doc that RECORDS the work (a per-task execution record) and the doc/section that ROUTES the next
# session (the plan's TOP status header) are different surfaces; a wrap that appends the record but
# leaves the header stale sends the next session to redo finished work -- record correct, router
# contradicts it, sometimes INSIDE THE SAME FILE (measured twice, G#211: a header
# "Tasks 1-7 implemented" above a Task-8 execution record; a NO-GO/OPEN header above a Task-10 COMPLETE
# record). CONSERVATIVE FRONTIER CHECK, by design: fire ONLY when the topmost "Tasks 1-K
# implemented/done" claim counts FEWER tasks than the highest task that already carries an "execution
# record" heading below. Two properties keep the false-positive rate near zero: (1) it parses task
# NUMBERS, never status WORDS -- a doc that deliberately preserves an old NO-GO checkpoint beneath a
# corrected top status never fires; (2) it takes the MAX stated frontier across the accreted header
# checkpoints, so a stale lower checkpoint alongside a current higher one is not flagged. Encoding-
# robust ([^0-9]+ spans an en/em-dash of any bytes so "Tasks 1-10" and "Tasks 1–– 10" both parse).
# Read-only; degrades to a clean skip on any project with no plan docs. Independent of HANDOFF presence.
PLAN_FILES=()
while IFS= read -r pf; do [ -f "$pf" ] && PLAN_FILES+=("$pf"); done < <(
  find docs context continuation -type f -path '*plans*' -name '*.md' 2>/dev/null
)
PLAN_FINDINGS=""
for pf in ${PLAN_FILES[@]+"${PLAN_FILES[@]}"}; do
  PLAN_OUT=$(awk '
    # header region = every line before the FIRST "## " section heading (the preamble + status
    # blockquotes). K_claim = the HIGHEST "Tasks 1<sep>K" frontier whose completion word
    # (implemented|done|complete) FOLLOWS the range in the SAME CLAUSE (no . or ; between) -- so a mixed
    # "Tasks 1-7 pending; Task 8 complete" does not bind "complete" to the pending 1-7 range (F14/c), and
    # the leading [^a-z] stops "incomplete"/"unimplemented"/"undone" from counting as completion (F14/a).
    # Fenced ``` regions are skipped so an EXAMPLE record/status inside a code block is not parsed (F14/d).
    # The frontier VALUE is number-derived; the status word only GATES the extraction (not a polarity
    # parse). A single "#"-level title does not close the header region.
    /^```/ { infence = !infence; next }
    NR==1 { inhdr=1 }
    /^##[[:space:]]/ { if (!infence) inhdr=0 }
    inhdr && !infence {
      line=tolower($0)
      if (match(line, /task[s]?[^0-9]*1[^0-9]+[0-9]+[^.;]*[^a-z](implemented|done|complete)/)) {
        seg=substr(line,RSTART,RLENGTH)
        if (match(seg, /[0-9]+[^0-9]*$/)) { k=substr(seg,RSTART)+0; if (k>kclaim) kclaim=k; haveclaim=1 }
      }
    }
    # N_rec = the highest task number in a NON-fenced heading that says "execution record" AND is NOT marked
    # not-done. A record whose heading carries a not-done disposition (the repo convention
    # "### Task N execution record -- <disposition>", e.g. "-- WIP / NO-GO at device handoff") means the
    # work is legitimately incomplete, so the TOP header correctly NOT claiming it is COHERENT, not a
    # lag. (G#211/F12: reading record PRESENCE not DISPOSITION false-fired on coherent WIP device-handoff
    # checkpoints and would have ordered a rewrite that MANUFACTURES the incoherence this check prevents.)
    # Disposition is read from the heading suffix; over-exclusion fails SAFE for this advisory -- it can
    # only miss a real lag (under-fire), never manufacture a bad rewrite. A plain "## Task N:" DEFINITION
    # heading is not a record and is deliberately ignored.
    !infence && /^#{2,6}[[:space:]]/ {
      hl=tolower($0)
      if (hl ~ /execution record/ && hl !~ /wip|no-?go|failed|pending|block|abandon|incomplete|deferred|not (yet )?(done|complete|implemented)|in progress|todo/ && match(hl, /task[^0-9]*[0-9]+/)) {
        seg=substr(hl,RSTART,RLENGTH)
        if (match(seg, /[0-9]+/)) { r=substr(seg,RSTART)+0; if (r>nrec) nrec=r; haverec=1 }
      }
    }
    END { if (haveclaim && haverec && kclaim < nrec) print kclaim, nrec }
  ' "$pf")
  if [ -n "$PLAN_OUT" ]; then
    set -- $PLAN_OUT
    PLAN_FINDINGS="${PLAN_FINDINGS:+$PLAN_FINDINGS
}THRESHOLD plan doc ($pf) TOP status claims 'Tasks 1-$1 implemented' but a Task-$2 execution record exists below -- the routing header lags the record (rewrite the top status THIS run; append-record-and-update-routing are one commit, G#211)"
  fi
done
[ -n "$PLAN_FINDINGS" ] && printf '%s\n' "$PLAN_FINDINGS"

echo
echo "== VERDICT =="
echo "Every TRIAGE line needs a class (commit/delete/leave-untracked). Every THRESHOLD line triggers"
echo "the rotation or hygiene pass in THIS run. Porcelain paths missing from the audit artifact = incomplete wrap."
echo "INFO lines are visibility-only (held or assessment); no mandatory action this run."
