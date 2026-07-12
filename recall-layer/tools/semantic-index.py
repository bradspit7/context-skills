#!/usr/bin/env python3
"""Build or query a local SEMANTIC (vector) search index over markdown memory/notes.

PC-portable variant (claude-infra/pc-bootstrap). Companion to build-search-index.py
in this folder: that one is FTS5 keyword search ("matches the words you typed"),
this one is meaning-based recall ("matches the idea, even if the words differ"),
via local embeddings + sqlite-vec.

DERIVED data: always rebuildable from source files, local-only, no cloud. Results
are pointers to existing files, not a substitute for reading those files.

Corpus roots — IDENTICAL resolution to build-search-index.py, so keyword and
semantic search always cover the same files:
  1. CLAUDE_FTS_ROOTS env var (os.pathsep-separated)
  2. fts-roots.txt next to the DB (one directory per line, # comments)
  3. fallback: every ~/.claude/projects/*/memory directory

DB: ~/.claude/memory-sync/semantic.db

Requires:
  - A venv with sqlite-vec installed. Run under that venv's python:
    Windows: ~/.claude/memory-sync/.venv-semantic/Scripts/python.exe
    macOS/Linux: ~/.claude/memory-sync/.venv-semantic/bin/python
  - Ollama running locally with `nomic-embed-text` pulled (ollama list)

The only network call is to localhost Ollama for embeddings.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path

import sqlite_vec

HOME = Path.home()
SYNC_DIR = HOME / ".claude" / "memory-sync"
DB_PATH = SYNC_DIR / "semantic.db"
ROOTS_FILE = SYNC_DIR / "fts-roots.txt"

SKIP_SUFFIXES = (".bak", ".tmp", ".swp", ".swo", ".orig")
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".venv", "__pycache__",
             "vendor", "sound_library", ".codex", "worktrees"}

# Embedding model config. nomic-embed-text is 768-dim and expects task prefixes:
# "search_document: " when indexing, "search_query: " when querying. The prefixes
# materially improve retrieval quality, so we always apply them.
OLLAMA_EMBED_URL = "http://localhost:11434/api/embed"
MODEL = "nomic-embed-text"
DIM = 768
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# Chunking: pack markdown into ~1200-char chunks on paragraph boundaries, each
# prefixed with its nearest heading so an isolated chunk keeps its context.
# CHUNK_HARD_MAX force-flushes even without a blank line, so a long unbroken
# section (e.g. a giant changelog or table) can never produce a chunk that
# exceeds the embedding model's context window.
CHUNK_TARGET = 1200
CHUNK_HARD_MAX = 1800
EMBED_CHAR_CAP = 8000  # final safety truncation before embedding
BATCH = 64

# Similarity floor (0-100%). SINGLE SOURCE for both the interactive query path and the
# semantic-recall.sh hook (which reads it from here via --json's `below_floor` instead of
# hardcoding its own copy). On-topic hits land ~62-63, off-topic ~55-59, so 58 catches the
# relevant band. Rows below the floor are ANNOTATED, never silently dropped, so a near-miss
# stays visible. Override per-invocation with --min-similarity.
DEFAULT_MIN_SIMILARITY = 58


def corpus_roots() -> list[Path]:
    env = os.environ.get("CLAUDE_FTS_ROOTS")
    if env:
        return [Path(os.path.expanduser(p)) for p in env.split(os.pathsep) if p.strip()]
    if ROOTS_FILE.exists():
        out = []
        for line in ROOTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(Path(os.path.expandvars(os.path.expanduser(line))))
        if out:
            return out
    proj = HOME / ".claude" / "projects"
    return sorted(proj.glob("*/memory")) if proj.exists() else []


def iter_source_files() -> list[Path]:
    files: set[Path] = set()
    for root in corpus_roots():
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            if f.suffix in SKIP_SUFFIXES or not f.is_file():
                continue
            if any(part in SKIP_DIRS for part in f.parts):
                continue
            files.add(f)
    return sorted(files)


def chunk_markdown(text: str) -> list[str]:
    """Split into ~CHUNK_TARGET-char chunks on blank-line boundaries, prepending
    the most recent markdown heading to each chunk for standalone context.

    A hard cap (CHUNK_HARD_MAX) force-flushes even mid-section, and pathologically
    long single lines are split, so no chunk can exceed the model's context."""
    chunks: list[str] = []
    current_header = ""
    buf: list[str] = []
    buf_len = 0

    def flush() -> None:
        nonlocal buf, buf_len
        body = "\n".join(buf).strip()
        if body:
            prefix = (current_header + "\n") if current_header else ""
            chunks.append((prefix + body).strip())
        buf = []
        buf_len = 0

    def add_line(line: str) -> None:
        nonlocal buf_len
        buf.append(line)
        buf_len += len(line) + 1
        if buf_len >= CHUNK_HARD_MAX:
            flush()

    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if stripped.startswith("#") and stripped.lstrip("#").startswith(" "):
            # Heading: flush the previous section, adopt this heading as context.
            flush()
            current_header = stripped
            continue
        if line.strip() == "":
            # Paragraph boundary: flush if we're over the soft target.
            if buf_len >= CHUNK_TARGET:
                flush()
            else:
                buf.append("")
                buf_len += 1
            continue
        # Hard-split a single line longer than the cap (giant table row, blob, etc.)
        while len(line) > CHUNK_HARD_MAX:
            add_line(line[:CHUNK_HARD_MAX])  # add_line will force a flush
            line = line[CHUNK_HARD_MAX:]
        add_line(line)
    flush()
    return [c for c in chunks if c.strip()]


def _embed_call(inputs: list[str], timeout: float = 180) -> list[list[float]]:
    """One HTTP call to Ollama. Raises HTTPError on a bad request (e.g. a chunk
    the model rejects) and URLError if Ollama is unreachable."""
    payload = {"model": MODEL, "input": inputs}
    req = urllib.request.Request(
        OLLAMA_EMBED_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    embs = data.get("embeddings")
    if not embs:
        raise RuntimeError(f"No embeddings in response: {str(data)[:200]}")
    return embs


def embed_batch(texts: list[str], prefix: str, timeout: float = 180) -> list[list[float] | None]:
    """Embed a batch, with prefixes and a final truncation safety. If the whole
    batch is rejected (HTTPError), retry item-by-item so a single bad chunk can't
    abort the run — failed items come back as None and the caller skips them.
    A genuine connection failure (Ollama down) is still a hard, helpful error."""
    inputs = [prefix + t[:EMBED_CHAR_CAP] for t in texts]
    try:
        return _embed_call(inputs, timeout=timeout)
    except urllib.error.HTTPError:
        out: list[list[float] | None] = []
        for s in inputs:
            try:
                out.append(_embed_call([s], timeout=timeout)[0])
            except Exception as e:  # noqa: BLE001 — skip the one bad chunk, keep going
                print(f"  WARN: skipped one chunk ({e})", flush=True)
                out.append(None)
        return out
    except urllib.error.URLError as e:
        raise SystemExit(
            f"Could not reach Ollama at {OLLAMA_EMBED_URL}: {e}\n"
            f"Is Ollama running, and is '{MODEL}' pulled? (ollama list)"
        )


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def rebuild(db_path: Path, quiet: bool = False) -> tuple[int, int, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS chunks")
        conn.execute("DROP TABLE IF EXISTS vec_chunks")
        conn.execute(
            "CREATE TABLE chunks ("
            "id INTEGER PRIMARY KEY, path TEXT, chunk_index INTEGER, body TEXT)"
        )
        conn.execute(
            f"CREATE VIRTUAL TABLE vec_chunks USING vec0(embedding float[{DIM}])"
        )

        files = iter_source_files()
        # Build the full chunk list first, then embed in batches.
        metas: list[tuple[str, int, str]] = []  # (path, chunk_index, body)
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, ch in enumerate(chunk_markdown(text)):
                metas.append((str(f), i, ch))

        total = len(metas)
        if not quiet:
            print(f"Embedding {total} chunks from {len(files)} files...", flush=True)

        rowid = 0
        skipped = 0
        for start in range(0, total, BATCH):
            batch = metas[start:start + BATCH]
            embs = embed_batch([m[2] for m in batch], DOC_PREFIX)
            for (path, idx, body), emb in zip(batch, embs):
                if emb is None:  # one chunk the model rejected; skip it
                    skipped += 1
                    continue
                rowid += 1
                conn.execute(
                    "INSERT INTO chunks(id, path, chunk_index, body) VALUES (?,?,?,?)",
                    (rowid, path, idx, body),
                )
                conn.execute(
                    "INSERT INTO vec_chunks(rowid, embedding) VALUES (?, ?)",
                    (rowid, sqlite_vec.serialize_float32(emb)),
                )
            if not quiet:
                done = min(start + BATCH, total)
                print(f"  {done}/{total} chunks embedded", flush=True)
        conn.commit()
        return len(files), rowid, skipped
    finally:
        conn.close()


def _best_per_path(rows: list[tuple[str, float, str]],
                   limit: int) -> list[tuple[str, float, str]]:
    """Collapse to the nearest chunk per path. `rows` must already be ascending by
    distance (nearest first): keep the first (closest) chunk seen for each path and
    cap at `limit` distinct paths."""
    seen: set[str] = set()
    best: list[tuple[str, float, str]] = []
    for path, dist, body in rows:
        if path in seen:
            continue
        seen.add(path)
        best.append((path, dist, body))
        if len(best) >= limit:
            break
    return best


def query(db_path: Path, q: str, limit: int,
          http_timeout: float = 180,
          distinct_paths: bool = False) -> list[tuple[str, float, str]]:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Semantic index not found at {db_path}. Run with --rebuild first."
        )
    conn = connect(db_path)
    try:
        qvec = embed_batch([q], QUERY_PREFIX, timeout=http_timeout)[0]
        # A single long note produces many chunks, so the naive top-`limit` neighbours
        # can be several chunks of ONE file, crowding out other distinct notes. When
        # --distinct-paths is set, over-fetch a wider neighbour window then keep the
        # closest chunk per path; default OFF returns the exact prior rows (back-compat).
        # sqlite-vec needs an explicit `k = ?` for the neighbor count when the vec0
        # table is joined (a bare LIMIT is ambiguous to it).
        k = max(limit * 4, 40) if distinct_paths else limit
        cur = conn.execute(
            "SELECT c.path, v.distance, c.body "
            "FROM vec_chunks v JOIN chunks c ON c.id = v.rowid "
            "WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (sqlite_vec.serialize_float32(qvec), k),
        )
        rows = list(cur.fetchall())
    finally:
        conn.close()
    return _best_per_path(rows, limit) if distinct_paths else rows


def format_results(results: list[tuple[str, float, str]],
                   min_similarity: int | None = None) -> str:
    if not results:
        return "(no matches)"
    out = []
    for path, dist, body in results:
        # Cosine distance in [0,2]; smaller = closer. Show as a rough similarity %.
        sim = max(0.0, 1.0 - dist / 2.0) * 100.0
        # Annotate (never drop) hits below the shared floor, so a near-miss stays visible.
        mark = " [below floor]" if (
            min_similarity is not None and round(sim) < min_similarity) else ""
        one_line = " ".join(body.split())
        snip = one_line[:200] + ("..." if len(one_line) > 200 else "")
        out.append(f"[{sim:4.0f}% match]{mark} {path}\n  {snip}")
    return "\n\n".join(out)


def main() -> int:
    # Windows consoles default to cp1252 — snippets with unicode crash --query
    # without this (same fix as build-search-index.py). No-op on UTF-8 terminals.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and rebuild the semantic index from source files.")
    parser.add_argument("--query", "-q", type=str,
                        help="Natural-language query. Matches by meaning, not keywords.")
    parser.add_argument("--limit", "-n", type=int, default=10,
                        help="Max results (default 10).")
    parser.add_argument("--quiet", action="store_true",
                        help="Suppress per-batch progress (for scheduled runs).")
    parser.add_argument("--json", action="store_true",
                        help="Emit query results as JSON (for hooks/automation).")
    parser.add_argument("--http-timeout", type=float, default=180,
                        help="Timeout (s) for the Ollama embed call.")
    parser.add_argument("--db", type=Path, default=DB_PATH,
                        help=f"Index path (default {DB_PATH}).")
    parser.add_argument("--roots", action="store_true",
                        help="Print the resolved corpus roots and exit.")
    parser.add_argument("--distinct-paths", action="store_true",
                        help="Collapse to the nearest chunk per path (over-fetches "
                             "neighbours first). Default off = exact prior behaviour.")
    parser.add_argument("--min-similarity", type=int, default=DEFAULT_MIN_SIMILARITY,
                        help="Similarity floor (percent) for below-floor annotation "
                             f"(default {DEFAULT_MIN_SIMILARITY}; the single source the "
                             "recall hook reads via --json below_floor).")
    args = parser.parse_args()

    if args.roots:
        for r in corpus_roots():
            print(f"{r}  {'(exists)' if r.exists() else '(MISSING)'}")
        return 0

    if not args.rebuild and not args.query:
        parser.error("Specify --rebuild and/or --query (or --roots).")

    if args.rebuild:
        files, chunks, skipped = rebuild(args.db, quiet=args.quiet)
        msg = f"Indexed {chunks} chunks from {files} files into {args.db}."
        if skipped:
            msg += f" ({skipped} chunks skipped.)"
        print(msg)

    if args.query:
        if args.json:
            # Fail-soft for hooks: emit empty JSON on ANY error, so automation
            # never crashes the caller or blocks a prompt.
            try:
                results = query(args.db, args.query, args.limit,
                                http_timeout=args.http_timeout,
                                distinct_paths=args.distinct_paths)
            except BaseException:  # noqa: BLE001
                print("[]")
                return 0
            print(json.dumps([
                {"path": p,
                 "similarity": (sim := round(max(0.0, 1.0 - d / 2.0) * 100)),
                 # Single-sourced floor: annotate (do not drop) so the hook can mark
                 # weak hits instead of hardcoding + silently filtering its own copy.
                 "below_floor": sim < args.min_similarity,
                 "snippet": " ".join(b.split())[:200]}
                for p, d, b in results
            ]))
            return 0
        try:
            results = query(args.db, args.query, args.limit,
                            http_timeout=args.http_timeout,
                            distinct_paths=args.distinct_paths)
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 2
        print(format_results(results, min_similarity=args.min_similarity))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
