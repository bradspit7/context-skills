#!/usr/bin/env bash
# check-harness-scripts.sh -- design-variants Step 2 harness gate.
#
# A single stacked comparison page must contain ZERO variant <script> tags, except
# AT MOST ONE deliberately-marked switcher carrying a `data-dv-harness` attribute.
# A substring/per-line grep cannot decide this: `data-dv-harness-disabled`, two
# switcher tags, or a leaked tag sharing a physical line with the harness string all
# false-pass it. This extracts each opening tag and checks the exact attribute + count.
#
# Usage:
#   check-harness-scripts.sh <stacked-comparison-page>   # silent + exit 0 = clean; prints offenders + exit 1 = fail
#   check-harness-scripts.sh --selftest                  # run the fixture battery; exit 0 = all pass
#
# Portable bash (no associative arrays); ASCII-only. LC_ALL is pinned to a UTF-8
# locale so case-insensitive grep does not SIGABRT under GNU grep 3.0 on git-bash.
set -u
export LC_ALL=C.UTF-8

# data-dv-harness as an EXACT attribute: the name must end at a boundary
# (whitespace, /, >, =, or end of tag) -- so `data-dv-harness-disabled` is NOT harness.
HARNESS_ATTR='data-dv-harness([[:space:]/>=]|$)'
OPEN_TAG='<[[:space:]]*script\b[^>]*>'

# Silent + return 0 when the page is gate-clean; print offenders + return 1 otherwise.
check_page() {
  page="$1"
  if [ ! -f "$page" ]; then
    echo "check-harness-scripts: no such page: $page" >&2
    return 2
  fi
  tags=$(grep -oiE "$OPEN_TAG" "$page")
  [ -z "$tags" ] && return 0                       # no <script> tags at all -> clean
  nonharness=$(printf '%s\n' "$tags" | grep -viE "$HARNESS_ATTR")
  hcount=$(printf '%s\n' "$tags" | grep -ciE "$HARNESS_ATTR")
  fail=0
  if [ -n "$nonharness" ]; then
    echo "LEAKED variant <script> tag(s) on the comparison page:"
    printf '%s\n' "$nonharness" | sed 's/^/  /'
    fail=1
  fi
  if [ "$hcount" -gt 1 ]; then
    echo "MORE THAN ONE data-dv-harness switcher tag (found $hcount); expected at most one."
    fail=1
  fi
  return $fail
}

selftest() {
  tmp=$(mktemp -d)
  rc=0
  # name|expected|content   (%b: \n in content becomes a real newline)
  specs='f1_clean_harness|PASS|<html><head><script data-dv-harness>switch()</script></head><body>hi</body></html>
f2_suffix_leak|FAIL|<html><script data-dv-harness-disabled>bad()</script></html>
f3_two_harness|FAIL|<script data-dv-harness>a()</script>\n<script data-dv-harness>b()</script>
f4_plain_leak|FAIL|<html><script src="v.js"></script></html>
f5_sameline|FAIL|<script data-dv-harness></script><script src="b.js"></script>
f6_upper_leak|FAIL|<HTML><SCRIPT SRC="up.js"></SCRIPT></HTML>
f7_no_scripts|PASS|<html><body>nothing</body></html>
f8_comment_mask|FAIL|<script src="b.js"></script><!-- data-dv-harness -->
f9_harness_eq|PASS|<script data-dv-harness="switch">go()</script>'
  while IFS= read -r spec; do
    name=${spec%%|*}; rest=${spec#*|}; want=${rest%%|*}; content=${rest#*|}
    printf '%b' "$content" > "$tmp/$name"
    if check_page "$tmp/$name" >/dev/null 2>&1; then got=PASS; else got=FAIL; fi
    if [ "$got" = "$want" ]; then
      printf '  ok   %-18s %s\n' "$name" "$got"
    else
      printf '  FAIL %-18s got=%s want=%s\n' "$name" "$got" "$want"
      rc=1
    fi
  done <<EOF
$specs
EOF
  rm -rf "$tmp"
  if [ "$rc" -eq 0 ]; then echo "SELFTEST PASS (9/9)"; else echo "SELFTEST FAILED"; fi
  return $rc
}

case "${1:-}" in
  --selftest) selftest ;;
  "") echo "usage: $0 <stacked-comparison-page> | --selftest" >&2; exit 2 ;;
  *) check_page "$1" ;;
esac
