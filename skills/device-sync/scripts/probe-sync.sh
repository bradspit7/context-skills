#!/usr/bin/env bash
# probe-sync.sh — cross-device sync probe for the device-sync skill.
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
# (cmd //c fsutil was unreliable from git-bash — //c needs MSYS conversion, which
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
echo "== SESSION-START BLOCK (CLAUDE.md) =="
HIT=""
for cm in CLAUDE.md .claude/CLAUDE.md context/CLAUDE.md; do
  [ -f "$cm" ] || continue
  M=$(grep -inE '^#+.*(session[ -]?start|run before any|bootstrap|fresh clone|fresh-laptop|cross-machine)' "$cm" 2>/dev/null | head -3)
  if [ -n "$M" ]; then HIT="yes"; printf '%s\n' "$M" | sed "s|^|  $cm: |"; fi
done
[ -z "$HIT" ] && echo "none found (no documented session-start heading)"

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
echo "== OUT-OF-BAND SYNC ROOT (hint only — recipe file is authoritative) =="
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
echo "== RECIPE FILE (project's documented transport) =="
if [ -d "$LIVE_MEM" ]; then
  RF=$(find "$LIVE_MEM" -maxdepth 1 -type f \( -iname '*memory_sync*' -o -iname '*memory-sync*' -o -iname 'cross-machine*' -o -iname '*cross_machine*' -o -iname '*onedrive*' -o -iname 'device*' \) 2>/dev/null)
  if [ -n "$RF" ]; then printf '%s\n' "$RF" | sed 's/^/  recipe: /'; else echo "  none (no memory-sync/onedrive/cross-machine recipe file in live memory dir)"; fi
else
  echo "  (live memory dir does not exist — cannot search for a recipe file)"
fi

echo
echo "== VERDICT =="
echo "Use these facts to pick ONE Step-2 branch in the device-sync skill."
echo "in-repo mirror+junction => no-op (git pull synced it) | mirror+bootstrap => bootstrap copied it"
echo "out-of-band bucket => read the recipe file, run it bucket->local | junction-to-bucket => OS auto-syncs"
echo "none => no cross-device memory sync. Always remote->local; never local->bucket here."
exit 0
