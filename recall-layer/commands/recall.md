---
description: "Unified memory recall — FTS5 keyword search, plus the semantic layer when semantic.db exists (interleaved, deduped by path, hits labeled [fts]/[sem]/[both])."
argument-hint: "<query>"
---

# Recall (PC)

Single entry point for memory lookup. FTS5 keyword search always; semantic search joins automatically once `~/.claude/memory-sync/semantic.db` exists (shipped 2026-06-10 — see `/semantic-search` for its mechanics and venv python).

## Usage

Run the FTS search per `/memory-search` mechanics:

```bash
python ~/.claude/memory-sync/build-search-index.py --query "<args>" --limit 10
```

Label every hit `[fts]`. If a semantic index is installed later (`semantic.db` exists in `~/.claude/memory-sync/`), also run it, interleave deduped by path, and label `[sem]`/`[both]` — same contract as the Mac version.

Results are pointers to source, not facts — Read before quoting. If the query is concept-shaped and FTS returns nothing, say that keyword search came up empty and fall back to reading MEMORY.md's index directly.
