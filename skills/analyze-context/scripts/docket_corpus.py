#!/usr/bin/env python3
"""docket_corpus -- one searchable corpus over every project's real docket files.

WHAT IT IS FOR
    "Is this already filed?" and "is row X still open?" are questions about EVERY place a
    docket row can live: a docket index, the split-out row bodies it points at, archives of
    closed rows, pending cross-repo inbox filings, a handoff. A de-dup that greps one
    hand-picked file list answers a narrower question and reports a clean zero for anything
    outside it -- measured: a mechanism whose only body lived in a split-out candidates file
    was invisible to a grep over the index plus the inboxes. This module enumerates the
    corpus once, maps every hit back to the ROW that holds it, and prints what it searched,
    so a partial scope is never silent.

API (stable; load by path -- the file is not on sys.path once installed):
        import importlib.util, os
        p = os.path.expanduser("~/.claude/skills/analyze-context/scripts/docket_corpus.py")
        spec = importlib.util.spec_from_file_location("docket_corpus", p)
        dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)
    discover(parent=None, project=None) -> list of dicts
        {project, root, path, kind, grammar}. `project` narrows to one project: a directory
        name under the parent, an absolute path, or a scope string ('root:<path>',
        'project:<name>', 'here', 'all'). The returned list also carries the denominator as
        attributes: .projects (names searched), .no_docket (names with no row-bearing docket
        file), .errors (config problems, never silently ignored), .files (count).
    search(pattern, scope='all', parent=None, ignore_case=True) -> list of dicts
        {project, id, state, path, line, head, kind, grammar, match_line, also}. One hit per
        ROW: every matching line is mapped to its enclosing row, and one id that appears as a
        stub in an index and as a body elsewhere collapses to ONE hit that points at the body.
        `head` is the row's first line, at most 160 characters -- never more text than that.
        `line` is the row head's line; `match_line` the first matching line. `also` lists the
        other places the same row id was hit. Carries the same denominator attributes as
        discover(), plus .files_searched.
    state(project, row_id, parent=None) -> 'open' | 'closed' | 'absent' | 'unknown'
        `row_id` may be spelled G#N, #N, N or PROJECT-N (numeric forms match numeric row ids;
        G#N matches only central-style G# rows), or a text id such as A1 or a table item name.
        Raises LookupError for a project that is not found.
    inboxes(root) -> list of dicts {path, age_days, status, tracked}
        Pending DOCKET-INBOX-*.md files at a project root, listed even when untracked (a
        filing written but never committed is the one most likely to be lost). status is
        'committed' (in HEAD), 'staged' (in the index only: `git add` with no commit) or
        'untracked'; tracked is True only when committed, and False outside a git work tree.
        age_days comes from the date in the file name, else from the file's mtime. Raises
        LookupError when root is not a directory.

SCOPES
    'all' (default), 'here' (the current project), 'project:<dirname>' (case-insensitive),
    'root:<path>' (any directory, even one outside the parent or without git). Several may
    be joined with commas: 'here,project:other'.

PROJECTS
    The parent is --parent, else the environment variable DOCKET_CORPUS_PARENT, else the
    directory that holds the current checkout (for a linked worktree, the directory that
    holds its MAIN checkout, so the estate is the same wherever the session runs). Projects
    are the parent's child directories whose `.git` is a DIRECTORY (a linked worktree's
    `.git` is a file) and whose name does not match '*-wt-*', plus the current project even
    when it is not a git repository. Inside a linked worktree the current project is that
    worktree ('here'), and its main checkout is listed separately under its own name.

DISCOVERY (per project; case-insensitive names; no recursion except config globs)
    docket      the session-start docket set: roadmap.md, docket.md, '* docket.md',
                '*_docket.md', '*-docket.md' and (outside memory dirs) 'docket[-_ ]*.md' at
                the root, context/, continuation/, docs/ and each memory dir
                (continuation/memory, context/memory, ~/.claude/projects/<slug>/memory).
                DOCKET-INBOX-* is never a docket. A Python port of update-context's
                session-evidence.sh `_docket_files`; its test pins parity with that bash.
    roadmap     any other roadmap*.md at those levels (split-out row bodies, audits)
    config      extra paths or globs from docket-corpus.json (see below)
    archive     roadmap*/docket*.md directly inside archive/ at the root and at each level
                above (never a subdirectory such as memory-bak-*)
    handoff-archive  handoff*.md in those archive/ dirs: searched like a handoff, so a
                numbered list in an old handoff never mints a docket id
    handoff     HANDOFF*.md at the root
    self-audit  SELF-AUDIT.md at the root
    inbox       DOCKET-INBOX-*.md at the root
    Always excluded: .claude/worktrees/**, node_modules/**, chrome_profile_*/**, .git/**.
    Files are de-duplicated by real path (a memory dir is often a junction into the repo).

docket-corpus.json (optional, at a project root)
    {"paths": ["bridge/BACKLOG.md", "notes/**/roadmap*.md"],   extra files, globs allowed
     "exclude": ["drafts/*"],                                   extra exclusions (fnmatch)
     "status": {"<glyph>": "closed", "BUILT": "closed"}}        per-project state words
    Paths are relative to the project root. A path or glob that matches no file, and an
    absolute or '..' path (never globbed), is reported as a config error: a partial corpus
    is never silent, and one project's config never stops another project's search.

GRAMMARS (detected per line)
    central-g         - **G#N** <marker>          marker-only state (the central docket)
    hash-bullet       - **#N ...  / > - **#N(a)   sub-ids (a), -t1, ' P0', '#44b' kept as a suffix
    hash-para         **#N ...                    duplicate heads are allowed and reported
    alpha-bullet      - **A1 ...                  a file-level id only where it dominates
    numbered          226. **...                  a file-level id only where it dominates
    table-first-cell  | id | ... |                id = first cell; a bare number only under an id
                                                  header ('#', 'id', 'row', 'item', 'no'); a dated
                                                  row yields the #N its DATE cell cites, else the
                                                  #N its item cell leads with, never a later cell
    glyph-first       - <glyph> ...               no id: keyed by file:line
    inbox-block       a proposal block in a DOCKET-INBOX file: keyed by file#block, open
    A numbered list in a handoff is not a docket, so numbered, alpha and table ids are
    project-level only in a docket/roadmap/archive/config file whose dominant grammar they
    are; elsewhere the row is keyed by file:line.
    ROW BODIES: a row with an id runs to the next head, heading or rule. Its glyph-led
    paragraphs, indented lines, quotes and embedded TABLES are its body (a table inside a
    row mints no ids). Under a LIST-shaped head ('- **#N', '> - **#N', '226. **') a column-0
    list or quote item is a sibling that ends the row: a glyph-led one is its own row, a
    plain one belongs to no row.

STATE
    central-g rows: the head marker alone -- open = red/orange/yellow/green circle, closed =
    check/cross, anything else unknown. Other rows: the first status WORD after the id (a
    config word, else CLOSED, DONE, BUILT ... / OPEN, NEW, CANDIDATE ...) and the leading
    GLYPH/tag (a config glyph, else check/cross closed; circles, pause, half-circle, warning
    open; no-entry ambiguous, because projects disagree about it; a [RED]/[YELLOW]/[GREEN]
    tag open). One definite answer, or two that agree, decide; a word and a glyph that
    DISAGREE ('<yellow> RULED ... edit NOT made') read unknown. When one id has rows in
    several files, the tiers are read in order (docket > roadmap/config > archive > handoff >
    inbox): a tier whose rows carry no status signal is passed over; a tier whose rows
    disagree, or that holds a contradicted or unrecognised marker, gives 'unknown'.

CLI (ASCII usage; every list/search prints its denominator)
    python docket_corpus.py list [--scope S] [--json]
    python docket_corpus.py search [-i] PATTERN [--scope S] [--json]    (-i: ignore case)
    python docket_corpus.py state PROJECT ID [--json]
    python docket_corpus.py inboxes [--root PATH | --scope S] [--json]
    python docket_corpus.py --selftest
    --parent PATH works with every subcommand.

EXIT STATUS
    list / search / inboxes: 0 ran (search: whether or not anything matched), 2 usage error,
    unknown scope or project, or an inboxes --root that is not a directory. state: 0 open or
    closed, 1 absent or unknown, 2 error.

FILES are read as UTF-8 (a BOM is dropped) or, by their BOM, UTF-16, and parsed once per
distinct content: a rewrite is re-read even when its size and mtime are unchanged.
"""
from __future__ import annotations

import argparse
import datetime
import fnmatch
import functools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CONFIG_NAME = "docket-corpus.json"
ENV_PARENT = "DOCKET_CORPUS_PARENT"
HEAD_MAX = 160

# ---------------------------------------------------------------------------------------
# State vocabulary
# ---------------------------------------------------------------------------------------

# The central docket's head markers. Parity with the central counting tool is pinned by a
# committed test that compares these two sets with that tool's own and classifies every
# live row both ways -- this module is public and cannot import it.
CENTRAL_OPEN = {
    "\U0001F534": "critical",   # red circle
    "\U0001F7E0": "high",       # orange circle
    "\U0001F7E1": "medium",     # yellow circle
    "\U0001F7E2": "low",        # green circle
}
CENTRAL_CLOSED = {
    "✅": "resolved",       # check mark
    "❌": "refuted",        # cross mark
}

GLYPHS = ("\U0001F534\U0001F7E0\U0001F7E1\U0001F7E2✅❌⛔⏸◐"
          "\U0001F504⚠")
DEFAULT_GLYPH = {
    "✅": "closed", "❌": "closed",
    "\U0001F534": "open", "\U0001F7E0": "open", "\U0001F7E1": "open", "\U0001F7E2": "open",
    "⏸": "open",           # pause: deferred
    "◐": "open",           # half circle: partial
    "\U0001F504": "open",       # arrows: in progress / inverted
    "⚠": "open",           # warning
    "⛔": "unknown",        # no entry: 'declined' in one project, 'blocked' in another
}
CLOSED_WORDS = {
    "CLOSED", "DONE", "RESOLVED", "SHIPPED", "REFUTED", "BUILT", "CHECKED", "FIXED",
    "ANSWERED", "RULED", "SETTLED", "SOLVED", "DECLINED", "SHELVED", "SUPERSEDED", "OBSOLETE",
    "RETIRED", "WONTFIX", "DELIVERED", "RECEIVED", "ADOPTED", "MERGED", "EXECUTED",
    "ACTIVATED", "DEPLOYED", "COMPLETE", "COMPLETED", "CANCELLED", "CANCELED", "DROPPED",
}
OPEN_WORDS = {
    "OPEN", "NEW", "REOPENED", "PARTIAL", "PARTIALLY", "PARTLY", "INCOMPLETE", "CANDIDATE",
    "ACTIVE", "BLOCKED", "DEFERRED", "DEFER", "PARKED", "PENDING", "PROPOSED", "IDEA",
    "QUEUED", "HOLD", "TODO", "IN-PROGRESS", "WIP", "UNBLOCKED", "BACKLOG",
}
COLOR_TAGS = {"RED", "ORANGE", "YELLOW", "GREEN"}
STATES = ("open", "closed", "absent", "unknown")

# ---------------------------------------------------------------------------------------
# Grammars
# ---------------------------------------------------------------------------------------

CENTRAL_RE = re.compile(r"^- \*\*G#(\d+)\*\*[ \t]+(\S)")
# A sub-id suffix stays part of the id: (a), -t1, ' P0', and a single letter ('#44b').
SUB_ID = r"(\([A-Za-z0-9]+\)|-t\d+| P\d\b|[a-z](?![A-Za-z0-9]))?"
HASH_BULLET_RE = re.compile(r"^(?:> )?- \*\*#(\d+)" + SUB_ID)
HASH_PARA_RE = re.compile(r"^\*\*#(\d+)" + SUB_ID)
ALPHA_RE = re.compile(r"^- \*\*([A-Z]\d{1,4})(?![\w#])")
NUMBERED_RE = re.compile(r"^(\d{1,3})\. \*\*")
TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
GLYPH_FIRST_RE = re.compile(r"^(?:[-*+] |\d+\. |> )?\s*(?:\*\*|__)?\s*([" + GLYPHS + r"])")
HEADING_RE = re.compile(r"^#{1,6}\s")
SUBHEADING_RE = re.compile(r"^#{2,6}\s")
HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
# An index stub: '[full row -> X]', '[full row → `X`](X)**' or '→ [archive](X)' at the line end.
STUB_RE = re.compile(r"\[full row (?:->|→) [^\]]+\](?:\([^)]*\))?[*_\s]*$|→ \[archive\]\([^)]+\)")
# The first cell of a table whose numeric cells ARE row ids ('| # | ...'). Under any other header
# ('| chars |', '| order |', '| width |') a number is data, never a docket id.
ID_HEADERS = {"#", "id", "row", "item", "no", "no.", "num", "number"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?!\d)")
CITED_RE = re.compile(r"(?<![\w&])#(\d{1,4})\b")
TAG_RE = re.compile(r"\[([A-Z][A-Z0-9/-]*)\]")
WORD_RE = re.compile(r"([A-Z][A-Z-]*(?:/[A-Z][A-Z-]*)*)(?![A-Za-z])")
# A proposal block in a DOCKET-INBOX file. Copied from the central backlog index's
# BLOCK_START; the committed test byte-compares the two patterns.
INBOX_BLOCK_START = re.compile(r"^(\*\*\[|## |- \*\*|\d+\. \*\*|\*\*(?:Candidate|Kernel|Row|Proposal)\b)", re.I)
INBOX_DATE_RE = re.compile(r"^docket-inbox-(\d{4}-\d{2}-\d{2})", re.I)

ID_GRAMMARS = ("central-g", "hash-bullet", "hash-para", "numbered", "alpha-bullet", "table-first-cell")
DOCKET_KINDS = ("docket", "roadmap", "config", "archive")
KIND_TIER = {"docket": 0, "roadmap": 1, "config": 1, "archive": 2,
             "handoff": 3, "handoff-archive": 3, "self-audit": 3, "inbox": 4}
KIND_ORDER = ("docket", "roadmap", "config", "archive", "handoff-archive", "handoff", "self-audit",
              "inbox")

LEVELS = ("", "context", "continuation", "docs")
MEMORY_LEVELS = ("continuation/memory", "context/memory")
ARCHIVE_PARENTS = ("", "context", "continuation", "docs", "continuation/memory", "context/memory")


class Result(list):
    """A list of dicts that also carries the denominator of the call that built it."""
    projects = ()
    no_docket = ()
    errors = ()
    files = 0
    files_searched = 0


# ---------------------------------------------------------------------------------------
# Projects and scopes
# ---------------------------------------------------------------------------------------

def _git(args, cwd):
    try:
        r = subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                           encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _key(path):
    return os.path.normcase(str(Path(path).resolve()))


@functools.lru_cache(maxsize=64)
def _checkout(cwd):
    """(toplevel, main checkout) for cwd; both are cwd itself outside git."""
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    if not top:
        here = Path(cwd).resolve()
        return here, here
    top_p = Path(top).resolve()
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], cwd)
    if common is None:
        raw = _git(["rev-parse", "--git-common-dir"], cwd)
        common = str((Path(cwd) / raw).resolve()) if raw else None
    main = top_p
    if common:
        c = Path(common)
        if c.name == ".git":
            main = c.parent.resolve()
    return top_p, main


def default_parent(cwd=None):
    env = os.environ.get(ENV_PARENT)
    if env:
        return Path(env).resolve()
    _, main = _checkout(str(Path(cwd or os.getcwd()).resolve()))
    return main.parent


def _project(name, root, current=False, main=None):
    return {"name": name, "root": Path(root), "current": current, "main": Path(main or root)}


def projects(parent=None, cwd=None):
    """Every project under the parent, plus the current project (even outside git)."""
    cwd = str(Path(cwd or os.getcwd()).resolve())
    parent = Path(parent).resolve() if parent else default_parent(cwd)
    out, seen = [], {}
    if parent.is_dir():
        for child in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            try:
                if not child.is_dir() or fnmatch.fnmatch(child.name.casefold(), "*-wt-*"):
                    continue
                if not (child / ".git").is_dir():
                    continue
            except OSError:
                continue
            k = _key(child)
            if k not in seen:
                seen[k] = len(out)
                out.append(_project(child.name, child.resolve()))
    top, main = _checkout(cwd)
    k = _key(top)
    if k in seen:
        out[seen[k]]["current"] = True
    elif k != _key(parent):  # run from the parent itself: there is no current project
        out.append(_project(top.name, top, current=True, main=main))
    return parent, out


def select(scope="all", parent=None, cwd=None):
    """Resolve a scope string to (parent, [project, ...]). Raises on an unknown name."""
    parts = [s.strip() for s in (scope or "all").split(",") if s.strip()]
    chosen, listing, par = [], None, None
    for part in parts:
        low = part.casefold()
        if low.startswith("root:"):
            r = Path(part[len("root:"):].strip()).expanduser()
            if not r.is_dir():
                raise LookupError("root:%s is not a directory" % r)
            chosen.append(_project(r.resolve().name, r.resolve()))
            continue
        if listing is None:
            par, listing = projects(parent, cwd)
        if low == "all":
            chosen.extend(listing)
        elif low == "here":
            chosen.extend(p for p in listing if p["current"])
        elif low.startswith("project:"):
            want = part[len("project:"):].strip().casefold()
            hit = [p for p in listing if p["name"].casefold() == want]
            if not hit:
                raise LookupError("no project named %r under %s (known: %s)" % (
                    part[len("project:"):].strip(), par, ", ".join(p["name"] for p in listing) or "none"))
            chosen.extend(hit)
        else:
            raise ValueError("unknown scope %r (use all, here, project:<name>, root:<path>)" % part)
    uniq, keys = [], set()
    for p in chosen:
        k = _key(p["root"])
        if k not in keys:
            keys.add(k)
            uniq.append(p)
    if par is None:
        par = Path(parent).resolve() if parent else None
    return par, uniq


def _as_scope(project):
    """A project argument (name, absolute path or scope string) as a scope string."""
    s = str(project)
    low = s.casefold()
    if low.startswith(("root:", "project:")) or low in ("all", "here"):
        return s
    if os.path.isdir(s) and (os.path.isabs(s) or s in (".", "..") or "/" in s or os.sep in s):
        return "root:" + os.path.abspath(s)
    return "project:" + s


# ---------------------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------------------

def is_docket_name(name, strict=False):
    """Port of session-evidence.sh _is_docket_name (case-insensitive basename test)."""
    b = os.path.basename(name).casefold()
    if b.startswith("docket-inbox-"):
        return False
    if b in ("roadmap.md", "docket.md"):
        return True
    if re.fullmatch(r".*[-_ ]docket\.md", b, re.S):
        return True
    if re.fullmatch(r"docket[-_ ].*\.md", b, re.S):
        return not strict
    return False


def excluded(rel, extra=()):
    """True for a root-relative path under a worktree, node_modules, a browser profile or .git."""
    rel = str(rel).replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    low = rel.casefold()
    parts = [p for p in low.split("/") if p]
    if low.startswith(".claude/worktrees/") or "/.claude/worktrees/" in "/" + low:
        return True
    if "node_modules" in parts or ".git" in parts:
        return True
    if any(fnmatch.fnmatch(p, "chrome_profile_*") for p in parts):
        return True
    return any(fnmatch.fnmatch(low, pat.casefold()) for pat in extra)


def _md_files(d):
    try:
        entries = sorted(os.listdir(d), key=str.casefold)
    except OSError:
        return []
    out = []
    for e in entries:
        if e.startswith(".") or not e.casefold().endswith(".md"):
            continue
        full = os.path.join(d, e)
        if os.path.isfile(full):
            out.append(full)
    return out


def _home_memory(main_root):
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(main_root)))
    d = Path.home() / ".claude" / "projects" / slug / "memory"
    return d if d.is_dir() else None


def _load_config(root):
    p = Path(root) / CONFIG_NAME
    if not p.is_file():
        return {}, None
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError("top level is not an object")
        for key in ("paths", "exclude"):
            if not isinstance(cfg.get(key, []), list):
                raise ValueError("%r must be a list" % key)
        if not isinstance(cfg.get("status", {}), dict):
            raise ValueError("'status' must be an object")
        return cfg, None
    except (ValueError, OSError) as e:
        return {}, "%s: %s" % (p, e)


def _status_map(cfg):
    out = {}
    for k, v in (cfg.get("status") or {}).items():
        v = str(v).casefold()
        if v in ("open", "closed", "unknown"):
            out[k.upper() if re.fullmatch(r"[A-Za-z][A-Za-z/-]*", k) else k] = v
    return out


def _project_files(p):
    """[(path, kind, rel)] for one project, de-duplicated by real path, plus config errors.

    Each scanned DIRECTORY is resolved once (a memory dir is often a junction into the
    repo), never each file: per-file resolution was the whole cost of a state() call.
    """
    root = Path(p["root"])
    root_real = os.path.realpath(str(root))
    root_norm = os.path.normcase(root_real)
    cfg, err = _load_config(root)
    extra_ex = [str(x) for x in cfg.get("exclude", [])]
    found, keys, dirs = [], set(), {}

    def add(path, kind):
        d, name = os.path.split(str(path))
        if d not in dirs:
            dirs[d] = os.path.realpath(d)
        real = os.path.join(dirs[d], name)
        norm = os.path.normcase(real)
        if norm.startswith(root_norm + os.sep):
            rel = os.path.relpath(real, root_real).replace("\\", "/")
            if excluded(rel, extra_ex):
                return
        else:
            rel = real  # outside the root (the home memory dir): never under an excluded tree
        if norm in keys:
            return
        keys.add(norm)
        found.append((str(path), kind, rel))

    mem = [root / m for m in MEMORY_LEVELS if (root / m).is_dir()]
    home = _home_memory(p["main"])
    if home is not None:
        mem.append(home)
    for lvl in LEVELS:
        for f in _md_files(root / lvl if lvl else root):
            if is_docket_name(f):
                add(f, "docket")
    for d in mem:
        for f in _md_files(d):
            if is_docket_name(f, strict=True):
                add(f, "docket")
    for d in [root / lvl if lvl else root for lvl in LEVELS] + mem:
        for f in _md_files(d):
            if os.path.basename(f).casefold().startswith("roadmap"):
                add(f, "roadmap")
    problems = []
    for n, pat in enumerate(cfg.get("paths", [])):
        pat = str(pat).replace("\\", "/")
        if os.path.isabs(pat) or re.match(r"^[A-Za-z]:", pat) or pat.startswith("/") or ".." in pat.split("/"):
            # Never globbed: an absolute glob raises out of Path.glob and would stop EVERY
            # project's search, and a path outside the project is not this project's docket.
            problems.append("paths[%d] %r is outside the project (absolute or '..'); ignored" % (n, pat))
            continue
        try:
            hits = sorted(root.glob(pat)) if any(c in pat for c in "*?[") else [root / pat]
        except (NotImplementedError, ValueError, OSError) as e:
            problems.append("paths[%d] %r could not be read: %s" % (n, pat, e))
            continue
        files = [f for f in hits if f.is_file()]
        if not files:
            # A typo or a later rename silently shrinks the corpus to a clean zero otherwise.
            problems.append("paths[%d] %r matched nothing" % (n, pat))
        for f in files:
            add(f, "config")
    if problems:
        err = "; ".join(([err] if err else []) + ["%s: %s" % (Path(root) / CONFIG_NAME, x) for x in problems])
    for lvl in ARCHIVE_PARENTS:
        for f in _md_files(root / lvl / "archive" if lvl else root / "archive"):
            b = os.path.basename(f).casefold()
            if b.startswith(("roadmap", "docket")):
                add(f, "archive")
            elif b.startswith("handoff"):
                add(f, "handoff-archive")
    for f in _md_files(root):
        b = os.path.basename(f).casefold()
        if b.startswith("handoff"):
            add(f, "handoff")
        elif b == "self-audit.md":
            add(f, "self-audit")
        elif b.startswith("docket-inbox-"):
            add(f, "inbox")
    found.sort(key=lambda t: KIND_ORDER.index(t[1]))
    return found, cfg, err


# ---------------------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------------------

def _central_state(marker):
    if marker in CENTRAL_OPEN:
        return "open"
    if marker in CENTRAL_CLOSED:
        return "closed"
    return "unknown"


def _word_candidates(word):
    out = []
    for part in word.split("/"):
        if part:
            out.append(part)
            head = part.split("-")[0]
            if head and head != part:
                out.append(head)
    return [word] + out


def status_of(text, smap=None):
    """State of a non-central row from the text that follows its id."""
    return _status(text, smap)[0]


def _status(text, smap=None):
    """(state, contested) of a non-central row from the text that follows its id.

    The leading status WORD and the leading GLYPH/tag are read separately. One definite answer
    wins; two that AGREE win; two that DISAGREE ('<yellow> RULED ... edit NOT made', '<check>
    OPEN') give 'unknown' -- the owner's glyph and the text contradict each other, and either
    answer could be the wrong direction. `contested` is True when the row carries a status
    signal that did not resolve (a contradiction, or an ambiguous glyph such as no-entry with no
    word), and False when it carries none; only a SILENT unknown lets a lower tier decide.
    """
    smap = smap or {}
    i, n, glyphs, tags = 0, len(text), [], []
    while i < n:
        ch = text[i]
        if ch in " \t*_`:️":
            i += 1
        elif ch in GLYPHS or unicodedata.category(ch) == "So":
            glyphs.append(ch)  # an unmapped symbol maps to nothing but must not hide the word
            i += 1
        elif ch == "[":
            m = TAG_RE.match(text, i)
            if not m:
                break
            tags.append(m.group(1))
            i = m.end()
        else:
            break
    m = WORD_RE.match(text, i)
    words = _word_candidates(m.group(1)) if m else []
    word = None
    for w in words:
        if w in smap:
            word = smap[w]
            break
    if word is None:
        for w in words:
            if w in CLOSED_WORDS:
                word = "closed"
                break
            if w in OPEN_WORDS:
                word = "open"
                break
    mark = None
    for g in glyphs + ["[%s]" % t for t in tags]:
        if g in smap:
            mark = smap[g]
            break
    if mark is None:
        for g in glyphs:
            st = DEFAULT_GLYPH.get(g, "unknown")
            if st != "unknown":
                mark = st
                break
    if mark is None and any(t in COLOR_TAGS for t in tags):
        mark = "open"
    definite = {s for s in (word, mark) if s in ("open", "closed")}
    if len(definite) == 1:
        return definite.pop(), False
    if definite:
        return "unknown", True
    signal = word is not None or mark is not None or any(g in DEFAULT_GLYPH for g in glyphs)
    return "unknown", signal


def _cells(line):
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def _clean_cell(c):
    return c.replace("**", "").replace("`", "").strip()


def _classify(lines, kind):
    """Per line: (grammar, id_text, rest) or a structural marker, or None."""
    out = [None] * len(lines)
    header0 = None  # first header cell of the table being read, casefolded
    for i, ln in enumerate(lines):
        if not ln.startswith("|"):
            header0 = None
        if HEADING_RE.match(ln):
            out[i] = ("heading", None, None)
            continue
        if HR_RE.match(ln):
            out[i] = ("hr", None, None)
            continue
        m = CENTRAL_RE.match(ln)
        if m:
            out[i] = ("central-g", "G#" + m.group(1), m.group(2))
            continue
        m = HASH_BULLET_RE.match(ln)
        if m:
            out[i] = ("hash-bullet", "#" + m.group(1) + (m.group(2) or ""), ln[m.end():])
            continue
        m = HASH_PARA_RE.match(ln)
        if m:
            out[i] = ("hash-para", "#" + m.group(1), ln[m.end():])
            continue
        m = ALPHA_RE.match(ln)
        if m:
            out[i] = ("alpha-bullet", m.group(1), ln[m.end():])
            continue
        m = NUMBERED_RE.match(ln)
        if m:
            out[i] = ("numbered", "#" + m.group(1), ln[m.end():])
            continue
        if ln.startswith("|"):
            if TABLE_SEP_RE.match(ln):
                out[i] = ("table-sep", None, None)
            elif i + 1 < len(lines) and TABLE_SEP_RE.match(lines[i + 1]):
                out[i] = ("table-header", None, None)
                hc = _cells(ln)
                header0 = _clean_cell(hc[0]).casefold() if hc else ""
            else:
                cells = _cells(ln)
                first = _clean_cell(cells[0]) if cells else ""
                mnum = re.fullmatch(r"(#?)(\d{1,4})", first)
                if mnum and (mnum.group(1) or header0 in ID_HEADERS):
                    # '#12' is an id anywhere; a bare 12 only under an id-column header.
                    ident = "#" + mnum.group(2)
                elif mnum:
                    ident = None  # a count, a width, an order: data, not a row
                elif DATE_RE.match(first):
                    # A dated (session-log) row is about the row its DATE cell cites, else the
                    # row its item cell LEADS with -- never an id mentioned later in the row.
                    cited = CITED_RE.search(cells[0])
                    if not cited and len(cells) > 1:
                        cited = re.match(r"#(\d{1,4})\b", _clean_cell(cells[1]))
                    ident = ("#" + cited.group(1)) if cited else first
                else:
                    ident = first[:60] or None
                out[i] = ("table-first-cell", ident, cells[1:])
            continue
        m = GLYPH_FIRST_RE.match(ln)
        if m:
            out[i] = ("glyph-first", None, ln[m.start(1):])
            continue
    return out


def _family(g):
    return "hash" if g in ("hash-bullet", "hash-para") else g


def _decode(raw):
    """Text of a file: UTF-16 by its BOM, UTF-8 with or without a BOM (PowerShell 5.1 writes both)."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _block_kind(line):
    """The block shape a line opens: indented, bullet, numbered, para, or inside a quote
    quote-bullet / quote (a quoted paragraph) / quote-indented / quote-blank."""
    if line[:1] in (" ", "\t"):
        return "indented"
    if line.startswith(">"):
        inner = line[1:]
        if inner.startswith(" "):
            inner = inner[1:]
        if not inner.strip():
            return "quote-blank"
        if inner[:1] in (" ", "\t"):
            return "quote-indented"
        if re.match(r"^[-*+] ", inner):
            return "quote-bullet"
        return "quote"
    if re.match(r"^[-*+] ", line):
        return "bullet"
    if re.match(r"^\d+\. ", line):
        return "numbered"
    return "para"


def _starts_sibling(head_line, line):
    """Does `line` END the open row whose head is head_line (a new item, not the row's body)?

    Measured on the live estate: inside an open row, glyph-led lines are overwhelmingly its
    body -- indented sub-points, paragraphs, quotes and tables of a paragraph-style row
    ('**#211 ...' followed by '<check> **(a) EXECUTED ...'); a paragraph-style row runs to the
    next head. Under a LIST-shaped row the one shape that is a new item is a column-0 list or
    quote item: '- **<check> Widget RESOLVED ...' and '- **Page redesign wave ...' after
    '- **#128 ...' are sibling bullets, '> - Tooling: ...' after '> - **#193** ...' is a sibling
    quoted bullet, and '> **<check> SESSION LOG' starts a new quoted block. Lines indented under
    the row, or inside its quote ('>   ...'), stay with it.
    """
    if _block_kind(head_line) not in ("bullet", "numbered", "quote-bullet"):
        return False
    return _block_kind(line) in ("bullet", "numbered", "quote-bullet", "quote")


_PARSE_CACHE = {}


def _parse_cached(path, kind, rel, smap_items, raw):
    smap = dict(smap_items)
    lines = _decode(raw).split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]
    rows, row_of = [], [None] * len(lines)

    def new_row(i, grammar, ident, label, key, state, contested=False):
        row = {"id": ident, "label": label, "key": key, "grammar": grammar, "state": state,
               "contested": contested, "line": i + 1, "head": lines[i].rstrip(),
               "stub": bool(STUB_RE.search(lines[i])), "kind": kind, "path": path, "rel": rel}
        rows.append(row)
        return row

    if kind == "inbox":
        # A filing that uses sub-headings for its candidates is split on those alone (its
        # bullets are the candidates' fields); one without headings is split on the
        # backlog index's proposal-lead shapes after a blank line. Text before the first
        # block is block 0.
        name = os.path.basename(path)
        by_heading = any(SUBHEADING_RE.match(ln) for ln in lines)
        k, cur = 0, None
        for i, ln in enumerate(lines):
            prev = lines[i - 1].strip() if i else ""
            if by_heading:
                start = bool(SUBHEADING_RE.match(ln))
            else:
                start = bool(INBOX_BLOCK_START.match(ln)) and (i == 0 or prev == "" or prev.startswith("---"))
            if start:
                k += 1
            if start or cur is None:
                ident = "%s#%d" % (name, k)
                cur = new_row(i, "inbox-block", ident, ident, ident.casefold(), "open")
            row_of[i] = cur
        return rows, row_of, lines, "inbox-block"

    cls = _classify(lines, kind)
    counts = {}
    for c in cls:
        if c and c[0] in ID_GRAMMARS:
            counts[_family(c[0])] = counts.get(_family(c[0]), 0) + 1
    order = ["central-g", "hash", "numbered", "alpha-bullet", "table-first-cell"]
    dominant = max(order, key=lambda f: (counts.get(f, 0), -order.index(f))) if counts else None
    if dominant is None:
        file_grammar = "glyph-first" if any(c and c[0] == "glyph-first" for c in cls) else "none"
    elif dominant == "hash":
        paras = sum(1 for c in cls if c and c[0] == "hash-para")
        file_grammar = "hash-para" if paras * 2 > counts["hash"] else "hash-bullet"
    else:
        file_grammar = dominant

    # `cur` is the row the current line belongs to; `idrow` the open id row (a head with an id,
    # never a table row). An id row's body runs to the next head, heading or rule: its
    # glyph-led paragraphs, indented sub-points and embedded TABLES stay with it (a table inside
    # a row is body, and its numbers are data), except for a sibling item (_starts_sibling).
    cur = idrow = None
    for i, c in enumerate(cls):
        g = c[0] if c else None
        if g in ("heading", "hr"):
            cur = idrow = None
        elif g in ("table-sep", "table-header", "table-first-cell") and idrow is not None:
            cur = idrow
        elif g == "glyph-first" and idrow is not None and not _starts_sibling(lines[idrow["line"] - 1],
                                                                               lines[i]):
            cur = idrow
        elif g is None and cur is not None and cur["grammar"] != "table-first-cell" and _starts_sibling(
                lines[cur["line"] - 1], lines[i]):
            cur = idrow = None  # a plain sibling item: not the open row's body, and itself no row
        elif g in ("table-sep", "table-header"):
            cur = None
        elif g in ID_GRAMMARS or g == "glyph-first":
            ident, rest = c[1], c[2]
            contested = False
            if g == "central-g":
                state = _central_state(rest)
                contested = state == "unknown"  # a marker is always present: unknown = unrecognised
            elif g == "table-first-cell":
                state = "unknown"
                for cell in rest:
                    st, amb = _status(cell, smap)
                    if st != "unknown":
                        state = st
                        break
                    contested = contested or amb
                if state != "unknown":
                    contested = False
            else:
                state, contested = _status(rest, smap)
            # Numbered, alpha and table ids are docket ids only in a docket-like file whose
            # dominant grammar they are -- a numbered list in a handoff is not row #1. A table
            # row whose id is a #N (a resolved table citing the row) joins a hash/numbered file.
            project_level = g in ("central-g", "hash-bullet", "hash-para") or (
                kind in DOCKET_KINDS and ident is not None and g != "glyph-first" and (
                    _family(g) == dominant or (g == "table-first-cell" and ident.startswith("#")
                                               and dominant in ("hash", "numbered"))))
            local = "%s:%d" % (rel, i + 1)
            if project_level:
                cur = new_row(i, g, ident, ident, ident.casefold(), state, contested)
            else:
                cur = new_row(i, g, local, ident, "@" + local.casefold(), state, contested)
            # A head with an id opens a body; a table row or a sibling glyph item ends one.
            idrow = cur if g in ID_GRAMMARS and g != "table-first-cell" else None
        elif cur is not None:
            if cur["grammar"] == "table-first-cell":
                cur = None
            elif cur["grammar"] == "glyph-first" and lines[i].strip() == "":
                cur = None
        row_of[i] = cur
    return rows, row_of, lines, file_grammar


def _parse(path, kind, rel, smap):
    """Parse one file, cached by CONTENT: the bytes are read every call and the parse is reused
    only when they are identical. An (mtime, size) key served a stale state after a same-size
    rewrite inside one clock tick ('OPEN' -> 'DONE')."""
    with open(path, "rb") as fh:
        raw = fh.read()
    key = (str(path), kind, rel, tuple(sorted(smap.items())))
    hit = _PARSE_CACHE.get(key)
    if hit is not None and hit[0] == raw:
        return hit[1]
    res = _parse_cached(str(path), kind, rel, key[3], raw)
    _PARSE_CACHE[key] = (raw, res)
    return res


def _central_ids(path):
    """Central-style row ids (ints) parsed from one file, in file order (test hook)."""
    rows, _, _, _ = _parse(path, "docket", os.path.basename(path), {})
    return [int(r["id"][2:]) for r in rows if r["grammar"] == "central-g"]


def _index(p):
    files, cfg, err = _project_files(p)
    smap = _status_map(cfg)
    parsed, by_key, local = [], {}, []
    for path, kind, rel in files:
        try:
            rows, row_of, lines, grammar = _parse(path, kind, rel, smap)
        except OSError as e:
            err = (err + "; " if err else "") + "%s: %s" % (path, e)
            continue
        parsed.append({"path": path, "kind": kind, "rel": rel, "rows": rows, "row_of": row_of,
                       "lines": lines, "grammar": grammar})
        for r in rows:
            if r["key"].startswith("@"):
                local.append(r)
            by_key.setdefault(r["key"], []).append(r)
    has_docket = any(f["kind"] in ("docket", "roadmap", "config") for f in parsed)
    return {"project": p, "files": parsed, "by_key": by_key, "local": local,
            "error": err, "has_docket": has_docket}


def _resolve(rows):
    """One state for one id from all of its rows: the most authoritative kind that STATES one decides.

    Tiers are read in order (docket > roadmap/config > archive > handoff > inbox). A tier whose
    rows carry no status signal at all (a shipped-ledger row, a summary pointer line) is passed
    over, so the archive row that states the answer decides. A tier whose rows disagree, or that
    holds a CONTESTED row (its glyph and word contradict, or an unrecognised central marker),
    stops the walk at 'unknown': a stale archive must never outvote a live contradiction.
    """
    if not rows:
        return "absent"
    for tier in sorted({KIND_TIER[r["kind"]] for r in rows}):
        trs = [r for r in rows if KIND_TIER[r["kind"]] == tier]
        known = {r["state"] for r in trs if r["state"] in ("open", "closed")}
        if len(known) > 1 or any(r["state"] == "unknown" and r.get("contested") for r in trs):
            return "unknown"
        if known:
            return known.pop()
    return "unknown"


_QUERY_RE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_ .]*-)?(G#|#)?(\d+)$", re.I)


def _rows_for(idx, row_id):
    q = str(row_id).strip()
    m = _QUERY_RE.match(q)
    if m:
        n = int(m.group(2))
        keys = ["g#%d" % n] if (m.group(1) or "").casefold() == "g#" else ["g#%d" % n, "#%d" % n]
        return [r for k in keys for r in idx["by_key"].get(k, [])]
    want = q.casefold()
    keys = [want]
    if re.fullmatch(r"\d+(?:[a-z]|\([a-z0-9]+\)|-t\d+| p\d)", want):
        keys.append("#" + want)  # a sub-id spelled without its hash: '44b', '188(a)'
    return [r for k in keys for r in idx["by_key"].get(k, [])] + [
        r for r in idx["local"] if r["label"] and r["label"].casefold() == want]


# ---------------------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------------------

def _denominated(items, idxs, errors):
    res = Result(items)
    res.projects = [i["project"]["name"] for i in idxs]
    res.no_docket = [i["project"]["name"] for i in idxs if not i["has_docket"]]
    res.errors = list(errors) + ["%s: %s" % (i["project"]["name"], i["error"]) for i in idxs if i["error"]]
    res.files = sum(len(i["files"]) for i in idxs)
    res.files_searched = res.files
    return res


def discover(parent=None, project=None):
    _, chosen = select(_as_scope(project) if project else "all", parent)
    idxs = [_index(p) for p in chosen]
    items = [{"project": i["project"]["name"], "root": str(i["project"]["root"]), "path": f["path"],
              "rel": f["rel"], "kind": f["kind"], "grammar": f["grammar"],
              "lines": len(f["lines"])}
             for i in idxs for f in i["files"]]
    return _denominated(items, idxs, [])


def search(pattern, scope="all", parent=None, ignore_case=True):
    rx = re.compile(pattern, re.I if ignore_case else 0)
    _, chosen = select(scope, parent)
    idxs = [_index(p) for p in chosen]
    items = []
    for idx in idxs:
        order, found = [], {}
        for fno, f in enumerate(idx["files"]):
            for i, ln in enumerate(f["lines"]):
                if not rx.search(ln):
                    continue
                row = f["row_of"][i]
                if row is None:
                    rel = "%s:%d" % (f["rel"], i + 1)
                    row = {"id": rel, "label": None, "key": "~" + rel.casefold(), "grammar": "loose",
                           "state": "unknown", "line": i + 1, "head": ln.rstrip(), "stub": False,
                           "kind": f["kind"], "path": f["path"], "rel": f["rel"]}
                slot = found.get(row["key"])
                if slot is None:
                    slot = found[row["key"]] = {}
                    order.append(row["key"])
                rid = (row["path"], row["line"])
                if rid not in slot:
                    slot[rid] = (row, i + 1, fno)
        for key in order:
            cands = list(found[key].values())
            best = min(cands, key=lambda t: (t[0]["stub"], KIND_TIER[t[0]["kind"]], t[2], t[0]["line"]))
            row, match_line, _ = best
            if key.startswith("~") or key.startswith("@"):
                state = row["state"]
            else:
                state = _resolve(idx["by_key"].get(key, [row]))
            also = ["%s:%d" % (c[0]["rel"], c[0]["line"]) for c in cands if c is not best]
            items.append({"project": idx["project"]["name"], "id": row["id"], "state": state,
                          "path": row["path"], "rel": row["rel"], "line": row["line"],
                          "head": row["head"][:HEAD_MAX],
                          "kind": row["kind"], "grammar": row["grammar"], "match_line": match_line,
                          "also": also})
    return _denominated(items, idxs, [])


def state(project, row_id, parent=None):
    return state_detail(project, row_id, parent)["state"]


def state_detail(project, row_id, parent=None):
    _, chosen = select(_as_scope(project), parent)
    if not chosen:
        raise LookupError("no project matched %r" % (project,))
    idx = _index(chosen[0])
    rows = _rows_for(idx, row_id)
    return {"project": chosen[0]["name"], "id": str(row_id), "state": _resolve(rows),
            "rows": [{"path": r["path"], "line": r["line"], "kind": r["kind"], "state": r["state"],
                      "id": r["id"]} for r in rows]}


def _inbox_git_state(root):
    """(committed, indexed) inbox basenames (casefolded) at root, or (None, None) outside git.

    COMMITTED is read from HEAD, never from the index: `git add` without a commit -- the state a
    guard that refuses a bare `git commit` routinely leaves behind -- puts a filing in the index
    while nothing durable exists yet.
    """
    idx = _git(["ls-files", "-z", "--", ":(glob,icase)DOCKET-INBOX-*.md"], root)
    if idx is None:
        return None, None
    head = _git(["ls-tree", "-z", "--name-only", "HEAD"], root)  # None on an unborn branch
    committed = {os.path.basename(x).casefold() for x in (head or "").split("\0") if x}
    indexed = {os.path.basename(x).casefold() for x in idx.split("\0") if x}
    return committed, indexed


def inboxes(root):
    root = Path(root)
    if not root.is_dir():
        raise LookupError("%s is not a directory" % root)
    names = [e for e in os.listdir(root)
             if e.casefold().startswith("docket-inbox-") and e.casefold().endswith(".md")
             and (root / e).is_file()]
    committed, indexed = _inbox_git_state(root) if names else (set(), set())
    today = datetime.date.today()
    out = []
    for n in sorted(names, key=str.casefold):
        m = INBOX_DATE_RE.match(n)
        age = None
        if m:
            try:
                age = (today - datetime.date.fromisoformat(m.group(1))).days
            except ValueError:
                age = None
        if age is None:
            age = int((time.time() - (root / n).stat().st_mtime) // 86400)
        low = n.casefold()
        if committed and low in committed:
            status = "committed"
        elif indexed and low in indexed:
            status = "staged"
        else:
            status = "untracked"
        out.append({"path": str(root / n), "age_days": age, "status": status,
                    "tracked": status == "committed"})
    return out


# ---------------------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------------------

def _print_denominator(res, noun="file(s)"):
    print("searched: %d %s in %d project(s): %s" % (
        res.files_searched, noun, len(res.projects), ", ".join(res.projects) or "none"))
    print("no docket found in: %s" % (", ".join(res.no_docket) or "none"))
    for e in res.errors:
        print("config error: %s" % e)


def _cmd_list(a):
    res = discover(a.parent, a.scope)
    if a.json:
        print(json.dumps({"files": list(res), "denominator": _denom_json(res)}, ensure_ascii=False, indent=1))
        return 0
    for f in res:
        print("%-24s %-15s %-16s %6d  %s" % (f["project"][:24], f["kind"], f["grammar"], f["lines"], f["rel"]))
    _print_denominator(res)
    return 0


def _denom_json(res):
    return {"files_searched": res.files_searched, "projects": list(res.projects),
            "no_docket": list(res.no_docket), "errors": list(res.errors)}


def _cmd_search(a):
    res = search(a.pattern, a.scope, a.parent, ignore_case=a.ignore_case)
    if a.json:
        print(json.dumps({"hits": list(res), "denominator": _denom_json(res)}, ensure_ascii=False, indent=1))
        return 0
    for h in res:
        print("%s:%s  %-7s %s:%d  %s" % (h["project"], h["id"], h["state"], h["rel"], h["line"], h["head"]))
    print("hits: %d row(s)" % len(res))
    _print_denominator(res)
    return 0


def _cmd_state(a):
    d = state_detail(a.project, a.id, a.parent)
    if a.json:
        print(json.dumps(d, ensure_ascii=False, indent=1))
    else:
        print("%s:%s %s" % (d["project"], d["id"], d["state"]))
        for r in d["rows"]:
            print("  %s:%d  [%s] %s" % (r["path"], r["line"], r["kind"], r["state"]))
    return 0 if d["state"] in ("open", "closed") else 1


def _cmd_inboxes(a):
    if a.root:
        roots = [("root", Path(a.root))]
    else:
        _, chosen = select(a.scope, a.parent)
        roots = [(p["name"], p["root"]) for p in chosen]
    rows = []
    for name, root in roots:
        for x in inboxes(root):
            x["project"] = name
            rows.append(x)
    if a.json:
        print(json.dumps({"inboxes": rows, "roots_checked": [str(r) for _, r in roots]},
                         ensure_ascii=False, indent=1))
        return 0
    label = {"committed": "committed", "staged": "STAGED-UNCOMMITTED", "untracked": "UNTRACKED"}
    for x in sorted(rows, key=lambda r: -r["age_days"]):
        print("%4dd  %-18s %s  %s" % (x["age_days"], label[x["status"]],
                                      x["project"], os.path.basename(x["path"])))
    print("checked %d project root(s); %d pending inbox file(s)" % (len(roots), len(rows)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="docket_corpus.py",
                                 description="Search every project's docket files as one corpus.")
    ap.add_argument("--parent", default=None, help="directory holding the projects")
    ap.add_argument("--selftest", action="store_true", help="run the offline battery")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("list", help="list the corpus files")
    p.add_argument("--scope", default="all")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("search", help="row-level search (Python regex)")
    p.add_argument("-i", dest="ignore_case", action="store_true", help="ignore case")
    p.add_argument("pattern")
    p.add_argument("--scope", default="all")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("state", help="open / closed / absent / unknown for one row")
    p.add_argument("project")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("inboxes", help="pending DOCKET-INBOX files with their age")
    p.add_argument("--root", default=None)
    p.add_argument("--scope", default="all")
    p.add_argument("--json", action="store_true")
    for sp in sub.choices.values():
        sp.add_argument("--parent", default=argparse.SUPPRESS, help="directory holding the projects")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if not a.cmd:
        ap.print_usage()
        return 2
    try:
        return {"list": _cmd_list, "search": _cmd_search, "state": _cmd_state,
                "inboxes": _cmd_inboxes}[a.cmd](a)
    except (LookupError, ValueError, re.error) as e:
        print("error: %s" % e, file=sys.stderr)
        return 2


# ---------------------------------------------------------------------------------------
# Selftest: a synthetic multi-project tree, both directions
# ---------------------------------------------------------------------------------------

def _w(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _fixture(tmp):
    parent = tmp / "estate"
    O, R, Y, G = "\U0001F7E0", "\U0001F534", "\U0001F7E1", "\U0001F7E2"
    OK, NO, STOP = "✅", "❌", "⛔"
    c = parent / "central"
    _w(c / "roadmap.md",
       "# Roadmap\n\nIntro prose.\n\n## Next tasks\n\n"
       "- **G#10** %s **CANDIDATE -- alpha widget fails silently** [full row -> roadmap-candidates.md]\n"
       "- **G#11** %s **SHIPPED -- beta gadget**\n"
       "- **G#12** %s **CANDIDATE -- gamma**\n\n"
       "- **G#13** %s **REFUTED -- delta**\n"
       "- **G#14** %s **SHIPPED -- epsilon** [full row -> archive/roadmap-closed-2026-01.md]\n"
       "- **G#15** \U0001F7E3 **odd marker**\n"
       "- **G#16** %s **CANDIDATE -- %s**\n"
       "- **G#17** %s **PARTIAL -- a row whose body carries a table**\n\n"
       "**DECISION PACKET** packet-sentinel\n\n"
       "| Lever | Bytes |\n|---|---|\n| design | 5 lever-cell-sentinel |\n\n"
       "  - **⚠ CONTRADICTION** central-after-table-sentinel\n"
       "- %s **a sibling bullet after the row** central-sibling-sentinel\n"
       % (O, OK, R, NO, OK, Y, "long " * 60, G, OK))
    _w(c / "roadmap-candidates.md",
       "# Candidates\n\nThis file is the BODY.\n\n"
       "- **G#10** %s **CANDIDATE -- alpha widget fails silently** body names the zorblat template "
       "and a quuxfrob-sentinel.\n  - **UPDATE:** continuation-token-xyz lives here.\n" % O)
    _w(c / "archive" / "roadmap-closed-2026-01.md",
       "- **G#14** %s **CANDIDATE -- epsilon** archived-sentinel body.\n"
       "- **G#20** %s **SHIPPED -- only in the archive**\n" % (G, OK))
    _w(c / "archive" / "upgrade-prompts-discontinued" / "roadmap-old.md", "- **G#99** %s x\n" % R)
    _w(c / "archive" / "notes-2026.md", "- **G#98** %s not a docket archive\n" % R)
    _w(c / "HANDOFF.md",
       "# Handoff\n\n- %s **Every deploy.** manual step deploy-sentinel\n\n"
       "## Notes\n\nloose-sentinel prose.\n\n1. **Step one** numbered-list-sentinel\n" % Y)
    _w(c / "SELF-AUDIT.md", "- **2026-01-01 %s miss** selfaudit-sentinel\n" % G)
    _w(c / "DOCKET-INBOX-2026-01-01-alpha.md",
       "# Inbox\n\n## Candidate A -- first\n\ntext\n\n## Candidate B -- second\n\ninbox-sentinel here\n")
    _w(c / "DOCKET-INBOX-2026-01-02-beta.md", "# Inbox\n\n## Candidate A -- untracked-sentinel\n")
    _w(c / "DOCKET-INBOX-2026-01-03-gamma.md", "# Inbox\n\n## Candidate A -- staged-sentinel\n")

    h = parent / "hashproj"
    _w(h / "continuation" / "memory" / "roadmap.md",
       "# Docket\n\n- **#235** %s **DONE 2026-01-01 -- done thing**\n"
       "- **#173 %s SMS consent on the callback form\n"
       "- **#208 \U0001F17F\uFE0F PARKED 2026-01-01 -- parked thing\n"
       "> - **#188(a)** decision-log sub-id\n"
       ">   ⚠️ **still owed** quoted-indented-sentinel\n"
       "> - Tooling: approved as no-input work quoted-plain-sibling-sentinel\n\n"
       "> %s **SESSION LOG -- a new quoted block** quote-sibling-sentinel\n\n"
       "- **#150 %s OPEN a bullet row with a body\n"
       "  %s **sub-point done** hb-indented-sentinel\n"
       "- **%s Sibling item RESOLVED** hb-sibling-sentinel\n"
       "- **#271** %s **RULED 2026-01-05 -- the titles violate the ban; edit deliberately NOT made**\n"
       "- **#272** %s **OPEN -- mirror: a closed glyph with an open word**\n"
       "- **#147 %s wave counter row, still open\n"
       "- **#44** %s **OPEN base row**\n"
       "- **#44b %s check-gold contrast gate**\n"
       "- **#273** %s **CLOSED -- owner answered** [full row → `archive/roadmap-closed-2026-09.md`]"
       "(archive/roadmap-closed-2026-09.md)**\n\n"
       "## Resolved\n\n"
       "| date | item | outcome |\n|---|---|---|\n| 2026-01-02 | #241 widget | %s resolved |\n"
       "| 2026-01-03 (#242 tail) | #242 tail | %s shipped |\n"
       "| 2026-01-04 (session log) | port an article | %s shipped -- #147 wave +1 |\n\n"
       "after-table-sentinel prose.\n\n"
       "## Meta lengths\n\n| chars | page |\n|---|---|\n| 193 | state-page.html chars-sentinel |\n"
       % (OK, G, OK, Y, OK, OK, Y, OK, Y, Y, OK, OK, OK, OK, OK))
    _w(h / "continuation" / "memory" / "archive" / "roadmap-closed-2026-09.md",
       "- **#273** %s **CLOSED -- owner answered** archived-body-sentinel\n" % OK)
    _w(h / "extra" / "notes" / "roadmap.md", "- **#300** %s config-glob-sentinel\n" % Y)
    for bad in (".claude/worktrees/wt1/roadmap.md", "node_modules/pkg/roadmap.md",
                "chrome_profile_1/roadmap.md"):
        _w(h / bad, "- **#301** %s excluded-sentinel\n" % Y)
    _w(h / "HANDOFF.md",
       "# Handoff\n\n## Previously shipped\n\n"
       "- **#145's gate WITHDRAWN in place** hs-id-sentinel\n"
       "- **Sandbox: three design generations** hs-plain-sibling-sentinel\n"
       "  ⚠️ **NOT applied to production.** hs-nested-glyph-sentinel\n")
    _w(h / CONFIG_NAME, json.dumps({"paths": ["**/roadmap.md"]}))

    p = parent / "paraproj"
    _w(p / "continuation" / "memory" / "roadmap.md",
       "**#259 [YELLOW] [A11Y] A keyboard user who tabs para-sentinel\n\n"
       "**#256** %s **CLOSED 2026-01-01** -- closed thing\n\n"
       "**#43 %s CLOSED -- first framing dup-sentinel\n\n"
       "**#43 [YELLOW] second framing dup-sentinel\n\n"
       "**#44** %s blocked or declined\n\n"
       "**#211 [YELLOW] [SEO] on-page audit para-open-sentinel\n\n"
       "**THE BASELINE IS STRONG** baseline-sentinel\n\n"
       "%s **(a) THE FINDING** body-red-sentinel\n\n"
       "| class | n |\n|---|---|\n| procedure | 55 class-cell-sentinel |\n\n"
       "%s **(a) EXECUTED on the owner's grant** body-check-sentinel\n"
       "  %s indented-check-sentinel\n"
       "> %s **NOTE** para-quote-sentinel\n\n"
       "- %s **a bullet inside a paragraph row** para-bullet-sentinel\n\n"
       "%s **(c) 26 descriptions too long**\n"
       "| chars | page | where |\n|---|---|---|\n| 193 | `state-page.html` | %s generated chars-cell-sentinel |\n"
       "**Do the hand-maintained ones first** after-inner-table-sentinel\n\n"
       "**#212** %s **CLOSED** the next row next-row-sentinel\n"
       % (OK, OK, STOP, R, OK, OK, Y, Y, Y, R, OK))

    n = parent / "numproj"
    active = ("226. **%s OPEN (2026-01-01) -- open row numbered-sentinel**\n"
              "223. **%s BUILT 2026-01-01 -- built row**\n"
              "84. **%s (2026-01-01) - the gate's DEFERRED findings.**\n"
              "90. **%s (2026-01-01) - no status word**\n"
              "91. **%s CANDIDATE -- a candidate**\n" % (R, G, O, G, G))
    _w(n / "docs" / "DOCKET-ACTIVE.md",
       active + "59. **%s MERGED to master -- the third review round is STILL OWED**\n" % Y)
    _w(n / "docs" / "DOCKET.md", "| # | What shipped |\n|---|---|\n| 12 | %s resolved ledger row |\n"
       "| 76 | the fix landed in abc123 |\n" % OK)
    _w(n / "HANDOFF.md", "# Handoff\n\n1. **Step one** do a thing\n2. **Step two** another\n")
    _w(n / CONFIG_NAME, json.dumps({"status": {G: "closed"}}))
    _w(n / "archive" / "DOCKET-closed-2026-01.md",
       "86. **%s RESOLVED -- closed row**\n76. **%s SHIPPED + MERGED -- archived body**\n"
       "59. **%s RESOLVED -- a stale archive copy**\n" % (OK, OK, OK))
    _w(n / "archive" / "HANDOFF-history-2026-01.md",
       "# Handoff history\n\n86. **%s OPEN handoff step**\n87. **another step**\n" % R)
    n2 = parent / "numproj2"
    _w(n2 / "docs" / "DOCKET-ACTIVE.md", active)

    a = parent / "alphaproj"
    _w(a / "continuation" / "memory" / "roadmap.md", "- **#81 %s The brand logo\n" % Y)
    _w(a / "continuation" / "memory" / "roadmap_audit_2026-01-01.md",
       "- **A1 %s SHIPPED AND DEPLOYED 2026-01-01**\n- **A2 %s open audit item**\n"
       "- **A3 %s third**\n1. **not a docket id** alpha-local-sentinel\n" % (OK, Y, Y))

    t = parent / "tableproj"
    _w(t / "HANDOFF.md", "| Item | State | Court |\n|---|---|---|\n| **T6** | DONE | theirs |\n")
    _w(t / "bridge" / "UPGRADE-BACKLOG.md",
       "| Item | What | Status |\n|---|---|---|\n"
       "| currency-check hardening | twelve fixes | **DONE** (2026-01-01) |\n"
       "| idea-thing | maybe | IDEA |\n")
    _w(t / CONFIG_NAME, json.dumps({"paths": ["bridge/UPGRADE-BACKLOG.md"]}))

    e = parent / "encproj"
    (e / "roadmap.md").parent.mkdir(parents=True, exist_ok=True)
    (e / "roadmap.md").write_bytes(b"\xef\xbb\xbf" + ("- **#1** %s **OPEN bom-first-row-sentinel**\n" % Y).encode("utf-8"))
    (e / "continuation" / "memory").mkdir(parents=True, exist_ok=True)
    (e / "continuation" / "memory" / "roadmap.md").write_bytes(
        ("- **#5** %s **OPEN utf16-sentinel**\n" % Y).encode("utf-16"))

    ty = parent / "typoproj"
    _w(ty / "roadmap.md", "- **#1** %s typo project row\n" % Y)
    _w(ty / "bridge" / "UPGRADE-BACKLOG.md", "| Item | Status |\n|---|---|\n| thing | backlog-only-sentinel OPEN |\n")
    _w(ty / CONFIG_NAME, json.dumps({"paths": ["bridge/UPGRADE-BACKLOG-typo.md", "notes/*.md"]}))

    _w(parent / "nodocket" / "README.md", "# readme\n")
    _w(parent / "brokencfg" / "roadmap.md", "- **#1** %s broken config row\n" % Y)
    _w(parent / "brokencfg" / CONFIG_NAME, "{not json")
    _w(parent / "sib-wt-x" / "roadmap.md", "- **#5** %s wt-sentinel\n" % Y)
    _w(parent / "linked" / "roadmap.md", "- **#6** %s linked-sentinel\n" % Y)
    _w(parent / "plaindir" / "roadmap.md", "- **#7** %s plain-sentinel\n" % Y)
    for d in ("hashproj", "paraproj", "numproj", "numproj2", "alphaproj", "tableproj",
              "nodocket", "brokencfg", "sib-wt-x", "encproj", "typoproj"):
        (parent / d / ".git").mkdir(parents=True, exist_ok=True)
    _w(parent / "linked" / ".git", "gitdir: elsewhere\n")

    loner = tmp / "loner"
    _w(loner / "roadmap.md", "- **#1** %s loner-sentinel\n" % Y)
    return parent, loner


def _git_init(repo, tmp):
    base = ["git", "-C", str(repo), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=" + str(tmp / "nohooks"), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True,
                   encoding="utf-8", errors="replace")
    subprocess.run(base + ["add", "--", "."], check=True, capture_output=True, encoding="utf-8", errors="replace")
    subprocess.run(base + ["rm", "-q", "--cached", "--", "DOCKET-INBOX-2026-01-02-beta.md",
                           "DOCKET-INBOX-2026-01-03-gamma.md"], check=True,
                   capture_output=True, encoding="utf-8", errors="replace")
    subprocess.run(base + ["commit", "-q", "-m", "init"], check=True, capture_output=True,
                   encoding="utf-8", errors="replace")
    # gamma is STAGED but never committed: the state the index alone reports as tracked.
    subprocess.run(base + ["add", "--", "DOCKET-INBOX-2026-01-03-gamma.md"], check=True, capture_output=True,
                   encoding="utf-8", errors="replace")


def selftest():
    passed = [0]
    failed = [0]

    def check(cond, label, extra=""):
        if cond:
            passed[0] += 1
            print("  PASS %s" % label)
        else:
            failed[0] += 1
            print("  FAIL %s %s" % (label, extra))

    tmp = Path(tempfile.mkdtemp(prefix="docket-corpus-selftest-")).resolve()
    old_cwd = os.getcwd()
    old_env = {k: os.environ.get(k) for k in (ENV_PARENT, "GIT_CEILING_DIRECTORIES")}
    try:
        os.environ.pop(ENV_PARENT, None)
        os.environ["GIT_CEILING_DIRECTORIES"] = str(tmp.parent)
        parent, loner = _fixture(tmp)
        central = parent / "central"
        _git_init(central, tmp)
        os.chdir(str(loner))
        _checkout.cache_clear()
        P = str(parent)

        def ids(res):
            return [h["id"] for h in res]

        def one(res, ident):
            return [h for h in res if h["id"] == ident]

        print("-- projects and scopes --")
        _, listing = projects(P)
        names = [x["name"] for x in listing]
        check("central" in names and "hashproj" in names and "nodocket" in names,
              "child dirs with a .git DIRECTORY are projects", str(names))
        check("sib-wt-x" not in names, "(g) a '*-wt-*' sibling is not a project", str(names))
        check("linked" not in names, "(g) a linked worktree (.git FILE) is not a project", str(names))
        check("plaindir" not in names, "a directory without .git is not a project", str(names))
        check(any(x["name"] == "loner" and x["current"] for x in listing),
              "the current project is included even without git", str(names))
        _, lp = projects(P, cwd=P)
        lp_names = [x["name"] for x in lp]
        check(all(x["name"] != parent.name for x in lp),
              "run from the parent itself, the parent is not listed as a project", str(lp_names))
        check("central" in lp_names and "hashproj" in lp_names,
              "run from the parent itself, the real child projects ARE listed (the absence above is not vacuous)",
              str(lp_names))
        _, here = select("here", P)
        check([x["name"] for x in here] == ["loner"], "scope 'here' is the current project only")
        _, pj = select("project:HASHPROJ", P)
        check([x["name"] for x in pj] == ["hashproj"], "scope 'project:<name>' is case-insensitive")
        _, rt = select("root:%s" % (parent / "numproj"), P)
        check([x["name"] for x in rt] == ["numproj"], "scope 'root:<path>' selects that directory")
        _, two = select("here,project:numproj", P)
        check([x["name"] for x in two] == ["loner", "numproj"], "comma-joined scopes union in order")
        try:
            select("project:nope", P)
            check(False, "an unknown project raises LookupError")
        except LookupError as e:
            check("known:" in str(e), "an unknown project raises LookupError naming the known ones")
        try:
            select("bogus", P)
            check(False, "an unknown scope raises ValueError")
        except ValueError:
            check(True, "an unknown scope raises ValueError")

        print("-- discovery --")
        cfiles = discover(P, "central")
        kinds = {os.path.relpath(f["path"], str(central)).replace("\\", "/"): f["kind"] for f in cfiles}
        check(kinds.get("roadmap.md") == "docket", "central roadmap.md is kind docket", str(kinds))
        check(kinds.get("roadmap-candidates.md") == "roadmap",
              "(a) roadmap-candidates.md is discovered as a body file", str(kinds))
        check(kinds.get("archive/roadmap-closed-2026-01.md") == "archive", "a top-level archive docket is kind archive")
        check(not any("upgrade-prompts-discontinued" in k for k in kinds),
              "an archive SUBDIRECTORY is never searched")
        check("archive/notes-2026.md" not in kinds, "an archive file that is not a docket/handoff is skipped")
        check(kinds.get("HANDOFF.md") == "handoff" and kinds.get("SELF-AUDIT.md") == "self-audit",
              "HANDOFF.md and SELF-AUDIT.md are discovered with their kinds")
        check(kinds.get("DOCKET-INBOX-2026-01-01-alpha.md") == "inbox"
              and kinds.get("DOCKET-INBOX-2026-01-02-beta.md") == "inbox",
              "(h) both inboxes are discovered, including the untracked one")
        grammars = {os.path.basename(f["path"]): f["grammar"] for f in cfiles}
        check(grammars.get("roadmap.md") == "central-g", "the central index's grammar is central-g",
              str(grammars))
        hfiles = [os.path.relpath(f["path"], str(parent / "hashproj")).replace("\\", "/")
                  for f in discover(P, "hashproj")]
        check("extra/notes/roadmap.md" in hfiles,
              "positive control: a docket-corpus.json glob adds a nested file", str(hfiles))
        check(not any(".claude/worktrees" in f for f in hfiles),
              "(g) a file under .claude/worktrees/ is excluded even when a config glob reaches it",
              str(hfiles))
        check(not any("node_modules" in f or "chrome_profile_" in f for f in hfiles),
              "(g) node_modules and chrome_profile_* are excluded", str(hfiles))
        check(hfiles.count("continuation/memory/roadmap.md") == 1,
              "a file reached by two routes is listed once")
        check(is_docket_name("my docket.md") and is_docket_name("my docket.md", strict=True),
              "the space-separated suffix form is a docket name at every level")
        check(is_docket_name("docket_rederivation.md") and not is_docket_name("docket_rederivation.md", strict=True),
              "the prefix form is a docket only outside memory dirs")
        check(not is_docket_name("DOCKET-INBOX-2026-01-01-x.md") and is_docket_name("DOCKET-ACTIVE.md"),
              "an inbox is never a docket; DOCKET-ACTIVE.md is")
        tf = discover(P, "tableproj")
        check(any(f["path"].replace("\\", "/").endswith("bridge/UPGRADE-BACKLOG.md") and f["kind"] == "config"
                  for f in tf), "a docket-corpus.json path adds a file of kind config")
        bc = discover(P, "brokencfg")
        check(any("brokencfg" in e for e in bc.errors), "a malformed docket-corpus.json is reported, not ignored",
              str(bc.errors))
        check(len(bc) == 1, "a malformed config still leaves default discovery working")
        ty = discover(P, "typoproj")
        tyerr = " ".join(ty.errors)
        check("'bridge/UPGRADE-BACKLOG-typo.md' matched nothing" in tyerr,
              "a docket-corpus.json path that names no file is reported as a config error", str(ty.errors))
        check("'notes/*.md' matched nothing" in tyerr,
              "a docket-corpus.json glob that matches no file is reported as a config error", str(ty.errors))
        check(not any("typoproj" in e for e in tf.errors) and not tf.errors,
              "a docket-corpus.json path that DOES match reports no config error (tableproj)", str(tf.errors))
        est2 = tmp / "estate2"
        _w(est2 / "absproj" / "roadmap.md", "- **#2** \U0001F7E1 abs row\n")
        _w(est2 / "absproj" / CONFIG_NAME,
           json.dumps({"paths": [str(tmp / "*.md").replace("\\", "/"), "../*.md"]}))
        _w(est2 / "healthy" / "roadmap.md", "- **#3** \U0001F7E1 healthy-sentinel\n")
        for d in ("absproj", "healthy"):
            (est2 / d / ".git").mkdir(parents=True, exist_ok=True)
        try:
            r2 = search("healthy-sentinel", "all", str(est2))
            check(ids(r2) == ["#3"], "an absolute glob in ONE project's config does not stop an 'all' search",
                  str(ids(r2)))
            check(sum(e.count("is outside the project") for e in r2.errors if e.startswith("absproj:")) == 2,
                  "an absolute or '..' config path is reported as a config error", str(r2.errors))
        except Exception as ex:  # a crash here is the defect under test; report it, never abort
            check(False, "an absolute glob in ONE project's config does not stop an 'all' search", repr(ex))
            check(False, "an absolute or '..' config path is reported as a config error", repr(ex))

        print("-- search: rows, collapse, precedence --")
        r = search("zorblat template", "project:central", P)
        check(ids(r) == ["G#10"], "(a) a term only in a split-out BODY (roadmap-candidates.md) is found", str(ids(r)))
        r = search("alpha widget|quuxfrob-sentinel", "project:central", P)
        g10 = one(r, "G#10")
        check(len(g10) == 1, "(b) stub + body of one id collapse to one hit", str(ids(r)))
        if g10:
            check(g10[0]["path"].replace("\\", "/").endswith("roadmap-candidates.md"),
                  "(b) the collapsed hit points at the body, not the stub", g10[0]["path"])
            check(len(g10[0]["also"]) == 1, "(b) the collapsed stub is listed in 'also'", str(g10[0]["also"]))
        r = search("continuation-token-xyz", "project:central", P)
        check(ids(r) == ["G#10"] and r[0]["head"].startswith("- **G#10**"),
              "a hit on an indented continuation line maps to its enclosing row head", str(list(r)))
        r = search("archived-sentinel", "project:central", P)
        check(ids(r) == ["G#14"] and r[0]["state"] == "closed",
              "an archived body hit carries the INDEX's state, not the archive's stale marker", str(list(r)))
        r = search("long long", "project:central", P)
        check(bool(r) and all(len(h["head"]) <= HEAD_MAX for h in r), "a hit's head is at most 160 chars")
        r = search("loose-sentinel", "project:central", P)
        check(len(r) == 1 and r[0]["grammar"] == "loose" and r[0]["state"] == "unknown",
              "a hit outside any row is still reported (keyed by file:line), never dropped", str(list(r)))
        r = search("deploy-sentinel", "project:central", P)
        check(len(r) == 1 and r[0]["grammar"] == "glyph-first" and r[0]["state"] == "open",
              "a glyph-first handoff bullet is a row keyed by file:line", str(list(r)))
        r = search("inbox-sentinel", "project:central", P)
        check(len(r) == 1 and r[0]["grammar"] == "inbox-block" and r[0]["id"].endswith("-alpha.md#2")
              and r[0]["state"] == "open", "an inbox hit is keyed by file and block index", str(ids(r)))
        r = search("untracked-sentinel", "project:central", P)
        check(len(r) == 1, "(h) the untracked inbox is searched")
        r = search("ZORBLAT", "project:central", P, ignore_case=False)
        check(len(r) == 0, "ignore_case=False is case-sensitive")
        # The positive sibling is UPPERCASE and sits on the same line as 'zorblat': a search
        # that casefolds the LINES still finds a lowercase term, so only an uppercase one
        # proves the case-sensitive mode can match at all.
        r = search("CANDIDATE -- alpha widget", "project:central", P, ignore_case=False)
        check(ids(r) == ["G#10"],
              "ignore_case=False still finds a same-case UPPERCASE term (the zero above is not vacuous)",
              str(ids(r)))

        print("-- search: a row's body stays with its row --")
        for term in ("baseline-sentinel", "body-red-sentinel", "class-cell-sentinel", "body-check-sentinel",
                     "indented-check-sentinel", "para-quote-sentinel", "para-bullet-sentinel",
                     "chars-cell-sentinel", "after-inner-table-sentinel"):
            r = search(term, "project:paraproj", P)
            check(ids(r) == ["#211"] and r[0]["state"] == "open",
                  "(C1) %s inside a paragraph row maps to that row (#211, open)" % term,
                  str([(h["id"], h["state"]) for h in r]))
        r = search("next-row-sentinel", "project:paraproj", P)
        check(ids(r) == ["#212"] and r[0]["state"] == "closed", "(C1) the next id head still starts a new row",
              str(ids(r)))
        for term in ("packet-sentinel", "lever-cell-sentinel", "central-after-table-sentinel"):
            r = search(term, "project:central", P)
            check(ids(r) == ["G#17"], "(C1) %s inside a central row's body (around its table) maps to G#17" % term,
                  str(ids(r)))
        r = search("central-sibling-sentinel", "project:central", P)
        check(len(r) == 1 and r[0]["grammar"] == "glyph-first" and r[0]["state"] == "closed",
              "(C1) a column-0 glyph BULLET after a bullet row is its own sibling row", str(list(r)))
        r = search("hb-indented-sentinel", "project:hashproj", P)
        check(ids(r) == ["#150"] and r[0]["state"] == "open",
              "(C1) an indented glyph line under a bullet row maps to that row", str(ids(r)))
        r = search("hb-sibling-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "glyph-first" and r[0]["state"] == "closed",
              "(C1) a column-0 '- **<glyph>' bullet after a bullet row is its own sibling row", str(list(r)))
        r = search("quote-sibling-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "glyph-first",
              "(C1) a new quoted glyph block after a quoted decision-log bullet is its own row", str(list(r)))
        r = search("quoted-indented-sentinel", "project:hashproj", P)
        check(ids(r) == ["#188(a)"],
              "(C1) an indented line INSIDE the quote ('>   <glyph>') continues the quoted bullet row", str(ids(r)))
        r = search("quoted-plain-sibling-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "loose",
              "(C1) a plain quoted sibling bullet ('> - Tooling:') is not attributed to the id row above it",
              str([(h["id"], h["grammar"]) for h in r]))
        r = search("hs-id-sentinel", "project:hashproj", P)
        check(ids(r) == ["#145"], "(C1) positive control: an id bullet in a handoff is its row", str(ids(r)))
        r = search("hs-plain-sibling-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "loose",
              "(C1) a plain sibling bullet after an id bullet is not attributed to that id",
              str([(h["id"], h["grammar"]) for h in r]))
        r = search("hs-nested-glyph-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "glyph-first",
              "(C1) a glyph line nested under a plain sibling bullet is not attributed to the id above it",
              str([(h["id"], h["grammar"]) for h in r]))
        r = search("owner answered", "project:hashproj", P)
        check(ids(r) == ["#273"] and r[0]["path"].replace("\\", "/").endswith("archive/roadmap-closed-2026-09.md"),
              "(C8) an arrow stub '[full row → `x`](x)**' collapses onto its archived body",
              str([(h["id"], h["rel"]) for h in r]))

        print("-- state --")
        st = lambda proj, i: state(proj, i, P)  # noqa: E731
        check(st("central", "G#10") == "open", "(c) an orange-circle central row is open")
        check(st("central", "G#11") == "closed" and st("central", "G#13") == "closed",
              "central check and cross rows are closed")
        check(st("central", "G#12") == "open", "a red-circle central row is open")
        check(st("central", "G#15") == "unknown", "an unrecognised central marker is unknown")
        check(st("central", "G#14") == "closed", "the index beats a stale archive marker")
        check(st("central", "G#20") == "closed", "an id only in an archive falls back to the archive row")
        check(st("central", "G#999") == "absent", "an id in no file is absent")
        for spelling in ("10", "#10", "G#10", "CENTRAL-10"):
            check(st("central", spelling) == "open", "state() accepts %r" % spelling)
        check(st("hashproj", "G#235") == "absent", "G#N matches only central-style rows")
        check(st("hashproj", "#235") == "closed" and st("hashproj", "235") == "closed",
              "(f) a hash-bullet with a DONE word is closed")
        check(st("hashproj", "#173") == "open", "(f) a hash-bullet with the glyph inside the bold is open")
        check(st("hashproj", "#188(a)") != "absent", "(f) the '> - **#N(a)' decision-log form is a row")
        check(st("hashproj", "#188") == "absent", "(f) a sub-id is not the bare id")
        check(st("hashproj", "#241") == "closed", "(f) a resolved-table row keyed by the #N it cites is closed")
        r = search("after-table-sentinel", "project:hashproj", P)
        check(len(r) == 1 and r[0]["grammar"] == "loose", "prose after a table is not attributed to its last row")
        check(st("paraproj", "#259") == "open", "(e) a hash-para row with a [YELLOW] tag is open")
        check(st("paraproj", "#256") == "closed", "(e) a hash-para CLOSED row is closed")
        check(st("paraproj", "#43") == "unknown", "(e) duplicate heads that disagree read unknown")
        r = search("dup-sentinel", "project:paraproj", P)
        check(len(r) == 1 and len(r[0]["also"]) == 1, "(e) duplicate heads collapse to one hit and are reported")
        check(st("paraproj", "#44") == "unknown", "a no-entry glyph is unknown by default")
        check(st("numproj", "#226") == "open", "(d) a numbered '226. **<red> OPEN' row parses and is open")
        check(st("numproj", "223") == "closed", "(d) a BUILT word closes a green numbered row")
        check(st("numproj", "84") == "open", "(d) a numbered orange row with no status word is open")
        check(st("numproj", "90") == "closed", "(d) green maps to closed under the project's status map")
        check(st("numproj2", "90") == "open", "(d) without a status map green is open")
        # Was "(d) a status WORD beats the project's glyph map" (== open). What it protected: the
        # glyph map's 'closed' must never close a CANDIDATE row. The contradiction now reads unknown,
        # which still never says closed, and no longer says open against the owner's own glyph.
        check(st("numproj", "91") == "unknown",
              "(d) a status WORD that contradicts the project's glyph map reads unknown, never the map's closed")
        check(st("hashproj", "#271") == "unknown",
              "(C3) an open glyph with a CLOSED word ('<yellow> RULED ... NOT made') reads unknown, not closed")
        check(st("hashproj", "#272") == "unknown",
              "(C3) the mirror, a closed glyph with an OPEN word, reads unknown")
        check(st("numproj", "59") == "unknown",
              "(C3) '<yellow> MERGED ... STILL OWED' reads unknown and a stale archive 'closed' does not decide it")
        check(st("numproj", "76") == "closed",
              "(C5) an index row with NO status signal falls through to the archive row that states one")
        check(st("central", "G#14") == "closed" and st("central", "G#15") == "unknown",
              "(C5) fall-through never overrides a stated index state or an unrecognised central marker")
        check(st("hashproj", "147") == "open",
              "(C2) a dated table row citing #N only in its OUTCOME cell is not row #N")
        check(st("hashproj", "193") == "absent",
              "(C2) a numeric first cell under a non-id header ('chars') mints no row id")
        check(st("paraproj", "193") == "absent",
              "(C2) a table inside a row's body mints no row ids")
        check(st("hashproj", "#44b") == "closed" and st("hashproj", "44b") == "closed",
              "(C7) a letter-suffixed sub-id '#44b' is its own row and keeps its glyph state")
        check(st("hashproj", "#44") == "open", "(C7) the base id '#44' is not merged with '#44b'")
        check(st("encproj", "1") == "open", "(C10) a row on line 1 of a UTF-8-with-BOM file is read")
        r = search("utf16-sentinel", "project:encproj", P)
        check(ids(r) == ["#5"] and r[0]["state"] == "open", "(C10) a UTF-16 docket file is decoded and searched",
              str(ids(r)))
        cp = tmp / "cacheproj"
        _w(cp / "roadmap.md", "- **#12** ⚠ **OPEN a row\n")  # 3-byte glyph, like the check mark
        first = state(str(cp), "12", P)
        stt = os.stat(str(cp / "roadmap.md"))
        _w(cp / "roadmap.md", "- **#12** ✅ **DONE a row\n")  # same size, same length word
        os.utime(str(cp / "roadmap.md"), ns=(stt.st_atime_ns, stt.st_mtime_ns))
        st2 = os.stat(str(cp / "roadmap.md"))
        check(first == "open" and st2.st_size == stt.st_size and st2.st_mtime_ns == stt.st_mtime_ns
              and state(str(cp), "12", P) == "closed",
              "(C6) a same-size rewrite with an unchanged mtime is re-read, not served from the cache",
              "first=%s size %d->%d" % (first, stt.st_size, st2.st_size))
        check(st("numproj", "12") == "closed", "a numeric first-cell table row in a docket file is an id")
        check(st("numproj", "1") == "absent", "a numbered list in a HANDOFF is not a docket id")
        check(st("numproj", "86") == "closed",
              "an archived docket row is not contradicted by a numbered step in an archived handoff")
        check(st("numproj", "87") == "absent", "a numbered list in an archived HANDOFF is not a docket id")
        nk = {os.path.basename(f["path"]): f["kind"] for f in discover(P, "numproj")}
        check(nk.get("HANDOFF-history-2026-01.md") == "handoff-archive"
              and nk.get("DOCKET-closed-2026-01.md") == "archive",
              "an archived handoff is kind handoff-archive, an archived docket kind archive", str(nk))
        check(st("hashproj", "#208") == "open", "a status word after an unmapped emoji still reads (PARKED)")
        check(st("hashproj", "#242") == "closed",
              "a resolved-table row whose date cell carries a note still keys by the #N it cites")
        check(st("alphaproj", "A1") == "closed" and st("alphaproj", "a2") == "open",
              "alpha-bullet rows resolve (case-insensitive)")
        check(st("alphaproj", "#81") == "open", "a hash-bullet row beside an audit file still resolves")
        check(st("alphaproj", "1") == "absent", "a numbered line in an alpha-dominant file is not an id")
        check(st("tableproj", "T6") == "closed", "a table row in a handoff resolves by its first cell")
        check(st("tableproj", "currency-check hardening") == "closed",
              "a config-listed table row resolves by item name (bold status)")
        check(st("tableproj", "idea-thing") == "open", "an IDEA status cell is open")
        try:
            state("nope", "1", P)
            check(False, "state() on an unknown project raises LookupError")
        except LookupError:
            check(True, "state() on an unknown project raises LookupError")

        print("-- denominator and inboxes --")
        res = search("sentinel", "all", P)
        check(res.files_searched > 10 and "central" in res.projects and "loner" in res.projects,
              "search carries files searched and projects searched", "%d %s" % (res.files_searched, res.projects))
        check("nodocket" in res.no_docket and "central" not in res.no_docket,
              "projects with no docket are named", str(res.no_docket))
        check(not any(h["id"] for h in res if "wt-sentinel" in h["head"] or "linked-sentinel" in h["head"]),
              "(g) nothing from an excluded sibling reaches an 'all' search")
        check(not any("excluded-sentinel" in h["head"] for h in res),
              "(g) nothing under an excluded tree reaches an 'all' search")
        ib = {os.path.basename(x["path"]): x for x in inboxes(central)}
        check(set(ib) == {"DOCKET-INBOX-2026-01-01-alpha.md", "DOCKET-INBOX-2026-01-02-beta.md",
                          "DOCKET-INBOX-2026-01-03-gamma.md"},
              "(h) inboxes() lists every root inbox", str(sorted(ib)))
        check(ib.get("DOCKET-INBOX-2026-01-01-alpha.md", {}).get("tracked") is True
              and ib.get("DOCKET-INBOX-2026-01-01-alpha.md", {}).get("status") == "committed",
              "(h) the committed inbox is tracked (status committed)")
        check(ib.get("DOCKET-INBOX-2026-01-02-beta.md", {}).get("tracked") is False
              and ib.get("DOCKET-INBOX-2026-01-02-beta.md", {}).get("status") == "untracked",
              "(h) the untracked inbox is listed and marked untracked")
        check(ib.get("DOCKET-INBOX-2026-01-03-gamma.md", {}).get("tracked") is False
              and ib.get("DOCKET-INBOX-2026-01-03-gamma.md", {}).get("status") == "staged",
              "(C4) a STAGED-but-never-committed inbox is not tracked (status staged)",
              str(ib.get("DOCKET-INBOX-2026-01-03-gamma.md")))
        try:
            inboxes(parent / "no-such-root")
            check(False, "(C9) inboxes() on a root that is not a directory raises LookupError")
        except LookupError:
            check(True, "(C9) inboxes() on a root that is not a directory raises LookupError")
        exp = (datetime.date.today() - datetime.date(2026, 1, 1)).days
        check(ib.get("DOCKET-INBOX-2026-01-01-alpha.md", {}).get("age_days") == exp,
              "an inbox's age comes from the date in its name")
        check(inboxes(parent / "nodocket") == [], "a root with no inbox lists nothing")

        print("-- CLI --")
        me = os.path.abspath(__file__)

        def cli(*args):
            rr = subprocess.run([sys.executable, me] + list(args), cwd=str(loner), capture_output=True,
                                encoding="utf-8", errors="replace", timeout=300)
            return rr.returncode, rr.stdout, rr.stderr

        rc, out, err = cli("search", "-i", "ZORBLAT", "--scope", "project:central", "--parent", P)
        check(rc == 0 and "central:G#10" in out, "CLI search -i prints the row id", out[-400:] + err[-400:])
        check(re.search(r"^searched: \d+ file\(s\) in 1 project\(s\): central$", out, re.M) is not None,
              "CLI search prints its denominator line", out[-400:])
        check(re.search(r"^no docket found in: none$", out, re.M) is not None,
              "CLI search prints the no-docket line")
        rc, out, err = cli("list", "--scope", "all", "--parent", P)
        check(rc == 0 and re.search(r"^no docket found in: .*nodocket", out, re.M) is not None,
              "CLI list names projects where no docket was found", out[-400:])
        check(re.search(r"^config error: brokencfg", out, re.M) is not None, "CLI list prints config errors")
        rc, out, err = cli("state", "numproj", "226", "--parent", P)
        check(rc == 0 and out.startswith("numproj:226 open"), "CLI state exits 0 for an open row", out)
        rc, out, err = cli("state", "central", "G#999", "--parent", P)
        check(rc == 1 and "absent" in out, "CLI state exits 1 for an absent row", out)
        rc, out, err = cli("state", "nope", "1", "--parent", P)
        check(rc == 2, "CLI state exits 2 for an unknown project")
        rc, out, err = cli("search", "CANDIDATE -- alpha widget", "--scope", "project:central", "--parent", P)
        check(rc == 0 and "central:G#10" in out,
              "CLI search WITHOUT -i finds a same-case UPPERCASE term (its default mode is not dead)",
              out[-400:] + err[-400:])
        rc, out, err = cli("inboxes", "--scope", "project:central", "--parent", P)
        check(rc == 0 and "UNTRACKED" in out and "STAGED-UNCOMMITTED" in out
              and "checked 1 project root(s); 3 pending inbox file(s)" in out,
              "CLI inboxes lists untracked and staged files with a denominator", out)
        rc, out, err = cli("inboxes", "--root", str(parent / "no-such-root"), "--parent", P)
        check(rc == 2 and "not a directory" in err and "checked" not in out,
              "(C9) CLI inboxes --root <missing dir> exits 2 instead of printing a clean zero", out + err)
        rc, out, err = cli("search", "x", "--scope", "bogus", "--parent", P)
        check(rc == 2 and "unknown scope" in err, "CLI rejects an unknown scope with exit 2")
        rc, out, err = cli("--help")
        check(rc == 0 and all(ord(ch) < 128 for ch in out), "--help is ASCII-only")
    finally:
        os.chdir(old_cwd)
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        _checkout.cache_clear()
        shutil.rmtree(tmp, ignore_errors=True)
    print("selftest: %d passed, %d failed" % (passed[0], failed[0]))
    return 1 if failed[0] else 0


if __name__ == "__main__":
    raise SystemExit(main())
