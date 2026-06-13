#!/usr/bin/env python3
"""Build or query a local SQLite FTS5 search index over markdown memory/notes.

PC-portable variant (claude-infra/pc-bootstrap). Pure stdlib — no pip installs.
Corpus roots come from, in priority order:
  1. CLAUDE_FTS_ROOTS env var — os.pathsep-separated directories
     (Windows: "C:/Users/you/ableton-claude-workspace;C:/Users/you/vault")
  2. fts-roots.txt next to the DB — one directory per line, # comments allowed
  3. fallback: every ~/.claude/projects/*/memory directory

Results are POINTERS to source, not facts — read the file before quoting.
DB: ~/.claude/memory-sync/search.db (override with --db).
Same query interface as the Mac original, so /memory-search and /recall work unchanged.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

HOME = Path.home()
SYNC_DIR = HOME / ".claude" / "memory-sync"
DB_PATH = SYNC_DIR / "search.db"
ROOTS_FILE = SYNC_DIR / "fts-roots.txt"

SKIP_SUFFIXES = (".bak", ".tmp", ".swp", ".swo", ".orig")
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".venv", "__pycache__",
             "vendor", "sound_library", ".codex", "worktrees"}


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


def rebuild(db_path: Path) -> tuple[int, int]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DROP TABLE IF EXISTS docs")
        conn.execute(
            "CREATE VIRTUAL TABLE docs USING fts5("
            "path UNINDEXED, body, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        files = iter_source_files()
        skipped = 0
        for f in files:
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                skipped += 1
                continue
            conn.execute("INSERT INTO docs (path, body) VALUES (?, ?)", (str(f), body))
        conn.commit()
        return len(files) - skipped, skipped
    finally:
        conn.close()


def query(db_path: Path, q: str, limit: int) -> list[tuple[str, str]]:
    if not db_path.exists():
        raise FileNotFoundError(f"Index not found at {db_path}. Run with --rebuild first.")
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT path, snippet(docs, 1, '<<', '>>', '...', 16) "
            "FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (q, limit),
        )
        return list(cur.fetchall())
    finally:
        conn.close()


def format_results(results: list[tuple[str, str]]) -> str:
    if not results:
        return "(no matches)"
    out = []
    for path, snip in results:
        out.append(f"{path}\n  {' '.join(snip.split())}")
    return "\n\n".join(out)


def main() -> int:
    # Windows consoles default to cp1252 — snippets with unicode crash --query
    # without this (PC bug 2026-06-10). No-op on UTF-8 terminals.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", action="store_true",
                        help="Drop and rebuild the index from current source files.")
    parser.add_argument("--query", "-q", type=str,
                        help="FTS5 query. Examples: 'drum rack', '\"session_state\"', 'EQ OR mixing'.")
    parser.add_argument("--limit", "-n", type=int, default=10)
    parser.add_argument("--db", type=Path, default=DB_PATH)
    parser.add_argument("--roots", action="store_true",
                        help="Print the resolved corpus roots and exit.")
    args = parser.parse_args()

    if args.roots:
        for r in corpus_roots():
            print(f"{r}  {'(exists)' if r.exists() else '(MISSING)'}")
        return 0
    if args.rebuild:
        n, skipped = rebuild(args.db)
        print(f"Indexed {n} files into {args.db} ({skipped} skipped).")
    if args.query:
        try:
            print(format_results(query(args.db, args.query, args.limit)))
        except sqlite3.OperationalError as e:
            print(f"Query error: {e}", file=sys.stderr)
            return 1
        except FileNotFoundError as e:
            print(str(e), file=sys.stderr)
            return 1
    if not args.rebuild and not args.query:
        parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
