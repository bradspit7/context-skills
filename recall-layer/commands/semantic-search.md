---
description: "Semantic (meaning-based) search over this machine's memory/notes via local embeddings + sqlite-vec. Finds conceptually-related notes even when they share no keywords. Companion to /memory-search (keyword). Returns file paths + snippets — pointers, not answers."
argument-hint: "<natural-language query>"
---

# Semantic Search (PC)

Meaning-based recall over the same corpus as `/memory-search` (roots in `~/.claude/memory-sync/fts-roots.txt`). Use when the query is concept-shaped and keyword search misses — different words, same idea.

## Usage

Must run under the sqlite-vec venv python (`SEMANTIC_PYTHON` env, else `~/.claude/memory-sync/.venv-semantic/Scripts/python.exe` on Windows, else `.venv-semantic/bin/python`):

```bash
SYNC="$HOME/.claude/memory-sync"
PY="${SEMANTIC_PYTHON:-}"
[ -z "$PY" ] && [ -x "$SYNC/.venv-semantic/Scripts/python.exe" ] && PY="$SYNC/.venv-semantic/Scripts/python.exe"
[ -z "$PY" ] && [ -x "$SYNC/.venv-semantic/bin/python" ] && PY="$SYNC/.venv-semantic/bin/python"
"$PY" "$SYNC/semantic-index.py" --query "<args>" --limit 10
```

`Semantic index not found` → rebuild first (needs Ollama running): `bash ~/.claude/memory-sync/run-semantic-rebuild.sh` (or `--rebuild` directly). `--roots` prints the resolved corpus.

## Critical rules

1. **Results are pointers, not answers.** The similarity % ranks candidates; Read the file before quoting any fact.
2. **Index freshness is rebuild-bound.** Notes written since the last rebuild are invisible here — if recency matters, also run `/memory-search` (FTS rebuilds are cheap and frequent).
3. **Ollama down → this command degrades, /memory-search doesn't.** Fall back to keyword search rather than reporting "nothing found".

## Report format

```
## Semantic Search — "<query>"

1. [NN% match] <path>
   <snippet>

(N results)

Next: Read the file(s) above before quoting any fact.
```
