#!/bin/bash
# Semantic-index rebuild wrapper — PC-portable variant (claude-infra/pc-bootstrap).
# Re-embeds the corpus into semantic.db so /semantic-search and /recall stay fresh.
# Pure local; needs Ollama running with nomic-embed-text pulled.
#
# Scheduling is the machine's choice: the Mac fires this from launchd at 04:00;
# on Windows use Task Scheduler (run via git-bash: `bash <path>/run-semantic-rebuild.sh`),
# or just run it manually / at session wrap. A stale index is harmless — this
# wrapper NEVER hard-fails; it logs and exits 0 so schedulers don't alarm.
#
# Venv python resolution (sqlite-vec lives in a venv, not system python):
#   1. $SEMANTIC_PYTHON env var, if set
#   2. $SYNC_DIR/.venv-semantic/Scripts/python.exe   (Windows venv layout)
#   3. $SYNC_DIR/.venv-semantic/bin/python           (macOS/Linux venv layout)
#
# Inspect: tail -n 80 ~/.claude/memory-sync/semantic-rebuild.log

set -euo pipefail

SYNC_DIR="$HOME/.claude/memory-sync"
SCRIPT="$SYNC_DIR/semantic-index.py"
LOG="$SYNC_DIR/semantic-rebuild.log"
LOCK="$SYNC_DIR/.semantic-rebuild.lock"
OLLAMA_URL="http://localhost:11434/api/tags"

PY="${SEMANTIC_PYTHON:-}"
[ -z "$PY" ] && [ -x "$SYNC_DIR/.venv-semantic/Scripts/python.exe" ] && PY="$SYNC_DIR/.venv-semantic/Scripts/python.exe"
[ -z "$PY" ] && [ -x "$SYNC_DIR/.venv-semantic/bin/python" ] && PY="$SYNC_DIR/.venv-semantic/bin/python"

# Scheduled jobs must not inherit a Claude Code session env.
unset CLAUDECODE CLAUDE_CODE_SESSION_ACCESS_TOKEN CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_MAX_OUTPUT_TOKENS 2>/dev/null || true

mkdir -p "$SYNC_DIR"

# Keep the log from growing forever (trim to last 400 lines past ~200KB).
if [[ -f "$LOG" && $(wc -c < "$LOG") -gt 200000 ]]; then
  tail -n 400 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log() { echo "$@" >> "$LOG"; }

log ""
log "================================================================"
log "=== Semantic rebuild starting $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
log "================================================================"

# Prevent overlapping runs (mkdir is atomic).
if ! mkdir "$LOCK" 2>/dev/null; then
  log "Another rebuild holds the lock ($LOCK); skipping this run."
  exit 0
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

# Soft checks: a stale index is harmless, so never hard-fail the schedule.
if [[ -z "$PY" || ! -x "$PY" ]]; then
  log "FATAL: no venv python found (SEMANTIC_PYTHON unset, no .venv-semantic/Scripts/python.exe or bin/python under $SYNC_DIR) — semantic search not set up?"
  exit 0
fi
if ! curl -s -o /dev/null --max-time 10 "$OLLAMA_URL"; then
  log "Ollama not reachable at $OLLAMA_URL — skipping rebuild, index left as-is."
  log "(Keep Ollama running / set it to launch at login so scheduled refreshes run.)"
  exit 0
fi

# Rebuild quietly (final summary only; no per-batch spam).
if "$PY" "$SCRIPT" --rebuild --quiet >> "$LOG" 2>&1; then
  log "=== Semantic rebuild done $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
else
  rc=$?
  log "=== Semantic rebuild FAILED (rc=$rc) at $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
fi
exit 0
