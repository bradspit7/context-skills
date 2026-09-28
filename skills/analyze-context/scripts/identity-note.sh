#!/usr/bin/env bash
# identity-note.sh -- flag a THROWAWAY git identity before more commits carry it.
# Shared by analyze-context's currency gate (session start) and update-context's evidence script
# (the wrap), so neither depends on someone remembering to look. Read-only (git config and git log
# reads). Run from a project root; works from a linked worktree. Always exits 0.
#
# Why it exists: a proof script ran `git config user.name tmp-proof` and `git config user.email
# tmp@proof.invalid` inside a throwaway LINKED worktree. A linked worktree shares the main repo's
# config, so that rewrote the main repo's identity: every later commit was authored tmp-proof
# (twelve of them, across a session wrap), and neither the wrap nor the next session start noticed.
# A guard hook stops such a command; this is the detective half, for the one that got through.
#
# Prints NOTHING unless the effective identity (git config user.name / user.email: what the next
# commit will use) looks throwaway:
#   - the email ends in .invalid, or its domain is example.com, example.org, example.net or localhost;
#   - or the name, or the email's local part, holds a whole token tmp, temp, test, proof, dummy or
#     fake (tokens split on non-alphanumerics, any case: tmp-proof matches, contest does not).
# Then one section with one line: the file that sets it (git config --show-origin) and how many
# unpushed commits already carry it. It is a NOTE, never a FINDING: currency-check.sh counts
# '^FINDING' lines to stop the briefing, and this must not stop anything. No repo, or no identity
# configured: nothing (history is not the signal -- the config is what authors the next commit).
set -u

git rev-parse --git-dir >/dev/null 2>&1 || exit 0

cfg() { git config --get "$1" 2>/dev/null | tr -d '\r'; }
NAME=$(cfg user.name)
EMAIL=$(cfg user.email)
[ -n "$NAME$EMAIL" ] || exit 0

# A whole token from the throwaway list, in any case.
has_token() {
  local t
  for t in $(printf '%s' "$1" | LC_ALL=C tr -c 'A-Za-z0-9' ' ' | LC_ALL=C tr 'A-Z' 'a-z'); do
    case "$t" in tmp|temp|test|proof|dummy|fake) return 0 ;; esac
  done
  return 1
}

EMAIL_BAD=""
if [ -n "$EMAIL" ]; then
  EL=$(printf '%s' "$EMAIL" | LC_ALL=C tr 'A-Z' 'a-z')
  case "$EL" in
    *@*) LOCAL=${EL%@*}; DOMAIN=${EL##*@} ;;
    *) LOCAL=$EL; DOMAIN="" ;;
  esac
  case "$EL" in *.invalid) EMAIL_BAD=1 ;; esac
  case "$DOMAIN" in example.com|example.org|example.net|localhost) EMAIL_BAD=1 ;; esac
  has_token "$LOCAL" && EMAIL_BAD=1
fi
NAME_BAD=""
if [ -n "$NAME" ] && has_token "$NAME"; then NAME_BAD=1; fi
[ -n "$EMAIL_BAD$NAME_BAD" ] || exit 0

# The throwaway PART is the key: where it is set is what to fix, and the commits carrying it are the
# ones to re-author. That is the email whenever the email is throwaway; otherwise the name, because
# counting a REAL email would count every legitimate commit its owner made.
if [ -n "$EMAIL_BAD" ]; then
  KEY=user.email; VAL=$EMAIL; FIELD=%ae
else
  KEY=user.name; VAL=$NAME; FIELD=%an
fi

# -z: the origin comes NUL-terminated and never C-quoted. Git prints the repo config RELATIVE to the
# worktree top (.git/config) from the main checkout, absolute from a linked worktree, so a relative
# path is anchored on the top: the NOTE names a file the reader can open from anywhere.
ORIGIN=$(git config --show-origin -z --get "$KEY" 2>/dev/null | tr '\0' '\n' | head -n 1 | tr -d '\r')
case "$ORIGIN" in
  file:*)
    ORIGIN=${ORIGIN#file:}
    case "$ORIGIN" in
      /*|[A-Za-z]:[\\/]*) ;;
      *) TOP=$(git rev-parse --show-toplevel 2>/dev/null) && [ -n "$TOP" ] && ORIGIN="$TOP/$ORIGIN" ;;
    esac
    ;;
  "") ORIGIN="an unknown config source" ;;
  *) ORIGIN=${ORIGIN%:} ;;
esac

# %ae / %an are the RAW author fields: the .mailmap-applied forms (%aE / %aN) could rewrite exactly
# the commits being counted.
if git rev-parse -q --verify '@{u}' >/dev/null 2>&1; then
  N=$(git log --format="$FIELD" '@{u}..HEAD' 2>/dev/null | tr -d '\r' | grep -cxF -- "$VAL")
  CARRY="${N:-0} unpushed commit(s) carry it"
else
  N=$(git log -n 20 --format="$FIELD" HEAD 2>/dev/null | tr -d '\r' | grep -cxF -- "$VAL")
  CARRY="no upstream -- ${N:-0} of the last 20 commits carry it"
fi

echo
echo "== IDENTITY =="
echo "NOTE throwaway git identity: ${NAME:-(unset)} <${EMAIL:-(unset)}> set in $ORIGIN -- $CARRY; fix the config (unset it or set the real identity) before committing, and re-author the unpushed ones if needed"
exit 0
