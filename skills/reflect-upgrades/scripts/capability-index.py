#!/usr/bin/env python
"""capability-index -- find an existing tool by WHAT IT DOES, across every project.

WHY. A general tool gets rebuilt when nobody can find the first copy. A lookup by
FILENAME cannot find it: two projects can build the same capability under two names
(check-production-parity.py, check-deploy-parity.py) and share only a word that a dozen
unrelated tools also carry. This index lists every project's scripts, hooks and skills
with a one-line purpose read from the file's own header, and ranks them by how many
CONCEPTS of a plain-words query they cover. It is generated, never hand-kept.

WHAT IT SEARCHES (the denominator, printed on every run):
  - every child dir of the projects parent whose `.git` is a DIRECTORY and whose name
    does not contain `-wt-` (linked worktrees and worktree-named copies are listed as
    NOT searched, never silently skipped). Parent: --parent, else $CAPINDEX_PARENT, else
    the parent of the current git toplevel (the main worktree's, when run from a linked
    worktree).
  - inside each: `git ls-files` (committed + staged), so untracked caches and ghosts are
    not tools. With --at PROJECT=REF that project is read at REF via ls-tree + cat-file.
  - user roots, when present: ~/.claude/skills, ~/.claude/*.py and
    ~/.claude/catalog/Workflow-recipes.
  - RETIRED tools: files deleted within --retired-days (default 180), read from the
    parent of the deleting commit and labelled retired@<sha8>. They are shown when
    --include-retired is given or when they cover >= 2 concepts of the query.

PURPOSE LADDER (first hit wins): SKILL.md `description:` -> a recipe's first body
paragraph -> Python module docstring -> `#` block after the shebang -> `/* */` or `//`
header -> argparse description= -> `?`. The first sentence is kept; a file-name echo,
a hook-event prefix (moved into kind) and docket ids (moved into ids) are stripped.

HOOK KIND. A script is kind `hook:<Event>` when ~/.claude/settings*.json or a project's
.claude/settings*.json wires it (every byte-identical copy is that hook, wherever it lives),
or when its header opens "<Event> hook", "Claude Code <Event> hook" or "<Event> guard".
Settings are the authority; a changed wiring rebuilds the cache.

CACHE. ~/.claude/run/capability-index.tsv (override with --index). `query` rebuilds it
automatically when it is missing, when any git root's indexed sha differs from the one
recorded, when a user root changed, or when this script changed; `build` forces it.
An --at view is not cached unless --index is given. A build in which git could not read
some root is never served as fresh: the next query retries it.

STATUS AND EXIT CODE (a `status:` line in text, a "status" field in --json):
  0 complete    every root in the denominator was read.
  1 incomplete  git could not read a root (dubious ownership, a corrupt index, an empty
                .git, history it cannot walk): that root is listed under "not searched" with
                git's own message, and a miss there is not an absence. Results cover the rest.
  2 usage error.
  3 invalid     no project was searched at all (no projects parent, or one holding no git
                repo): nothing printed speaks for the estate.

USAGE
    python capability-index.py query "compare production to git"
    python capability-index.py query "compare production to git" --include-retired --json
    python capability-index.py query check-deploy-parity          # a name lookup
    python capability-index.py build
    python capability-index.py query "..." --at myproject=abc1234^ --index /tmp/x.tsv

A keyword miss is never an absence proof: a tool whose header does not say what it does
cannot be found by what it does.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCHEMA = "capindex-2"
FOOTER = "a keyword miss is never an absence proof."
DEFAULT_TOP = 10
RETIRED_DAYS = 180
HDR_LINES = 12
HDR_CAP = 800
PURPOSE_CAP = 200

CODE_EXT = {".py", ".sh", ".bash", ".js", ".mjs", ".cjs", ".ps1", ".pl"}
ROOT_LEVEL_EXT = {".py", ".sh", ".bash", ".ps1", ".pl"}
ALWAYS_SCRIPT_EXT = {".sh", ".bash", ".ps1", ".pl"}
TOOL_DIRS = {"scripts", "tools", "bin", "hooks", ".githooks", "githooks", ".husky", "mutations"}
GITHOOK_DIRS = {".githooks", "githooks", ".husky"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "worktrees",
             ".sync-skills-backup", "fixtures", "vendor", "plugins"}
TEST_DIRS = {"tests", "test"}
TEST_NAME = re.compile(r"^(test[-_].*|.*[-_]test\.[^.]+|.*\.(test|spec)\.[^.]+|conftest\.py)$", re.I)
ARCHIVE_SEG = re.compile(r"archive", re.I)
WT_NAME = re.compile(r"-wt-")
MAIN_RE = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]""")
CODING_RE = re.compile(r"^#.*coding[:=]")
ARGPARSE_RE = re.compile(
    r"ArgumentParser\((?:[^()]|\([^()]*\))*?\bdescription\s*=\s*[rRuU]?(?P<q>'''|\"\"\"|'|\")(?P<d>.*?)(?P=q)",
    re.S)

HOOK_EVENTS = ("PreToolUse", "PostToolUse", "UserPromptSubmit", "Stop", "SubagentStop", "SessionStart",
               "SessionEnd", "Notification", "PreCompact", "PermissionRequest")
_EV = "|".join(HOOK_EVENTS)
DASHES = "(?:--|\u2014|\u2013|-|:)"
HOOK_PREFIX = re.compile(
    r"^(?:(?:Claude\s+Code\s+)?(?P<e1>%s)\s+hook\b(?:\s*\([^)]*\))?|hook\s*[:\-]\s*(?P<e2>%s)\b)\s*%s?\s*"
    % (_EV, _EV, DASHES), re.I)
# "<Event> guard": the kind is a hook either way; the words are stripped only when a separator
# follows ("PreToolUse guard: blocks X"), never from "PreToolUse guard for the shared checkout".
HOOK_GUARD = re.compile(r"^(?:Claude\s+Code\s+)?(?P<e>%s)\s+guard\b(?P<sep>\s*(?::|--|\u2014|\u2013)\s*)?" % _EV,
                        re.I)
NAME_ECHO = re.compile(r"^(?P<n>[\w.\-]+)\s*%s\s+" % DASHES)
ID_TOKEN = r"(?:G#\d+[a-z]?(?:\([a-z0-9]+\))?|(?<![\w#&/])#\d+[a-z]?(?:\([a-z0-9]+\))?)"
ID_RE = re.compile(ID_TOKEN)
ID_PAREN = re.compile(
    r"\(\s*(?:(?:roadmap|docket|row|issue|see|per|cf\.?|from)\s+)?%s(?:\s*(?:,|;|/|&|and)\s*%s)*\s*\)"
    % (ID_TOKEN, ID_TOKEN), re.I)
ID_LEAD = re.compile(r"^%s(?:\s*(?:,|/|&)\s*%s)*\s*[.:;,\-\u2014]*\s*" % (ID_TOKEN, ID_TOKEN))
SEPARATOR = re.compile(r"^[-=*#~_+]{3,}$")
SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[`*_])")

# Concept groups. A query word in a group matches every word of its group. Generic
# developer vocabulary only; extend it when a real lookup misses a real tool.
SYNONYMS = (
    ("compare", "comparison", "parity", "diff", "differ", "difference", "match", "mismatch", "versus",
     "vs", "drift", "behind", "identical", "equal", "reconcile"),
    ("production", "prod", "live", "deploy", "deployed", "deployment", "serve", "served", "serves",
     "serving", "hosted", "publish", "published", "release", "released"),
    ("git", "head", "commit", "committed", "repo", "repository", "blob", "tree", "ref", "sha", "branch",
     "tracked", "history"),
    ("test", "testing", "suite", "selftest", "assert", "assertion"),
    ("lint", "linter", "linting"),
    ("hook", "pretooluse", "posttooluse", "precommit"),
    ("secret", "credential", "token", "password", "apikey", "leak"),
    ("encoding", "utf8", "unicode", "charset", "cp1252", "crlf", "newline"),
    ("search", "find", "lookup", "query", "grep", "locate"),
    ("docket", "roadmap", "backlog", "inbox", "ticket", "issue"),
    ("link", "url", "href", "redirect"),
    ("image", "photo", "picture", "img", "png", "jpg", "jpeg", "webp"),
    ("schema", "jsonld", "structured"),
    ("contrast", "colour", "color", "wcag", "a11y", "accessibility", "accessible"),
    ("mutation", "mutant", "mutate"),
    ("sync", "mirror", "propagate", "copy"),
    ("cache", "cached", "stale", "cachebust"),
    ("summary", "summarise", "summarize", "digest", "brief", "briefing"),
)
STOPWORDS = {"a", "an", "the", "to", "of", "is", "are", "be", "does", "do", "what", "which", "that",
             "this", "it", "its", "for", "and", "or", "in", "on", "with", "by", "from", "if", "whether",
             "check", "checks", "tool", "tools", "script", "scripts", "file", "files", "should", "says"}
WEIGHTS = (("name", 3), ("purpose", 2), ("path", 1), ("hdr", 1))
STATUS_RANK = {"live": 0, "archived": 1, "retired": 2}
COLUMNS = ("project", "path", "kind", "status", "purpose", "ids", "sha", "copies", "note", "hdr")


def stem(w):
    for suf in ("ing", "ed", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w2 = w[:-len(suf)]
            if suf in ("ing", "ed") and len(w2) >= 4 and w2[-1] == w2[-2] and w2[-1] not in "aeiouls":
                w2 = w2[:-1]
            return w2
    return w


def words(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]


STEM_GROUP = {}
GROUP_STEMS = []
for _gi, _grp in enumerate(SYNONYMS):
    GROUP_STEMS.append({stem(w) for w in _grp})
    for _w in _grp:
        STEM_GROUP.setdefault(stem(_w), _gi)


# --------------------------------------------------------------------------- #
# git
# --------------------------------------------------------------------------- #

def git_text(root, *args, timeout=300):
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false"] + list(args),
                       capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def git_bytes(root, *args, stdin=None, timeout=300):
    r = subprocess.run(["git", "-C", str(root), "-c", "core.quotePath=false"] + list(args),
                       input=stdin, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr.decode("utf-8", "replace")


class GitFailed(Exception):
    """git could not read a root (or part of it). Never read as "this root has no tools"."""


def first_line(err, rc):
    lines = [ln.strip() for ln in (err or "").splitlines() if ln.strip()]
    fatal = [ln for ln in lines if ln.lower().startswith(("fatal", "error"))]
    return (fatal or lines or ["exit %d, no message" % rc])[0][:200]


def rev_parse(root, ref):
    rc, out, _ = git_text(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
    return out.strip() if rc == 0 and out.strip() else None


def same_dir(a, b):
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def git_root_problem(d):
    """None when git reads `d` as ITS OWN repo; otherwise why not.

    A non-zero exit (dubious ownership, a corrupt or empty .git) is a failure, and so is a
    toplevel that is not `d`: an empty `.git` inside a parent repo makes `git -C d` answer
    for the PARENT, whose files would then be indexed under this project's name."""
    rc, out, err = git_text(d, "rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        return "git could not read this repo: " + first_line(err, rc)
    if not same_dir(out.strip(), d):
        return "git resolves to %s, not this dir" % out.strip()
    return None


def cat_blobs(root, specs):
    """Read many `<rev>:<path>` blobs in one git process. Missing ones map to None."""
    res = {}
    if not specs:
        return res
    rc, out, err = git_bytes(root, "cat-file", "--batch", stdin=("\n".join(specs) + "\n").encode("utf-8"))
    if rc != 0:
        raise GitFailed("git cat-file failed: " + first_line(err, rc))
    pos = 0
    for spec in specs:
        nl = out.find(b"\n", pos)
        if nl < 0:
            res[spec] = None
            continue
        header = out[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(header) != 3 or header[1] != "blob":
            res[spec] = None
            continue
        size = int(header[2])
        res[spec] = out[pos:pos + size]
        pos += size + 1
    return res


# --------------------------------------------------------------------------- #
# Roots and the projects parent
# --------------------------------------------------------------------------- #

def derive_parent(arg):
    if arg:
        return Path(arg).resolve(), "--parent"
    env = os.environ.get("CAPINDEX_PARENT")
    if env:
        return Path(env).resolve(), "$CAPINDEX_PARENT"
    rc, out, _ = git_text(os.getcwd(), "rev-parse", "--show-toplevel")
    if rc != 0 or not out.strip():
        return None, "not inside a git repo (pass --parent or set CAPINDEX_PARENT)"
    top = Path(out.strip())
    if (top / ".git").is_file():
        rc2, common, _ = git_text(top, "rev-parse", "--git-common-dir")
        if rc2 == 0 and common.strip():
            c = Path(common.strip())
            if not c.is_absolute():
                c = (top / c)
            top = c.resolve().parent
    return top.resolve().parent, "parent of the current git toplevel"


def home_dir():
    return Path(os.environ.get("CAPINDEX_HOME") or Path.home())


def discover_roots(parent, home, no_user):
    roots, not_searched = [], []
    if parent is not None and parent.is_dir():
        for child in sorted(parent.iterdir(), key=lambda p: p.name.casefold()):
            if not child.is_dir():
                continue
            name = child.name
            if WT_NAME.search(name):
                not_searched.append((name, "worktree-named dir"))
                continue
            dotgit = child / ".git"
            if dotgit.is_dir():
                roots.append({"project": name, "dir": child, "type": "git"})
            elif dotgit.is_file():
                not_searched.append((name, ".git is a file (linked worktree)"))
            else:
                not_searched.append((name, "no .git"))
    elif parent is not None:
        not_searched.append((str(parent), "projects parent is not a directory"))
    if no_user:
        not_searched.append(("user roots", "--no-user-roots"))
        return roots, not_searched
    c = home / ".claude"
    for label, project, d, mode in (("~/.claude/skills", "~/.claude/skills", c / "skills", "skills"),
                                    ("~/.claude/*.py", "~/.claude", c, "toplevel-py"),
                                    ("~/.claude/catalog/Workflow-recipes", "~/.claude/catalog/Workflow-recipes",
                                     c / "catalog" / "Workflow-recipes", "recipes")):
        if d.is_dir():
            roots.append({"project": project, "dir": d, "type": "user", "mode": mode, "label": label})
        else:
            not_searched.append((label, "absent"))
    return roots, not_searched


# --------------------------------------------------------------------------- #
# Which files are tools
# --------------------------------------------------------------------------- #

def classify_path(rel):
    """None (not a tool), 'skill', 'tool' (by location) or 'entry' (only if it has an entry point)."""
    parts = rel.split("/")
    name, dirs = parts[-1], [d.lower() for d in parts[:-1]]
    if any(d in SKIP_DIRS for d in dirs):
        return None
    if name == "SKILL.md":
        return "skill"
    ext = os.path.splitext(name)[1].lower()
    if ext not in CODE_EXT:
        if ext == "" and not name.startswith(".") and any(d in GITHOOK_DIRS or d == "hooks" for d in dirs):
            return "tool"
        return None
    if any(d in TEST_DIRS for d in dirs):
        if "mutations" in dirs and not TEST_NAME.match(name):
            return "tool"
        if name.startswith(("lint-", "lint_")):
            return "tool"
        return None
    if TEST_NAME.match(name):
        return None
    if any(d in TOOL_DIRS for d in dirs):
        return "tool"
    if not dirs and ext in ROOT_LEVEL_EXT:
        return "tool"
    return "entry"


def is_entry(text, ext):
    if ext in ALWAYS_SCRIPT_EXT:
        return True
    if text.startswith("#!"):
        return True
    return ext == ".py" and MAIN_RE.search(text) is not None


def kind_of(rel, cat, text):
    parts = rel.split("/")
    name, dirs = parts[-1], [d.lower() for d in parts[:-1]]
    ext = os.path.splitext(name)[1].lower()
    if cat == "skill":
        return "skill"
    if name.endswith(".workflow.js"):
        return "workflow"
    if "mutations" in dirs:
        return "mutation"
    if any(d in TEST_DIRS for d in dirs) and name.startswith("lint"):
        return "lint"
    if any(d in GITHOOK_DIRS for d in dirs):
        return "githook"
    if "hooks" in dirs:
        return "hook"
    if ext == ".py" and not text.startswith("#!") and not MAIN_RE.search(text):
        return "lib"
    return "script"


def status_of(rel):
    return "archived" if any(ARCHIVE_SEG.search(d) for d in rel.split("/")[:-1]) else "live"


# --------------------------------------------------------------------------- #
# Purpose extraction
# --------------------------------------------------------------------------- #

def split_frontmatter(text):
    if not text.startswith("---"):
        return "", text
    lines = text.splitlines()
    for k in range(1, len(lines)):
        if lines[k].strip() == "---":
            return "\n".join(lines[1:k]), "\n".join(lines[k + 1:])
    return "", text


def fm_field(fm, key):
    lines = fm.splitlines()
    for i, ln in enumerate(lines):
        m = re.match(r"^%s\s*:\s*(.*)$" % re.escape(key), ln)
        if not m:
            continue
        val = m.group(1).strip()
        if val in ("", ">", "|", ">-", "|-", ">+", "|+"):
            cont = []
            for ln2 in lines[i + 1:]:
                if ln2.strip() and not ln2.startswith((" ", "\t")):
                    break
                cont.append(ln2.strip())
            return "\n".join(cont).strip()
        if val[:1] in ("'", '"'):
            q = val[0]
            if len(val) >= 2 and val.endswith(q):
                return val[1:-1]
            cont = [val[1:]]
            for ln2 in lines[i + 1:]:
                s = ln2.strip()
                if s.endswith(q):
                    cont.append(s[:-1])
                    break
                cont.append(s)
            return "\n".join(cont)
        return val
    return ""


def md_body_after_heading(body):
    """The first section that carries prose: headings with nothing under them yet are passed over."""
    out = []
    for ln in body.splitlines():
        s = ln.strip()
        if s.startswith("#"):
            if any(x.strip() for x in out):
                break
            out = []
            continue
        if s.startswith("<!--"):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def py_docstring(lines, j):
    if j >= len(lines):
        return None
    m = re.match(r"^\s*[rRuUbBfF]{0,2}(\"\"\"|''')(.*)$", lines[j])
    if not m:
        return None
    q, rest = m.group(1), m.group(2)
    if q in rest:
        return rest[:rest.index(q)]
    buf = [rest]
    for ln in lines[j + 1:]:
        if q in ln:
            buf.append(ln[:ln.index(q)])
            return "\n".join(buf)
        buf.append(ln)
    return "\n".join(buf)


def strip_hash(lines):
    return "\n".join(re.sub(r"^\s*#+ ?", "", ln) for ln in lines)


def hash_block(lines, i):
    while i < len(lines) and not lines[i].strip():
        i += 1
    block = []
    while i < len(lines) and lines[i].lstrip().startswith("#"):
        if not CODING_RE.match(lines[i].strip()):
            block.append(lines[i])
        i += 1
    return strip_hash(block)


def header_block(text, rel):
    """(source, raw header text) following the purpose ladder."""
    name = rel.split("/")[-1]
    ext = os.path.splitext(name)[1].lower()
    if ext == ".md":
        fm, body = split_frontmatter(text)
        desc = fm_field(fm, "description")
        if desc:
            return "description", desc
        if name == "SKILL.md":
            return "", ""
        return "body", md_body_after_heading(body)
    lines = text.splitlines()
    i = 1 if lines and lines[0].startswith("#!") else 0
    if ext == ".py":
        j, comments = i, []
        while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#")):
            if lines[j].strip() and not CODING_RE.match(lines[j].strip()):
                comments.append(lines[j])
            j += 1
        doc = py_docstring(lines, j)
        if doc is not None and doc.strip():
            return "docstring", doc
        if comments:
            return "comment", strip_hash(comments)
        m = ARGPARSE_RE.search(text)
        if m and m.group("d").strip():
            return "argparse", m.group("d")
        return "", ""
    if ext in (".js", ".mjs", ".cjs"):
        while i < len(lines) and (not lines[i].strip() or re.match(r"""^\s*['"]use strict['"];?\s*$""", lines[i])):
            i += 1
        if i < len(lines) and lines[i].lstrip().startswith("/*"):
            buf = []
            for ln in lines[i:]:
                s = ln.strip()
                end = "*/" in s
                s = s.split("*/")[0]
                s = re.sub(r"^/\*+!?", "", s)
                s = re.sub(r"^\*+ ?", "", s)
                buf.append(s)
                if end:
                    break
            return "comment", "\n".join(buf)
        buf = []
        while i < len(lines) and lines[i].lstrip().startswith("//"):
            buf.append(re.sub(r"^\s*//+ ?", "", lines[i]))
            i += 1
        return ("comment", "\n".join(buf)) if buf else ("", "")
    if ext == ".ps1":
        k = i
        while k < len(lines) and not lines[k].strip():
            k += 1
        if k < len(lines) and lines[k].lstrip().startswith("<#"):
            buf = []
            for ln in lines[k:]:
                end = "#>" in ln
                buf.append(ln.replace("<#", "").split("#>")[0])
                if end:
                    break
            return "comment", "\n".join(buf)
    block = hash_block(lines, i)
    return ("comment", block) if block.strip() else ("", "")


def norm_name(s):
    s = s.lower()
    s = re.sub(r"\.(py|sh|bash|js|mjs|cjs|ps1|pl|md)$", "", s)
    return s.replace("_", "-")


def paragraphs(block):
    paras, cur = [], []
    for ln in block.splitlines():
        s = ln.strip()
        if SEPARATOR.match(s):
            s = ""
        if not s:
            if cur:
                paras.append(" ".join(cur))
                cur = []
            continue
        cur.append(s)
    if cur:
        paras.append(" ".join(cur))
    return [re.sub(r"\s+", " ", p).strip() for p in paras if p.strip()]


def strip_prefixes(p, names, kind):
    for _ in range(2):
        m = NAME_ECHO.match(p)
        if m and norm_name(m.group("n")) in names:
            p = p[m.end():]
        m = HOOK_PREFIX.match(p)
        if m:
            ev = (m.group("e1") or m.group("e2") or "").lower()
            canon = [e for e in HOOK_EVENTS if e.lower() == ev]
            if canon:
                kind = "hook:" + canon[0]
            p = p[m.end():]
        m = HOOK_GUARD.match(p)
        if m:
            canon = [e for e in HOOK_EVENTS if e.lower() == m.group("e").lower()]
            if canon:
                kind = "hook:" + canon[0]
            if m.group("sep"):
                p = p[m.end():]
    return p.strip(), kind


def clean_ids(p):
    ids = ID_RE.findall(p)
    p = ID_PAREN.sub("", p)
    p = ID_LEAD.sub("", p)
    p = re.sub(r"\s+([.,;:?!])(?=\s|$)", r"\1", p)
    p = re.sub(r"\(\s*\)", "", p)
    return re.sub(r"\s+", " ", p).strip(), ids


def sentences(p):
    return [s.strip() for s in SENT_END.split(p) if s.strip()]


def too_thin(s):
    ws = s.split()
    if len(ws) <= 4:
        return True
    if re.match(r"^runnable for \[\[", s, re.I):
        return True
    alpha = [w for w in ws if w[:1].isalpha()]
    return len(ws) <= 6 and bool(alpha) and all(w[:1].isupper() for w in alpha) and s[-1:] not in ".!?"


def purpose_of(block, rel, kind):
    """-> (purpose, ids, kind, hdr)"""
    parts = rel.split("/")
    base = parts[-2] if parts[-1] == "SKILL.md" and len(parts) > 1 else parts[-1]
    names = {norm_name(base), norm_name(os.path.splitext(base)[0])}
    nonblank = [ln.strip() for ln in block.splitlines() if ln.strip()]
    hdr = " ".join(nonblank[:HDR_LINES])[:HDR_CAP]
    paras = paragraphs(block)
    ids, pool = [], []
    for p in paras:
        p, kind = strip_prefixes(p, names, kind)
        p, found = clean_ids(p)
        ids.extend(found)
        if p and norm_name(p.rstrip(".:")) not in names:
            pool.append(sentences(p))
    purpose = ""
    if pool:
        first = pool[0]
        purpose = first[0]
        nxt = first[1] if len(first) > 1 else (pool[1][0] if len(pool) > 1 else "")
        if nxt and too_thin(purpose):
            sep = " " if purpose[-1:] in ".!?:" else ". "
            purpose = purpose + sep + nxt
    if len(purpose) > PURPOSE_CAP:
        purpose = purpose[:PURPOSE_CAP - 3].rsplit(" ", 1)[0] + "..."
    seen, uniq = set(), []
    for i in ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    return (purpose or "?"), " ".join(uniq), kind, hdr


def make_row(project, rel, cat, data, status, note=""):
    text = data.decode("utf-8", "replace").lstrip("\ufeff")
    kind = kind_of(rel, cat, text)
    _src, block = header_block(text, rel)
    purpose, ids, kind, hdr = purpose_of(block, rel, kind)
    digest = hashlib.sha256(data).hexdigest()
    return {"project": project, "path": rel, "kind": kind, "status": status, "purpose": purpose,
            "ids": ids, "sha": digest[:12], "copies": [], "note": note, "hdr": hdr, "_digest": digest}


# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #

def user_files(root):
    d, mode = root["dir"], root["mode"]
    out = []
    if mode == "skills":
        for sk in sorted(d.iterdir(), key=lambda p: p.name.casefold()):
            if not sk.is_dir() or sk.name.startswith(".") or sk.name in SKIP_DIRS:
                continue
            if (sk / "SKILL.md").is_file():
                out.append((sk.name + "/SKILL.md", "skill"))
            for sub in ("scripts", "hooks"):
                sd = sk / sub
                if sd.is_dir():
                    for f in sorted(sd.iterdir(), key=lambda p: p.name.casefold()):
                        if f.is_file() and f.suffix.lower() in CODE_EXT and not TEST_NAME.match(f.name):
                            out.append(("%s/%s/%s" % (sk.name, sub, f.name), "tool"))
    elif mode == "toplevel-py":
        for f in sorted(d.iterdir(), key=lambda p: p.name.casefold()):
            if f.is_file() and f.suffix.lower() == ".py" and not TEST_NAME.match(f.name):
                out.append((f.name, "tool"))
    elif mode == "recipes":
        for f in sorted(d.iterdir(), key=lambda p: p.name.casefold()):
            if not f.is_file() or TEST_NAME.match(f.name):
                continue
            low = f.name.lower()
            if low.endswith(".md") and low not in ("_index.md", "readme.md"):
                out.append((f.name, "recipe"))
            elif f.suffix.lower() in (".js", ".mjs", ".cjs", ".py"):
                out.append((f.name, "tool"))
    return out


def user_fingerprint(root):
    h = hashlib.sha256()
    for rel, _cat in user_files(root):
        try:
            st = (root["dir"] / rel).stat()
        except OSError:
            continue
        h.update(("%s\0%d\0%d\n" % (rel, st.st_size, st.st_mtime_ns)).encode("utf-8"))
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Hook wiring: settings.json is the authority on which scripts are hooks
# --------------------------------------------------------------------------- #

WIRED_EXT = re.compile(r"\.(?:py|sh|bash|js|mjs|cjs|ps1|pl)$", re.I)
QUOTED = re.compile(r'"([^"]*)"|\'([^\']*)\'')
TOKEN_SPLIT = re.compile(r"[\s\"'`;|&<>()=]+")
PROJECT_VAR = re.compile(r"\$\{CLAUDE_PROJECT_DIR\}|\$CLAUDE_PROJECT_DIR\b|%CLAUDE_PROJECT_DIR%|\$\{ROOT\}|\$ROOT\b")
HOME_VAR = re.compile(r"\$\{HOME\}|\$HOME\b|%USERPROFILE%")
MSYS_DRIVE = re.compile(r"^/([a-zA-Z])/")
SETTINGS_FILES = ("settings.json", "settings.local.json")


def hook_commands(cfg):
    """(event, command text incl. args) for every command hook in one settings object."""
    hooks = cfg.get("hooks") if isinstance(cfg, dict) else None
    if not isinstance(hooks, dict):
        return
    for event, entries in hooks.items():
        for entry in entries if isinstance(entries, list) else []:
            for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
                if not isinstance(h, dict):
                    continue
                args = h.get("args") if isinstance(h.get("args"), list) else []
                yield event, " ".join([str(h.get("command") or "")] + ['"%s"' % a for a in args])


def wired_paths(text, base, home):
    """Candidate script paths named in one hook command: every quoted string (a path may hold
    spaces) and every shell word ending in a script extension. Over-generation is harmless --
    the caller keeps only candidates that exist. `base` is the project dir (None for user
    settings, where a project-relative path cannot be resolved and is skipped)."""
    toks = [g for m in QUOTED.finditer(text) for g in m.groups() if g and WIRED_EXT.search(g)]
    toks += [t for t in TOKEN_SPLIT.split(text) if t and WIRED_EXT.search(t)]
    for tok in dict.fromkeys(toks):
        if PROJECT_VAR.search(tok):
            if base is None:
                continue
            tok = PROJECT_VAR.sub(lambda _m: str(base).replace("\\", "/"), tok)
        tok = HOME_VAR.sub(lambda _m: str(home).replace("\\", "/"), tok)
        if tok.startswith("~"):
            tok = str(home).replace("\\", "/") + tok[1:]
        tok = MSYS_DRIVE.sub(lambda mm: mm.group(1).upper() + ":/", tok)
        p = Path(tok)
        if not p.is_absolute():
            if base is None:
                continue
            p = Path(base) / tok
        yield p


def collect_wiring(roots, home):
    """{sha256 of a wired script: [events]} from ~/.claude and every readable git root's
    .claude/settings*.json. Identical bytes anywhere in the index are then the same hook."""
    sources = [(home / ".claude" / f, None) for f in SETTINGS_FILES]
    for r in roots:
        if r["type"] == "git" and not r.get("failed"):
            sources.extend((r["dir"] / ".claude" / f, r["dir"]) for f in SETTINGS_FILES)
    wiring = {}
    for path, base in sources:
        try:
            cfg = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, ValueError):
            continue  # an absent or unreadable settings file wires nothing; it only labels kinds
        for event, text in hook_commands(cfg):
            for p in wired_paths(text, base, home):
                if os.path.splitext(p.name)[1].lower() not in CODE_EXT:
                    continue
                try:
                    dg = hashlib.sha256(p.read_bytes()).hexdigest()
                except OSError:
                    continue
                evs = wiring.setdefault(dg, [])
                if event not in evs:
                    evs.append(event)
    return {k: sorted(v) for k, v in wiring.items()}


def wiring_fingerprint(wiring):
    h = hashlib.sha256()
    for dg in sorted(wiring):
        h.update(("%s:%s\n" % (dg, ",".join(wiring[dg]))).encode("utf-8"))
    return h.hexdigest()[:16]


def git_root_rows(root, days, wiring=None):
    """Rows for one git root at its resolved sha. Returns (rows, files_enumerated).

    A git failure marks the root failed (root["failed"]) and returns no rows: the root is then
    reported as NOT searched, never as a project that has no tools."""
    d, project, sha, ref = root["dir"], root["project"], root["sha"], root["ref"]
    if root.get("failed"):
        return [], 0
    rows = []
    if ref == "HEAD":
        rc, out, err = git_bytes(d, "ls-files", "-z")
        if rc != 0:
            root["failed"] = "git ls-files failed: " + first_line(err, rc)
            return [], 0
        # during a merge conflict ls-files lists a path once per stage: one file, one name
        names = list(dict.fromkeys(n for n in out.decode("utf-8", "replace").split("\0") if n))
        cands = [(n, classify_path(n)) for n in names]
        cands = [(n, c) for n, c in cands if c]
        blobs = {}
        for n, _c in cands:
            try:
                blobs[n] = (d / n).read_bytes()
            except OSError:
                blobs[n] = None
    else:
        rc, out, err = git_bytes(d, "ls-tree", "-r", "-z", "--name-only", sha)
        if rc != 0:
            root["failed"] = "git ls-tree failed: " + first_line(err, rc)
            return [], 0
        names = [n for n in out.decode("utf-8", "replace").split("\0") if n]
        cands = [(n, classify_path(n)) for n in names]
        cands = [(n, c) for n, c in cands if c]
        try:
            got = cat_blobs(d, ["%s:%s" % (sha, n) for n, _c in cands])
        except GitFailed as e:
            root["failed"] = str(e)
            return [], 0
        blobs = {n: got.get("%s:%s" % (sha, n)) for n, _c in cands}
    for n, c in cands:
        data = blobs.get(n)
        if data is None:
            continue
        ext = os.path.splitext(n)[1].lower()
        if c == "entry" and not is_entry(data.decode("utf-8", "replace").lstrip("\ufeff"), ext) \
                and hashlib.sha256(data).hexdigest() not in (wiring or {}):
            continue  # not a tool -- unless a settings.json wires it as a hook
        rows.append(make_row(project, n, c, data, status_of(n)))
    if sha and days > 0:
        rows.extend(retired_rows(root, set(names), days))
    return rows, len(names)


def retired_rows(root, live_names, days):
    d, project, sha = root["dir"], root["project"], root["sha"]
    fmt = "%x1e%H%x1f%s%x1f%b%x1d"
    rc, out, err = git_text(d, "log", sha, "-M", "--diff-filter=D", "--name-only",
                            "--since=%d days ago" % days, "--format=" + fmt)
    if rc != 0:
        root["retired_failed"] = "git log failed: " + first_line(err, rc)
        return []
    picks = []
    seen = set()
    for chunk in out.split("\x1e"):
        if "\x1d" not in chunk:
            continue
        head, rest = chunk.split("\x1d", 1)
        fields = head.split("\x1f")
        if len(fields) < 3:
            continue
        commit, subject, body = fields[0], fields[1], fields[2]
        trailer = re.search(r"^Upgrade:[ \t]*(\S.*)$", body, re.M)
        for n in rest.strip().splitlines():
            n = n.strip()
            if not n or n in seen or n in live_names:
                continue
            c = classify_path(n)
            if not c:
                continue
            seen.add(n)
            note = "retired by %s %s" % (commit[:8], subject)
            if trailer:
                note += " | Upgrade: " + trailer.group(1).strip()
            picks.append((n, c, commit, note))
    try:
        got = cat_blobs(d, ["%s^:%s" % (commit, n) for n, _c, commit, _note in picks])
    except GitFailed as e:
        root["retired_failed"] = str(e)
        return []
    rows = []
    for n, c, commit, note in picks:
        data = got.get("%s^:%s" % (commit, n))
        if data is None:
            continue
        ext = os.path.splitext(n)[1].lower()
        if c == "entry" and not is_entry(data.decode("utf-8", "replace").lstrip("\ufeff"), ext):
            continue
        rows.append(make_row(project, n, c, data, "retired@" + commit[:8], note))
    return rows


MEMBER_KEYS = ("project", "path", "kind", "status")


def member(r):
    return {k: r[k] for k in MEMBER_KEYS}


def fold_copies(rows):
    """Identical live bytes in several places become ONE row that names the other copies.

    Every other copy is kept on the row as a member {project, path, kind, status}, so a
    --project/--kind filter or a name lookup can still reach a copy that is not the
    representative (the fold key, a content digest, is coarser than those lookup keys)."""
    live = [r for r in rows if not r["status"].startswith("retired")]
    groups = {}
    for r in live:
        groups.setdefault(r["_digest"], []).append(r)
    folded = 0
    keep = []
    for r in rows:
        if r["status"].startswith("retired"):
            keep.append(r)
            continue
        grp = groups[r["_digest"]]
        if len(grp) == 1:
            keep.append(r)
            continue
        # status FIRST: a live copy always represents its group, so a lookup never reports a
        # live tool only as "archived" (which a reader takes as "do not reuse").
        grp.sort(key=lambda x: (STATUS_RANK[status_class(x["status"])], x["_rootrank"],
                                x["project"].casefold(), x["path"]))
        if grp[0] is r:
            r["copies"] = [member(o) for o in grp[1:]]
            keep.append(r)
        else:
            folded += 1
    return keep, folded


# --------------------------------------------------------------------------- #
# State, build and cache
# --------------------------------------------------------------------------- #

def tool_digest():
    try:
        return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
    except OSError:
        return "unknown"


def parse_at(specs):
    at = {}
    for s in specs or []:
        if "=" not in s:
            raise SystemExit("usage: --at PROJECT=REF (got %r)" % s)
        p, ref = s.split("=", 1)
        at[p.strip().casefold()] = ref.strip()
    return at


def resolve_state(args):
    parent, how = derive_parent(args.parent)
    home = home_dir()
    roots, not_searched = discover_roots(parent, home, args.no_user_roots)
    at = parse_at(args.at)
    known = {r["project"].casefold(): r for r in roots if r["type"] == "git"}
    unknown = [p for p in at if p not in known]
    if unknown:
        print("capability-index: unknown project in --at: %s (git roots: %s)"
              % (", ".join(sorted(unknown)), ", ".join(sorted(r["project"] for r in known.values())) or "none"),
              file=sys.stderr)
        raise SystemExit(2)
    if parent is None:
        # the whole project estate went unsearched: say so where every skipped root is named
        not_searched.insert(0, ("projects parent", how))
    for r in roots:
        if r["type"] == "git":
            ref = at.get(r["project"].casefold(), "HEAD")
            problem = git_root_problem(r["dir"])
            if problem:
                if r["project"].casefold() in at:
                    print("capability-index: cannot read %s for --at: %s" % (r["project"], problem), file=sys.stderr)
                    raise SystemExit(2)
                r["ref"], r["sha"], r["failed"] = ref, "", problem
                continue
            sha = rev_parse(r["dir"], ref)
            if sha is None and ref != "HEAD":
                print("capability-index: cannot resolve %s=%s" % (r["project"], ref), file=sys.stderr)
                raise SystemExit(2)
            r["ref"], r["sha"] = ref, sha or ""
        else:
            r["fingerprint"] = user_fingerprint(r)
    return {"parent": parent, "parent_how": how, "home": home, "roots": roots, "not_searched": not_searched,
            "at": at, "retired_days": args.retired_days, "wiring": collect_wiring(roots, home)}


def state_meta(state):
    return {
        "schema": SCHEMA, "tool": tool_digest(),
        "parent": str(state["parent"]) if state["parent"] else None,
        "retired_days": state["retired_days"],
        "wiring": wiring_fingerprint(state.get("wiring") or {}),
        "roots": [{"project": r["project"], "dir": str(r["dir"]), "type": r["type"],
                   "ref": r.get("ref", ""), "sha": r.get("sha", ""), "fingerprint": r.get("fingerprint", ""),
                   "failed": r.get("failed", ""), "retired_failed": r.get("retired_failed", "")}
                  for r in state["roots"]],
        "not_searched": [[a, b] for a, b in state["not_searched"]],
    }


def build_rows(state):
    t0 = time.time()
    rows, files = [], 0
    for rank, r in enumerate(state["roots"]):
        if r["type"] == "git":
            rr, n = git_root_rows(r, state["retired_days"], state.get("wiring"))
        else:
            rr = []
            listed = user_files(r)
            n = len(listed)
            for rel, cat in listed:
                try:
                    data = (r["dir"] / rel).read_bytes()
                except OSError:
                    continue
                row = make_row(r["project"], rel, cat, data, status_of(rel))
                if cat == "recipe":
                    row["kind"] = "recipe"
                rr.append(row)
        for row in rr:
            row["_rootrank"] = (0 if r["type"] == "git" else 1, rank)
        rows.extend(rr)
        files += n
    wiring = state.get("wiring") or {}
    for row in rows:
        # settings.json is the authority: identical bytes to a wired script ARE that hook
        if row["_digest"] in wiring and not row["status"].startswith("retired"):
            row["kind"] = "hook:" + "+".join(wiring[row["_digest"]])
    rows, folded = fold_copies(rows)
    meta = state_meta(state)
    meta.update({
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"), "build_seconds": round(time.time() - t0, 2),
        "files_enumerated": files, "copies_folded": folded,
    })
    return rows, meta


def clean_cell(s):
    if isinstance(s, list):
        # copies: a JSON list, never a space-joined string (project names contain spaces)
        s = json.dumps(s, separators=(",", ":"), ensure_ascii=False) if s else ""
    return re.sub(r"[\t\r\n]+", " ", str(s))


def parse_copies(cell):
    if isinstance(cell, list):
        return cell
    if not cell:
        return []
    v = json.loads(cell)
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise ValueError("copies cell is not a list of objects")
    return v


def write_index(path, rows, meta):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["#capindex-meta\t" + json.dumps(meta, sort_keys=True), "\t".join(COLUMNS)]
    for r in rows:
        lines.append("\t".join(clean_cell(r.get(c, "")) for c in COLUMNS))
    tmp = path.with_name(path.name + ".tmp%d" % os.getpid())
    try:
        tmp.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
        os.replace(str(tmp), str(path))
    except OSError:
        # a concurrent reader holding the cache open (Windows) must not strand a full-size copy
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path.stat().st_size


def read_index(path):
    meta, rows, header = None, [], None
    for line in Path(path).read_bytes().decode("utf-8", "replace").splitlines():
        if line.startswith("#capindex-meta\t"):
            meta = json.loads(line.split("\t", 1)[1])
            continue
        if line.startswith("#") or not line.strip():
            continue
        cells = line.split("\t")
        if header is None:
            header = cells
            continue
        r = dict(zip(header, cells))
        r["copies"] = parse_copies(r.get("copies", ""))
        rows.append(r)
    return meta, rows


def stale_reason(meta, state):
    if meta is None:
        return "cache has no meta line"
    cur = state_meta(state)
    if meta.get("schema") != cur["schema"]:
        return "schema changed"
    if meta.get("tool") != cur["tool"]:
        return "capability-index.py changed"
    if meta.get("wiring") != cur["wiring"]:
        return "hook wiring changed"
    if meta.get("parent") != cur["parent"]:
        return "projects parent changed"
    if meta.get("retired_days") != cur["retired_days"]:
        return "retired window changed"
    bad = [r["project"] for r in meta.get("roots", []) if r.get("failed") or r.get("retired_failed")]
    if bad:
        # A partial build is never served as fresh: the failed root's HEAD may not move for weeks.
        return "git could not read %s at the last build -- retrying" % ", ".join(bad)
    old = {(r["project"], r["type"]): r for r in meta.get("roots", [])}
    new = {(r["project"], r["type"]): r for r in cur["roots"]}
    if set(old) != set(new):
        added = sorted(p for p, _t in set(new) - set(old))
        gone = sorted(p for p, _t in set(old) - set(new))
        return "roots changed (+%s -%s)" % (",".join(added) or "none", ",".join(gone) or "none")
    moved = [k[0] for k in sorted(new) if (old[k].get("ref"), old[k].get("sha"), old[k].get("failed", ""))
             != (new[k].get("ref"), new[k].get("sha"), new[k].get("failed", ""))]
    if moved:
        return "HEAD moved (or git can no longer read it): " + ", ".join(moved)
    changed = [k[0] for k in sorted(new) if old[k].get("fingerprint") != new[k].get("fingerprint")]
    if changed:
        return "user root changed: " + ", ".join(changed)
    return None


def default_index(home):
    return home / ".claude" / "run" / "capability-index.tsv"


def obtain(args, state, force=False):
    """-> (rows, meta, cache_info)"""
    explicit = args.index is not None
    path = Path(args.index) if explicit else default_index(state["home"])
    if state["at"] and not explicit:
        rows, meta = build_rows(state)
        return rows, meta, {"path": None, "action": "not written", "reason": "--at view (pass --index to cache it)"}
    reason = "forced (build)" if force else None
    meta = None
    rows = []
    if not force:
        if not path.is_file():
            reason = "no cache at %s" % path
        else:
            try:
                meta, rows = read_index(path)
                reason = stale_reason(meta, state)
            except (OSError, ValueError) as e:
                reason = "cache unreadable (%s)" % e
    if reason is None:
        return rows, meta, {"path": str(path), "action": "fresh", "reason": "every root at its recorded revision"}
    rows, meta = build_rows(state)
    action = "built" if force else "rebuilt"
    try:
        size = write_index(path, rows, meta)
    except OSError as e:
        # A concurrent reader can hold the file on Windows. The lookup still answers from
        # the rows just built; the cache simply is not refreshed this time, and says so.
        return rows, meta, {"path": str(path), "action": action + " (NOT written: %s)" % e, "reason": reason}
    meta["index_bytes"] = size
    return rows, meta, {"path": str(path), "action": action, "reason": reason, "bytes": size}


# --------------------------------------------------------------------------- #
# Query
# --------------------------------------------------------------------------- #

def parse_query(q):
    groups, seen = [], {}
    for w in words(q):
        if w in STOPWORDS:
            continue
        s = stem(w)
        gi = STEM_GROUP.get(s)
        key = ("g", gi) if gi is not None else ("w", s)
        if key in seen:
            continue
        seen[key] = len(groups)
        groups.append({"label": w, "stems": GROUP_STEMS[gi] if gi is not None else {s},
                       "words": list(SYNONYMS[gi]) if gi is not None else [w]})
    return groups


def row_name(r):
    parts = r["path"].split("/")
    return parts[-2] if parts[-1] == "SKILL.md" and len(parts) > 1 else parts[-1]


def candidates(r):
    """The representative first, then every folded copy -- each as {project, path, kind, status}."""
    return [member(r)] + list(r.get("copies") or [])


def view(r, cand):
    """The row as seen from one of its copies: that copy's project/path/kind/status, the others as copies."""
    cands = candidates(r)
    if cand == cands[0]:
        return r
    v = dict(r)
    v.update(cand)
    v["copies"] = [c for c in cands if c != cand]
    return v


def field_index(r):
    cands = candidates(r)
    fields = {
        "name": " ".join(row_name(c) for c in cands),
        "purpose": r.get("purpose", ""),
        "path": " ".join(" ".join(c["path"].split("/")[:-1]) + " " + c["project"] for c in cands),
        "hdr": r.get("hdr", ""),
    }
    out = {}
    for k, text in fields.items():
        surf = {}
        for w in words(text):
            surf.setdefault(stem(w), w)
        out[k] = surf
    return out


def status_class(status):
    return "retired" if status.startswith("retired") else status


def score_capability(rows, groups, include_retired):
    res = []
    for r in rows:
        fi = field_index(r)
        hit, score, matched = 0, 0, {}
        for g in groups:
            best, found = 0, set()
            for fname, wgt in WEIGHTS:
                inter = set(fi[fname]) & g["stems"]
                if inter:
                    best = max(best, wgt)
                    found.update(fi[fname][s] for s in inter)
            if best:
                hit += 1
                score += best
                matched[g["label"]] = sorted(found)
        if not hit:
            continue
        if status_class(r["status"]) == "retired" and not (include_retired or hit >= 2):
            continue
        res.append(dict(r, groups_hit=hit, groups_total=len(groups), score=score, matched=matched))
    res.sort(key=lambda x: (-x["groups_hit"], -x["score"], STATUS_RANK[status_class(x["status"])],
                            x["project"].casefold(), x["path"]))
    return res


def score_name(rows, q):
    """Name lookup over EVERY copy of a folded group; the best-matching copy is the one printed."""
    qn = norm_name(q.strip())
    res = []
    for r in rows:
        best = None
        for c in r.get("_cands") or candidates(r):
            n = norm_name(row_name(c))
            exact = 0 if n == qn else (1 if qn in n else None)
            if exact is not None and (best is None or exact < best[0]):
                best = (exact, c)
        if best is None:
            continue
        exact, c = best
        v = view(r, c)
        res.append(dict(v, groups_hit=1, groups_total=1, score=2 - exact, matched={"name": [row_name(c)]}))
    res.sort(key=lambda x: (-x["score"], STATUS_RANK[status_class(x["status"])], x["project"].casefold(), x["path"]))
    return res


def is_name_query(q):
    q = q.strip()
    return bool(re.fullmatch(r"[\w.\-]+", q)) and any(c in q for c in "-_.")


def cand_matches(c, args):
    if getattr(args, "kind", None) and not c["kind"].startswith(args.kind):
        return False
    if getattr(args, "project", None) and c["project"].casefold() != args.project.casefold():
        return False
    return True


def filter_rows(rows, args):
    """--kind/--project match ANY copy of a folded group, and the row is then shown from the
    first matching copy. Filtering only the representative hid a project's own tools whenever
    their bytes also lived in an earlier-ranked project."""
    if not (getattr(args, "kind", None) or getattr(args, "project", None)):
        return rows
    out = []
    for r in rows:
        ok = [c for c in candidates(r) if cand_matches(c, args)]
        if not ok:
            continue
        v = dict(view(r, ok[0]))
        v["_cands"] = ok
        out.append(v)
    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def failures(state):
    """(root label, reason) for every root -- or part of one -- that git could not read."""
    out = []
    for r in state["roots"]:
        if r.get("failed"):
            out.append((r["project"], r["failed"]))
        elif r.get("retired_failed"):
            out.append((r["project"] + " (retired pass)", r["retired_failed"]))
    return out


def not_searched_all(state):
    return list(state["not_searched"]) + failures(state)


def run_status(state):
    """-> (status, exit code). INVALID: no project was searched, so nothing -- a hit or a miss --
    speaks for the estate. INCOMPLETE: git could not read some root; a miss there is no absence."""
    if not any(r["type"] == "git" and not r.get("failed") for r in state["roots"]):
        return "invalid", 3
    if failures(state):
        return "incomplete", 1
    return "complete", 0


def status_line(state):
    st, _rc = run_status(state)
    if st == "invalid":
        return ("status: INVALID -- no project was searched (see 'not searched'); this answer covers the "
                "user roots at most")
    if st == "incomplete":
        return ("status: INCOMPLETE -- git could not read %d root(s): %s; a miss there is not an absence"
                % (len(failures(state)), ", ".join(p for p, _r in failures(state))))
    return "status: complete"


def denominator(rows, meta, state):
    git_n = sum(1 for r in state["roots"] if r["type"] == "git" and not r.get("failed"))
    user_n = sum(1 for r in state["roots"] if r["type"] == "user")
    classes = [status_class(r["status"]) for r in rows]
    return {
        "parent": str(state["parent"]) if state["parent"] else None,
        "parent_how": state["parent_how"],
        "roots_searched": git_n + user_n, "git_roots": git_n, "user_roots": user_n,
        "files_enumerated": meta.get("files_enumerated"),
        "rows": len(rows), "live": classes.count("live"), "archived": classes.count("archived"),
        "retired": classes.count("retired"), "copies_folded": meta.get("copies_folded"),
        "purpose_unknown": sum(1 for r in rows if r.get("purpose") == "?"),
        "retired_days": state["retired_days"],
    }


def revisions(state):
    out = []
    for r in state["roots"]:
        if r["type"] == "git":
            if r.get("failed"):
                continue  # not searched: listed with its reason, never with a revision
            out.append({"project": r["project"], "type": "git", "ref": r["ref"], "sha": r["sha"]})
        else:
            out.append({"project": r["project"], "type": "user", "ref": "", "sha": r.get("fingerprint", "")})
    return out


def footer_lines(den, revs, not_searched, cache, status=None):
    out = []
    if status:
        out.append(status)
    if cache:
        if cache.get("path"):
            out.append("cache: %s -- %s (%s)" % (cache["action"], cache["path"], cache["reason"]))
        else:
            out.append("cache: %s -- %s" % (cache["action"], cache["reason"]))
    out.append("denominator: %d roots searched (%d git, %d user) under %s; %s files enumerated; %d tool rows "
               "(%d live, %d archived, %d retired within %d days); %s identical copies folded; %d with no "
               "extractable purpose"
               % (den["roots_searched"], den["git_roots"], den["user_roots"],
                  den["parent"] or "UNKNOWN projects parent (%s)" % den["parent_how"],
                  den["files_enumerated"], den["rows"], den["live"], den["archived"], den["retired"],
                  den["retired_days"], den["copies_folded"], den["purpose_unknown"]))
    parts = []
    for v in revs:
        if v["type"] == "git":
            if v["ref"] == "HEAD":
                parts.append("%s HEAD %s" % (v["project"], v["sha"][:8] if v["sha"] else "(no commits)"))
            else:
                parts.append("%s @%s %s" % (v["project"], v["ref"], v["sha"][:8]))
    if parts:
        out.append("revisions (tracked files; HEAD roots read from the working tree): " + " | ".join(parts))
    out.append("not searched (%d): %s" % (len(not_searched),
                                           " | ".join("%s -- %s" % (a, b) for a, b in not_searched) or "none"))
    out.append(FOOTER)
    return out


def print_results(q, mode, groups, res, top, den, revs, not_searched, cache, status=None):
    if mode == "name":
        print('capability-index: "%s" -- name lookup (describe what the tool DOES, in words, for a capability '
              'lookup)' % q)
    else:
        print('capability-index: "%s" -- capability lookup over %d concept(s): %s'
              % (q, len(groups), "; ".join("%s{%s}" % (g["label"], ",".join(g["words"][:6])) for g in groups)))
    for i, r in enumerate(res[:top], 1):
        print("%2d. %s  %s  [%s, %s]  %d/%d concepts" % (i, r["project"], r["path"], r["kind"], r["status"],
                                                          r["groups_hit"], r["groups_total"]))
        print("      %s" % r["purpose"])
        m = "  ".join("%s=%s" % (k, ",".join(v)) for k, v in r["matched"].items())
        extra = ("   ids: %s" % r["ids"]) if r.get("ids") else ""
        print("      matched: %s%s" % (m, extra))
        if r.get("copies"):
            print("      identical copies: %s" % " | ".join("%s:%s" % (c["project"], c["path"]) for c in r["copies"]))
        if r.get("note"):
            print("      %s" % r["note"])
    if not res:
        print("  (no row matched)")
    elif len(res) > top:
        print("(showing %d of %d matching rows; --top N for more)" % (top, len(res)))
    for ln in footer_lines(den, revs, not_searched, cache, status):
        print(ln)


def public_row(r, rank):
    keep = ("project", "path", "kind", "status", "purpose", "ids", "copies", "note", "groups_hit", "groups_total",
            "score", "matched")
    d = {k: r.get(k) for k in keep}
    d["copies"] = [dict(c) for c in (r.get("copies") or [])]
    d["rank"] = rank
    return d


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_build(args):
    state = resolve_state(args)
    t0 = time.time()
    rows, meta, cache = obtain(args, state, force=True)
    den = denominator(rows, meta, state)
    revs = revisions(state)
    elapsed = round(time.time() - t0, 2)
    status, rc = run_status(state)
    if args.json:
        print(json.dumps({"status": status, "cache": cache, "build_seconds": elapsed, "denominator": den,
                          "revisions": revs,
                          "not_searched": [{"root": a, "reason": b} for a, b in not_searched_all(state)],
                          "footer": FOOTER}, indent=2))
        return rc
    print("capability-index: built %d rows in %.2fs%s" % (len(rows), elapsed,
                                                          (", %d bytes" % cache["bytes"]) if cache.get("bytes") else ""))
    for ln in footer_lines(den, revs, not_searched_all(state), cache, status_line(state)):
        print(ln)
    return rc


def cmd_query(args):
    state = resolve_state(args)
    rows, meta, cache = obtain(args, state)
    den = denominator(rows, meta, state)
    revs = revisions(state)
    q = args.text
    mode = "name" if (args.name or (is_name_query(q) and not args.capability)) else "capability"
    pool = filter_rows(rows, args)
    if mode == "name":
        groups = []
        res = score_name(pool, q)
    else:
        groups = parse_query(q)
        res = score_capability(pool, groups, args.include_retired) if groups else []
    status, rc = run_status(state)
    if args.json:
        print(json.dumps({
            "query": q, "mode": mode, "status": status,
            "groups": [{"label": g["label"], "words": g["words"]} for g in groups],
            "results": [public_row(r, i) for i, r in enumerate(res[:args.top], 1)],
            "matching": len(res), "shown": min(len(res), args.top),
            "cache": cache, "denominator": den, "revisions": revs,
            "not_searched": [{"root": a, "reason": b} for a, b in not_searched_all(state)],
            "footer": FOOTER}, indent=2))
        return rc
    print_results(q, mode, groups, res, args.top, den, revs, not_searched_all(state), cache, status_line(state))
    return rc


def main(argv=None):
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--parent", help="projects parent dir (default: $CAPINDEX_PARENT, else the parent of "
                                         "the current git toplevel)")
    common.add_argument("--index", help="cache file (default: ~/.claude/run/capability-index.tsv)")
    common.add_argument("--at", action="append", metavar="PROJECT=REF",
                        help="index PROJECT's tree at REF instead of its working tree (repeatable)")
    common.add_argument("--retired-days", type=int, default=RETIRED_DAYS,
                        help="window for the retired pass, in days (0 disables it; default %d)" % RETIRED_DAYS)
    common.add_argument("--no-user-roots", action="store_true", help="skip the ~/.claude user roots")
    common.add_argument("--json", action="store_true", help="machine-readable output")
    ap = argparse.ArgumentParser(
        prog="capability-index.py",
        description="Find an existing tool by what it does, across every project's scripts, hooks and "
                    "skills. A keyword miss is never an absence proof.")
    sub = ap.add_subparsers(dest="cmd")
    sub.required = True
    b = sub.add_parser("build", parents=[common], help="rebuild the index now")
    b.set_defaults(func=cmd_build)
    q = sub.add_parser("query", parents=[common], help="rank tools against a plain-words capability")
    q.add_argument("text", help='what the tool does, in 3-6 words (e.g. "compare production to git"), or a '
                                'file name for a name lookup')
    q.add_argument("--top", type=int, default=DEFAULT_TOP, help="rows to show (default %d)" % DEFAULT_TOP)
    q.add_argument("--include-retired", action="store_true",
                   help="show every matching retired tool (default: only those covering >= 2 concepts)")
    q.add_argument("--kind", help="only rows whose kind starts with this (script, lib, hook, skill, ...)")
    q.add_argument("--project", help="only rows from this project")
    q.add_argument("--name", action="store_true", help="force a file-name lookup")
    q.add_argument("--capability", action="store_true", help="force a capability lookup")
    q.set_defaults(func=cmd_query)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
