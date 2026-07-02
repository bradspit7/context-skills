#!/usr/bin/env bash
# probe-sync.sh -- cross-device sync probe for the device-sync skill.
# Read-only. Dumps the raw transport facts the skill reasons over (probe-before-
# parse: never assume a transport). Always exits 0; any section that cannot be
# determined prints "unknown" rather than failing.

set -u

echo "== MACHINE =="
hostname

echo
echo "== GIT =="
if git rev-parse --git-dir >/dev/null 2>&1; then
  echo "is-git: yes"
  CUR_WT=$(git rev-parse --show-toplevel 2>/dev/null)
  echo "repo-root: $CUR_WT"
  if git rev-parse '@{upstream}' >/dev/null 2>&1; then
    BEHIND=$(git rev-list --count HEAD..@{upstream} 2>/dev/null || echo '?')
    AHEAD=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo '?')
    echo "behind-upstream: $BEHIND   ahead-upstream: $AHEAD"
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
MIR=""
for d in claude-infra/memory continuation/memory; do
  if [ -d "$d" ]; then MIR="yes"; echo "  $d ($(ls "$d"/*.md 2>/dev/null | wc -l | tr -d ' ') md files)"; fi
done
[ -z "$MIR" ] && echo "none (no claude-infra/memory or continuation/memory in repo)"

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
echo "  5 none of the above => no cross-device memory transport"
echo "A sync root EXISTING is not branch 4 -- only a positive bucket-match is. DIRECTION is the"
echo "calling skill's job: device-sync pulls bucket->local (arrival); device-handoff pushes local->bucket (departure)."
exit 0
