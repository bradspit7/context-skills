---
description: "Search this machine's memory/notes markdown via SQLite FTS5. Returns file paths and snippets — pointers to source, not synthesized facts."
argument-hint: "<query — terms, \"exact phrase\", OR/NOT supported>"
---

# Memory Search (PC)

Locate where information lives across the corpus roots in `~/.claude/memory-sync/fts-roots.txt` (workspace repo memory + vault if present). Local-only, stdlib SQLite FTS5.

## Usage

```bash
python ~/.claude/memory-sync/build-search-index.py --query "<args>" --limit 10
```

`Index not found` → rebuild first: `python ~/.claude/memory-sync/build-search-index.py --rebuild`
FTS5 syntax error → retry the query wrapped in double quotes (phrase match).
`--roots` prints the resolved corpus roots (each marked exists/MISSING).

## Critical rules

1. **Results are pointers, not answers.** Read the actual file before reporting any fact.
2. **Do not synthesize.** Locate candidates, Read them, answer from current contents.
3. **Index can be stale.** Rebuild on demand; if a snippet conflicts with the source file, trust the file.

## Report format

```
## Memory Search — "<query>"

1. <path>
   <snippet>

(N results)

Next: Read the file(s) above before quoting any fact.
```
