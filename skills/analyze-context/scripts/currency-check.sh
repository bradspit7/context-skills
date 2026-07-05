#!/usr/bin/env bash
# currency-check.sh — consolidated session-start currency gate for analyze-context.
# Read-only except `git fetch`. Prints a structured report; any line starting with
# FINDING or THRESHOLD requires action before synthesis. Always exits 0.
#
# Usage: bash currency-check.sh [primary-doc ...]
#   primary-doc defaults to: HANDOFF.md CONTEXT.md continuation/context.md
#   (first that exists is treated as "the doc" for drift comparison)

set -u

if [ $# -gt 0 ]; then DOCS=("$@"); else DOCS=(HANDOFF.md CONTEXT.md continuation/context.md); fi

echo "== MACHINE =="
hostname

echo
echo "== PATTERN MARKERS =="
for m in HANDOFF.md CONTEXT.md CLAUDE.md continuation context coordination docs/decisions; do
  [ -e "$m" ] && echo "present: $m"
done
for pd in HANDOFF-*.md; do [ -e "$pd" ] && echo "present: $pd (multi-dev marker)"; done

# ---------- no-git fallback ----------
if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo
  echo "== NO-GIT =="
  echo "Not a git repo. Staleness must be judged from file mtimes + in-content dates:"
  for f in "${DOCS[@]}"; do
    # mtime chain is GNU-first then BSD: GNU `date -r <file>` / `stat -c`; macOS/BSD
    # `date -r` wants an epoch (fails on a filename) and `stat -c` is illegal, so both
    # fall through to BSD `stat -f`. (Per Jacob's 2026-06-10 field report, Bug 2.)
    [ -f "$f" ] && echo "  $f  last-modified: $(date -r "$f" '+%Y-%m-%d %H:%M' 2>/dev/null || stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' -t '%Y-%m-%d %H:%M' "$f" 2>/dev/null)"
  done
  echo
  echo "== VERDICT =="
  echo "No git history to verify currency against. If the doc is >7 days old, flag staleness in the briefing header."
  exit 0
fi

DOC=""
for f in "${DOCS[@]}"; do [ -f "$f" ] && DOC="$f" && break; done

# Every report section runs inside ONE captured function so the RESUME CLASS block at the
# bottom can count FINDING lines MECHANICALLY — they are emitted inside while-loop subshells,
# so a flag variable could never see them, and a prose-only "if no FINDINGs above" gate lets
# the classifier headline contradict a finding (review-fleet 2026-07-04, primary #2).
# Output is printed verbatim after capture; section behavior is unchanged.
emit_report() {
echo
echo "== FETCH =="
# Hardened per Jacob's 2026-06-10 field report: GIT_TERMINAL_PROMPT=0 (a credential
# prompt would hang session start forever), timeout when available, and a failed
# fetch surfaces as a FINDING (stale remote view invalidates the currency gate)
# instead of silently passing as "no new branches".
if command -v timeout >/dev/null 2>&1; then
  FETCH_OUT=$(GIT_TERMINAL_PROMPT=0 timeout 30 git fetch --all 2>&1)
else
  FETCH_OUT=$(GIT_TERMINAL_PROMPT=0 git fetch --all 2>&1)
fi
FETCH_RC=$?
if [ "$FETCH_RC" -ne 0 ]; then
  echo "FINDING fetch-failed (rc=$FETCH_RC — offline / auth / timeout): remote view is STALE; branch survey + upstream checks below are unreliable"
fi
NEWBR=$(printf '%s\n' "$FETCH_OUT" | grep -i 'new branch' || true)
if [ -n "$NEWBR" ]; then printf '%s\n' "$NEWBR" | sed 's/^/FINDING new-remote-branch: /'; elif [ "$FETCH_RC" -eq 0 ]; then echo "fetched; no new branches"; fi

echo
echo "== WORKTREES =="
CUR_WT=$(git rev-parse --show-toplevel)
CUR_TS=$(git log -1 --format=%ct HEAD 2>/dev/null || echo 0)
git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print}' | while read -r wt; do
  [ "$wt" = "$CUR_WT" ] && continue
  TS=$(git -C "$wt" log -1 --format=%ct HEAD 2>/dev/null || echo 0)
  if [ "$TS" -gt "$CUR_TS" ]; then
    echo "FINDING newer-sibling-worktree: $wt  ($(git -C "$wt" log -1 --format='%h %ai' HEAD 2>/dev/null))"
  fi
done
echo "(current worktree: $CUR_WT)"

echo
echo "== UPSTREAM =="
UP=$(git log HEAD..@{upstream} --oneline 2>/dev/null | head -5)
if [ -n "$UP" ]; then printf '%s\n' "$UP" | sed 's/^/FINDING unpulled-upstream: /'; else echo "no upstream drift (or no upstream configured)"; fi

if [ -n "$DOC" ]; then
  echo
  echo "== BRANCH SURVEY ($DOC) =="
  # Union of: 10 most-recently-committed refs + any ref committed in the last 24h.
  # Supersession test, not recency: a branch doc-blob is silent only if that exact content
  # appears somewhere in HEAD's history of the doc (covers squash-merges); any blob outside
  # HEAD's history is a divergent fork REGARDLESS OF AGE. (A timestamp guard here silently
  # converted "divergent fork older than HEAD's copy" into "ignore" — an unmerged fork >7
  # days old was permanently invisible while the survey printed the all-clear below.)
  CUR_HASH=$(git ls-tree HEAD -- "$DOC" 2>/dev/null | awk '{print $3}')
  HIST_BLOBS=$(git log -m --no-abbrev --no-renames --raw --format= HEAD -- "$DOC" 2>/dev/null | awk '$4 !~ /^0+$/ {print $4}' | sort -u)
  NOW=$(date +%s); TH=$((NOW - 86400))
  git for-each-ref --sort=-committerdate refs/heads refs/remotes --format='%(refname:short) %(committerdate:unix)' \
    | awk -v t="$TH" 'NR<=10 || $2>t {print $1}' | grep -v '/HEAD$' | sort -u | while read -r br; do
      H=$(git ls-tree "$br" -- "$DOC" 2>/dev/null | awk '{print $3}')
      if [ -n "$H" ] && [ "$H" != "$CUR_HASH" ] && ! printf '%s\n' "$HIST_BLOBS" | grep -qx "$H"; then
        echo "FINDING divergent-branch-doc: $br carries $DOC content absent from HEAD's history  ($(git log -1 --format='%h %ai' "$br" -- "$DOC" 2>/dev/null))"
      fi
    done
  echo "(silence above = no surveyed branch carries $DOC content outside HEAD's history)"

  echo
  echo "== RECENT $DOC COMMITS — all refs, 7 days, reachability vs HEAD =="
  git log --all --since='7 days ago' --format='%h %ai %s' -- "$DOC" 2>/dev/null | head -10 | while read -r line; do
    SHA=${line%% *}
    if git merge-base --is-ancestor "$SHA" HEAD 2>/dev/null; then
      echo "ok       $line"
    else
      echo "FINDING not-reachable-from-HEAD: $line"
    fi
  done

  echo
  echo "== LAG =="
  # `git log -- <untracked-path>` exits 0 with EMPTY output, so an `|| echo` fallback is
  # dead code — test the output, not the exit code, or an uncommitted doc prints a blank.
  LAST_DOC=$(git log -1 --format='%ai (%h)' -- "$DOC" 2>/dev/null)
  echo "$DOC last commit:   ${LAST_DOC:-never committed — $DOC is on disk but has no history reachable from HEAD (untracked/uncommitted; check BRANCH SURVEY for other refs)}"
  echo "repo HEAD commit:  $(git log -1 --format='%ai (%h)' 2>/dev/null)"
  LAST_DOC_SHA=$(git log -1 --format=%H -- "$DOC" 2>/dev/null)
  if [ -n "$LAST_DOC_SHA" ]; then
    echo "commits since last $DOC touch: $(git rev-list --count "$LAST_DOC_SHA"..HEAD 2>/dev/null)"
  fi

  echo
  echo "== HEADER STAMPS (advisory only — never proof of currency; truncated to 200 chars) =="
  grep -m6 -E '^\*\*(Updated|Last write from|Machine|Branch|Author|Summary):' "$DOC" 2>/dev/null | cut -c1-200 || echo "(no structured header stamps found)"
else
  echo
  echo "== NO PRIMARY DOC ON DISK =="
  # cwd has no handoff doc — check whether any ref carries one (wrong-branch / fresh-clone signal)
  git for-each-ref --sort=-committerdate refs/heads refs/remotes --format='%(refname:short)' | head -10 | while read -r br; do
    if git ls-tree "$br" -- HANDOFF.md 2>/dev/null | grep -q .; then
      echo "FINDING doc-exists-elsewhere: $br carries HANDOFF.md but the current checkout does not"
    fi
  done
fi

echo
echo "== MEMORY DIR (out-of-repo convention) =="
MAIN_WT=$(git worktree list --porcelain | awk '/^worktree /{sub(/^worktree /,""); print; exit}')
if command -v cygpath >/dev/null 2>&1; then NATIVE=$(cygpath -w "$MAIN_WT"); else NATIVE="$MAIN_WT"; fi
SLUG=$(printf '%s' "$NATIVE" | sed 's/[^A-Za-z0-9]/-/g')
echo "expected: ~/.claude/projects/$SLUG/memory/"
if [ "$MAIN_WT" != "$CUR_WT" ]; then
  echo "NOTE: running in a LINKED WORKTREE — memory keys off the MAIN checkout path above, not this worktree's path."
fi
if [ -d "$HOME/.claude/projects/$SLUG/memory" ]; then
  echo "exists: yes ($(ls "$HOME/.claude/projects/$SLUG/memory" 2>/dev/null | wc -l | tr -d ' ') files)"
else
  echo "exists: no"
fi
}

REPORT=$(emit_report)
printf '%s\n' "$REPORT"
FINDINGS_N=$(printf '%s\n' "$REPORT" | grep -c '^FINDING')

if [ -n "$DOC" ]; then
  echo
  echo "== RESUME CLASS (routing signal: full briefing vs the slim analyze-handoff path) =="
  # Mechanizes the analyze-context <-> analyze-handoff routing that invocation-time judgment
  # measurably never performs (2026-07-04 audit: 0 slim-path uses in 204 sessions; 20+
  # same-day resumes each paid the full briefing). The slim path requires ALL of: zero
  # FINDING lines (counted mechanically from the captured report), doc committed <24h ago,
  # <=3 commits behind HEAD, single-doc pattern, and a machine stamp MATCHING this host —
  # an absent stamp cannot confirm the machine, so it forces the full briefing (fail-safe).
  LAST_DOC_SHA=$(git log -1 --format=%H -- "$DOC" 2>/dev/null)
  DOC_EPOCH=$(git log -1 --format=%ct -- "$DOC" 2>/dev/null)
  BEHIND_N=$(git rev-list --count "${LAST_DOC_SHA:-HEAD}"..HEAD 2>/dev/null)
  STAMP=$(grep -m1 -E '^\*\*(Machine|Last write from):\*\*' "$DOC" 2>/dev/null | sed -E 's/^\*\*(Machine|Last write from):\*\* *//; s/[^A-Za-z0-9_.-].*$//')
  HOSTN=$(hostname 2>/dev/null)
  MULTIDEV=""
  for pd in HANDOFF-*.md; do [ -e "$pd" ] && MULTIDEV=1 && break; done
  AGE_H=""
  REASONS=""
  [ "${FINDINGS_N:-0}" -gt 0 ] && REASONS="$REASONS; $FINDINGS_N FINDING line(s) in the report (resolve source-of-truth first)"
  if [ -z "${DOC_EPOCH:-}" ]; then
    REASONS="$REASONS; $DOC has no commit history (never committed)"
  else
    AGE_H=$(( ($(date +%s) - DOC_EPOCH) / 3600 ))
    [ "$AGE_H" -ge 24 ] && REASONS="$REASONS; last $DOC commit ${AGE_H}h ago (>=24h)"
  fi
  [ "${BEHIND_N:-0}" -gt 3 ] && REASONS="$REASONS; $DOC is ${BEHIND_N} commits behind HEAD (work landed after the last wrap)"
  [ -n "$MULTIDEV" ] && REASONS="$REASONS; multi-dev pattern (per-dev files + feed need the full read)"
  if [ -z "$STAMP" ]; then
    REASONS="$REASONS; no machine stamp in $DOC (cannot confirm same machine)"
  elif [ -n "$HOSTN" ] && [ "$(printf '%s' "$STAMP" | tr '[:upper:]' '[:lower:]')" != "$(printf '%s' "$HOSTN" | tr '[:upper:]' '[:lower:]')" ]; then
    REASONS="$REASONS; machine stamp '$STAMP' != host '$HOSTN' (machine switch -> device-sync, then the full briefing)"
  fi
  if [ -z "$REASONS" ]; then
    echo "SAME-DAY RESUME CANDIDATE — gate clean (0 FINDINGs); last $DOC commit ${AGE_H}h ago; ${BEHIND_N:-0} commit(s) since; machine stamp matches; single-doc pattern."
    echo "=> UNLESS the user asked for a full briefing: take the SLIM PATH (analyze-handoff contract):"
    echo "   read $DOC fully, deliver the 3-line summary (last completed / next intended / blocker),"
    echo "   offer the full briefing on request. Skip the deep content reads."
  else
    echo "FULL BRIEFING — reason(s): ${REASONS#; }"
  fi
fi

echo
echo "== VERDICT =="
echo "Any FINDING line above => STOP: resolve source-of-truth with the user BEFORE reading content files."
echo "No FINDING lines => proceed to content reads (RESUME CLASS above says full vs slim). Re-run this script after any git switch/pull/reset."
