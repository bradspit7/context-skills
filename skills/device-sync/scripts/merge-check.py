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
  * a leftover conflict marker.

This tool compares the merge RESULT against both parents (and their merge base)
and reports each of those as one line:

    FINDING <kind> <path>: <detail>

Kinds: conflict-marker, lost-test, shrunk-test, duplicate-def, duplicate-id,
result-unparseable (a .py result that does not parse while both parents do --
the orphaned fragment a line-range splice leaves behind).

A row id counts as a duplicate only when it appears at least twice in the result
AND at most once in each of base, ours and theirs: an id that was never unique
(a '1.' ordered list, a '- **3 files**' count) is not behaving as a registry key.
An id token must end at the bold close, whitespace, ':' + non-digit, or the end
of the line, so dates, versions and times ('2026-09-16', '1.4.0', '10:12') are
never read as ids.

A deliberate, documented test drop is accepted with --accept PATH::NAME
(repeatable). A matching lost-test or shrunk-test finding prints

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

DENOMINATOR_FMT = "checked %d files (%d test files, %d registry files); findings: %d"


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
_ROW_RES = (
    # - **#12**   - <one glyph> **G#12**   - **12** text
    re.compile(r"^[ \t]*[-*+][ \t]+(?:[^\s\w*]\S*[ \t]+)?\*\*" + _ID),
    # | **#303 title | ...
    re.compile(r"^[ \t]*\|[ \t]*\*\*" + _ID),
    # 12. **row**
    re.compile(r"^[ \t]*(\d+)\.[ \t]+\*\*"),
)
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
                    "longer parses. Checks only files "
                    "changed on both sides since the merge base.",
        epilog="Exit status: 0 clean, 1 findings or an UNUSED --accept, 2 usage error "
               "or not in a merge state.")
    p.add_argument("--repo", default=".", help="repository path (default: current directory)")
    p.add_argument("--commit", metavar="SHA", help="check this two-parent merge commit")
    p.add_argument("--mode", choices=("auto", "in-progress", "head", "commit"), default="auto",
                   help="override mode detection (default: auto)")
    p.add_argument("--accept", metavar="PATH::NAME", action="append", default=[],
                   help="accept a deliberate, documented drop of test NAME in file PATH "
                        "(repeatable). A matching lost-test or shrunk-test finding prints "
                        "as ACCEPTED and does not affect the exit status. An --accept "
                        "that matches no finding prints UNUSED and makes the run exit 1.")
    return p


ACCEPT_KINDS = ("lost-test", "shrunk-test")


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
    checked = n_test = n_reg = skipped = 0
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
            continue
        checked += 1
        f, nt, is_test, is_reg = check_file(path, {k: decode(d) for k, d in raw.items()})
        findings.extend(f)
        notes.extend(nt)
        n_test += int(is_test)
        n_reg += int(is_reg)

    accepted, open_findings, used = [], [], set()
    for kind, path, detail, name in findings:
        if kind in ACCEPT_KINDS and (path, name) in accepts:
            accepted.append((kind, path, name))
            used.add((path, name))
        else:
            open_findings.append((kind, path, detail))
    unused = [a for a in accepts if a not in used]

    for line in notes:
        print(line)
    for kind, path, detail in open_findings:
        print("FINDING %s %s: %s" % (kind, path, detail))
    for kind, path, name in accepted:
        print("ACCEPTED %s %s: %s" % (kind, path, name))
    for path, name in unused:
        print("UNUSED --accept %s::%s" % (path, name))
    print("skipped %d files (binary or over 2 MB)" % skipped)
    print(DENOMINATOR_FMT % (checked, n_test, n_reg, len(open_findings)))
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
