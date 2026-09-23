#!/usr/bin/env python
"""merge-check.py -- catch the damage a resolved git merge can do silently.

A merge is judged "done" when git stops complaining and the suite is green. Both
signals miss the same class of damage:

  * a conflict resolved by LINE RANGE can split a test function, leaving a test
    that still passes but no longer asserts the behaviour it is named for;
  * a resolution can drop one side's test entirely, or keep a function twice so
    the second definition silently shadows the first;
  * two branches can each allocate the same id in an append-only registry
    (a docket, a changelog, a migration list). Git merges the two rows WITHOUT a
    conflict, because they are different lines -- so this one arrives on a clean
    merge too;
  * a leftover conflict marker;
  * in a handoff or docket file, a fact restated on BOTH sides. These files record
    current state, so they are not append-only: when one machine's unpushed commit
    changed a row and the other machine's later wrap re-stated the older state on a
    different line, git merges both lines without a conflict and the merged file
    states the fact two ways. The rule is that the later FACT date wins -- when the
    recorded event happened, not when a line or commit was written -- and each side's
    NEW items survive.

This tool compares the merge RESULT against both parents (and their merge base)
and reports each of those as one line:

    FINDING <kind> <path>: <detail>

Kinds: conflict-marker, lost-test, shrunk-test, duplicate-def, duplicate-id,
result-unparseable (a .py result that does not parse while both parents do --
the orphaned fragment a line-range splice leaves behind), restated-fact,
reverted-fact and lost-item.

restated-fact, reverted-fact and lost-item apply only to handoff/docket files:
HANDOFF*.md, DOCKET*.md (not DOCKET-INBOX filings), roadmap*.md and context.md. A
line STATES a row id when the id is its row id ('- **#12**', '| **G#12') or the
only id it mentions ('docket 12', 'row 12' and '#12' are one key). A numbered list
line ('2. **...**') is a list position, not an id. An id's statements are a
MULTISET of lines: a verbatim copy of a base row carried forward into another
section is a second statement, and a stale restatement is most often exactly that.

  restated-fact  the id is stated in the merge base and both sides changed its
                 statements, differently. The tool cannot read a fact date: a date in
                 the text may be the day the line was written, and commit order is not
                 the rule. So every restated id is a finding -- whichever statement the
                 result kept -- printed with each side's own statement lines and the
                 commit that wrote each, until it is re-derived from live source and
                 accepted.
  reverted-fact  the id is stated in the merge base, one side changed its statements
                 (edited, added a line about it, or deleted it) and the result states it
                 exactly as the merge base: a resolution that took the other side's hunk
                 reverted that side's newer fact.
  lost-item      a side's NEW item did not survive. An item is a ROW: an id absent
                 from the merge base that one side added a row for, and the result has
                 no row for (a row the resolution RENUMBERED or edited survives); an id
                 both sides minted rows for, different work (a collision), where the
                 result keeps only one side's row. It is reported under the dropped
                 row's OWN id, never under the ids that row cites. A prose line naming
                 a new id is not an item -- its '#N' can be a finding number, and a
                 resolution that edits the line can drop it -- so an id one side names
                 only on new prose lines is lost only when the result names it nowhere.

Rotated archives of these files (under an 'archive' directory, or with a YYYY-MM date
in the name, e.g. archive/HANDOFF-history-2026-09.md, roadmap-closed-2026-09.md) hold
verbatim records, not current state: they are append-only, so there is no
restated-fact or reverted-fact there, and every row record each side appended must
survive (lost-item); prose there is checked by mention, as in a live file.

The denominator line also counts the new or changed handoff/docket lines that state
no single row id. The tool cannot tell whether those lines restate a fact -- a fact
restated on id-less prose lines merges silently -- so the count says how many lines
to read (UNKNOWN when a handoff/docket file could not be read at all).

A row id counts as a duplicate only when it appears at least twice in the result
AND at most once in each of base, ours and theirs: an id that was never unique
(a '1.' ordered list, a '- **3 files**' count) is not behaving as a registry key.
An id token must end at the bold close, whitespace, ':' + non-digit, or the end
of the line, so dates, versions and times ('2026-09-16', '1.4.0', '10:12') are
never read as ids.

A deliberate, documented test drop, a restated or reverted fact that was re-derived
from live source, or a deliberately dropped item is accepted with --accept PATH::NAME
(repeatable; NAME is the test name or the row id such as '#179'). A matching
lost-test, shrunk-test, restated-fact, reverted-fact or lost-item finding prints

    ACCEPTED <kind> <path>: <name>

instead of FINDING and does not affect the exit status. An --accept that matches
no finding prints "UNUSED --accept <path>::<name>" and makes the run exit 1, so a
stale or mistyped accept cannot silently pass.

When any version of a .py file does not parse, every version falls back to a
regex extractor and the shrunk-test check cannot run; that is announced as

    NOTE shrunk-test skipped for <path>: <versions> do(es) not parse

Only files changed on BOTH sides since the merge base are checked (a file changed
on one side only is taken verbatim and cannot be damaged by a resolution). Binary
files and files over 2 MB are skipped and counted on their own line.

Modes (auto-detected):
  in-progress  a merge is in progress: ours=HEAD, theirs=MERGE_HEAD,
               result=the working tree
  head         HEAD is a two-parent merge commit: ours=HEAD^1, theirs=HEAD^2,
               result=HEAD
  commit       --commit <sha> checks that two-parent merge commit

Exit status: 0 clean, 1 at least one (unaccepted) finding or an unused --accept,
2 usage error (including "not in a merge state" and a malformed --accept).
Standard library only.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from collections import Counter

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2

MAX_BYTES = 2 * 1024 * 1024
MODULE = "<module>"

PY_EXTS = {".py"}
JS_EXTS = {".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"}
GD_EXTS = {".gd"}
REGISTRY_EXTS = {".md", ".markdown", ".mdx", ".txt", ".rst"}

DENOMINATOR_FMT = ("checked %d files (%d test files, %d registry files, %d handoff/docket "
                   "files); findings: %d; handoff/docket lines stating no single row id: %s "
                   "(new or changed; merge-check cannot tell whether they restate a fact -- "
                   "read them)")


class UsageError(Exception):
    pass


# --------------------------------------------------------------------------- git

def git(repo, *args, input_bytes=None):
    """Run git; return (rc, stdout_bytes, stderr_text)."""
    proc = subprocess.run(["git", "-C", repo] + list(args),
                          input=input_bytes, capture_output=True)
    return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", "replace")


def git_text(repo, *args):
    rc, out, err = git(repo, *args)
    if rc != 0:
        raise UsageError("git %s failed: %s" % (" ".join(args), err.strip()))
    return out.decode("utf-8", "replace").strip()


def verify(repo, ref):
    rc, out, _ = git(repo, "rev-parse", "-q", "--verify", ref + "^{commit}")
    return out.decode().strip() if rc == 0 else None


def parents_of(repo, sha):
    line = git_text(repo, "rev-list", "--parents", "-n", "1", sha)
    return line.split()[1:]


def empty_tree(repo):
    rc, out, err = git(repo, "hash-object", "-t", "tree", "--stdin", input_bytes=b"")
    if rc != 0:
        raise UsageError("cannot compute the empty tree id: %s" % err.strip())
    return out.decode().strip()


def changed_paths(repo, a, b):
    rc, out, err = git(repo, "diff", "--name-only", "--no-renames", "-z", a, b)
    if rc != 0:
        raise UsageError("git diff %s %s failed: %s" % (a, b, err.strip()))
    return {p for p in out.decode("utf-8", "replace").split("\0") if p}


def read_blob(repo, sha, path):
    if sha is None:
        return None
    rc, out, _ = git(repo, "cat-file", "blob", "%s:%s" % (sha, path))
    return out if rc == 0 else None


def read_worktree(top, path):
    full = os.path.join(top, *path.split("/"))
    if not os.path.isfile(full):
        return None
    with open(full, "rb") as fh:
        return fh.read()


def resolve(repo, mode, commit):
    """Return dict(mode, ours, theirs, result) where result is a sha or None
    (None = the working tree). Raises UsageError when not in a merge state."""
    if commit:
        if mode not in ("auto", "commit"):
            raise UsageError("--commit cannot be combined with --mode %s" % mode)
        sha = verify(repo, commit)
        if not sha:
            raise UsageError("--commit %s does not name a commit" % commit)
        ps = parents_of(repo, sha)
        if len(ps) != 2:
            raise UsageError("commit %s has %d parent(s); a two-parent merge commit is required"
                             % (sha[:12], len(ps)))
        return {"mode": "commit", "ours": ps[0], "theirs": ps[1], "result": sha}

    merge_head = verify(repo, "MERGE_HEAD")
    head = verify(repo, "HEAD")
    if mode in ("auto", "in-progress") and merge_head:
        if not head:
            raise UsageError("MERGE_HEAD exists but HEAD does not resolve")
        return {"mode": "in-progress", "ours": head, "theirs": merge_head, "result": None}
    if mode == "in-progress":
        raise UsageError("no merge in progress (MERGE_HEAD is absent)")
    if head:
        ps = parents_of(repo, head)
        if len(ps) == 2:
            return {"mode": "head", "ours": ps[0], "theirs": ps[1], "result": head}
        why = "HEAD has %d parent(s), not 2" % len(ps)
    else:
        why = "HEAD does not resolve"
    raise UsageError("not in a merge state: no merge in progress and %s "
                     "(use --commit <sha> to check an earlier merge commit)" % why)


# ------------------------------------------------------------------ text helpers

def decode(data):
    if data is None:
        return None
    text = data.decode("utf-8", "replace")
    if text.startswith("﻿"):
        text = text[1:]
    return text


def split_lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def is_binary(data):
    return data is not None and b"\0" in data[:8192]


# ------------------------------------------------------------------ python defs

_PY_DEF_RE = re.compile(r"^([ \t]*)(?:async[ \t]+)?def[ \t]+(\w+)[ \t]*\(")
_PY_CLASS_RE = re.compile(r"^([ \t]*)class[ \t]+(\w+)\b")


def py_defs_ast(text):
    """[(scope, name, statement_count)] for functions at module or class scope
    (classes nest; functions nested in functions are not collected)."""
    tree = ast.parse(text)
    out = []

    def walk(body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                n = sum(1 for x in ast.walk(node) if isinstance(x, ast.stmt)) - 1
                out.append((scope, node.name, n))
            elif isinstance(node, ast.ClassDef):
                walk(node.body, node.name if scope == MODULE else scope + "." + node.name)

    walk(tree.body, MODULE)
    return out


def py_defs_regex(text):
    """Indentation-stack fallback with the same (scope, name) shape as the AST
    walk; statement counts are unknown (None)."""
    out = []
    stack = []  # (indent, kind, name)
    for line in split_lines(text):
        c = _PY_CLASS_RE.match(line)
        d = _PY_DEF_RE.match(line)
        m = d or c
        if not m:
            continue
        ind = len(m.group(1).expandtabs(8))
        while stack and stack[-1][0] >= ind:
            stack.pop()
        if d:
            if all(kind == "class" for _, kind, _ in stack):
                scope = ".".join(name for _, _, name in stack) or MODULE
                out.append((scope, d.group(2), None))
            stack.append((ind, "def", d.group(2)))
        else:
            stack.append((ind, "class", c.group(2)))
    return out


def parse_error(text):
    """None when text parses as Python, else a one-line description of the error."""
    try:
        ast.parse(text)
        return None
    except SyntaxError as e:
        return "line %s: %s" % (e.lineno if e.lineno is not None else "?", e.msg)
    except ValueError as e:  # e.g. source containing a null byte
        return str(e) or e.__class__.__name__


def py_defs_all(texts):
    """texts: {label: text or None}. Uses the AST for every version when every
    present version parses, else the regex fallback for ALL of them, so the
    name sets being compared always come from the same extractor.
    Returns ({label: defs or None}, used_ast, {label: error} for the versions
    that do not parse)."""
    errors = {k: parse_error(v) for k, v in texts.items() if v is not None}
    errors = {k: e for k, e in errors.items() if e is not None}
    if not errors:
        return ({k: (py_defs_ast(v) if v is not None else None) for k, v in texts.items()},
                True, errors)
    return ({k: (py_defs_regex(v) if v is not None else None) for k, v in texts.items()},
            False, errors)


def qualify(scope, name):
    return name if scope == MODULE else scope + "." + name


# ------------------------------------------------------------ js / gd extractors

_JS_TEST_RE = re.compile(
    r"(?<![\w$.])(?:it|test)(?:\.(?:only|skip|todo|concurrent|failing))*\s*\(\s*"
    r"(['\"`])((?:\\.|(?!\1)[^\\])*)\1", re.S)
_JS_DEF_RE = re.compile(
    r"^(?:export[ \t]+(?:default[ \t]+)?)?(?:async[ \t]+)?function[ \t]*\*?[ \t]*"
    r"([A-Za-z_$][\w$]*)[ \t]*\(", re.M)
_GD_TEST_RE = re.compile(r"^[ \t]*(?:static[ \t]+)?func[ \t]+(test_\w*)[ \t]*\(", re.M)
_GD_DEF_RE = re.compile(r"^(?:static[ \t]+)?func[ \t]+(\w+)[ \t]*\(", re.M)


def regex_defs(rx, text):
    return [(MODULE, m.group(1), None) for m in rx.finditer(text)]


# ------------------------------------------------------------------ registry ids

# An id ends at the bold close, whitespace, ':' + non-digit, or end of line --
# never in '-', '.', or ':' + digit, which would make '2026-09-16', '1.4.0' and
# '10:12' read as the ids '2026', '1' and '10'.
_ID = r"(G#\d+|#\d+|\d+)(?=\*\*|\s|:(?!\d)|$)"
# - **#12**   - <one glyph> **G#12**   - **12** text
_BULLET_ROW_RE = re.compile(r"^[ \t]*[-*+][ \t]+(?:[^\s\w*]\S*[ \t]+)?\*\*" + _ID)
# | **#303 title | ...
_TABLE_ROW_RE = re.compile(r"^[ \t]*\|[ \t]*\*\*" + _ID)
# 12. **row**
_NUMBERED_ROW_RE = re.compile(r"^[ \t]*(\d+)\.[ \t]+\*\*")
_ROW_RES = (_BULLET_ROW_RE, _TABLE_ROW_RE, _NUMBERED_ROW_RE)
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~)")


def row_ids(text):
    """Counter of registry row ids, ignoring fenced code blocks."""
    counts = Counter()
    if text is None:
        return counts
    fence = None
    for line in split_lines(text):
        fm = _FENCE_RE.match(line)
        if fm:
            if fence is None:
                fence = fm.group(1)
            elif fence == fm.group(1):
                fence = None
            continue
        if fence:
            continue
        for rx in _ROW_RES:
            m = rx.match(line)
            if m:
                counts[m.group(1)] += 1
                break
    return counts


# ------------------------------------------------ handoff / docket fact statements

# A live handoff or docket file is a record of CURRENT STATE, not an append-only log
# (its rotated archives are the append-only exception: see is_archive_doc). Its
# name decides it: HANDOFF*.md, DOCKET*.md (never a DOCKET-INBOX filing, which is a
# new-file-only drop), roadmap*.md, and context.md (CONTEXT.md, continuation/context.md).
_HANDOFF_NAME_RE = re.compile(
    r"^(?:handoff[^/]*|(?!docket-inbox)docket[^/]*|roadmap[^/]*|context)\.md$", re.I)

# Inline mentions of a row id. A '#N' that is part of 'G#N', an HTML entity ('&#35;'),
# a colour ('#123abc'), a range ('#7-8'), a sub-row ('#9.1') or a time is not an id.
# 'G#130/G#131' is two ids.
_ID_TAIL = r"(?![\w]|[-.:/]\d)"
_INLINE_G_RE = re.compile(r"(?<![\w&#])G#(\d{1,6})" + _ID_TAIL)
_INLINE_H_RE = re.compile(r"(?<![\w&#])#(\d{1,6})" + _ID_TAIL)
_INLINE_WORD_RE = re.compile(r"(?i)\b(?:docket|row)\s+#?(\d{1,6})" + _ID_TAIL)
# Row ids for FACT statements come from bullet and table rows only. A numbered row
# ('2. **...**') is a list POSITION: measured on this estate's own merges, a HANDOFF's
# numbered next-steps list made '#1', '#2' and '#3' read as restated facts in both
# real divergence merges. The duplicate-id check keeps all three row forms.
_STMT_ROW_RES = (_BULLET_ROW_RE, _TABLE_ROW_RE)


def is_handoff_doc(path):
    return bool(_HANDOFF_NAME_RE.match(path.replace("\\", "/").rsplit("/", 1)[-1]))


# A rotated archive of a handoff/docket file (archive/HANDOFF-history-2026-09.md,
# archive/roadmap-closed-2026-09.md, docket_rederivation_2026-08-19.md) holds VERBATIM
# records: two machines each rotating a record about the same id is history, not a
# restatement, and "keep one statement" would delete a record. Live current-state files
# (HANDOFF.md, HANDOFF-<dev>.md, DOCKET-ACTIVE.md, roadmap.md, context.md) carry no date.
_ARCHIVE_DIRS = {"archive", "archives"}
_DATED_NAME_RE = re.compile(r"(?<!\d)\d{4}-\d{2}(?!\d)")


def is_archive_doc(path):
    parts = path.replace("\\", "/").split("/")
    return (any(p.lower() in _ARCHIVE_DIRS for p in parts[:-1])
            or bool(_DATED_NAME_RE.search(parts[-1])))


def _norm_id(tok):
    """'G#12' stays 'G#12'; '#12', a bare row number '12', 'row 12' and 'docket 12'
    all become '#12', so a row and a prose pointer to it share one key."""
    return tok if tok.startswith("G#") or tok.startswith("#") else "#" + tok


def _line_ids(line):
    """(row_id or None, set of every id the line mentions)."""
    row = None
    for rx in _STMT_ROW_RES:
        m = rx.match(line)
        if m:
            row = _norm_id(m.group(1))
            break
    ids = {"G#" + m.group(1) for m in _INLINE_G_RE.finditer(line)}
    ids |= {"#" + m.group(1) for m in _INLINE_H_RE.finditer(line)}
    ids |= {"#" + m.group(1) for m in _INLINE_WORD_RE.finditer(line)}
    if row:
        ids.add(row)
    return row, ids


def _unfenced(text):
    fence = None
    for line in split_lines(text):
        fm = _FENCE_RE.match(line)
        if fm:
            if fence is None:
                fence = fm.group(1)
            elif fence == fm.group(1):
                fence = None
            continue
        if not fence:
            yield line


def _stmt_key(line):
    """The id a line STATES -- its row id, or the only id it mentions -- else None."""
    row, ids = _line_ids(line)
    return row if row else (next(iter(ids)) if len(ids) == 1 else None)


def fact_statements(text):
    """{id: Counter of stripped lines that STATE that id's fact}. A line states an id
    when the id is the line's row id, or the only id the line mentions. A prose line
    naming several ids (a summary, a changelog sentence) states none of them. Fenced
    code blocks are ignored. A MULTISET, not a set: a verbatim copy of a base row carried
    forward into another section is a second statement of the fact, and a set would
    make that side's statements equal the base's."""
    out = {}
    if text is None:
        return out
    for line in _unfenced(text):
        key = _stmt_key(line)
        if key:
            out.setdefault(key, Counter())[line.strip()] += 1
    return out


def line_counts(text):
    """Counter of the stripped non-blank lines outside fenced code blocks."""
    out = Counter()
    if text is None:
        return out
    for line in _unfenced(text):
        s = line.strip()
        if s:
            out[s] += 1
    return out


def _row_body(line):
    """A row line with its row id blanked, so a row the resolution RENUMBERED (the
    right fix for an id collision) still matches; None for a line that is not a row."""
    for rx in _STMT_ROW_RES:
        m = rx.match(line)
        if m:
            return line[:m.start(1)] + "\0" + line[m.end(1):]
    return None


def _rows(lines):
    """The row lines ('- **#12** ...', '| **G#12 ...') among `lines`."""
    return [l for l in lines if _row_body(l) is not None]


def mentioned_ids(text):
    """Every id mentioned anywhere outside fenced code blocks."""
    out = set()
    if text is None:
        return out
    for line in _unfenced(text):
        out |= _line_ids(line)[1]
    return out


SIDES = ("ours", "theirs")


def check_handoff(path, v, append_only=False):
    """restated-fact, reverted-fact and lost-item for one handoff/docket file.
    append_only: the file is a rotated archive of verbatim records (is_archive_doc).

    Returns (findings, evidence, unkeyed): evidence maps (kind, id) to
    [(side, [that side's own lines])], and unkeyed is the number of distinct lines one
    or both sides added or changed that state no single id -- the lines this check
    cannot see."""
    findings, evidence = [], {}
    st = {k: fact_statements(t) for k, t in v.items()}
    lines = {k: line_counts(t) for k, t in v.items()}
    new = {s: lines[s] - lines["base"] for s in SIDES}
    # rows the RESULT added, by body: a side's row renumbered there still survives
    res_bodies = {_row_body(l) for l in lines["result"] - lines["base"]} - {None}

    def survives(line):
        return lines["result"][line] > 0 or _row_body(line) in res_bodies

    def who(sides):
        return "both sides" if len(sides) == 2 else sides[0]

    def lost(key, new_on, detail, ev):
        findings.append((
            "lost-item", path,
            "'%s' is new on %s%s; each side's new items survive a handoff merge "
            "(--accept %s::%s if the drop is deliberate)" % (key, new_on, detail, path, key),
            key))
        evidence[("lost-item", key)] = ev

    empty = Counter()
    for key in sorted(set().union(*(set(s) for s in st.values()))):
        b = st["base"].get(key, empty)
        o = st["ours"].get(key, empty)
        t = st["theirs"].get(key, empty)
        r = st["result"].get(key, empty)
        if o == b and t == b:
            continue  # neither side changed how this id is stated
        own = {"ours": o - b, "theirs": t - b}
        if append_only:
            # An archive of verbatim records: every ROW record each side appended survives.
            # (Prose is layout -- a re-wrapped paragraph moves an id to another line -- so
            # prose is checked by mention below, as in a live file.)
            gone = {s: sorted(l for l in _rows(own[s]) if not survives(l)) for s in SIDES}
            sides = [s for s in SIDES if gone[s]]
            if sides:
                lost(key, who(sides),
                     " (appended to this append-only archive), but the result dropped %d of "
                     "those record line(s)" % sum(len(gone[s]) for s in sides),
                     [(s, gone[s]) for s in sides])
            continue
        if not b:
            # A NEW id. Its item is a ROW: each side's new row survives -- kept, renumbered,
            # or replaced by an edited row the result wrote. A prose line naming a new id
            # is not an item (its '#N' may be a finding number, and a resolution that edits
            # the line can drop it); prose is checked by mention below.
            minted = [s for s in SIDES if _rows(own[s])]
            successor = bool(_rows(r - o - t))
            gone = {s: sorted(_rows(own[s])) for s in minted
                    if not successor and not any(survives(l) for l in _rows(own[s]))}
            sides = [s for s in SIDES if s in gone]
            if sides and len(minted) == 2 and o != t:
                kept = [s for s in SIDES if s not in gone]
                lost(key, "both sides",
                     " (an id collision: each side minted it for different work), but the "
                     "result keeps %s and dropped %s row -- renumber one side's row instead "
                     "of dropping it" % ("%s' row only" % kept[0] if kept else "neither row",
                                         " and ".join("%s'" % s for s in sides)),
                     [(s, gone[s]) for s in sides])
            elif sides:
                lost(key, who(sides), " (absent from the merge base) but missing from the "
                     "result", [(s, gone[s]) for s in sides])
            continue
        if o != b and t != b and o != t:
            # RESTATED: both sides changed how an existing fact is stated, differently.
            o_own = sorted(l for l in o if o[l] > max(b[l], t[l]))
            t_own = sorted(l for l in t if t[l] > max(b[l], o[l]))
            keeps_o = any(r[l] > 0 for l in o_own)
            keeps_t = any(r[l] > 0 for l in t_own)
            keeps = ("both" if keeps_o and keeps_t else "ours only" if keeps_o
                     else "theirs only" if keeps_t else "neither side's statement")
            findings.append((
                "restated-fact", path,
                "'%s' is restated on both sides; the result keeps %s. A restatement is not "
                "an append-only entry: the later FACT date wins (when the recorded event "
                "happened, not when a line or commit was written), so re-derive it from live "
                "source, keep one statement and each side's new items, then pass --accept "
                "%s::%s and name the source in the merge commit" % (key, keeps, path, key),
                key))
            evidence[("restated-fact", key)] = [("ours", o_own), ("theirs", t_own)]
            continue
        # One side changed how an existing id is stated (or both made the same change):
        # the result must carry that change, not the merge base's statement.
        if r == b:
            sides = [s for s, x in zip(SIDES, (o, t)) if x != b]
            findings.append((
                "reverted-fact", path,
                "'%s' was changed on %s, but the result states it exactly as the merge base: "
                "the resolution reverted that newer fact (a hunk taken from the other side). "
                "Restore it, or re-derive it from live source and pass --accept %s::%s"
                % (key, "both sides" if len(sides) == 2 else sides[0] + " only", path, key),
                key))
            evidence[("reverted-fact", key)] = [(sides[0], sorted(own[sides[0]]))]

    # An id a side names only on NEW prose lines (not a row of its own) is lost when the
    # result names it nowhere. The ids a side's new ROWS cite are left to that row's own
    # finding, so a dropped row is reported once, under its own id -- never under the ids
    # it cites.
    row_keys = {k for s in st.values() for k, c in s.items() if _rows(c)}
    named_elsewhere = mentioned_ids(v["base"]) | mentioned_ids(v["result"])
    named = {}
    for side in SIDES:
        prose, cited = {}, set()
        for l in new[side]:
            ids = _line_ids(l)[1]
            if _row_body(l) is not None:
                cited |= ids
            else:
                for i in ids:
                    prose.setdefault(i, []).append(l)
        for i, ls in prose.items():
            if i not in cited and i not in row_keys and i not in named_elsewhere:
                named.setdefault(i, {})[side] = sorted(ls)
    for i in sorted(named):
        sides = [s for s in SIDES if s in named[i]]
        lost(i, who(sides), ", named only on prose lines (it has no row of its own), and the "
             "result names it nowhere", [(s, named[i][s]) for s in sides])

    unkeyed = len({l for s in SIDES for l in new[s] if not _stmt_key(l)})
    return findings, evidence, unkeyed


# ------------------------------------------------------------- conflict markers

def marker_lines(text):
    """Line numbers of conflict-marker lines. '=======' and '|||||||' count only
    when an opening or closing marker is also present, so a markdown setext
    underline alone never counts."""
    if text is None:
        return []
    lines = split_lines(text)
    edges = [i for i, l in enumerate(lines, 1)
             if l.startswith("<<<<<<< ") or l == "<<<<<<<"
             or l.startswith(">>>>>>> ") or l == ">>>>>>>"]
    if not edges:
        return []
    mids = [i for i, l in enumerate(lines, 1)
            if l == "=======" or l.startswith("||||||| ") or l == "|||||||"]
    return sorted(edges + mids)


# ------------------------------------------------------------------ the checks

def check_file(path, v):
    """v: {'base','ours','theirs','result'} -> text or None.
    Returns (findings, notes, is_test_file, is_registry_file). A finding is
    (kind, path, detail, name); name is the test name for lost-test and
    shrunk-test (the only kinds --accept can match) and None otherwise."""
    findings = []
    notes = []
    ext = os.path.splitext(path)[1].lower()
    result = v["result"]
    parents = [v["ours"], v["theirs"]]

    # 1. conflict markers
    res_m = marker_lines(result)
    par_m = max(len(marker_lines(p)) for p in parents)
    if len(res_m) > par_m:
        shown = ", ".join(str(n) for n in res_m[:6]) + (", ..." if len(res_m) > 6 else "")
        findings.append(("conflict-marker", path,
                         "%d conflict-marker line(s) (parents had at most %d), at line(s) %s"
                         % (len(res_m), par_m, shown), None))

    # extract definitions per version
    defs = None
    used_ast = False
    if ext in PY_EXTS:
        defs, used_ast, errors = py_defs_all(v)
        if errors:
            bad = [k for k in ("base", "ours", "theirs", "result") if k in errors]
            notes.append("NOTE shrunk-test skipped for %s: %s %s not parse"
                         % (path, ", ".join(bad), "does" if len(bad) == 1 else "do"))
        parents_parse = all(v[k] is not None and k not in errors for k in ("ours", "theirs"))
        if "result" in errors and parents_parse:
            findings.append(("result-unparseable", path, errors["result"], None))
    elif ext in JS_EXTS:
        defs = {k: (regex_defs(_JS_DEF_RE, t) if t is not None else None) for k, t in v.items()}
    elif ext in GD_EXTS:
        defs = {k: (regex_defs(_GD_DEF_RE, t) if t is not None else None) for k, t in v.items()}

    is_test = False
    if defs is not None:
        # tests per version
        tests = {}
        for k, t in v.items():
            if t is None:
                tests[k] = None
            elif ext in PY_EXTS:
                tests[k] = {qualify(s, n) for s, n, _ in defs[k] if n.startswith("test")}
            elif ext in JS_EXTS:
                tests[k] = {m.group(2) for m in _JS_TEST_RE.finditer(t)}
            else:
                tests[k] = {m.group(1) for m in _GD_TEST_RE.finditer(t)}
        is_test = any(tests[k] for k in tests if tests[k])

        # 2. lost-test
        ours_t = tests["ours"] or set()
        theirs_t = tests["theirs"] or set()
        base_t = tests["base"] or set()
        res_t = tests["result"] or set()
        deleted = {n for n in base_t if n not in ours_t or n not in theirs_t}
        expected = (ours_t | theirs_t) - deleted
        for name in sorted(expected - res_t):
            where = "both parents" if (name in ours_t and name in theirs_t) else \
                ("ours" if name in ours_t else "theirs")
            findings.append(("lost-test", path,
                             "'%s' is present in %s but missing from the result" % (name, where),
                             name))

        # 3. shrunk-test (.py, AST only)
        if ext in PY_EXTS and used_ast and defs["result"] is not None:
            def sizes(label):
                d = defs[label]
                if d is None:
                    return {}
                out = {}
                for s, n, cnt in d:
                    if n.startswith("test"):
                        q = qualify(s, n)
                        out[q] = min(cnt, out.get(q, cnt))
                return out
            res_sz = sizes("result")
            ours_sz, theirs_sz = sizes("ours"), sizes("theirs")
            for name in sorted(res_sz):
                parent_sizes = [d[name] for d in (ours_sz, theirs_sz) if name in d]
                if parent_sizes and res_sz[name] < min(parent_sizes):
                    findings.append(("shrunk-test", path,
                                     "'%s' body has %d statement(s); the smallest parent "
                                     "version has %d" % (name, res_sz[name], min(parent_sizes)),
                                     name))

        # 4. duplicate-def
        def dup_counts(label):
            d = defs[label]
            return Counter((s, n) for s, n, _ in d) if d is not None else Counter()
        res_c = dup_counts("result")
        ours_c, theirs_c = dup_counts("ours"), dup_counts("theirs")
        for (scope, name), cnt in sorted(res_c.items()):
            prev = max(ours_c[(scope, name)], theirs_c[(scope, name)])
            if cnt >= 2 and cnt > prev:
                findings.append(("duplicate-def", path,
                                 "'%s' is defined %d times in scope %s (parents had at most %d)"
                                 % (name, cnt, scope, prev), None))

    # 5. duplicate-id
    is_registry = False
    if ext in REGISTRY_EXTS:
        ids = {k: row_ids(t) for k, t in v.items()}
        is_registry = any(ids[k] for k in ids)
        for rid, cnt in sorted(ids["result"].items()):
            b, o, t = ids["base"][rid], ids["ours"][rid], ids["theirs"][rid]
            # only an id that was unique everywhere behaves like a registry key
            if cnt >= 2 and max(b, o, t) <= 1:
                findings.append(("duplicate-id", path,
                                 "row id '%s' appears %d times (base %d, ours %d, theirs %d)"
                                 % (rid, cnt, b, o, t), None))

    return findings, notes, is_test, is_registry


# ------------------------------------------------------------------------ main

def build_parser():
    p = argparse.ArgumentParser(
        prog="merge-check.py",
        description="After a git merge is resolved, report damage a merge can do "
                    "silently: lost or shrunk tests, duplicated functions, duplicated "
                    "registry row ids, leftover conflict markers, a .py result that no "
                    "longer parses, and -- in handoff/docket files (HANDOFF*.md, "
                    "DOCKET*.md, roadmap*.md, context.md) -- a row fact restated on both "
                    "sides (restated-fact: the later FACT date wins; re-derive it from "
                    "live source), one side's change to an existing row that the "
                    "resolution reverted to the merge base (reverted-fact), or a new item "
                    "one side added that the result dropped, including one side's row of "
                    "an id both sides minted (lost-item). Rotated archives (under an "
                    "archive directory, or dated names) are append-only: every appended "
                    "row record must survive. The last line counts the new or changed "
                    "handoff/docket lines that state no single row id: the tool cannot "
                    "tell whether they restate a fact, so read them. Checks only files "
                    "changed on both sides since the merge base.",
        epilog="Exit status: 0 clean, 1 findings or an UNUSED --accept, 2 usage error "
               "or not in a merge state.")
    p.add_argument("--repo", default=".", help="repository path (default: current directory)")
    p.add_argument("--commit", metavar="SHA", help="check this two-parent merge commit")
    p.add_argument("--mode", choices=("auto", "in-progress", "head", "commit"), default="auto",
                   help="override mode detection (default: auto)")
    p.add_argument("--accept", metavar="PATH::NAME", action="append", default=[],
                   help="accept a deliberate, documented drop of test NAME in file PATH, "
                        "or a restated-fact / reverted-fact / lost-item on row id NAME (e.g. "
                        "'#179') after re-deriving it from live source (repeatable). A "
                        "matching finding "
                        "prints as ACCEPTED and does not affect the exit status. An "
                        "--accept that matches no finding prints UNUSED and makes the run "
                        "exit 1.")
    return p


ACCEPT_KINDS = ("lost-test", "shrunk-test", "restated-fact", "reverted-fact", "lost-item")
MAX_BLAME = 6


def line_numbers(text, stmt):
    """1-based numbers of the lines whose stripped text is `stmt`."""
    return [i for i, line in enumerate(split_lines(text or ""), 1) if line.strip() == stmt]


def blame_sha(repo, rev, path, lineno):
    rc, out, _ = git(repo, "blame", "--porcelain", "-L", "%d,%d" % (lineno, lineno), rev,
                     "--", path)
    if rc != 0 or not out.strip():
        return None
    return out.decode("utf-8", "replace").split()[0]


def in_base(repo, sha, base):
    rc, _, _ = git(repo, "merge-base", "--is-ancestor", sha, base)
    return rc == 0


def written(repo, rev, base, path, text, stmt):
    """'<date> <short sha> <subject>' of the commit that wrote `stmt` in `path` on
    `rev`, from `git blame`. This is when the line was WRITTEN -- evidence for the
    reader, never the fact date itself. When the line occurs more than once (a base row
    carried forward as a verbatim copy), the copy this side's own history wrote is the
    one shown: the first occurrence whose commit is not already in the merge base."""
    first = None
    for lineno in line_numbers(text, stmt)[:MAX_BLAME]:
        sha = blame_sha(repo, rev, path, lineno)
        if sha is None:
            continue
        if first is None:
            first = sha
        if base is None or not in_base(repo, sha, base):
            first = sha
            break
    if first is None:
        return "unknown"
    rc, out, _ = git(repo, "log", "-1", "--format=%ad %h %s", "--date=short", first)
    if rc != 0:
        return first[:12]
    return out.decode("utf-8", "replace").strip()[:90]


def trunc(s, n=150):
    return s if len(s) <= n else s[:n - 3] + "..."


def evidence_lines(repo, st, base, path, ev, texts):
    """The indented lines printed under a restated-fact, reverted-fact or lost-item
    finding: each side's own statement(s) of the fact, with the commit that wrote each."""
    out = []
    for side, stmts in ev:
        if not stmts:
            out.append("    %-6s (no longer states it)" % side)
            continue
        for stmt in stmts[:2]:
            when = written(repo, st[side], base, path, texts[side], stmt)
            out.append("    %-6s written %s: %s" % (side, when, trunc(stmt)))
        if len(stmts) > 2:
            out.append("    %-6s ... and %d more line(s) stating it" % (side, len(stmts) - 2))
    return out


def parse_accepts(values):
    """['PATH::NAME', ...] -> ordered list of unique (path, name)."""
    out = []
    for raw in values:
        path, sep, name = raw.partition("::")
        path = path.strip().replace("\\", "/")
        if not sep or not path or not name:
            raise UsageError("--accept %r must have the form PATH::NAME" % raw)
        if (path, name) not in out:
            out.append((path, name))
    return out


def run(argv):
    args = build_parser().parse_args(argv)
    if args.mode == "commit" and not args.commit:
        raise UsageError("--mode commit requires --commit <sha>")
    accepts = parse_accepts(args.accept)
    if not os.path.isdir(args.repo):
        raise UsageError("--repo %s is not a directory" % args.repo)
    rc, out, err = git(args.repo, "rev-parse", "--show-toplevel")
    if rc != 0:
        raise UsageError("%s is not inside a git repository" % args.repo)
    top = out.decode("utf-8", "replace").strip()

    st = resolve(top, args.mode, args.commit)
    rc, out, _ = git(top, "merge-base", st["ours"], st["theirs"])
    base = out.decode().strip() if rc == 0 and out.strip() else None
    base_tree = base or empty_tree(top)

    print("merge-check: mode=%s ours=%s theirs=%s base=%s result=%s" % (
        st["mode"], st["ours"][:12], st["theirs"][:12],
        base[:12] if base else "none",
        st["result"][:12] if st["result"] else "working-tree"))

    both = sorted(changed_paths(top, base_tree, st["ours"])
                  & changed_paths(top, base_tree, st["theirs"]))

    findings = []
    notes = []
    evidence = {}
    checked = n_test = n_reg = n_handoff = skipped = n_unkeyed = 0
    unkeyed_known = True
    for path in both:
        raw = {
            "base": read_blob(top, base, path),
            "ours": read_blob(top, st["ours"], path),
            "theirs": read_blob(top, st["theirs"], path),
            "result": (read_blob(top, st["result"], path) if st["result"]
                       else read_worktree(top, path)),
        }
        present = [d for d in raw.values() if d is not None]
        if not present:
            continue
        if any(is_binary(d) or len(d) > MAX_BYTES for d in present):
            skipped += 1
            if is_handoff_doc(path):
                unkeyed_known = False  # its lines were never read: the count is unknown
            continue
        checked += 1
        texts = {k: decode(d) for k, d in raw.items()}
        f, nt, is_test, is_reg = check_file(path, texts)
        findings.extend(f)
        notes.extend(nt)
        n_test += int(is_test)
        n_reg += int(is_reg)
        if is_handoff_doc(path):
            n_handoff += 1
            hf, ev, unkeyed = check_handoff(path, texts, append_only=is_archive_doc(path))
            findings.extend(hf)
            n_unkeyed += unkeyed
            evidence[path] = (ev, texts)

    accepted, open_findings, used = [], [], set()
    for kind, path, detail, name in findings:
        if kind in ACCEPT_KINDS and (path, name) in accepts:
            accepted.append((kind, path, name))
            used.add((path, name))
        else:
            open_findings.append((kind, path, detail, name))
    unused = [a for a in accepts if a not in used]

    for line in notes:
        print(line)
    for kind, path, detail, name in open_findings:
        print("FINDING %s %s: %s" % (kind, path, detail))
        ev, texts = evidence.get(path, ({}, None))
        if (kind, name) in ev:
            for line in evidence_lines(top, st, base, path, ev[(kind, name)], texts):
                print(line)
    for kind, path, name in accepted:
        print("ACCEPTED %s %s: %s" % (kind, path, name))
    for path, name in unused:
        print("UNUSED --accept %s::%s" % (path, name))
    print("skipped %d files (binary or over 2 MB)" % skipped)
    print(DENOMINATOR_FMT % (checked, n_test, n_reg, n_handoff, len(open_findings),
                             n_unkeyed if unkeyed_known else "UNKNOWN"))
    return EXIT_FINDINGS if (open_findings or unused) else EXIT_CLEAN


def main(argv=None):
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except UsageError as e:
        build_parser().print_usage(sys.stderr)
        print("merge-check.py: error: %s" % e, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
