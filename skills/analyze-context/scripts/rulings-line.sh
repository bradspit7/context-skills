#!/usr/bin/env bash
# rulings-line.sh -- print this project's standing owner rulings (the briefing's RULED OUT
# section), or with --lost the wrap's RULING LOSS check (a ruling a rewrite silently dropped).
# Shared by analyze-context's currency gate and update-context's evidence script, so neither
# depends on someone remembering to look. Read-only (file reads + git reads). Always exits 0.
#
# Why it exists: a briefing built from current state cannot show a decision whose whole content
# is that something will NOT happen. A docket row rewritten from NEW to BUILT dropped the block
# holding two killed options, and the next session proposed both back to the owner.
#
# Prints NOTHING when the project has no ruling (and, for --lost, outside git). Every failure is
# a 'could not check' line under the section header -- never silence, which would read as
# "there are no rulings". These are STATE lines, never FINDINGs (currency-check.sh counts
# '^FINDING' lines to block synthesis).
set -u
if [ "${1:-}" = "--lost" ]; then
  HDR="== RULING LOSS (owner rulings in HEAD or in commits since the last wrap, gone from the working tree) =="
  TAG="RULING LOSS"
else
  HDR="== RULED OUT (owner rulings - do not re-propose) =="
  TAG="RULED OUT"
fi
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cant() { echo; echo "$HDR"; echo "$TAG: could not check -- $1"; exit 0; }

TOP=$(git rev-parse --show-toplevel 2>/dev/null) || TOP=""
[ -n "$TOP" ] || TOP=$(pwd)
[ -f "$HERE/rulings.py" ] || cant "rulings.py is missing beside rulings-line.sh"
PY=""
# `python` first: on Windows a bare `python3` can resolve to the Microsoft Store alias stub.
for c in python python3 py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || cant "no Python 3.8+ on PATH"

ERRF=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/rulings.$$")
OUT=$(cd "$TOP" && "$PY" "$HERE/rulings.py" "$@" 2>"$ERRF")
RC=$?
[ -n "$OUT" ] && printf '%s\n' "$OUT"
if [ "$RC" -ne 0 ]; then
  WHY=$(grep -v '^[[:space:]]*$' "$ERRF" 2>/dev/null | tail -1 | tr -d '\r' | cut -c1-200)
  [ -n "$OUT" ] || { echo; echo "$HDR"; }
  echo "$TAG: could not check -- rulings.py exited $RC (a crash, not a verdict)${WHY:+: $WHY}"
fi
rm -f "$ERRF" 2>/dev/null
exit 0
