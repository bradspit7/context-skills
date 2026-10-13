#!/usr/bin/env bash
# memory-hygiene.sh — wrap-time FIXER for the mechanical hygiene classes session-evidence.sh
# detects. Detect (session-evidence.sh) stays separate from repair (this) on purpose: the
# detector runs read-only at Step 1; this runs at Step 5/7 when the wrap decides to fix.
# Ships because the strip/copy/verify rounds were hand-retyped at nearly every wrap across
# 4+ projects (2026-07-04 skill audit — highest-frequency manual ritual in the corpus).
#
# Usage: bash memory-hygiene.sh <memory_dir> [mirror_dir]
#   1. Strips trailing whitespace INSIDE YAML frontmatter of every *.md in <memory_dir>,
#      in place, idempotent. Scope matches session-evidence.sh's detector exactly —
#      markdown BODY lines are untouched (a hard break legitimately ends in two spaces).
#   2. Lists MEMORY.md index lines over 200 chars (line number + length). REPORT-ONLY:
#      trimming is a judgment MOVE (verify the detail lives in the topic file first).
#   3. With [mirror_dir]: copies *.md into the mirror (never *.md.bak), then verifies
#      byte parity. A mirror-only *.md (in the mirror, not in live) is classified when
#      <memory_dir>/.restored-from names the commit the mirror was last copied INTO live
#      from (a restore step writes it; a dotfile, so it is never mirrored or indexed):
#        deleted live  -- present at that commit with the SAME bytes, so live received it and
#                         it is gone there: REMOVED from the mirror, named with its recovery
#                         command (git show <sha>:<path>);
#        arrived later -- absent from that commit's tree (a pull brought it after the restore):
#                         named, never deleted; the next restore copies it into live;
#        conflict      -- present at that commit but its bytes changed since: named, never
#                         deleted.
#      No stamp, a stamp that is not a full commit id, a commit the mirror's repository
#      does not have, or no git: the STRAY report, unchanged, plus one line saying why the
#      check did not run. Only a classified deletion is ever removed.
# Always exits 0. Writes ONLY inside <memory_dir> (pass 1) and [mirror_dir] (pass 3).

set -u

MEMDIR="${1:-}"
MIRROR="${2:-}"

if [ -z "$MEMDIR" ] || [ ! -d "$MEMDIR" ]; then
  echo "usage: memory-hygiene.sh <memory_dir> [mirror_dir]   (memory_dir missing or not a dir: '${MEMDIR}')"
  exit 0
fi

echo "== FRONTMATTER TRAILING-WS STRIP ($MEMDIR) =="
FIXED=0
for f in "$MEMDIR"/*.md; do
  [ -f "$f" ] || continue
  [ "$(sed -n '1p' "$f" 2>/dev/null | tr -d '\r')" = "---" ] || continue
  # closing fence line number (tolerates CRLF); frontmatter body = lines 2..END-1
  END=$(awk 'NR==1{next} {l=$0; sub(/\r$/,"",l)} l=="---"{print NR; exit}' "$f")
  [ -n "$END" ] && [ "$END" -gt 2 ] || continue
  # detection uses the SAME awk expression as session-evidence.sh's HYGIENE scan
  L=$(awk 'NR==1{infm=1;next} infm&&$0=="---"{exit} infm&&/[ \t]$/{printf "%s ",NR}' "$f" 2>/dev/null)
  if [ -n "$L" ]; then
    # Byte-preserving rewrite via awk temp+swap — NOT sed -i: MSYS GNU sed rewrites the
    # WHOLE file's line endings (CRLF->LF) in text mode, and BSD sed both needs `-i ''`
    # and reads \t in a bracket class as a literal 't' (review-fleet 2026-07-04, primary
    # #3/#4/#5). Each line keeps its own terminator: \r is detached, the strip runs on
    # the frontmatter body only, then \r is re-attached. BINMODE=3 forces binary I/O on
    # Windows gawk, which otherwise strips \r on INPUT (measured live — without it the
    # rewrite still flattened CRLF); elsewhere it is an ordinary ignored variable.
    TMP="${f}.hygtmp"
    awk -v BINMODE=3 -v end="$END" '{
      if (NR >= 2 && NR < end) {
        cr = sub(/\r$/, "") ? "\r" : ""
        sub(/[ \t]+$/, "")
        $0 = $0 cr
      }
      print
    }' "$f" > "$TMP" && mv "$TMP" "$f" || { rm -f "$TMP"; echo "ERROR   $f rewrite failed — file left untouched"; continue; }
    echo "FIXED   $f (line(s): $L)"
    FIXED=$((FIXED+1))
  fi
done
[ "$FIXED" -eq 0 ] && echo "(clean — no frontmatter trailing whitespace)"

IDX="$MEMDIR/MEMORY.md"
echo
echo "== INDEX LINES >200 CHARS (report-only — a trim is a MOVE into the topic file, never a cut) =="
if [ -f "$IDX" ]; then
  # single pass prints matches AND the clean line (locale matches session-evidence.sh's
  # detector on purpose — the fixer must count exactly like the detector)
  LC_ALL=en_US.UTF-8 awk 'length > 200 {printf "LONG    line %d (%d chars): %.80s...\n", NR, length, $0; n++} END {if (!n) print "(clean — no over-length index lines)"}' "$IDX"
else
  echo "(no MEMORY.md index at $IDX)"
fi

# git, run in the mirror's own repository. cd in a subshell rather than -C: under
# MSYS_NO_PATHCONV (needed so <sha>:<path> reaches git verbatim) a POSIX -C path would
# not be converted either. A GIT_DIR/GIT_WORK_TREE leaked from a hook would point the
# lookups at another repository, so they are dropped.
mgit() {
  ( cd "$MIRROR" 2>/dev/null || exit 128
    unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE
    MSYS_NO_PATHCONV=1 git "$@" )
}

# The commit live memory was last restored from, checked against the mirror's repository.
# Sets RSHA (full id) and RPREFIX (the mirror's path inside its repo) and returns 0, or
# sets WHY and returns 1. A symbolic name ("HEAD", a branch) or an abbreviated id is
# refused: it would name whatever commit it points at NOW, not the one restored from.
restore_point() {
  RSHA=""; RPREFIX=""; WHY=""
  local f s
  f="$MEMDIR/.restored-from"
  if [ ! -f "$f" ]; then
    WHY="no .restored-from stamp in $MEMDIR, so nothing records which commit live memory was last restored from"
    return 1
  fi
  s=$(sed -n '1p' "$f" 2>/dev/null | tr -d '\r')
  case "$s" in
    ""|*[!0-9a-f]*) WHY="the .restored-from stamp does not hold a full commit id"; return 1 ;;
  esac
  if [ "${#s}" -ne 40 ] && [ "${#s}" -ne 64 ]; then
    WHY="the .restored-from stamp does not hold a full commit id"
    return 1
  fi
  if ! command -v git >/dev/null 2>&1; then
    WHY="git is not on PATH"
    return 1
  fi
  if ! RPREFIX=$(mgit rev-parse --show-prefix 2>/dev/null); then
    RPREFIX=""
    WHY="the mirror is not inside a git repository"
    return 1
  fi
  if ! mgit cat-file -e "$s^{commit}" 2>/dev/null; then
    WHY="the .restored-from stamp names $s, a commit the mirror's repository does not have"
    return 1
  fi
  RSHA="$s"
}

# One mirror-only file, against the restore commit. Removes it ONLY when that commit holds
# it with the same bytes; every other outcome leaves it and names it.
classify() {
  local m b ent rc mode type oid rest
  m="$1"; b="$2"
  ent=$(mgit ls-tree --full-tree "$RSHA" -- "$RPREFIX$b" 2>/dev/null)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    echo "UNKNOWN $b could not be looked up in $SHORT (git ls-tree exited $rc): left in place"
    N_UNK=$((N_UNK+1)); return
  fi
  if [ -z "$ent" ]; then
    echo "ARRIVED $b is not in $SHORT, the commit live memory was restored from: it reached the mirror later (a pull), so it is left in place and the next bootstrap copies it into live"
    N_ARR=$((N_ARR+1)); return
  fi
  read -r mode type oid rest <<< "$ent"
  case "$ent" in *"
"*) type="(several entries)" ;; esac
  if [ "$type" != "blob" ] || { [ "$mode" != "100644" ] && [ "$mode" != "100755" ]; }; then
    echo "UNKNOWN $b is not a plain file at $SHORT ($mode $type): left in place"
    N_UNK=$((N_UNK+1)); return
  fi
  mgit cat-file blob "$oid" 2>/dev/null | cmp -s - "$m"
  local ps=("${PIPESTATUS[@]}")
  if [ "${ps[0]}" -ne 0 ] || [ "${ps[1]}" -gt 1 ]; then
    echo "UNKNOWN $b could not be compared with its blob at $SHORT: left in place"
    N_UNK=$((N_UNK+1)); return
  fi
  if [ "${ps[1]}" -eq 1 ]; then
    echo "CONFLICT $b was deleted live here but changed elsewhere since $SHORT: left in place (compare: git diff $SHORT -- $RPREFIX$b; remove it from the mirror by hand if the deletion should win)"
    N_CON=$((N_CON+1)); return
  fi
  rm -f "$m"
  if [ -e "$m" ]; then
    echo "ERROR   $b was deleted live but could not be removed from the mirror"
    N_UNK=$((N_UNK+1)); return
  fi
  echo "DELETED $b was deleted live (restored into live at $SHORT, unchanged since): removed from the mirror. Recover: git show $RSHA:$RPREFIX$b"
  N_DEL=$((N_DEL+1))
}

if [ -n "$MIRROR" ]; then
  echo
  echo "== MIRROR SYNC ($MEMDIR -> $MIRROR) =="
  if [ ! -d "$MIRROR" ]; then
    echo "mirror dir does not exist: $MIRROR (create it first; nothing copied)"
  else
    COPIED=0
    for f in "$MEMDIR"/*.md; do
      [ -f "$f" ] || continue
      b=$(basename "$f")
      if [ ! -f "$MIRROR/$b" ] || ! cmp -s "$f" "$MIRROR/$b"; then
        cp "$f" "$MIRROR/$b"
        echo "SYNCED  $b"
        COPIED=$((COPIED+1))
      fi
    done
    [ "$COPIED" -eq 0 ] && echo "(already in parity — nothing copied)"
    BAD=0
    for f in "$MEMDIR"/*.md; do
      [ -f "$f" ] || continue
      b=$(basename "$f")
      cmp -s "$f" "$MIRROR/$b" || { echo "PARITY-FAIL $b"; BAD=1; }
    done
    # Mirror-only files: a deletion in live, or a file that reached the mirror after live
    # was last restored from it? Only the restore commit can tell them apart (pass 3 above).
    NONLY=0
    for m in "$MIRROR"/*.md; do
      [ -f "$m" ] || continue
      [ -f "$MEMDIR/$(basename "$m")" ] || NONLY=$((NONLY+1))
    done
    if [ "$NONLY" -gt 0 ]; then
      if restore_point; then
        SHORT=$(printf '%s' "$RSHA" | cut -c1-12)
        N_DEL=0; N_ARR=0; N_CON=0; N_UNK=0
        for m in "$MIRROR"/*.md; do
          [ -f "$m" ] || continue
          b=$(basename "$m")
          [ -f "$MEMDIR/$b" ] || classify "$m" "$b"
        done
        echo "deletion check (live restored from $SHORT): $N_DEL removed, $N_ARR arrived later, $N_CON conflict(s), $N_UNK unknown"
      else
        for m in "$MIRROR"/*.md; do
          [ -f "$m" ] || continue
          b=$(basename "$m")
          [ -f "$MEMDIR/$b" ] || echo "STRAY   $b exists only in the mirror (deleted live? remove by hand if intended)"
        done
        echo "NOT-RUN deletion check: $WHY. The STRAY file(s) above are left in place."
      fi
    fi
    [ "$BAD" -eq 0 ] && echo "parity: OK"
  fi
fi

echo
echo "== DONE =="
echo "If memory files get written AFTER this run (the auto-memory normalizer re-adds trailing"
echo "whitespace on every write), re-run this before the wrap commit — it is idempotent."
