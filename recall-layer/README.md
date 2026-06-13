# Local memory recall layer — keyword (FTS) + semantic (Ollama)

A two-engine, fully-local recall layer over your Claude memory + notes. Nothing leaves the machine.

- **Keyword / FTS** (`build-search-index.py` → `search.db`) — SQLite FTS5, **pure stdlib, zero dependencies**. Matches the *words you type*.
- **Semantic / vector** (`semantic-index.py` → `semantic.db`) — local **Ollama** embeddings (`nomic-embed-text`, 768-dim) stored in **`sqlite-vec`**. Matches the *idea*, even with no shared words.

`/recall` runs both and interleaves; the two are otherwise independent. Stand up FTS first (no model, no pip) and use it standalone — semantic auto-joins later with zero rewiring once `semantic.db` exists.

> Ported from a macOS estate to be Windows/git-bash-portable: no hardcoded paths, corpus roots from config, venv autodetect. Provided as a give-back — adopt whole, in part (FTS-only is a legitimate stopping point), or as reference.

---

## The two engines & how they stay in sync

| | Keyword (FTS) | Semantic (vector) |
|---|---|---|
| Indexer | `tools/build-search-index.py` | `tools/semantic-index.py` |
| DB | `~/.claude/memory-sync/search.db` | `~/.claude/memory-sync/semantic.db` |
| Deps | **none** (stdlib `sqlite3` FTS5) | Ollama + a venv with `sqlite-vec==0.1.9` |
| Cost / cadence | seconds → rebuild often (on each memory write / wrap) | ~tens of seconds → rebuild on a daily schedule |
| Finds | exact words, `bm25` ranked | meaning / concept, cosine-nearest |

**They stay in sync by indexing the SAME corpus roots.** Both read roots in this priority:

1. `CLAUDE_FTS_ROOTS` env var — `os.pathsep`-separated dirs (Windows: `;`), e.g. `C:/Users/you/notes;C:/Users/you/vault`
2. `fts-roots.txt` next to the DBs (`~/.claude/memory-sync/fts-roots.txt`) — one dir per line, `#` comments allowed
3. fallback: every `~/.claude/projects/*/memory` directory

Point both indexers at the identical roots and the two DBs cover the same corpus by construction. Both skip `.git/.obsidian/node_modules/.venv/__pycache__/vendor/worktrees` and `.bak/.tmp/.swp` files. A note is keyword-findable right after an FTS rebuild; semantic-findable after the next vector rebuild — so if recency matters, lean on FTS (its rebuilds are cheap).

---

## Install — keyword half (do this first; zero deps)

```bash
# 1. install the indexer + choose your corpus roots
mkdir -p ~/.claude/memory-sync
cp tools/build-search-index.py ~/.claude/memory-sync/   # the /recall + /memory-search docs invoke it from here
printf '%s\n' "$HOME/.claude/projects" > ~/.claude/memory-sync/fts-roots.txt   # edit to your real roots

# 2. build the index (pure stdlib python — use a REAL python, NOT the MS Store python3 stub)
python ~/.claude/memory-sync/build-search-index.py --rebuild
python ~/.claude/memory-sync/build-search-index.py --roots          # sanity: prints resolved roots + exists/MISSING
python ~/.claude/memory-sync/build-search-index.py --query "loss limit" --limit 5
```

Wire `commands/memory-search.md` and `commands/recall.md` into `~/.claude/commands/`. Re-run `--rebuild` whenever your notes change (tie it to your memory-write/wrap flow, or a scheduled task). That's the entire keyword layer.

## Install — semantic half (adds Ollama + one pip dep)

```bash
# 1. Ollama + the embedding model (Windows build; default port 11434)
ollama pull nomic-embed-text
ollama list                         # expect: nomic-embed-text:latest (~274 MB)

# 2. venv whose ONLY dependency is the vector store
python -m venv ~/.claude/memory-sync/.venv-semantic
~/.claude/memory-sync/.venv-semantic/Scripts/python.exe -m pip install sqlite-vec==0.1.9
# pip freeze of that venv should be exactly one line: sqlite-vec==0.1.9

# 3. install the semantic scripts where the schedule + smoke-test expect them
cp tools/semantic-index.py tools/run-semantic-rebuild.sh ~/.claude/memory-sync/

# 4. build the vector index (Ollama must be running)
SEMANTIC_PYTHON=~/.claude/memory-sync/.venv-semantic/Scripts/python.exe \
  bash ~/.claude/memory-sync/run-semantic-rebuild.sh
```

Wire `commands/semantic-search.md` into `~/.claude/commands/`. `/recall` upgrades itself to interleave `[fts]`/`[sem]`/`[both]` automatically once `semantic.db` exists.

### Schedule the semantic rebuild (Windows Task Scheduler ≈ launchd)

```bat
schtasks /create /tn "semantic-index" /sc daily /st 04:00 ^
  /tr "%USERPROFILE%\.claude\memory-sync\run-semantic-rebuild.sh"
```

Run the wrapper through git-bash. **Enable "Run task as soon as possible after a scheduled start is missed"** in the task's Settings — launchd catches a missed run on wake; Task Scheduler skips by default. The wrapper takes a `mkdir` lock, probes Ollama, and **soft-skips (exit 0) if Ollama is down**, so a missed embed never breaks the schedule.

## Optional — always-on auto-recall (`hooks/semantic-recall.sh`)

A `UserPromptSubmit` hook that injects the top semantic hits as context on every substantive prompt (so relevant past notes surface without invoking `/semantic-search`). Skips prompts under 25 chars and slash-commands, min-similarity 58, top-3, short HTTP timeout, **always exits 0 / fails silent**. Needs `jq` + the semantic venv. Tunables via `RECALL_MIN_SIMILARITY` / `RECALL_MAX_RESULTS` / `RECALL_HTTP_TIMEOUT`. Wire it:

```json
"hooks": { "UserPromptSubmit": [ { "hooks": [ {
  "type": "command",
  "command": "bash %USERPROFILE%/.claude/hooks/semantic-recall.sh"
} ] } ] }
```

The on-demand `/recall` works fully without the hook — the hook is just the ambient version.

---

## Known Windows gaps (verify these — they couldn't be tested from macOS)

1. **`sqlite-vec` Windows wheel.** On macOS the wheel ships `vec0.dylib`; the Windows wheel *should* ship `vec0.dll` (the loader uses a bare stem and SQLite appends the platform suffix). After `pip install`, confirm `...\.venv-semantic\Lib\site-packages\sqlite_vec\vec0.dll` exists. If missing, the 0.1.9 wheel didn't bundle the Windows binary — grab a newer `sqlite-vec` or place `vec0.dll` manually.
2. **`sqlite3.enable_load_extension`** must be available in your Python (some python.org Windows builds compile it out). 10-second check:
   ```
   python -c "import sqlite3; sqlite3.connect(':memory:').enable_load_extension(True)"
   ```
   If it raises `AttributeError`/"not authorized", use a Python whose `sqlite3` supports loadable extensions (conda is known-good).
3. **Microsoft Store `python3` stub.** Build the venv with a real python.org/conda interpreter, not the Store stub (it silently no-ops). Invoke the venv's `Scripts\python.exe` by full path.
4. **`jq` + `curl` on the git-bash PATH** — the rebuild wrapper and the auto-recall hook need them. Without them, skip the hook and use on-demand commands.
5. **Ollama liveness is a hard runtime dep** for the semantic half only. Down → semantic returns nothing and `/recall` degrades to FTS-only; the wrapper soft-skips.

## Smoke test (semantic half)

```bash
# extension loads (gap #2)
~/.claude/memory-sync/.venv-semantic/Scripts/python.exe -c \
  "import sqlite3,sqlite_vec; c=sqlite3.connect(':memory:'); c.enable_load_extension(True); sqlite_vec.load(c); print(c.execute('select vec_version()').fetchone())"
# expect: ('v0.1.9',)

# query round-trip (after a rebuild)
~/.claude/memory-sync/.venv-semantic/Scripts/python.exe \
  ~/.claude/memory-sync/semantic-index.py --query "test recall" --limit 5
# expect: [NN% match] <path> lines
```

If the version tuple prints, you're ~90% home — the rest is pointing the command docs at the venv python.
