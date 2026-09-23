#!/usr/bin/env bash
# ci-verdict-line.sh -- print the ONE CI line for a project that declares GitHub Actions
# workflows (.github/workflows/*.yml|*.yaml), and print NOTHING for a project that does not.
# Shared by analyze-context's currency gate and update-context's evidence script, so the
# briefing and the wrap re-derive CI the same way and nobody has to remember to look.
# Read-only (gh API reads). Always exits 0.
#
# Why it exists: a project's CI failed on every push for twelve days while its owner was
# emailed each time, and no briefing, docket or wrap recorded it. On a board that is already
# red, a new failure looks exactly like the old redness -- so the verdict must carry HOW LONG
# it has been red and how many runs failed, re-derived every time, never remembered.
#
# One of:
#   CI (<branch>): green at <sha> (<date>)
#   CI (<branch>): RED since <date> (<N> days, <M> failing runs) - last red <sha>
#   CI (<branch>): no runs yet / no completed pass-fail run ...
#   CI: could not check - <gh missing|not authenticated|timeout|parse error|...>
# <branch> is the DEFAULT branch, the only one measured; when this checkout is on another branch
# the line adds "-- this checkout is on <branch>", so "green" is never read as the work in hand.
# Verdicts are per workflow (a green lint run must not mask a red test run); the one red the
# LONGEST is printed, with a count of the other red workflows. cancelled / skipped / neutral /
# stale runs are not a verdict either way. Every other non-success conclusion counts as red, so
# an unfamiliar conclusion is visible.
#
# It is a STATE line, never a FINDING (currency-check.sh counts '^FINDING' to block synthesis).
# A non-success is an open item to carry into the briefing / handoff, verbatim -- and the helper
# says so itself on the next line, because the skill's default for a non-FINDING is to move on.
#
# CI_VERDICT_TIMEOUT (seconds, default 20) bounds each gh call. GH_PROMPT_DISABLED=1 keeps a
# credential prompt from hanging session start.
set -u
TOP=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
[ -n "$TOP" ] || exit 0
shopt -s nullglob
WF=("$TOP"/.github/workflows/*.yml "$TOP"/.github/workflows/*.yaml)
shopt -u nullglob
[ "${#WF[@]}" -gt 0 ] || exit 0

echo
echo "== CI =="
route() { echo "(a state line, not a FINDING -- carry it verbatim into the briefing / handoff; RED or could not check is an open item)"; }
cant() { echo "CI: could not check - $1"; route; exit 0; }

command -v gh >/dev/null 2>&1 || cant "gh missing"
PY=""
# `python` first: on Windows a bare `python3` can resolve to the Microsoft Store alias stub.
for c in python python3 py; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)' >/dev/null 2>&1; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || cant "no Python 3 on PATH (needed to read gh's JSON)"

T=${CI_VERDICT_TIMEOUT:-20}
ERRF=$(mktemp 2>/dev/null || echo "${TMPDIR:-/tmp}/cvl.$$")
trap 'rm -f "$ERRF"' EXIT

gh_call() {   # stdout = gh stdout; stderr goes to $ERRF; returns gh's exit status
  if command -v timeout >/dev/null 2>&1; then
    ( cd "$TOP" && GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 timeout "$T" gh "$@" ) 2>"$ERRF"
  else
    ( cd "$TOP" && GH_PROMPT_DISABLED=1 GH_NO_UPDATE_NOTIFIER=1 gh "$@" ) 2>"$ERRF"
  fi
}
why() {   # $1 = rc, $2 = what failed -> a reason; never a verdict
  local e
  e=$(tr -d '\r' < "$ERRF" 2>/dev/null)
  case "$1" in
    124|137) echo "timeout"; return ;;
    127) echo "gh missing"; return ;;
    4) echo "not authenticated"; return ;;
  esac
  if printf '%s' "$e" | LC_ALL=C.UTF-8 grep -qiE 'auth login|not logged in|authentication|bad credentials|HTTP 401'; then
    echo "not authenticated"; return
  fi
  echo "$2 failed (rc $1): $(printf '%s\n' "$e" | sed -n '/[^[:space:]]/{p;q;}' | cut -c1-160)"
}

# The DEFAULT branch: origin/HEAD when the clone recorded it, else ask GitHub.
BR=$(git -C "$TOP" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)
BR=${BR#origin/}
if [ -z "$BR" ]; then
  BR=$(gh_call repo view --json defaultBranchRef --jq .defaultBranchRef.name)
  RC=$?
  [ "$RC" -eq 0 ] || cant "$(why "$RC" "gh repo view")"
  BR=$(printf '%s' "$BR" | tr -d '\r\n')
  [ -n "$BR" ] || cant "default branch unknown (gh repo view printed nothing)"
fi

RUNS=$(gh_call run list --branch "$BR" --limit 100 --json status,conclusion,headSha,createdAt,workflowName)
RC=$?
[ "$RC" -eq 0 ] || cant "$(why "$RC" "gh run list")"
CUR=$(git -C "$TOP" symbolic-ref -q --short HEAD 2>/dev/null)

# The verdict is computed from gh's raw JSON. Kept apostrophe-free: it lives inside single quotes.
printf '%s' "$RUNS" | "$PY" -c '
import datetime, json, sys
branch = sys.argv[1]
cur = sys.argv[2] if len(sys.argv) > 2 else ""
pre = "CI (%s):" % branch
note = "" if cur == branch else " -- this checkout is on %s" % (cur or "a detached HEAD")
try:
    runs = json.load(sys.stdin)
    if not isinstance(runs, list):
        raise ValueError("not a list")
    runs = [r for r in runs if isinstance(r, dict)]
except Exception:
    print("CI: could not check - parse error")
    sys.exit(0)
NOT_A_VERDICT = {"cancelled", "skipped", "neutral", "stale"}
runs.sort(key=lambda r: str(r.get("createdAt") or ""), reverse=True)
if not runs:
    print("%s no runs yet%s" % (pre, note))
    sys.exit(0)
def sha(r):
    return (str(r.get("headSha") or "?"))[:7]
def day(r):
    return (str(r.get("createdAt") or "????-??-??"))[:10]
decisive = [r for r in runs if r.get("status") == "completed" and (r.get("conclusion") or "") not in NOT_A_VERDICT]
if not decisive:
    print("%s no completed pass-fail run in the last %d run(s)%s" % (pre, len(runs), note))
    sys.exit(0)
groups = {}
for r in decisive:
    groups.setdefault(str(r.get("workflowName") or "(unnamed)"), []).append(r)
reds = []
for name, rs in groups.items():
    streak = []
    for r in rs:
        if r.get("conclusion") == "success":
            break
        streak.append(r)
    if streak:
        reds.append((day(streak[-1]), name, streak, len(streak) == len(rs), len(rs)))
newest = decisive[0]
pending = 0
for r in runs:
    if r is newest:
        break
    if r.get("status") != "completed":
        pending += 1
tail = ""
if pending:
    tail = " (%d newer run%s in progress)" % (pending, "" if pending == 1 else "s")
if reds:
    reds.sort(key=lambda t: t[0])
    since, name, streak, nogreen, total = reds[0]
    try:
        today = datetime.datetime.now(datetime.timezone.utc).date()
        n = (today - datetime.date.fromisoformat(since)).days
    except ValueError:
        n = -1
    line = "%s RED since %s (%s day%s, %d failing run%s) - last red %s" % (
        pre, since, n if n >= 0 else "?", "" if n == 1 else "s", len(streak), "" if len(streak) == 1 else "s", sha(streak[0]))
    if nogreen:
        line += " - no green run in the last %d" % total
    if len(groups) > 1:
        line += " [workflow %s%s]" % (name, "; %d other workflow(s) red" % (len(reds) - 1) if len(reds) > 1 else "")
    print(line + tail + note)
else:
    ok = decisive[0]
    line = "%s green at %s (%s)" % (pre, sha(ok), day(ok))
    if len(groups) > 1:
        line += " [%d workflows]" % len(groups)
    print(line + tail + note)
' "$BR" "$CUR" 2>/dev/null || echo "CI: could not check - parse error (the verdict reader crashed)"
route
exit 0
