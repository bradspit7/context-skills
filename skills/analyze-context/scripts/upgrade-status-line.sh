#!/usr/bin/env bash
# upgrade-status-line.sh -- print what is PENDING or RECENTLY LANDED in this project's upgrade
# loop, so the briefing (currency-check.sh) and the wrap (session-evidence.sh) show it without
# anyone asking. Prints NOTHING when there is nothing to report. Read-only (file reads + git
# log). Always exits 0.
#
# Up to three lines under one '== UPGRADES ==' header:
#   pending inbox:   DOCKET-INBOX-*.md filings sitting at this project's root -- count, the
#                    oldest and its age in days (date from the FILENAME; mtime only when the
#                    name carries no date), up to 5 names oldest-first, then 'and N more'.
#                    A handback left at a project root is otherwise read by nobody.
#   upgrade queue:   UPGRADE-QUEUE.md at the root. Each item is a level-2 heading
#                    '## YYYY-MM-DD <U+00B7> <title>', oldest first, cap 5. A '## ' heading in any
#                    other shape is reported as NOT counted rather than silently dropped.
#   landed here in the last 30 days:
#                    every line that STARTS with 'Upgrade:' in the full message of each commit
#                    of the last 30 days (newest 5, with the short sha, then 'and N more').
#                    The whole message is read, not git's trailer block: the commit shape puts
#                    'Upgrade:' ABOVE a Co-Authored-By paragraph, where the trailer parser
#                    never looks.
#
# These are STATE lines, never FINDINGs: nothing printed here may start with FINDING, because
# currency-check.sh counts '^FINDING' lines to block synthesis. A git failure prints
# 'could not check: <reason>' -- never silence, which would read as "nothing landed".
set -u
# Byte semantics throughout: the queue separator is a two-byte UTF-8 character, and sort/awk
# must not depend on whatever locale the calling shell happened to have.
export LC_ALL=C

if TOP=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$TOP" ]; then
  IN_GIT=1
else
  TOP=$(pwd); IN_GIT=0
fi

TODAY=$(date +%Y-%m-%d 2>/dev/null)
MID=$(printf '\302\267')     # U+00B7 MIDDLE DOT, the queue heading separator (kept out of the source bytes)

# Days since 1970-01-01 for a Y M D triple (proleptic Gregorian). Pure shell arithmetic, so it
# behaves the same under GNU and BSD date -- `date -d` does not exist on BSD/macOS.
_days() {
  local y=$((10#$1)) m=$((10#$2)) d=$((10#$3)) era yoe mp doy doe
  [ "$m" -le 2 ] && y=$((y - 1))
  era=$(( (y >= 0 ? y : y - 399) / 400 ))
  yoe=$(( y - era * 400 ))
  mp=$(( (m + 9) % 12 ))
  doy=$(( (153 * mp + 2) / 5 + d - 1 ))
  doe=$(( yoe * 365 + yoe / 4 - yoe / 100 + doy ))
  echo $(( era * 146097 + doe - 719468 ))
}
_age_days() {   # $1 = YYYY-MM-DD
  local a b
  a=$(_days "${1:0:4}" "${1:5:2}" "${1:8:2}")
  b=$(_days "${TODAY:0:4}" "${TODAY:5:2}" "${TODAY:8:2}")
  echo $(( b - a ))
}
_mtime_date() {   # GNU `date -r <file>` first, then BSD `stat -f`, then GNU `stat -c`
  local d
  d=$(date -r "$1" '+%Y-%m-%d' 2>/dev/null) && [ -n "$d" ] && { echo "$d"; return 0; }
  d=$(stat -f '%Sm' -t '%Y-%m-%d' "$1" 2>/dev/null) && [ -n "$d" ] && { echo "$d"; return 0; }
  d=$(stat -c '%y' "$1" 2>/dev/null) && echo "${d:0:10}"
}

OUT=()

# ---- (a) pending inbox -----------------------------------------------------------------------
# Filings land on the DEFAULT branch whatever is checked out (file-inbox.py commits there), and
# ingest drains them there. A checkout on the default branch reads its own root (which also sees an
# untracked handback). A checkout on any OTHER branch -- a linked worktree, a feature branch,
# a detached HEAD -- sees its branch-point snapshot instead: it listed a filing the default branch
# had already drained (inviting a duplicate ingest) and missed one that landed after the branch
# point. So there the pending set is: the default branch's filings, PLUS any filing committed only
# on this branch (never added on the default branch), PLUS any untracked one at this root. A filing
# that WAS added on the default branch and is gone from its tip was drained, and is not pending.
# The line then says which ref it read. With no default branch known (no origin/HEAD) the root is
# read as before.
# Append one sortable row "date<TAB>source<TAB>name[suffix]" to ROWS. The date comes from the NAME;
# only an undated name pays for a fallback (the file's mtime, or the commit that last touched it on
# a ref). No subshell for a dated name: a fork per filing cost seconds on Windows.
#   $1 fallback (mtime|commit)  $2 name  $3 suffix  $4 file path (mtime) or ref (commit)
_addrow() {
  local b="$2" d src
  if [[ "$b" =~ ^DOCKET-INBOX-([0-9]{4}-[0-9]{2}-[0-9]{2}) ]]; then
    d=${BASH_REMATCH[1]}; src=name
  else
    src=$1
    if [ "$1" = mtime ]; then d=$(_mtime_date "$4")
    else d=$(git -C "$TOP" log -1 --format=%cd --date=short "$4" -- "$b" 2>/dev/null); fi
  fi
  [[ "$d" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { d="9999-12-31"; src=undated; }
  ROWS="$ROWS$d"$'\t'"$src"$'\t'"$b$3"$'\n'
}
ROWS=""; FROM="at the project root"
DEF=""; CUR=""; DEFREF=""
if [ "$IN_GIT" = 1 ]; then
  DEF=$(git -C "$TOP" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null); DEF=${DEF#origin/}
  CUR=$(git -C "$TOP" symbolic-ref -q --short HEAD 2>/dev/null)
  if [ -n "$DEF" ] && [ "$CUR" != "$DEF" ]; then
    if git -C "$TOP" rev-parse -q --verify "refs/heads/$DEF^{commit}" >/dev/null 2>&1; then
      DEFREF="refs/heads/$DEF"; DEFSHOW="$DEF"
    elif git -C "$TOP" rev-parse -q --verify "refs/remotes/origin/$DEF^{commit}" >/dev/null 2>&1; then
      DEFREF="refs/remotes/origin/$DEF"; DEFSHOW="origin/$DEF"
    fi
  fi
fi
if [ -n "$DEFREF" ]; then
  DSHA=$(git -C "$TOP" rev-parse --short "$DEFREF" 2>/dev/null)
  FROM="read from $DEFSHOW@$DSHA (the default branch, where filings land -- this checkout is on ${CUR:-a detached HEAD})"
  SEEN=$'\n'
  _tree_names() { git -C "$TOP" ls-tree -z --name-only "$1" 2>/dev/null | tr '\0' '\n' | grep -E '^DOCKET-INBOX-.*[.]md$'; }
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    _addrow commit "$b" "" "$DEFREF"; SEEN="$SEEN$b"$'\n'
  done < <(_tree_names "$DEFREF")
  EVER=""
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    case "$SEEN" in *$'\n'"$b"$'\n'*) continue ;; esac
    if [ -z "$EVER" ]; then   # one pass over the default branch's history, only when needed
      EVER=$'\n'$(git -C "$TOP" log --format= --name-only --diff-filter=A "$DEFREF" -- 'DOCKET-INBOX-*.md' 2>/dev/null)$'\n'
    fi
    case "$EVER" in *$'\n'"$b"$'\n'*) continue ;; esac     # was on the default branch: drained
    _addrow commit "$b" " [only on this branch]" HEAD; SEEN="$SEEN$b"$'\n'
  done < <(_tree_names HEAD)
  while IFS= read -r b; do
    [ -n "$b" ] || continue
    case "$SEEN" in *$'\n'"$b"$'\n'*) continue ;; esac
    _addrow mtime "$b" " [untracked here]" "$TOP/$b"
  done < <(git -C "$TOP" ls-files --others --exclude-standard -- 'DOCKET-INBOX-*.md' 2>/dev/null)
else
  shopt -s nullglob
  for f in "$TOP"/DOCKET-INBOX-*.md; do _addrow mtime "${f##*/}" "" "$f"; done
  shopt -u nullglob
fi
if [ -n "$ROWS" ]; then
  SORTED=$(printf '%s' "$ROWS" | LC_ALL=C sort)     # ROWS ends in a newline: no blank row to sort first
  N=$(printf '%s\n' "$SORTED" | grep -c .)
  IFS=$'\t' read -r od osrc oname <<< "$(printf '%s\n' "$SORTED" | head -1)"
  if [ "$osrc" = undated ]; then
    AGE="age unknown (no date in the name, no readable mtime)"
  else
    AGE="$(_age_days "$od") day(s)"
    [ "$osrc" = mtime ] && AGE="$AGE (from mtime; no date in the name)"
    [ "$osrc" = commit ] && AGE="$AGE (from its commit date; no date in the name)"
  fi
  NAMES=$(printf '%s\n' "$SORTED" | head -5 | cut -f3 | paste -sd, - | sed 's/,/, /g')
  MORE=""
  [ "$N" -gt 5 ] && MORE=" and $((N - 5)) more"
  OUT+=("pending inbox: $N DOCKET-INBOX file(s) $FROM, oldest $AGE ($oname): ${NAMES}${MORE}")
fi

# ---- (b) the upgrade queue -------------------------------------------------------------------
Q="$TOP/UPGRADE-QUEUE.md"
if [ -f "$Q" ]; then
  QN=0; QBAD=0; QOLD=""; QTITLE=""
  while IFS= read -r ln || [ -n "$ln" ]; do
    ln=${ln%$'\r'}
    case "$ln" in "## "*) ;; *) continue ;; esac
    qd=""; qt=""
    if [[ "$ln" =~ ^'## '([0-9]{4}-[0-9]{2}-[0-9]{2})' '(.*)$ ]]; then
      qd=${BASH_REMATCH[1]}
      case "${BASH_REMATCH[2]}" in "$MID "?*) qt=${BASH_REMATCH[2]#"$MID "} ;; esac
    fi
    if [ -n "$qt" ]; then
      QN=$((QN + 1))
      if [ -z "$QOLD" ] || [[ "$qd" < "$QOLD" ]]; then QOLD=$qd; QTITLE=$qt; fi
    else
      QBAD=$((QBAD + 1))
    fi
  done < "$Q"
  if [ "$QN" -gt 0 ] || [ "$QBAD" -gt 0 ]; then
    QL="upgrade queue: $QN item(s)"
    [ "$QN" -gt 0 ] && QL="$QL, oldest $QOLD $QTITLE"
    [ "$QN" -ge 5 ] && QL="$QL -- FULL (cap 5)"
    [ "$QBAD" -gt 0 ] && QL="$QL ($QBAD '## ' heading(s) not in the '## YYYY-MM-DD $MID <title>' form -- not counted)"
    OUT+=("$QL")
  fi
fi

# ---- (c) Upgrade: lines landed in the last 30 days -------------------------------------------
RECENT=()
if [ "$IN_GIT" = 1 ] && git -C "$TOP" rev-parse -q --verify 'HEAD^{commit}' >/dev/null 2>&1; then
  ERRF=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/usl.$$")
  LOG=$(git -C "$TOP" log --since=30.days --format='%x1e%h%x1f%B' 2>"$ERRF")
  LRC=$?
  if [ "$LRC" -ne 0 ]; then
    WHY=$(head -1 "$ERRF" 2>/dev/null | tr -d '\r' | cut -c1-160)
    RECENT=("landed here in the last 30 days: could not check: git log exited $LRC${WHY:+ -- $WHY}")
  else
    HITS=$(printf '%s' "$LOG" | LC_ALL=C awk 'BEGIN { RS = "\036"; FS = "\037" }
      NF >= 2 {
        n = split($2, L, "\n")
        for (i = 1; i <= n; i++) {
          l = L[i]; sub(/\r$/, "", l)
          if (l ~ /^Upgrade:[ \t]*[^ \t]/) { sub(/^Upgrade:[ \t]*/, "", l); print $1 "\t" l }
        }
      }')
    if [ -n "$HITS" ]; then
      HN=$(printf '%s\n' "$HITS" | grep -c .)
      RECENT=("landed here in the last 30 days:")
      while IFS=$'\t' read -r sha sentence; do
        RECENT+=("  $sha  $sentence")
      done < <(printf '%s\n' "$HITS" | head -5)
      [ "$HN" -gt 5 ] && RECENT+=("  and $((HN - 5)) more")
    fi
  fi
  rm -f "$ERRF" 2>/dev/null
fi

if [ "${#OUT[@]}" -gt 0 ] || [ "${#RECENT[@]}" -gt 0 ]; then
  echo
  echo "== UPGRADES =="
  for l in ${OUT[@]+"${OUT[@]}"} ${RECENT[@]+"${RECENT[@]}"}; do printf '%s\n' "$l"; done
  # The skill default for anything that is not a FINDING is to move on, so the section says itself
  # where it belongs (the deploy-parity helper does the same).
  echo "(state lines, not FINDINGs -- carry them into the briefing / handoff; a pending inbox, a FULL queue or a could-not-check is an open item)"
fi
exit 0
