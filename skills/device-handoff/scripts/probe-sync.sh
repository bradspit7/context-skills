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

EXACT=""; DECL_M=""; ALIAS_M=""; SUBSTR_LIST=""
for root in "${CLAUDE_MEMORY_SYNC_DIR:-}" "$HOME/OneDrive/claude-memory" "$HOME/Dropbox/claude-memory"; do
  [ -n "$root" ] && [ -d "$root" ] || continue
  for b in "$root"/*/; do
    [ -d "$b" ] || continue
    bn=$(basename "$b")
    nb=$(norm "$bn")
    [ -n "$nb" ] || continue
    # NOTE: exact/declared/alias are whole-string equality with NO minimum length
    # (a short exact name is still strong ownership evidence); the >=4 gate below
    # guards only the fuzzy substring tier. Pinned by fixture (short-exact case).
    if [ "$nb" = "$NPROJ" ]; then
      [ -z "$EXACT" ] && EXACT="$root/$bn"; continue
    fi
    if [ -n "$NDECL" ] && [ "$nb" = "$NDECL" ]; then
      [ -z "$DECL_M" ] && DECL_M="$root/$bn"; continue
    fi
    if [ -n "$ALIASES" ]; then
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
      if [ -n "$amatch" ]; then [ -z "$ALIAS_M" ] && ALIAS_M="$root/$bn"; continue; fi
    fi
    [ ${#nb} -ge 4 ] || continue
    case "$NPROJ" in *"$nb"*) SUBSTR_LIST="${SUBSTR_LIST}${root}/${bn}
";; esac
  done
done

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
  if [ -n "$NDECL" ] || [ -n "$ALIASES" ]; then
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

echo
echo "== RECIPE FILE (out-of-band transport recipe only) =="
# Deliberately narrow: only out-of-band/OneDrive sync recipes, NOT generic
# cross-machine/git-mirror transfer notes (those are not runnable bucket recipes).
if [ -d "$LIVE_MEM" ]; then
  RF=$(find "$LIVE_MEM" -maxdepth 1 -type f \( -iname '*memory_sync*' -o -iname '*memory-sync*' -o -iname '*onedrive*' \) 2>/dev/null)
  if [ -n "$RF" ]; then printf '%s\n' "$RF" | sed 's/^/  recipe: /'; else echo "  none (no memory-sync/onedrive recipe file in live memory dir)"; fi
else
  echo "  (live memory dir does not exist -- cannot search for a recipe file)"
fi

echo
echo "== VERDICT =="
echo "Identify the transport branch IN ORDER; take the FIRST that matches:"
echo "  1 junction-into-repo => no-op (git already syncs it)"
echo "  2 in-repo mirror + bootstrap script => bootstrap / mirror copy-back handles it"
echo "  3 junction-to-out-of-band => OS auto-syncs"
echo "  4 POSITIVE bucket-match (exact/declared/alias) => out-of-band bucket transport; open the recipe file."
echo "    bucket-match-lowconf (substring) is NOT branch 4 -- surface candidates + confirm with the user."
echo "  4b repo-is-transport: yes => the git-tracked memory dir IS the transport; it travels on the"
echo "     push the handoff already performs. A no-op FOR A STATED REASON, not an absent transport."
echo "  5 none of the above AND repo-is-transport: no => genuinely no cross-device memory transport."
echo "     Branch 5 means work WILL be stranded -- it is the only branch worth alarming about."
echo "A sync root EXISTING is not branch 4 -- only a positive bucket-match is. DIRECTION is the"
echo "calling skill's job: device-sync pulls bucket->local (arrival); device-handoff pushes local->bucket (departure)."
exit 0
