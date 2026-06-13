#!/usr/bin/env bash
# Hook: UserPromptSubmit — semantic auto-recall (PC-portable variant)
#
# Purpose: on each substantive prompt, search memory + notes by MEANING and inject the
#          most relevant ones as context — so past rules/decisions surface at the moment
#          they're relevant, without anyone invoking /semantic-search. Companion to the
#          keyword index; uses the local Ollama + sqlite-vec stack via semantic-index.py.
#
# SAFETY (do not weaken):
#   - ALWAYS exits 0. Exit 2 would BLOCK and erase the prompt — never acceptable here.
#   - Fails silent on any error: no venv, no jq, Ollama down, timeout → no output.
#   - Short HTTP timeout so a cold embedding model can't stall a prompt.
#   - Length + slash-command gates keep it quiet on short acks and command invocations.
#
# Portability vs the Mac original: no hardcoded paths. SYNC_DIR defaults to
# ~/.claude/memory-sync (override CLAUDE_SYNC_DIR). The venv python is autodetected the
# same way as run-semantic-rebuild.sh: $SEMANTIC_PYTHON → .venv-semantic/Scripts/python.exe
# (Windows) → .venv-semantic/bin/python (POSIX). Runs under git-bash on Windows; needs jq.
#
# Wire it in settings.json under UserPromptSubmit, e.g.:
#   "hooks": { "UserPromptSubmit": [ { "hooks": [ {
#       "type": "command",
#       "command": "bash %USERPROFILE%/.claude/hooks/semantic-recall.sh"
#   } ] } ] }
# Output: UserPromptSubmit additionalContext JSON → added to the model's context.

# ---- tunables ----
MIN_SIMILARITY="${RECALL_MIN_SIMILARITY:-58}"   # on-topic ~62-63, off-topic ~55-59; 58 catches the relevant band
MAX_RESULTS="${RECALL_MAX_RESULTS:-3}"
MIN_PROMPT_CHARS=25     # skip short acks ("ok thanks", "yes do it")
MAX_PROMPT_CHARS=2000   # cap arg size on huge pastes
HTTP_TIMEOUT="${RECALL_HTTP_TIMEOUT:-5}"   # seconds; fail-open if the model is cold/hung

SYNC_DIR="${CLAUDE_SYNC_DIR:-$HOME/.claude/memory-sync}"
SCRIPT="$SYNC_DIR/semantic-index.py"

# ---- venv python autodetect (mirrors run-semantic-rebuild.sh) ----
PY="${SEMANTIC_PYTHON:-}"
[ -z "$PY" ] && [ -x "$SYNC_DIR/.venv-semantic/Scripts/python.exe" ] && PY="$SYNC_DIR/.venv-semantic/Scripts/python.exe"
[ -z "$PY" ] && [ -x "$SYNC_DIR/.venv-semantic/bin/python" ] && PY="$SYNC_DIR/.venv-semantic/bin/python"
[ -z "$PY" ] && exit 0          # semantic layer not set up → silent no-op
[ -f "$SCRIPT" ] || exit 0

# ---- read input ----
INPUT=$(cat)
command -v jq >/dev/null 2>&1 || exit 0
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

# ---- gates (every failure path exits 0 with no output) ----
[ -z "$PROMPT" ] && exit 0
[ "${#PROMPT}" -lt "$MIN_PROMPT_CHARS" ] && exit 0
case "$PROMPT" in /*) exit 0 ;; esac           # skip slash-command invocations
PROMPT="${PROMPT:0:$MAX_PROMPT_CHARS}"

# ---- semantic search (JSON, short timeout, fail-soft) ----
RESULTS=$("$PY" "$SCRIPT" --query="$PROMPT" --limit "$MAX_RESULTS" --json --http-timeout "$HTTP_TIMEOUT" 2>/dev/null)
[ -z "$RESULTS" ] && exit 0

# ---- keep only hits at/above the relevance threshold ----
LINES=$(printf '%s' "$RESULTS" | jq -r --argjson t "$MIN_SIMILARITY" \
  '.[] | select(.similarity >= $t) | "- (\(.similarity)%) \(.path)\n    \(.snippet)"' 2>/dev/null)
[ -z "$LINES" ] && exit 0

MSG="Semantic recall (auto, by meaning) — possibly-relevant notes from your memory/notes, surfaced because they relate to this prompt. POINTERS, not verified facts: read the file before relying on or quoting anything, and note they can be stale or match the wrong sense of a word.
$LINES"

# ---- emit as additionalContext (jq handles all escaping); always exit 0 ----
jq -n --arg ctx "$MSG" \
  '{hookSpecificOutput:{hookEventName:"UserPromptSubmit",additionalContext:$ctx}}' 2>/dev/null
exit 0
