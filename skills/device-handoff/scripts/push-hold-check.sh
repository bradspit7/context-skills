#!/usr/bin/env bash
# push-hold-check.sh -- does a repo carry a deliberate push hold? Run it before a departure pushes the repo.
#
# device-handoff Step 4 item 3 pushes each repo ONLY as
#     bash ~/.claude/skills/device-handoff/scripts/push-hold-check.sh <repo> && git -C <repo> push ...
# so a hold stops the push mechanically. Joined with ";" instead, the push runs whatever this prints
# (measured 2026-11-19: a hold grep hit, and the push in the same command ran before anyone read the hit).
#
# A HOLD is a deliberate marker in a TRACKED markdown file (git ls-files, *.md or *.markdown in any
# case, so an untracked note never counts), matched without regard to case, outside fenced code blocks
# (``` or ~~~, including one opened inside a list item or a blockquote):
#   1. a heading at any level whose text starts with "Push hold"   (## Push hold, ### Push hold: until X)
#   2. a line whose first non-blank text is "push-hold:"           (push-hold: <reason>, lift when <X>)
# A mention in the middle of a line (prose that describes the rule) never counts. CR bytes are stripped
# before matching, so a CRLF file reads the same as an LF one. A fence that never closes may be one this
# scan misread, so a marker inside it still counts (with a NOTE line): a misread must never hide a hold.
#
# Output: one "HOLD <file>:<line>: <the line>" per hit, then always the denominator
# "scanned N tracked markdown file(s) in <repo>", then one RESULT line.
#
# Exit codes:
#   0  clean: the scan completed over at least one tracked markdown file and found no hold
#   1  hold found: read the HOLD lines and report the hold; the repo is not pushed
#   2  the check did not run (usage, not a git work tree, git failed, zero tracked markdown files,
#      a file could not be read, awk failed). The reason is printed; the repo is not pushed. A scan
#      of nothing never reads as clean, and this path never prints the word.
#
# Usage: bash push-hold-check.sh <repo>
# A path inside a work tree scans that whole work tree: a push carries the whole repo.
# Matching runs in awk, never grep -i (git-bash grep 3.0 aborts with rc 134 on -i plus two patterns).
set -u

repo="${1:-}"
scanned=0
tmp=""

cleanup() {
  if [ -n "$tmp" ]; then rm -rf "$tmp"; fi
}
trap cleanup EXIT

not_run() {
  # $1: the reason. The denominator is printed on this path too, and the verdict is never "clean".
  echo "scanned $scanned tracked markdown file(s) in $repo"
  echo "RESULT: NOT RUN -- $1 (exit 2: the check did not run, so this repo is not pushed)"
  exit 2
}

first_line() {
  # the first 300 bytes of a file, on one line (for a reason quoted from git or awk)
  head -c 300 "$1" 2>/dev/null | tr '\r\n' '  '
}

if [ "$#" -ne 1 ] || [ -z "$repo" ]; then
  echo "usage: bash push-hold-check.sh <repo>"
  not_run "expected exactly one argument, the repo path"
fi

tmp=$(mktemp -d 2>/dev/null) || tmp=""
if [ -z "$tmp" ] || [ ! -d "$tmp" ]; then
  tmp=""
  not_run "could not make a temp dir"
fi

top=$(git -C "$repo" rev-parse --show-toplevel 2>"$tmp/err")
rc=$?
if [ "$rc" -ne 0 ] || [ -z "$top" ]; then
  not_run "not a git work tree, or git failed (git rev-parse rc=$rc: $(first_line "$tmp/err"))"
fi

# :(icase): git pathspecs are case-sensitive even on Windows, so a plain '*.md' never lists HOLD.MD.
git -C "$top" ls-files -z -- ':(icase)*.md' ':(icase)*.markdown' >"$tmp/list0" 2>"$tmp/err"
rc=$?
if [ "$rc" -ne 0 ]; then
  not_run "git ls-files failed (rc=$rc: $(first_line "$tmp/err"))"
fi

# NUL-separated names (spaces kept) -> one name per line for awk. A name holding a newline cannot be
# carried that way, so it stops the check rather than going unscanned.
listed=0
if ! : >"$tmp/list"; then
  not_run "could not write the temp file list"
fi
while IFS= read -r -d '' f || [ -n "$f" ]; do
  case "$f" in
    *$'\n'*) not_run "a tracked file name holds a newline, which this check cannot scan: $(printf '%q' "$f")" ;;
  esac
  printf '%s\n' "$f" >>"$tmp/list" || not_run "could not write the temp file list"
  listed=$((listed + 1))
done <"$tmp/list0"

if [ "$listed" -eq 0 ]; then
  not_run "zero tracked markdown files in the work tree at $top: a scan of nothing proves nothing"
fi

# BINMODE=1: read every file byte for byte. Git-for-Windows gawk otherwise drops CR itself while awk on
# Linux keeps it, and the scan strips CR explicitly, so a CRLF file reads the same everywhere.
PHC_TOP="$top" PHC_LIST="$tmp/list" PHC_COUNT="$tmp/count" LC_ALL=C awk -v BINMODE=1 '
BEGIN {
  top = ENVIRON["PHC_TOP"]; list = ENVIRON["PHC_LIST"]; countfile = ENVIRON["PHC_COUNT"]
  scanned = 0; holds = 0; bad = 0
  while ((lr = (getline name < list)) > 0) {
    path = top "/" name
    ln = 0; fence = ""; flen = 0; fopen = 0; npend = 0
    while ((r = (getline line < path)) > 0) {
      ln++
      sub(/\r$/, "", line)
      if (ln == 1) sub(/^\357\273\277/, "", line)
      low = tolower(line)
      is_heading = (low ~ /^ ? ? ?#+[ \t]+push[ \t]+hold/)
      is_marker = (low ~ /^[ \t]*push-hold:/)
      hit = (is_heading || is_marker)
      # a code fence: three or more backticks or tildes after any indent and any list-item or
      # blockquote markers, so a fence opened on a "- ```" line is seen and closes on its indented "```"
      s = line
      while (match(s, /^[ \t]+/) || match(s, /^>[ \t]?/) || match(s, /^[-*+][ \t]+/) || match(s, /^[0-9]+[.)][ \t]+/))
        s = substr(s, RLENGTH + 1)
      c = substr(s, 1, 1); run = 0
      if (c == "`" || c == "~") { while (substr(s, run + 1, 1) == c) run++ }
      if (fence != "") {
        if (c == fence && run >= flen && substr(s, run + 1) ~ /^[ \t]*$/) { fence = ""; flen = 0; npend = 0 }
        else if (hit) pend[++npend] = "HOLD " name ":" ln ": " line
        continue
      }
      if (run >= 3) {
        if (c == "~" || index(substr(s, run + 1), "`") == 0) { fence = c; flen = run; fopen = ln; npend = 0; continue }
      }
      if (hit) {
        print "HOLD " name ":" ln ": " line
        holds++
      }
    }
    if (r < 0) { print "push-hold-check: cannot read " name; bad = 1; break }
    # a fence that never closes may be a misread one hiding the rest of the file, so what it covered counts
    if (fence != "" && npend > 0) {
      for (i = 1; i <= npend; i++) print pend[i]
      holds += npend
      print "NOTE " name ": the code fence opened at line " fopen " never closes, so the hold(s) inside it count"
    }
    close(path)
    scanned++
  }
  if (lr < 0) { print "push-hold-check: cannot read the file list"; bad = 1 }
  close(list)
  print scanned > countfile
  close(countfile)
  if (bad) exit 2
  exit (holds > 0) ? 1 : 0
}' </dev/null 2>"$tmp/err"
rc=$?

scanned=$(cat "$tmp/count" 2>/dev/null)
case "$scanned" in
  '' | *[!0-9]*) scanned=0 ;;
esac
if [ "$rc" -ne 0 ] && [ "$rc" -ne 1 ]; then
  not_run "the scan failed (awk rc=$rc: $(first_line "$tmp/err"))"
fi
if [ "$scanned" -ne "$listed" ] || [ "$scanned" -lt 1 ]; then
  not_run "the scan read $scanned of $listed tracked markdown file(s)"
fi

echo "scanned $scanned tracked markdown file(s) in $repo"
if [ "$rc" -eq 1 ]; then
  echo "RESULT: HOLD -- a deliberate push hold is marked above: do not push this repo; report the hold (exit 1)"
  exit 1
fi
echo "RESULT: clean -- no push hold in $scanned tracked markdown file(s) (exit 0)"
exit 0
