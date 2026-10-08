#!/usr/bin/env bash
# worktrees-note.sh -- name every linked worktree that holds work this checkout's HEAD does not carry.
# Shared by analyze-context's currency gate (session start, inside its WORKTREES section) and
# update-context's evidence script (the wrap, with --header), so neither depends on someone
# remembering to look. Read-only (git worktree list, status, rev-list, merge-base). Run from a
# project root; works from a linked worktree. Always exits 0.
#
# Why it exists: a background build helper works in its own linked worktree (a scratchpad `wt-*`,
# or `<project>/.claude/worktrees/agent-*` under Agent-tool isolation). Stopped before it reports
# (a laptop restart, a departure, a closed session), its partial diff stays there: untracked,
# machine-local, and named by no wrap, departure or briefing step. The gate's own WORKTREES loop
# only reports a worktree whose HEAD commit is NEWER, so uncommitted work printed nothing. Measured
# once: a resumed session saved such a diff by hand (9 files) and the next session landed the build
# from it. reflect-upgrades/scripts/park-worktree.py turns one into a committed patch.
#
# One line per linked worktree other than the MAIN checkout and the CURRENT one, every line a
# `NOTE worktree-<kind>:` (never a FINDING: currency-check.sh counts '^FINDING' lines to stop the
# briefing, and this must not stop anything):
#   work      branch commits not in HEAD, modified or untracked files: path, branch, base (the
#             merge-base with HEAD), and the counts;
#   emptied   every change is a deletion and nothing else is there (a temp cleaner's leftovers):
#             `emptied (prune)`, nothing to park;
#   prunable  git marks it prunable (its directory or .git link is gone), or its directory is gone
#             while a lock keeps the registration;
#   battery   it holds the mutation-harness strand sentinel: a battery in flight or stranded,
#             never build work (the same predicate tests/mutations/shard-battery.py uses);
#   unknown   git status failed there: could not check, never read as clean.
# A clean worktree, or one merely behind HEAD, prints nothing. --header prints a '== WORKTREES =='
# header first, and only when there is a line to print.
set -u

HEADER=""
[ "${1:-}" = "--header" ] && HEADER=1

git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# = SENTINEL_NAME in tests/mutations/mutation_harness.py (tests/test-worktrees-note.py asserts the two
# agree byte for byte, so a rename on either side fails there rather than here, silently).
SENTINEL=".mutation-in-flight.json"

# One spelling per path: forward slashes, lower case, no trailing slash (Windows git prints C:/...,
# and two spellings of one directory must compare equal).
norm() { printf '%s' "$1" | tr 'A-Z\\' 'a-z/' | sed 's:/*$::'; }

CUR=$(git rev-parse --show-toplevel 2>/dev/null)
CURN=$(norm "$CUR")
HEAD_SHA=$(git rev-parse -q --verify HEAD 2>/dev/null)

LINES=()

# One record per line, fields split on the unit separator \037 (a tab is IFS WHITESPACE, so `read`
# would collapse the empty fields of a tab-split record): path, HEAD sha, branch, locked flag,
# prunable reason, bare flag. The first record is the main checkout (git always lists it first).
RECORDS=$(git worktree list --porcelain 2>/dev/null | tr -d '\r' | awk '
  function out() { if (p != "") printf "%s\037%s\037%s\037%s\037%s\037%s\n", p, h, b, l, pr, bare; p = h = b = l = pr = bare = "" }
  /^worktree / { out(); p = substr($0, 10); next }
  /^HEAD /     { h = substr($0, 6); next }
  /^branch /   { b = substr($0, 8); sub(/^refs\/heads\//, "", b); next }
  /^detached/  { b = ""; next }
  /^locked/    { l = "locked"; next }
  /^prunable/  { pr = substr($0, 10); if (pr == "") pr = "prunable"; next }
  /^bare/      { bare = "bare"; next }
  END { out() }')

first=1
while IFS=$'\037' read -r wt wsha wbr wlock wprune wbare; do
  [ -n "$wt" ] || continue
  if [ "$first" = 1 ]; then first=0; continue; fi      # the main checkout (bare or not) is never a helper's
  [ "$(norm "$wt")" = "$CURN" ] && continue            # never the checkout this runs in

  if [ -n "$wprune" ]; then
    LINES+=("NOTE worktree-prunable: $wt -- prunable ($wprune); nothing left to park: git worktree prune")
    continue
  fi
  if [ ! -d "$wt" ]; then
    LINES+=("NOTE worktree-prunable: $wt -- its directory is gone, and a lock keeps the registration; nothing left to park: git worktree unlock \"$wt\" && git worktree prune")
    continue
  fi
  # A worktree whose .git link is gone would let `git -C` discover an ENCLOSING repo (a nested
  # .claude/worktrees/agent-* sits inside the main checkout) and report that repo's state as its own.
  WTOP=$(git -C "$wt" rev-parse --show-toplevel 2>/dev/null)
  if [ "$(norm "$WTOP")" != "$(norm "$wt")" ]; then
    LINES+=("NOTE worktree-prunable: $wt -- its .git link no longer resolves to it; nothing git can read there: inspect the directory, then git worktree prune")
    continue
  fi

  ST=$(git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null); SRC=$?
  if [ "$SRC" -ne 0 ]; then
    LINES+=("NOTE worktree-unknown: $wt -- could not check: git status exited $SRC there; inspect it before treating it as empty")
    continue
  fi
  ST=$(printf '%s' "$ST" | tr -d '\r')
  UNTR=0; MOD=0; DEL=0
  if [ -n "$ST" ]; then
    UNTR=$(printf '%s\n' "$ST" | grep -c '^??')
    MOD=$(printf '%s\n' "$ST" | grep -vc '^??')
    DEL=$(printf '%s\n' "$ST" | grep -cE '^( D|D )')
  fi

  if [ -e "$wt/$SENTINEL" ]; then
    LINES+=("NOTE worktree-battery: $wt -- holds $SENTINEL: a mutation battery in flight or stranded, not build work ($MOD modified); inspect with git -C \"$wt\" diff before anything else, and never park it")
    continue
  fi

  AHEAD=0; BASE=""
  if [ -n "$wsha" ]; then
    if [ -n "$HEAD_SHA" ]; then
      AHEAD=$(git rev-list --count "HEAD..$wsha" 2>/dev/null || echo 0)
      BASE=$(git merge-base HEAD "$wsha" 2>/dev/null)
    else
      AHEAD=$(git rev-list --count "$wsha" 2>/dev/null || echo 0)
    fi
  fi
  [ "$MOD" -eq 0 ] && [ "$UNTR" -eq 0 ] && [ "${AHEAD:-0}" -eq 0 ] && continue    # clean, or merely behind

  LOCKNOTE=""; [ -n "$wlock" ] && LOCKNOTE=", locked"
  if [ "$UNTR" -eq 0 ] && [ "${AHEAD:-0}" -eq 0 ] && [ "$MOD" -gt 0 ] && [ "$DEL" -eq "$MOD" ]; then
    TOTAL=$(git ls-tree -r --name-only "$wsha" 2>/dev/null | grep -c .)
    LINES+=("NOTE worktree-emptied: $wt -- emptied (prune): every change is a deletion ($DEL of $TOTAL tracked files deleted), nothing untracked, no branch commits; nothing to park: git worktree remove --force \"$wt\"${wlock:+ (unlock it first)}")
    continue
  fi

  if [ -n "$wbr" ]; then WHERE="branch $wbr$LOCKNOTE"; else WHERE="detached at ${wsha:0:7}$LOCKNOTE"; fi
  if [ -n "$BASE" ]; then BASEW="base ${BASE:0:7} (merge-base with HEAD)"; else BASEW="base: none (no history in common with HEAD)"; fi
  LINES+=("NOTE worktree-work: $wt ($WHERE) -- $BASEW; ${AHEAD:-0} branch commit(s) not in HEAD; $MOD modified, $UNTR untracked -- work HEAD does not carry, on this machine only: park it (python ~/.claude/skills/reflect-upgrades/scripts/park-worktree.py \"$wt\") or drop it")
done <<< "$RECORDS"

[ "${#LINES[@]}" -gt 0 ] || exit 0
if [ -n "$HEADER" ]; then
  echo
  echo "== WORKTREES =="
fi
printf '%s\n' "${LINES[@]}"
exit 0
