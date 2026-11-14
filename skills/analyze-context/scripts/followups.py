#!/usr/bin/env python3
"""followups.py -- the dated follow-ups that are due, here and in every other project.

A project keeps its dated checks in FOLLOW-UPS.md at its root, one entry per check:

    ## YYYY-MM-DD <middle dot> <title>   (the date is the due date; the dot is U+00B7)
    - **Check:** what to look at
    - **Evidence:** where: a file, a URL, or a read-only command
    - **Then:** the next action, by outcome
    - **Hold:** (optional) a hold the date does not lift

A due date allows a check; it never lifts a hold.

USAGE
    python followups.py due [--today YYYY-MM-DD] [--root DIR] [--parent DIR]

    Prints, when anything is due or could not be read:
      one summary line: "follow-ups: N due here, K later; M due in other projects"
        (plus "; X could not check" when a file or heading could not be read)
      this project's entries dated on or before today, in full, each heading marked
        "due today" or "N day(s) overdue"; a Hold line is followed by the sentence
        "(the date allows the check; it does not lift the hold)"
      one line per OTHER project under the parent folder with a due entry:
        "other project <name>: N due -- <title>; <title>"
      from a linked worktree, the main checkout's FOLLOW-UPS.md is read as well: an entry
        with the same date and title is one entry, and an entry only the main checkout
        holds prints with "(from the main checkout)" after its due words
      "could not check: other projects (parent folder <path> not found)" when the parent
        folder is missing or is not a folder; this project's own entries still print
      "could not check: <file>:<line> ..." for every unreadable file or heading whose
        date does not parse -- never skipped
    Entries due later are counted, never listed. Nothing due and nothing unreadable
    prints nothing at all. Exit 0 whenever it ran; 2 on a bad argument.

    --root    this project (any folder in it; default: the current folder)
    --parent  the folder holding the projects (default: docket_corpus.py's parent: the
              environment variable DOCKET_CORPUS_PARENT, else the folder that holds this
              project's main checkout)
    --today   the day to read against (default: this machine's date)

    Projects are enumerated by docket_corpus.py's projects() (the same scripts folder),
    so the estate is the one every other analyze-context reader sees. Read-only.
"""
import argparse
import importlib.util
import os
import re
import sys
from datetime import date
from pathlib import Path

FILE_NAME = "FOLLOW-UPS.md"
HOLD_NOTE = "(the date allows the check; it does not lift the hold)"
MAIN_NOTE = "(from the main checkout)"
HEADING_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})(?:\s+(?:·\s*)?(.*?))?\s*$")
HOLD_RE = re.compile(r"^\s*-\s+\*\*Hold:\*\*")
BULLET_RE = re.compile(r"^\s*-\s+")


def _key(path):
    return os.path.normcase(str(Path(path).resolve()))


def load_docket_corpus():
    """docket_corpus.py from this file's own folder, loaded by path (it is not on sys.path once installed)."""
    p = Path(__file__).resolve().with_name("docket_corpus.py")
    if not p.is_file():
        raise LookupError("docket_corpus.py is missing beside followups.py")
    spec = importlib.util.spec_from_file_location("docket_corpus", str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_entries(path):
    """(entries, errors) for one FOLLOW-UPS.md. An entry is {date, title, line, body}; an error is a
    `could not check:` line. A missing file is ([], [])."""
    if not os.path.lexists(str(path)):
        return [], []
    try:
        with open(str(path), "rb") as fh:
            raw = fh.read()
    except OSError as exc:
        return [], ["could not check: %s:0 unreadable (%s: %s)" % (path, type(exc).__name__, exc.strerror or exc)]
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        return [], ["could not check: %s:0 not UTF-8 (byte %d)" % (path, exc.start)]
    entries, errors, cur, in_comment = [], [], None, False
    for n, line in enumerate(text.split("\n"), 1):
        line = line.rstrip("\r")
        s = line.strip()
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith("<!--"):
            in_comment = "-->" not in s[4:]
            continue
        if line.startswith("## "):
            cur = None
            m = HEADING_RE.match(line)
            when = None
            if m:
                try:
                    when = date.fromisoformat(m.group(1))
                except ValueError:
                    when = None
            if when is None:
                errors.append("could not check: %s:%d heading has no due date it can read: %r" % (path, n, line[:120]))
                continue
            cur = {"date": when, "title": (m.group(2) or "").strip() or "(untitled)", "line": n, "body": []}
            entries.append(cur)
            continue
        if line.startswith("# "):
            cur = None
            continue
        if cur is not None and s:
            cur["body"].append(line)
    return entries, errors


def render(entry, today):
    days = (today - entry["date"]).days
    when = "due today" if days == 0 else "%d day(s) overdue" % days
    if entry.get("from_main"):
        when += " " + MAIN_NOTE
    out = ["%s · %s -- %s" % (entry["date"].isoformat(), entry["title"], when)]
    body = entry["body"]
    for i, line in enumerate(body):
        out.append("  " + line)
        nxt = body[i + 1] if i + 1 < len(body) else None
        if in_hold(body, i) and (nxt is None or BULLET_RE.match(nxt)):
            out.append("    " + HOLD_NOTE)
    return out


def in_hold(body, i):
    """True when line i belongs to a Hold bullet (the bullet itself or one of its continuation lines)."""
    for j in range(i, -1, -1):
        if BULLET_RE.match(body[j]):
            return bool(HOLD_RE.match(body[j]))
    return False


def main_only(own, path, errors):
    """The main checkout's entries the worktree's own file does not hold, each marked from_main.
    Equal date and title is the same entry. What cannot be read there goes on `errors`."""
    entries, errs = read_entries(path)
    errors.extend(errs)
    have = {(e["date"], e["title"]) for e in own}
    out = []
    for e in entries:
        if (e["date"], e["title"]) not in have:
            e["from_main"] = True
            out.append(e)
    return out


def due_report(today, root=None, parent=None):
    """The lines `due` prints (an empty list prints nothing)."""
    root = Path(root or os.getcwd()).resolve()
    errors, others, here_root, main_root = [], [], root, None
    try:
        dc = load_docket_corpus()
        par, listing = dc.projects(parent, cwd=str(root))
        here = [p for p in listing if p["current"]]
        if here:
            here_root, main_root = here[0]["root"], here[0]["main"]
        else:
            here_root = None
        skip = {_key(p) for p in (here_root, main_root) if p is not None}
        others = [p for p in listing if not p["current"] and _key(p["root"]) not in skip]
        # projects() does not raise on a parent that is not there (--parent or DOCKET_CORPUS_PARENT):
        # it lists the current project alone, which would read as "nothing due anywhere else".
        if not Path(par).is_dir():
            errors.append("could not check: other projects (parent folder %s not found)" % par)
    except Exception as exc:  # noqa: BLE001 -- a broken enumerator is a could-not-check, never a silent zero
        errors.append("could not check: other projects (%s: %s)" % (type(exc).__name__, exc))

    due_here, later = [], 0
    if here_root is not None:
        entries, errs = read_entries(Path(here_root) / FILE_NAME)
        errors.extend(errs)
        # A linked worktree holds the file its branch was cut with, and the main checkout is skipped
        # as an "other project" above: an entry added there afterwards would be read by nobody.
        if main_root is not None and _key(main_root) != _key(here_root):
            entries = entries + main_only(entries, Path(main_root) / FILE_NAME, errors)
        for e in entries:
            if e["date"] <= today:
                due_here.append(e)
            else:
                later += 1
    due_here.sort(key=lambda e: (e["date"], bool(e.get("from_main")), e["line"]))

    other_lines, other_n = [], 0
    for p in others:
        entries, errs = read_entries(Path(p["root"]) / FILE_NAME)
        errors.extend(errs)
        due = sorted((e for e in entries if e["date"] <= today), key=lambda e: (e["date"], e["line"]))
        if due:
            other_n += len(due)
            other_lines.append("other project %s: %d due -- %s" % (
                p["name"], len(due), "; ".join(e["title"] for e in due)))

    if not due_here and not other_n and not errors:
        return []
    summary = "follow-ups: %d due here, %d later; %d due in other projects" % (len(due_here), later, other_n)
    if errors:
        summary += "; %d could not check" % len(errors)
    lines = [summary]
    for e in due_here:
        lines.extend(render(e, today))
    lines.extend(other_lines)
    lines.extend(errors)
    return lines


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="followups.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    d = sub.add_parser("due", help="print the follow-ups due on or before today")
    d.add_argument("--today", help="YYYY-MM-DD (default: this machine's date)")
    d.add_argument("--root", help="this project (default: the current folder)")
    d.add_argument("--parent", help="the folder holding the projects (default: docket_corpus.py's)")
    a = ap.parse_args(argv)
    if a.cmd != "due":
        ap.print_help()
        return 2
    try:
        today = date.fromisoformat(a.today) if a.today else date.today()
    except ValueError:
        print("followups.py: --today %r is not a YYYY-MM-DD date" % a.today, file=sys.stderr)
        return 2
    if a.root and not Path(a.root).is_dir():
        print("followups.py: --root %s is not a folder" % a.root, file=sys.stderr)
        return 2
    for line in due_report(today, a.root, a.parent):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
