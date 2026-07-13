#!/usr/bin/env bash
# validate.sh - repo-level integrity gate for context-skills.
#
# Catches the drift classes that have actually bitten this repo:
#   1. SKILL.md frontmatter rot (missing name/description, over-1024-char
#      description that silently unregisters the skill, no --- delimiters)
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

# This gate covers the COMMITTED tree: file lists come from `git ls-files`, so a
# local scratch .md / copied .py / temp script / venv cannot fail an otherwise
# clean repo (important when this backs a pre-commit hook). Requires a git work tree.
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf 'validate: must run inside the context-skills git repo\n'; exit 2
fi
gate_files() { git ls-files -- "$@"; }

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
  close=$(awk 'NR>1 && /^---$/{print NR; exit}' "$f")
  if [ -z "$close" ]; then FAIL "$s/SKILL.md: no closing --- frontmatter delimiter"; continue; fi
  fm=$(sed -n "2,$((close-1))p" "$f")
  printf '%s\n' "$fm" | grep -q '^name:'        || FAIL "$s/SKILL.md: frontmatter missing 'name:'"
  printf '%s\n' "$fm" | grep -q '^description:' || FAIL "$s/SKILL.md: frontmatter missing 'description:'"
  # description length: Claude Code silently UNREGISTERS a skill whose frontmatter
  # description: exceeds 1024 CHARACTERS (not bytes) - no error is shown. Count
  # codepoints locale-free (total bytes minus UTF-8 continuation bytes 0x80-0xBF)
  # so multibyte em-dashes are not over-counted into a false failure. The 950 band
  # is an advisory early-warning (note only), not an enforced limit.
  desc=$(printf '%s\n' "$fm" | sed -n 's/^description:[[:space:]]*//p' | head -1)
  if [ -n "$desc" ]; then
    dnb=$(printf '%s' "$desc" | LC_ALL=C wc -c | tr -d ' ')
    dnc=$(printf '%s' "$desc" | LC_ALL=C tr -cd '\200-\277' | LC_ALL=C wc -c | tr -d ' ')
    dlen=$((dnb - dnc))
    if [ "$dlen" -gt 1024 ]; then
      FAIL "$s/SKILL.md: description is $dlen chars (>1024) - Claude Code silently unregisters it"
    elif [ "$dlen" -ge 950 ]; then
      note "WARN $s/SKILL.md: description $dlen chars - approaching the 1024 cap (advisory)"
    fi
  fi
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
done < <(gate_files '*.sh')

# 4. python compiles
if [ -n "$PY" ]; then
  while IFS= read -r f; do
    "$PY" -m py_compile "$f" 2>/dev/null || FAIL "py_compile failed: $f"
  done < <(gate_files '*.py')
else
  note "(no working python found - skipping py_compile)"
fi

# 5. no CRLF in tracked text. Counts CR bytes with `tr` rather than `grep -U`:
#    grep -U intermittently mis-handles a \r pattern under MSYS git-bash (false
#    positives on clean files), so a validator must not depend on it.
while IFS= read -r f; do
  [ "$(tr -cd '\r' < "$f" | wc -c)" -gt 0 ] && FAIL "CRLF line endings: $f"
done < <(gate_files '*.sh' '*.py' '*.md')

# 6. duplicated probe stays byte-identical
A=skills/device-sync/scripts/probe-sync.sh
B=skills/device-handoff/scripts/probe-sync.sh
if [ -f "$A" ] && [ -f "$B" ]; then
  cmp -s "$A" "$B" && OK "probe-sync.sh byte-identical across device-sync/device-handoff" \
                   || FAIL "probe-sync.sh DIFFERS between device-sync and device-handoff"
fi

# 7. behavioral tests (fixture-based -- the net the structural checks 1-6 cannot give).
#    Committed tests/*.py run when a working python is present; each exits non-zero on
#    failure. Needs bash on PATH for the currency-check subprocess (git-bash on Windows) --
#    the same shell validate.sh itself runs in, so that is already satisfied here.
if [ -n "$PY" ]; then
  while IFS= read -r t; do
    out=$("$PY" "$t" 2>&1); rc=$?
    if [ "$rc" -eq 0 ]; then
      OK "behavioral test: $t"
      # A test can PASS while skipping an optional leg (e.g. the jq-gated semantic-recall path on
      # a box with no jq executable). Surface each skip as UNVERIFIED so a green gate never hides
      # skipped coverage -- but do NOT fail this portable base gate on an optional dependency. A
      # jq-equipped box runs the same leg and these lines simply do not appear.
      while IFS= read -r s; do
        [ -n "$s" ] && note "UNVERIFIED (optional leg skipped): $s"
      done < <(printf '%s\n' "$out" | grep '^SKIP ' || true)
    else
      FAIL "behavioral test: $t"
      printf '%s\n' "$out" | sed 's/^/     /'   # show the failure output (was suppressed)
    fi
  done < <(gate_files 'tests/*.py')
fi

if [ "$fail" -eq 0 ]; then printf '\nvalidate: PASS\n'; exit 0; else printf '\nvalidate: FAILED\n'; exit 1; fi
