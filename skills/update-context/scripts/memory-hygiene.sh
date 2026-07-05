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
#      byte parity. Mirror-only strays are REPORTED, never deleted.
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
    for m in "$MIRROR"/*.md; do
      [ -f "$m" ] || continue
      b=$(basename "$m")
      [ -f "$MEMDIR/$b" ] || echo "STRAY   $b exists only in the mirror (deleted live? remove by hand if intended)"
    done
    [ "$BAD" -eq 0 ] && echo "parity: OK"
  fi
fi

echo
echo "== DONE =="
echo "If memory files get written AFTER this run (the auto-memory normalizer re-adds trailing"
echo "whitespace on every write), re-run this before the wrap commit — it is idempotent."
