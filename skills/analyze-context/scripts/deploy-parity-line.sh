#!/usr/bin/env bash
# deploy-parity-line.sh -- print the ONE production-vs-git line for a project that declares
# a deploy target (deploy-parity.json at the repo root), and print NOTHING for a project that
# does not. Shared by analyze-context's currency gate and update-context's evidence script,
# so the briefing and the wrap read production the same way and neither depends on someone
# remembering a command. Read-only (HTTP GETs + git reads). Always exits 0.
#
# The line is a STATE, not a FINDING: production trailing HEAD is normal when deploys are
# manual. What it replaces is the hand-written "production is current" sentence, which is
# only ever true as of the moment it was measured. "could not check" is reported, never
# swallowed -- a silent skip would read as "nothing to report".
#
# DEPLOY_PARITY_BUDGET (seconds, default 120) bounds the fetches.
set -u
TOP=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -f "$TOP/deploy-parity.json" ] || exit 0
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
echo
echo "== DEPLOY PARITY (production vs HEAD; this project declares deploy-parity.json) =="
PY=""
# `python` first: on Windows a bare `python3` can resolve to the Microsoft Store alias stub.
for c in python python3 py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
if [ ! -f "$HERE/deploy-parity.py" ]; then
  echo "production: could not check -- deploy-parity.py is missing beside deploy-parity-line.sh"
elif [ -z "$PY" ]; then
  echo "production: could not check -- no Python 3.9+ on PATH"
else
  OUT=$("$PY" "$HERE/deploy-parity.py" --repo "$TOP" --brief --budget "${DEPLOY_PARITY_BUDGET:-120}" 2>&1)
  RC=$?
  printf '%s\n' "$OUT"
  case "$RC" in
    0|1|2) ;;
    *) echo "production: could not check -- deploy-parity.py exited $RC (a crash, not a verdict)" ;;
  esac
fi
echo "(a state line, not a FINDING -- carry it verbatim into the briefing / handoff; detail: python $HERE/deploy-parity.py)"
exit 0
