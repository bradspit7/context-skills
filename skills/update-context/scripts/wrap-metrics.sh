#!/usr/bin/env bash
# wrap-metrics.sh -- byte deltas and the clean/dirty verdict for a wrap, COMPUTED.
#
# Run AFTER `git add` and BEFORE the commit:
#     bash wrap-metrics.sh HANDOFF.md roadmap.md
#
# WHY THIS IS A SCRIPT AND NOT ANOTHER PARAGRAPH. update-context already tells the wrap to
# re-derive self-referential metrics after the last write (G#455, shipped) and to report the
# tree state from git. A measured wrap did both wrong anyway:
#   * it reported HANDOFF.md "-1,100 B" where the committed blobs moved -378 B, and the docket
#     "-6,152 B" where the bytes moved -6,269 -- that second figure is the CHARACTER delta, so
#     the wrap had mixed len(str) and len(bytes) across two scratch scripts;
#   * it opened its final message with "Both repos verified clean" while its OWN table two
#     lines below read "3 paths -- not mine".
# Neither is a discipline failure a further reminder fixes: the numbers came from ad-hoc
# scratch commands, and the headline was free prose written beside a correct table. This
# emits both as DATA the wrap quotes verbatim.
#
# ANCHOR = THE STAGED BLOB, not "the final committed blob". A claim that goes INTO the commit
# message cannot be computed from the commit that contains it; taken literally that demands an
# amend loop, and in practice it silently degrades to a working-tree measurement -- the exact
# defect. `git cat-file -s :<path>` reads the INDEX blob, which is byte-identical to what the
# commit will contain, and is readable before the commit exists.
#
# `git cat-file -s`, NEVER `git show <ref>:<p> | wc -c`. On a path absent from HEAD (a
# project's FIRST wrap) the pipe form prints 0 while the pipe swallows rc 128 (G#202/G#506),
# so a brand-new file reports a base of 0 and the largest possible phantom saving, silently.
# cat-file fails LOUD at rc 128 and this script prints NEW instead.
#
# That hazard is defended TWICE here, and the second layer was found by the mutation run
# rather than designed in: `set -o pipefail` at the top ALSO propagates rc 128 out of the
# pipe. So swapping in the pipe form alone is behaviourally inert in this file and its
# mutation SURVIVES -- correctly, because the behaviour is still protected. The kill needs
# both layers removed at once (pipe form + no pipefail), which is exactly the shape of the
# ad-hoc scratch command that produced the measured incident; that mutant prints
# `base 0B - staged 10B - delta 10B` for a file with no base at all. Do not "simplify" either
# layer on the grounds that the other one covers it.
#
# SCOPE (G#478): the exact figures here are for the REPORT and the COMMIT MESSAGE, which sit
# outside the measured set and are therefore a genuine fixed point. A number written INTO an
# artifact this wrap edits still needs G#478's range-plus-deriving-command form -- re-measuring
# cannot repair a metric whose own correction is a write to the file it measures.
#
# Exit 0 = metrics printed. Exit 2 = a path is unstaged or was edited after `git add`, so no
# delta can be honestly reported. The VERDICT never exits non-zero merely because foreign
# paths exist: a gate whose cheapest silencing path is `git add -A` would re-create the very
# index sweep G#95 exists to prevent (G#385), so the classification is DATA, not a block.
set -uo pipefail

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "wrap-metrics: not a git repo -- no metrics, no verdict"
  exit 2
fi

RC=0
echo "== WRAP METRICS (base = HEAD blob, target = STAGED blob) =="
if [ "$#" -eq 0 ]; then
  echo "  (no paths given -- pass the paths this wrap is committing)"
else
  for p in "$@"; do
    base=$(git cat-file -s "HEAD:$p" 2>/dev/null); base_rc=$?
    staged=$(git cat-file -s ":$p" 2>/dev/null); staged_rc=$?
    if [ "$staged_rc" -ne 0 ]; then
      echo "  $p: NOT STAGED -- refusing to report a delta (run git add first)"
      RC=2
      continue
    fi
    if [ -n "$(git diff --name-only -- "$p" 2>/dev/null)" ]; then
      echo "  $p: UNSTAGED EDIT AFTER add -- the staged blob is not your final bytes; re-run git add"
      RC=2
      continue
    fi
    if [ "$base_rc" -ne 0 ]; then
      echo "  $p: NEW (no base at HEAD) - staged ${staged}B - no delta - derive: git cat-file -s :$p"
    else
      echo "  $p: base ${base}B - staged ${staged}B - delta $((staged - base))B - derive: git cat-file -s HEAD:$p / :$p"
    fi
  done
fi

echo
echo "== WRAP VERDICT (same snapshot as the table above -- quote this line verbatim) =="
# This runs BEFORE the commit, so the staged paths are not residue -- they are the commit.
# Porcelain XY: X is the index column, Y the worktree column. A line whose X is a status
# letter is STAGED; a line starting with a space (worktree-only change) or `?` (untracked)
# is what will still be there afterwards. Counting all porcelain lines would call every wrap
# dirty and make the verdict useless, which is how a computed check gets ignored.
STAGED=$(git status --porcelain | grep -c '^[MADRCU]' || true)
RESIDUE=$(git status --porcelain | grep -c '^[ ?]' || true)
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  AHEAD="ahead $(git rev-list --count '@{u}..HEAD') of $(git rev-parse --abbrev-ref '@{u}')"
else
  AHEAD="no upstream configured"
fi
# The literal token `clean` is emitted ONLY at zero residue. That is the whole point: the
# measured wrap's headline said "clean" over three real paths, so the word must be computed.
if [ "$RESIDUE" -eq 0 ]; then
  echo "  READY - ${STAGED} path(s) staged, tree clean after this commit - $AHEAD"
else
  echo "  READY - ${STAGED} path(s) staged, ${RESIDUE} path(s) remain and each must be classified pre-existing/leave-untracked - $AHEAD"
  git status --porcelain | grep '^[ ?]' | sed 's/^/    /'
fi
exit $RC
