#!/usr/bin/env python3
"""SessionStart hook: keep the FTS `search.db` fresh, automatically.

Cheap path: stat the corpus roots for the newest *.md mtime and compare to
`search.db`. If memory changed since the last build, spawn a DETACHED background
rebuild (non-blocking, so session start is never delayed); otherwise no-op. This
is the FTS counterpart to the semantic daily-rebuild schedule - but event-driven
(rebuilds only when memory actually changed) instead of time-driven.

Pure stdlib. Fails silent. Pairs with the on-demand /recall and the always-on
fts-recall hook - both read whatever search.db currently holds, so a slightly-late
rebuild only delays findability of brand-new notes by one session, never breaks
anything. Reversible: remove from ~/.claude/settings.json SessionStart.

Roots are resolved exactly like build-search-index.py:
  FTS_RECALL_ROOTS env (os.pathsep-separated) -> fts-roots.txt -> ~/.claude/projects/*/memory.
Env: FTS_RECALL_DB / FTS_RECALL_INDEXER override the db + indexer paths.

Install: wire into ~/.claude/settings.json under SessionStart, e.g.
  {"hooks": {"SessionStart": [ { "hooks": [ {
     "type": "command",
     "command": "python ~/.claude/hooks/fts-refresh.py",
     "shell": "bash" } ] } ] }}
"""
import os
import subprocess
import sys
from pathlib import Path

SYNC = Path.home() / ".claude" / "memory-sync"
DB = Path(os.environ.get("FTS_RECALL_DB", str(SYNC / "search.db")))
INDEXER = Path(os.environ.get("FTS_RECALL_INDEXER", str(SYNC / "build-search-index.py")))
ROOTS_FILE = SYNC / "fts-roots.txt"
SKIP_DIRS = {".git", ".obsidian", "node_modules", ".venv", "__pycache__",
             "vendor", "sound_library", ".codex", "worktrees"}


def roots():
    env = os.environ.get("FTS_RECALL_ROOTS")
    if env:
        return [os.path.expanduser(p) for p in env.split(os.pathsep) if p.strip()]
    out = []
    if ROOTS_FILE.exists():
        for line in ROOTS_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(os.path.expandvars(os.path.expanduser(line)))
    if out:
        return out
    proj = Path.home() / ".claude" / "projects"
    return [str(p) for p in proj.glob("*/memory")] if proj.exists() else []


def newest_md_mtime(dirs):
    newest = 0.0
    for root in dirs:
        if not os.path.isdir(root):
            continue
        for dirpath, subdirs, files in os.walk(root):
            subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
            for f in files:
                if f.endswith(".md"):
                    try:
                        m = os.path.getmtime(os.path.join(dirpath, f))
                        if m > newest:
                            newest = m
                    except OSError:
                        pass
    return newest


def main():
    if not INDEXER.exists():
        return
    db_mtime = os.path.getmtime(DB) if DB.exists() else 0.0
    if newest_md_mtime(roots()) <= db_mtime:
        return  # index already current - no-op
    py = sys.executable or "python"
    try:
        subprocess.Popen(
            [py, str(INDEXER), "--rebuild"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
