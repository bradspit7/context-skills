#!/usr/bin/env bash
# probe-sync.sh -- cross-device sync probe for the device-sync skill.
# Read-only. Dumps the raw transport facts the skill reasons over (probe-before-
# parse: never assume a transport). Exits 0 on every probe; any section that cannot
# be determined prints "unknown" rather than failing. The one exception is a usage
# error (an unknown argument), which exits 2 before probing anything.
#
# The same file is bundled with device-sync (arrival) and device-handoff (departure),
# byte-identical. The direction decides what "ahead of upstream" means, so it is
# derived from the skill directory this copy lives in (device-handoff = departure,
# anything else = arrival) and can be forced with --arrival / --departure.

set -u

usage() {
  echo "usage: probe-sync.sh [--arrival | --departure]" >&2
  echo "  --arrival    read ahead-of-upstream as a prior departure that did not push (device-sync)" >&2
  echo "  --departure  read ahead-of-upstream as this handoff's pending push (device-handoff)" >&2
  echo "  default: departure when this copy lives in a device-handoff skill dir, else arrival" >&2
}

SKILL_DIR_NAME=$(basename "$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)")
case "$SKILL_DIR_NAME" in
  device-handoff) DIRECTION=departure; DIRECTION_WHY="default for the device-handoff copy" ;;
  *)              DIRECTION=arrival;   DIRECTION_WHY="default for the $SKILL_DIR_NAME copy" ;;
esac
for arg in "$@"; do
  case "$arg" in
    --arrival)   DIRECTION=arrival;   DIRECTION_WHY="forced by --arrival" ;;
    --departure) DIRECTION=departure; DIRECTION_WHY="forced by --departure" ;;
    -h|--help)   usage; exit 0 ;;
    *) echo "probe-sync.sh: unknown argument '$arg'" >&2; usage; exit 2 ;;
  esac
done

# How many unpushed commits the arrival listing shows before it prints a remainder.
UNPUSHED_CAP=20

echo "== MACHINE =="
hostname

echo
echo "== GIT =="
echo "probe-direction: $DIRECTION ($DIRECTION_WHY)"
if git rev-parse --git-dir >/dev/null 2>&1; then
  echo "is-git: yes"
  CUR_WT=$(git rev-parse --show-toplevel 2>/dev/null)
  echo "repo-root: $CUR_WT"
  if git rev-parse '@{upstream}' >/dev/null 2>&1; then
    BEHIND=$(git rev-list --count HEAD..@{upstream} 2>/dev/null || echo '?')
    AHEAD=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo '?')
    # This probe runs no `git fetch`, so both counts are relative to the remote-tracking
    # ref as it stood at the last fetch. behind is the stale one: the other machine may
    # have pushed since. ahead counts commits made here that never left this machine.
    echo "behind-upstream: $BEHIND   ahead-upstream: $AHEAD   (as of last fetch; this probe does not fetch)"
    case "$AHEAD" in
      ''|*[!0-9]*) AHEAD_N=0 ;;
      *) AHEAD_N=$AHEAD ;;
    esac
    if [ "$AHEAD_N" -gt 0 ]; then
      if [ "$DIRECTION" = arrival ]; then
        # Measured (a sibling project, 2026-09-10): behind 4 / ahead 1 printed as two bare
        # counts. The unpushed commit recorded an acceptance as DONE; the remote's four
        # later commits were written without it and re-asserted the older state, and the
        # divergence read as a plain merge job. Name the condition and show the facts the
        # remote never saw, BEFORE the pull merges them.
        echo "unpushed-local: $AHEAD_N -- a prior departure did not push; the remote's later wrap may be stale on the facts these commits record:"
        git log --format='  %h %ad %s' --date=short -n "$UNPUSHED_CAP" '@{upstream}..HEAD' 2>/dev/null
        if [ "$AHEAD_N" -gt "$UNPUSHED_CAP" ]; then
          echo "  ... and $((AHEAD_N - UNPUSHED_CAP)) more (git log --oneline @{upstream}..HEAD)"
        fi
      else
        echo "unpushed-local: $AHEAD_N -- departure: expected; this handoff's push sends them"
      fi
    fi
  else
    echo "upstream: none configured"
  fi
else
  echo "is-git: no"
  CUR_WT="$(pwd)"
  echo "repo-root: $CUR_WT (not a git repo)"
fi

echo
echo "== PROJECT SLUG / LIVE MEMORY DIR =="
MAIN_WT="$CUR_WT"
if git rev-parse --git-dir >/dev/null 2>&1; then
  MAIN_WT=$(git worktree list --porcelain 2>/dev/null | awk '/^worktree /{sub(/^worktree /,""); print; exit}')
  [ -z "$MAIN_WT" ] && MAIN_WT="$CUR_WT"
fi
if command -v cygpath >/dev/null 2>&1; then NATIVE=$(cygpath -w "$MAIN_WT" 2>/dev/null); else NATIVE="$MAIN_WT"; fi
SLUG=$(printf '%s' "$NATIVE" | sed 's/[^A-Za-z0-9]/-/g')
LIVE_MEM="$HOME/.claude/projects/$SLUG/memory"
echo "slug: $SLUG"
echo "live-memory-dir: $LIVE_MEM"
if [ -d "$LIVE_MEM" ]; then
  echo "exists: yes ($(ls "$LIVE_MEM" 2>/dev/null | wc -l | tr -d ' ') files)"
else
  echo "exists: no"
fi

# junction / symlink detection (fail-open). Windows junctions are NOT symlinks,
# so [ -L ] misses them; PowerShell's LinkType is the reliable Windows API answer.
# (cmd //c fsutil was unreliable from git-bash -- //c needs MSYS conversion, which
# conflicts with the MSYS_NO_PATHCONV needed for the colon-bearing path arg.)
echo -n "live-dir-junction: "
if [ -L "$LIVE_MEM" ]; then
  echo "yes (symlink -> $(readlink "$LIVE_MEM" 2>/dev/null))"
elif [ -d "$LIVE_MEM" ] && command -v cygpath >/dev/null 2>&1 && command -v powershell.exe >/dev/null 2>&1; then
  NATIVE_MEM=$(cygpath -w "$LIVE_MEM" 2>/dev/null)
  LT=$(powershell.exe -NoProfile -NonInteractive -Command "\$i = Get-Item -LiteralPath '$NATIVE_MEM' -Force -ErrorAction SilentlyContinue; if (\$i.LinkType) { Write-Output (\$i.LinkType + ' -> ' + (\$i.Target -join ',')) }" 2>/dev/null | tr -d '\r' | head -1)
  if [ -n "$LT" ]; then echo "yes ($LT)"; else echo "no"; fi
else
  echo "unknown"
fi

echo
echo "== SESSION-START HINT (CLAUDE.md headings; a HINT, not authoritative -- verify against the doc body) =="
# Anchored at heading start so incidental wording (e.g. a 'Coordination feed
# (auto-surfaced at session start)' heading) does not register as a bootstrap
# section. The skill still reads the doc to find the real commands, and always
# falls back to git pull, so a miss here never skips the pull.
HIT=""
for cm in CLAUDE.md .claude/CLAUDE.md context/CLAUDE.md; do
  [ -f "$cm" ] || continue
  M=$(grep -inE '^#+[[:space:]]*(session[ -]?start|bootstrap|fresh[ -]?(clone|laptop)|getting started|setup|run before)' "$cm" 2>/dev/null | head -3)
  if [ -n "$M" ]; then HIT="yes"; printf '%s\n' "$M" | sed "s|^|  $cm: |"; fi
done
[ -z "$HIT" ] && echo "none (no session-start/bootstrap heading; Step 1 falls back to git pull)"

echo
echo "== BOOTSTRAP SCRIPT =="
BS=$(ls bootstrap*.sh 2>/dev/null | head -3)
if [ -n "$BS" ]; then printf '%s\n' "$BS" | sed 's/^/  /'; else echo "none at repo root"; fi

echo
echo "== IN-REPO MEMORY MIRROR =="
# TRACKED count, not just files-on-disk. The transport question is "does memory travel
# on the push?", and only `git ls-files` answers it -- an untracked (or ignored) memory
# dir is a local directory that looks identical on disk to one that syncs.
MIR=""; TRACKED_MEM=0
for d in claude-infra/memory continuation/memory; do
  if [ -d "$d" ]; then
    MIR="yes"
    N_DISK=$(ls "$d"/*.md 2>/dev/null | wc -l | tr -d ' ')
    N_TRK=$(git ls-files -- "$d" 2>/dev/null | wc -l | tr -d ' ')
    TRACKED_MEM=$(( TRACKED_MEM + N_TRK ))
    echo "  $d ($N_DISK md files on disk, $N_TRK git-tracked)"
  fi
done
[ -z "$MIR" ] && echo "none (no claude-infra/memory or continuation/memory in repo)"
# A capability must be probed by its EFFECT, never by an implementation marker. The
# branch list used to require a BOOTSTRAP SCRIPT to credit an in-repo mirror -- but a
# bootstrap script is one project's implementation of a live->mirror COPY step, i.e.
# evidence a copy is NEEDED, never evidence a transport EXISTS. That inverted the test:
# a project whose memory is simply git-tracked, with nothing to copy, is the cleanest
# arrangement and was classified as having NO transport at all. Measured on a sibling
# project with 58 tracked memory files carried between two machines for its whole life;
# the probe said "none", the session repeated it, and the owner corrected it in one line.
# The failure is loud and wrong in the ALARMING direction, which is worse than silent:
# it invites a session to BUILD a transport, and the obvious build is a sync bucket --
# the mechanism this estate already superseded by moving memory into git.
echo -n "repo-is-transport: "
if [ "$TRACKED_MEM" -gt 0 ]; then
  echo "yes ($TRACKED_MEM tracked memory file(s) travel on the push; a live->mirror copy step may still be needed -- see BOOTSTRAP SCRIPT)"
else
  echo "no (no git-tracked in-repo memory; the push carries no memory)"
fi
# TWO FACTS, TWO LINES. A project can have BOTH an in-repo tracked memory dir AND an
# out-of-repo live dir, and they are carried by different mechanisms -- folding them
# into one verdict is the borrowed-symbol shape (one line, two facts, and anything
# downstream needing to tell them apart is dead). Measured on a sibling project whose
# out-of-repo MEMORY.md carries a deliberate "these two are NOT a mirror -- never point
# a sync tool at the pair" warning: read at handoff time beside a single fused verdict,
# that correct warning made the false negative MORE convincing, not less.
if [ -d "$LIVE_MEM" ]; then
  LIVE_N=$(ls "$LIVE_MEM"/*.md 2>/dev/null | wc -l | tr -d ' ')
  if [ "${LIVE_N:-0}" -gt 0 ]; then
    if [ "$TRACKED_MEM" -gt 0 ]; then
      echo "out-of-repo live memory dir: $LIVE_N md file(s) at $LIVE_MEM -- NOT carried by the push; a separate fact from repo-is-transport, and in scope only if this project's convention mirrors it"
    else
      echo "out-of-repo live memory dir: $LIVE_N md file(s) at $LIVE_MEM -- NOT carried by the push, and no tracked in-repo memory either; if these files matter across machines, nothing is carrying them"
    fi
  fi
fi

echo
echo "== OUT-OF-BAND SYNC ROOT (hint only -- recipe file is authoritative) =="
PROJ_NAME=$(basename "$MAIN_WT")
FOUND=""
for root in "${CLAUDE_MEMORY_SYNC_DIR:-}" "$HOME/OneDrive/claude-memory" "$HOME/Dropbox/claude-memory"; do
  [ -n "$root" ] && [ -d "$root" ] || continue
  FOUND="yes"
  echo "sync-root: $root"
  ls -1 "$root" 2>/dev/null | grep -v '\.txt$\|\.bat$\|\.md$' | sed 's/^/  bucket: /'
done
[ -z "$FOUND" ] && echo "no conventional sync root found (\$CLAUDE_MEMORY_SYNC_DIR / OneDrive / Dropbox)"
echo "repo-folder-name (for bucket matching): $PROJ_NAME"

echo
echo "== BUCKET MATCH (does a sync-root bucket belong to THIS project?) =="
# A sync root merely EXISTING is not enough -- other projects' buckets share it.
# Skill Step-2 branch 4 (out-of-band) keys off a POSITIVE bucket-match line.
# F5 tiers: exact > declared > alias > substring. Only exact/declared/alias are
# confident (provenance printed in parens). Substring is a LOW-CONFIDENCE hint
# (bucket-match-lowconf block): the calling skill must confirm with the user --
# never silently execute, never silently ignore. declared/alias come from
# optional recipe-file lines (whole-string equality after normalization, never
# substring):
#   sync-bucket: <exact-bucket-dir-name>
#   sync-bucket-aliases: <name1>, <name2>
# single normalization rule for every tier comparison -- the whole exact/declared/
# alias equality contract rests on all call sites applying the identical rule.
norm() { printf '%s' "$1" | tr 'A-Z' 'a-z' | sed 's/[^a-z0-9]//g'; }
NPROJ=$(norm "$PROJ_NAME")

DECLARED=""; ALIASES=""
if [ -d "$LIVE_MEM" ]; then
  while IFS= read -r rf; do
    [ -n "$rf" ] && [ -f "$rf" ] || continue
    [ -z "$DECLARED" ] && DECLARED=$(grep -i '^sync-bucket:' "$rf" 2>/dev/null | head -1 | sed 's/^[^:]*:[[:space:]]*//' | tr -d '\r')
    [ -z "$ALIASES" ] && ALIASES=$(grep -i '^sync-bucket-aliases:' "$rf" 2>/dev/null | head -1 | sed 's/^[^:]*:[[:space:]]*//' | tr -d '\r')
  done <<RFEOF
$(find "$LIVE_MEM" -maxdepth 1 -type f \( -iname '*memory_sync*' -o -iname '*memory-sync*' -o -iname '*onedrive*' \) 2>/dev/null)
RFEOF
fi
NDECL=$(norm "$DECLARED")

# RETIRED buckets -- checked per bucket BEFORE the tier tests, so every tier (and any
# later change to a tier's predicate) composes with it. A bucket whose TOP LEVEL holds a
# regular file whose name contains SUPERSEDED (case-SENSITIVE substring, e.g.
# 00-SUPERSEDED-BY-GIT.md) carries its own retirement tombstone: it is never a
# candidate at any tier. Measured live: a project repo was offered its own
# tombstoned bucket as a lowconf candidate on every arrival, and the
# settle-it hint below would have DECLARED the dead bucket. Matching on bucket NAMES
# alone cannot see this. Deliberately NOT a `*retired*` glob and NOT case-insensitive:
# a live bucket legitimately holds memory files such as
# project_debug_menu_grants_retired.md. A retired bucket that is ALSO this project's
# exact/declared/alias match is a CONFLICT (a stale name or declaration), printed as a
# bucket-match-warning and treated as no match -- never as a positive bucket-match.
# A retired bucket that would have been this project's substring (lowconf) candidate
# prints `bucket-retired:` instead. A retired bucket matching this project at NO tier
# prints nothing: it is another project's bucket, and naming it would put a line about
# that project into every unrelated project's arrival (measured on the live root).
retired_tombstone() { # $1 bucket dir -> prints the first tombstone file name, if any
  local f
  for f in "$1"*; do
    [ -f "$f" ] || continue
    case "${f##*/}" in *SUPERSEDED*) printf '%s' "${f##*/}"; return 0 ;; esac
  done
  return 0
}

EXACT=""; DECL_M=""; ALIAS_M=""; SUBSTR_LIST=""; RETIRED_HITS=""; RETIRED_DECL=""
for root in "${CLAUDE_MEMORY_SYNC_DIR:-}" "$HOME/OneDrive/claude-memory" "$HOME/Dropbox/claude-memory"; do
  [ -n "$root" ] && [ -d "$root" ] || continue
  for b in "$root"/*/; do
    [ -d "$b" ] || continue
    bn=$(basename "$b")
    nb=$(norm "$bn")
    [ -n "$nb" ] || continue
    tomb=$(retired_tombstone "$b")
    # NOTE: exact/declared/alias are whole-string equality with NO minimum length
    # (a short exact name is still strong ownership evidence); the >=4 gate below
    # guards only the fuzzy substring tier. Pinned by fixture (short-exact case).
    tier=""
    if [ "$nb" = "$NPROJ" ]; then
      tier=exact
    elif [ -n "$NDECL" ] && [ "$nb" = "$NDECL" ]; then
      tier=declared
    elif [ -n "$ALIASES" ]; then
      amatch=""
      # set -f: the comma-split fields must NOT glob-expand against the cwd --
      # an alias like 'proj-*' would otherwise expand to repo filenames and could
      # mint a spurious (alias) positive feeding the branch-4 write path.
      set -f; OLDIFS=$IFS; IFS=','
      for a in $ALIASES; do
        na=$(norm "$a")
        [ -n "$na" ] && [ "$nb" = "$na" ] && amatch=yes
      done
      IFS=$OLDIFS; set +f
      [ -n "$amatch" ] && tier=alias
    fi
    if [ -n "$tomb" ] && [ -n "$tier" ]; then
      RETIRED_HITS="${RETIRED_HITS}bucket-match-warning: $root/$bn is this project's $tier bucket but carries a retirement tombstone ($tomb); treated as no match -- the name or declaration pointing at it is stale
"
      [ "$tier" != exact ] && RETIRED_DECL=yes
      continue
    fi
    case "$tier" in
      exact) [ -z "$EXACT" ] && EXACT="$root/$bn"; continue ;;
      declared) [ -z "$DECL_M" ] && DECL_M="$root/$bn"; continue ;;
      alias) [ -z "$ALIAS_M" ] && ALIAS_M="$root/$bn"; continue ;;
    esac
    [ ${#nb} -ge 4 ] || continue
    case "$NPROJ" in *"$nb"*)
      if [ -n "$tomb" ]; then
        echo "bucket-retired: $root/$bn (tombstone $tomb) -- not a candidate"
      else
        SUBSTR_LIST="${SUBSTR_LIST}${root}/${bn}
"
      fi ;;
    esac
  done
done

printf '%s' "$RETIRED_HITS"
BMATCH="none"; BTIER=""
if [ -n "$EXACT" ]; then
  BMATCH="$EXACT"; BTIER="exact"
  [ -n "$DECL_M" ] && echo "bucket-match-warning: recipe declares '$DECLARED' ($DECL_M) but an exact-name bucket also exists; preferring exact"
elif [ -n "$DECL_M" ]; then BMATCH="$DECL_M"; BTIER="declared"
elif [ -n "$ALIAS_M" ]; then BMATCH="$ALIAS_M"; BTIER="alias"
fi
if [ "$BMATCH" != "none" ]; then
  echo "bucket-match: $BMATCH ($BTIER)"
else
  echo "bucket-match: none"
  # A declared/alias bucket that exists but is RETIRED was already warned about above;
  # "no matching bucket exists" would be false about it.
  if { [ -n "$NDECL" ] || [ -n "$ALIASES" ]; } && [ -z "$RETIRED_DECL" ]; then
    DECL_DESC="$DECLARED"
    [ -z "$DECL_DESC" ] && DECL_DESC="$ALIASES"
    echo "bucket-match-warning: recipe declares '$DECL_DESC' but no matching bucket exists in any sync root"
  fi
  if [ -n "$SUBSTR_LIST" ]; then
    echo "bucket-match-lowconf (substring only -- confirm with the user before treating as branch 4; never silently execute, never silently ignore):"
    printf '%s' "$SUBSTR_LIST" | sed '/^$/d;s/^/  candidate: /'
    # Name the PERMANENT fix at the moment of need, not just the one-time decision.
    # Measured on a sibling project: a folder-name mismatch (repo `X - Final Solution
    # type v2` vs bucket `X-AUTOMATION`) made this lowconf every time, and NINE
    # consecutive handoffs each paused to re-adjudicate a settled fact -- the recorded
    # answer lived in the recipe's prose, which no detector reads. The loop closed only
    # when someone finally added the machine-readable line below.
    #
    # Deliberately NOT auto-promoting on a prose absolute path found in the recipe: a
    # path can be mentioned in passing, and promoting to `declared` SKIPS the user
    # confirmation this branch exists to require. Failing toward "ask" is correct here;
    # failing toward "silently execute a bucket recipe" is not. So the fix is to make
    # the declaration cheap to record, not to guess at it.
    echo "  -> to settle this permanently, add a machine-readable line to the recipe file above:"
    echo "     sync-bucket: <bucket folder name>        (or: sync-bucket-aliases: <name> <name>)"
    echo "     Without it this stays lowconf and EVERY future handoff re-asks the same question."
  fi
fi

# recipe_shape <file> -- where a recipe note's RECIPE ends and its dated history log
# begins, so the calling skill reads the recipe and not the log. Read-only.
# Measured (a sibling project, 2026-09-23): a 44 KB recipe note whose recipe was its
# first 24 lines (5 KB); the rest was 41 dated "**UPDATE <date> (...):**" entries, not
# in date order, and an arrival read all of it to get one copy command.
#   body        = every line before the first dated entry (a line starting
#                 "**UPDATE <YYYY-MM-DD>") or a heading naming History/Log/Updates/
#                 Changelog. No such line = the whole file is the body.
#   entries     = "**UPDATE <date>" lines, dated headings and date-led bullets, from
#                 the log start on. Fenced code blocks are skipped for every rule here,
#                 so a "# ... log" shell comment in a fence is not a heading.
#   newest-*    = the entry with the latest YYYY-MM-DD (ties: the later line) whose
#                 FIRST direction marker is an arrival ("arrival", or "pulled ... down")
#                 or a departure ("departure", or "pushed ... up"). A departure entry
#                 that mentions "the next arrival" is still a departure. The calling
#                 skill checks the command's direction anyway.
#   sync-arrival: / sync-departure: = line-start declarations, printed verbatim (the
#                 same convention as sync-bucket:). One saves the next run the search
#                 for the command; the body is still read, since it states the guard.
# LC_ALL=C makes length() count bytes; BINMODE=1 stops Windows gawk dropping the CR
# of a CRLF line, which would under-count the body by one byte per line.
recipe_shape() {
  local rf="$1" size
  size=$(wc -c < "$rf" 2>/dev/null | tr -d ' ')
  LC_ALL=C awk -v BINMODE=1 -v size="${size:-0}" -v dir="$DIRECTION" '
    function datekey(s) {
      if (match(s, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) return substr(s, RSTART, 10)
      return ""
    }
    function datelabel(s,   t) {
      if (!match(s, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) return "undated"
      t = substr(s, RSTART)
      sub(/[(:*].*$/, "", t)
      sub(/[ \t]+$/, "", t)
      return substr(t, 1, 40)
    }
    function firstmark(t, word, re,   a, b) {
      a = index(t, word)
      b = match(t, re) ? RSTART : 0
      return (!a || (b && b < a)) ? b : a
    }
    function newest(kind,   i, best) {
      best = 0
      for (i = 1; i <= n; i++)
        if (hit[kind, i] && (best == 0 || key[i] >= key[best])) best = i
      return best
    }
    function report(kind,   b, last) {
      b = newest(kind)
      if (!b) {
        printf "    newest-%s-entry: none (no dated entry mentions a %s)\n", kind, kind
        return
      }
      last = (b < n) ? start[b + 1] - 1 : NR
      printf "    newest-%s-entry: lines %d-%d (%s)\n", kind, start[b], last, lab[b]
    }
    {
      raw = $0; line = raw; sub(/\r$/, "", line)
      nbytes[NR] = length(raw) + 1
      if (line ~ /^[ \t]*(```|~~~)/) { fence = !fence; next }
      if (fence) next
      low = tolower(line)
      # A declaration counts only in the BODY. Once the dated log has started, a line-start
      # sync-arrival:/sync-departure: is a quoted, possibly superseded command: history.
      if (low ~ /^sync-(arrival|departure):/) {
        if (logstart) stale++
        else {
          decl[++nd] = line
          declared[(low ~ /^sync-arrival:/) ? "arrival" : "departure"] = 1
        }
      }
      is_update = (line ~ /^\*\*UPDATE [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)
      is_loghead = (low ~ /^#+[ \t]/ && low ~ /(^|[^a-z])(history|log|updates|changelog)([^a-z]|$)/)
      if (!logstart && (is_update || is_loghead)) logstart = NR
      if (!logstart) next
      if (is_update || line ~ /^#+[ \t].*[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/ ||
          line ~ /^[-*][ \t]+(\*\*)?[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/) {
        n++; start[n] = NR; key[n] = datekey(line); lab[n] = datelabel(line); text[n] = low
      } else if (n) {
        text[n] = text[n] " " low
      }
    }
    END {
      # An entry takes the direction of its FIRST marker. Real entries mention both
      # ("DEPARTURE ... the next arrival takes them"), so any mention is not enough.
      for (i = 1; i <= n; i++) {
        a = firstmark(text[i], "arrival", "pulled[^a-z].*[^a-z]down([^a-z]|$)")
        d = firstmark(text[i], "departure", "pushed[^a-z].*[^a-z]up([^a-z]|$)")
        hit["arrival", i] = (a && (!d || a < d))
        hit["departure", i] = (d && (!a || d < a))
      }
      printf "    size: %d bytes, %d lines\n", size, NR
      for (i = 1; i <= nd; i++) print "    " decl[i]
      if (stale)
        printf "    ignored: %d sync-arrival/sync-departure line(s) inside the dated history log -- history, not a live declaration\n", stale
      bb = 0
      if (!logstart) {
        printf "    body: lines 1-%d (%d bytes) -- the whole file; there is no dated history log\n", NR, size
      } else if (logstart == 1) {
        print "    body: none -- the file opens with its dated history log"
      } else {
        for (i = 1; i < logstart; i++) bb += nbytes[i]
        printf "    body: lines 1-%d (%d bytes) -- the recipe; read this range, not the whole file\n", logstart - 1, bb
      }
      if (logstart) {
        printf "    history-log: lines %d-%d (%d bytes, %d dated entries) -- never read it whole\n", logstart, NR, size - bb, n
        report("arrival")
        report("departure")
      }
      if (!declared[dir])
        printf "    -> add a line  sync-%s: <command>  to this file so the next %s takes the command from it instead of searching the note\n", dir, dir
    }
  ' "$rf" 2>/dev/null || echo "    shape: unknown (could not read the recipe file; read it with care)"
}

echo
echo "== RECIPE FILE (out-of-band transport recipe only) =="
# Deliberately narrow: only out-of-band/OneDrive sync recipes, NOT generic
# cross-machine/git-mirror transfer notes (those are not runnable bucket recipes).
# Each "  recipe: <path>" line is unchanged; its shape lines follow it, indented.
if [ -d "$LIVE_MEM" ]; then
  RF=$(find "$LIVE_MEM" -maxdepth 1 -type f \( -iname '*memory_sync*' -o -iname '*memory-sync*' -o -iname '*onedrive*' \) 2>/dev/null)
  if [ -n "$RF" ]; then
    while IFS= read -r rf; do
      [ -n "$rf" ] || continue
      printf '  recipe: %s\n' "$rf"
      recipe_shape "$rf"
    done <<RSEOF
$RF
RSEOF
  else
    echo "  none (no memory-sync/onedrive recipe file in live memory dir)"
  fi
else
  echo "  (live memory dir does not exist -- cannot search for a recipe file)"
fi

# == OUT-OF-REPO DELIVERABLES == (departure only). Measured (a sibling project,
# 2026-09-30): another agent wrote a 481-file, 52 MB audit to ~/Documents/<NAME>_SEO_.../
# with a README_CLAUDE.md addressed to Claude. Everything above enumerates the repo tree,
# so the departure named nothing and the owner had to ask for it by hand. This section
# POINTS at such a dir so the handoff report can name it; it never copies, moves or
# modifies anything (copying was refused as a sensitive source), and it never blocks.
# Two traps, both from the incident:
#   time -- this probe runs AFTER the wrap committed HANDOFF.md, so a deliverable written
#           earlier in the session is OLDER than HEAD's newest handoff commit. The threshold
#           is what the other machine last received: the newest handoff-doc commit on
#           @{upstream}; else the second-newest on HEAD; else 7 days ago.
#   name -- the real README never said the repo name, only its first word, and the dir was
#           named <WORD>_SEO_... So the match is on whole-word tokens of the repo name, in
#           the file's text or its directory's name, minus a stoplist of generic words.
if [ "$DIRECTION" = departure ]; then
  echo
  echo "== OUT-OF-REPO DELIVERABLES (departure only; a pointer for the report -- never copied, never blocks the push) =="
  DELIV_ROOT="${PROBE_DELIVERABLE_ROOT:-$HOME/Documents}"
  [ "$DELIV_ROOT" != "/" ] && DELIV_ROOT="${DELIV_ROOT%/}"
  if [ ! -d "$DELIV_ROOT" ]; then
    echo "search-root: $DELIV_ROOT -- MISSING (or not a directory); nothing searched (PROBE_DELIVERABLE_ROOT overrides it)"
  else
    HANDOFF_DOCS=(HANDOFF.md context/HANDOFF.md CONTEXT.md continuation/context.md)
    DT=""; DT_SRC=""
    if git rev-parse --git-dir >/dev/null 2>&1; then
      if git rev-parse '@{upstream}' >/dev/null 2>&1; then
        DT=$(git -C "$CUR_WT" log -1 --format='%ct %ci' '@{upstream}' -- "${HANDOFF_DOCS[@]}" 2>/dev/null)
        [ -n "$DT" ] && DT_SRC="newest handoff-doc commit on @{upstream}: what the other machine last received"
      fi
      if [ -z "$DT" ]; then
        DT=$(git -C "$CUR_WT" log -2 --format='%ct %ci' HEAD -- "${HANDOFF_DOCS[@]}" 2>/dev/null | sed -n 2p)
        [ -n "$DT" ] && DT_SRC="second-newest handoff-doc commit on HEAD (no upstream, or no handoff-doc commit on it)"
      fi
    fi
    case "${DT%% *}" in
      ''|*[!0-9]*)
        DT_EPOCH=$(( $(date +%s) - 7 * 86400 ))
        DT_HUMAN=$(date -d "@$DT_EPOCH" '+%Y-%m-%d %H:%M:%S %z' 2>/dev/null || date -r "$DT_EPOCH" '+%Y-%m-%d %H:%M:%S %z' 2>/dev/null || echo "epoch $DT_EPOCH")
        DT_SRC="7 days ago (no usable handoff-doc commit)" ;;
      *) DT_EPOCH=${DT%% *}; DT_HUMAN=${DT#* } ;;
    esac
    # Words of a name: split on every non-alphanumeric and on camelCase, lowercased.
    deliv_words() {
      printf '%s\n' "$1" | sed 's/\([a-z0-9]\)\([A-Z]\)/\1 \2/g; s/\([A-Z]\)\([A-Z][a-z]\)/\1 \2/g' \
        | tr -c 'A-Za-z0-9\n' '\n' | tr 'A-Z' 'a-z' | sed '/^$/d'
    }
    DELIV_STOP=" claude website site main project projects repo the and docs app web for with final solution type "
    DELIV_TOKS=""
    while IFS= read -r w; do
      [ "${#w}" -ge 3 ] || continue
      case "$DELIV_STOP" in *" $w "*) continue ;; esac
      case " $DELIV_TOKS " in *" $w "*) continue ;; esac
      DELIV_TOKS="${DELIV_TOKS:+$DELIV_TOKS }$w"
    done <<DWEOF
$(deliv_words "$PROJ_NAME")
DWEOF
    [ -z "$DELIV_TOKS" ] && DELIV_TOKS=$(norm "$PROJ_NAME")
    echo "search-root: $DELIV_ROOT (find -maxdepth 3 for README_CLAUDE.md / *HANDOFF*.md; node_modules, .git, venvs pruned)"
    echo "threshold: $DT_HUMAN -- $DT_SRC"
    if [ -z "$DELIV_TOKS" ]; then
      echo "project-tokens: none (no usable word in '$PROJ_NAME') -- nothing can match; check $DELIV_ROOT by hand"
    else
      echo "project-tokens: $DELIV_TOKS (whole words of '$PROJ_NAME', generic words dropped)"
      DELIV_RE="(^|[^[:alnum:]])($(printf '%s' "$DELIV_TOKS" | tr ' ' '|'))([^[:alnum:]]|$)"
      # Physical, lowercased path: the repo's own handoff doc is never an out-of-repo deliverable.
      deliv_phys() { (cd "$1" 2>/dev/null && pwd -P) | tr 'A-Z' 'a-z'; }
      REPO_P=$(deliv_phys "$CUR_WT"); MAIN_P=$(deliv_phys "$MAIN_WT")
      DELIV_FOUND=$(find "$DELIV_ROOT" -mindepth 1 -maxdepth 3 \
        \( -type d \( -name node_modules -o -name .git -o -name .venv -o -name venv -o -name __pycache__ \) \) -prune \
        -o -type f \( -iname 'README_CLAUDE.md' -o -iname '*HANDOFF*.md' \) -print 2>/dev/null)
      DELIV_FIND_RC=$?
      N_CAND=0; N_NEW=0; DELIV_HITS=""; DELIV_UNREAD=""
      while IFS= read -r f; do
        [ -n "$f" ] || continue
        N_CAND=$((N_CAND + 1))
        m=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
        case "$m" in ''|*[!0-9]*) DELIV_UNREAD="${DELIV_UNREAD}  could not read the mtime of $f -- check it by hand
"; continue ;; esac
        [ "$m" -gt "$DT_EPOCH" ] || continue
        d=$(dirname "$f")
        dp=$(deliv_phys "$d")
        if [ -n "$dp" ]; then
          [ -n "$REPO_P" ] && case "$dp/" in "$REPO_P/"*) continue ;; esac
          [ -n "$MAIN_P" ] && case "$dp/" in "$MAIN_P/"*) continue ;; esac
        fi
        N_NEW=$((N_NEW + 1))
        # A file loose in the root is its own deliverable; never size the whole root.
        if [ "$d" = "$DELIV_ROOT" ]; then unit="$f"; else unit="$d"; fi
        hit=""
        for dw in $(deliv_words "$(basename "$d")"); do
          case " $DELIV_TOKS " in *" $dw "*) hit=yes ;; esac
        done
        if [ -z "$hit" ]; then
          LC_ALL=C.UTF-8 grep -qiE "$DELIV_RE" "$f" 2>/dev/null
          grc=$?
          if [ "$grc" -eq 0 ]; then hit=yes
          elif [ "$grc" -ne 1 ]; then DELIV_UNREAD="${DELIV_UNREAD}  could not scan $f (grep rc=$grc) -- check it by hand
"; fi
        fi
        if [ -n "$hit" ]; then
          case "
$DELIV_HITS" in *"
$unit
"*) ;; *) DELIV_HITS="${DELIV_HITS}${unit}
" ;; esac
        fi
      done <<DFEOF
$DELIV_FOUND
DFEOF
      N_HIT=0
      while IFS= read -r u; do
        [ -n "$u" ] || continue
        N_HIT=$((N_HIT + 1))
        n=$(find "$u" -type f 2>/dev/null | wc -l | tr -d ' ')
        sz=$(du -sh "$u" 2>/dev/null | cut -f1)
        [ "$n" = 1 ] && nf="1 file" || nf="$n files"
        echo "OUT-OF-REPO DELIVERABLE: $u ($nf, ${sz:-size unknown}) -- will NOT travel with the push"
      done <<DHEOF
$DELIV_HITS
DHEOF
      echo "scanned: $N_CAND named file(s), $N_NEW newer than the threshold and outside this repo, $N_HIT deliverable(s) naming this project"
      [ -n "$DELIV_UNREAD" ] && printf '%s' "$DELIV_UNREAD"
      [ "$DELIV_FIND_RC" -ne 0 ] && echo "  note: find exited $DELIV_FIND_RC under $DELIV_ROOT (unreadable entries?) -- the listing may be partial"
      [ "$N_HIT" -eq 0 ] && echo "OUT-OF-REPO DELIVERABLES: none found under $DELIV_ROOT newer than $DT_HUMAN naming: $DELIV_TOKS"
    fi
  fi
fi

echo
echo "== VERDICT =="
echo "Identify the transport branch IN ORDER; take the FIRST that matches:"
echo "  1 junction-into-repo => no-op (git already syncs it)"
echo "  2 in-repo mirror + bootstrap script => bootstrap / mirror copy-back handles it"
echo "  3 junction-to-out-of-band => OS auto-syncs"
echo "  4 POSITIVE bucket-match (exact/declared/alias) => out-of-band bucket transport; use the recipe's declared command or read only its body range (RECIPE FILE above)."
echo "    bucket-match-lowconf (substring) is NOT branch 4 -- surface candidates + confirm with the user."
echo "    bucket-retired (tombstoned) is NOT branch 4 -- never executed, never asked about."
echo "  4b repo-is-transport: yes => the git-tracked memory dir IS the transport; it travels on the"
echo "     push the handoff already performs. A no-op FOR A STATED REASON, not an absent transport."
echo "  5 none of the above AND repo-is-transport: no => genuinely no cross-device memory transport."
echo "     Branch 5 means work WILL be stranded -- it is the only branch worth alarming about."
echo "A sync root EXISTING is not branch 4 -- only a positive bucket-match is. DIRECTION is the"
echo "calling skill's job: device-sync pulls bucket->local (arrival); device-handoff pushes local->bucket (departure)."
exit 0
