#!/usr/bin/env bash
# validate.sh - repo-level integrity gate for context-skills.
#
# Catches the drift classes that have actually bitten this repo:
#   1. SKILL.md frontmatter rot (missing name/description, no --- delimiters)
#   2. docs/skill-list drift (a skill dir not mentioned in README.md / CLAUDE.md)
#   3. shell scripts that no longer parse (bash -n)
#   4. python files that no longer compile
#   5. CRLF line endings (the LF-everywhere rule; CRLF breaks bash run-in-place
#      and parses clean, so it is invisible to bash -n)
#   6. the intentionally-duplicated probe-sync.sh drifting between the two skills
#
# Unlike the lifecycle DIAGNOSTIC scripts (currency-check / session-evidence,
# which exit 0 and signal via FINDING/THRESHOLD lines), this is a GATE: it exits
# non-zero on any failure so it can back a pre-commit hook or CI. Pure bash; runs
# on Windows git-bash and macOS.
set -u
cd "$(dirname "$0")"

fail=0
FAIL() { printf 'FAIL %s\n' "$1"; fail=1; }
OK()   { printf 'OK   %s\n' "$1"; }
note() { printf '     %s\n' "$1"; }

# Keep py_compile bytecode out of the tree.
export PYTHONPYCACHEPREFIX="$(mktemp -d 2>/dev/null || echo "${TMPDIR:-/tmp}/pycache_$$")"

# Pick a python that actually runs (on Windows, `python3` is a Store stub that
# does not execute; prefer real `python`). Test by running it, not just locating.
PY=""
for c in python python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys' >/dev/null 2>&1; then PY="$c"; break; fi
done

# 1. frontmatter present and well-formed
for d in skills/*/; do
  s=$(basename "$d"); f="${d}SKILL.md"
  if [ ! -f "$f" ]; then FAIL "skill '$s': no SKILL.md"; continue; fi
  if [ "$(sed -n '1p' "$f")" != "---" ]; then FAIL "$s/SKILL.md: missing opening --- frontmatter"; continue; fi
  fm=$(sed -n '2,/^---$/p' "$f")
  printf '%s\n' "$fm" | grep -q '^name:'        || FAIL "$s/SKILL.md: frontmatter missing 'name:'"
  printf '%s\n' "$fm" | grep -q '^description:' || FAIL "$s/SKILL.md: frontmatter missing 'description:'"
done

# 2. every skill dir is named in both README.md and CLAUDE.md (catches list drift)
for d in skills/*/; do
  s=$(basename "$d")
  grep -qF "$s" README.md || FAIL "README.md does not mention skill '$s'"
  grep -qF "$s" CLAUDE.md || FAIL "CLAUDE.md does not mention skill '$s'"
done

# 3. shell scripts parse
while IFS= read -r f; do
  bash -n "$f" 2>/dev/null || FAIL "bash -n failed: $f"
done < <(find . -name '*.sh' -not -path './.git/*' -not -path '*/__pycache__/*')

# 4. python compiles
if [ -n "$PY" ]; then
  while IFS= read -r f; do
    "$PY" -m py_compile "$f" 2>/dev/null || FAIL "py_compile failed: $f"
  done < <(find . -name '*.py' -not -path './.git/*' -not -path '*/__pycache__/*')
else
  note "(no working python found - skipping py_compile)"
fi

# 5. no CRLF in tracked text. Counts CR bytes with `tr` rather than `grep -U`:
#    grep -U intermittently mis-handles a \r pattern under MSYS git-bash (false
#    positives on clean files), so a validator must not depend on it.
while IFS= read -r f; do
  [ "$(tr -cd '\r' < "$f" | wc -c)" -gt 0 ] && FAIL "CRLF line endings: $f"
done < <(find . \( -name '*.sh' -o -name '*.py' -o -name '*.md' \) -not -path './.git/*' -not -path '*/__pycache__/*')

# 6. duplicated probe stays byte-identical
A=skills/device-sync/scripts/probe-sync.sh
B=skills/device-handoff/scripts/probe-sync.sh
if [ -f "$A" ] && [ -f "$B" ]; then
  cmp -s "$A" "$B" && OK "probe-sync.sh byte-identical across device-sync/device-handoff" \
                   || FAIL "probe-sync.sh DIFFERS between device-sync and device-handoff"
fi

if [ "$fail" -eq 0 ]; then printf '\nvalidate: PASS\n'; exit 0; else printf '\nvalidate: FAILED\n'; exit 1; fi
