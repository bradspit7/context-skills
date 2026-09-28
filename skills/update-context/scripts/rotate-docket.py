#!/usr/bin/env python3
"""rotate-docket -- move CLOSED docket rows into a dated archive, leaving a one-line stub.

It ships with update-context, whose Step 5 rotation contract it implements, so a wrap in
ANY project can run it. (It used to live only in the repo that built it, where no other
project's wrap could reach it; a hand-rolled substitute then cut 11 of 12 stubs inside a
bold span.)

    python ~/.claude/skills/update-context/scripts/rotate-docket.py              dry run
    python ~/.claude/skills/update-context/scripts/rotate-docket.py --apply      write
    ... --docket continuation/memory/roadmap.md    when a project has several docket files
    ... --selftest

WHICH ROWS MOVE
    A row moves when it is CLOSED, is not already a stub, has no copy in any archive file
    of the project, carries no standing ruling, and is longer than the stub that would
    replace it. Rows, their exact line spans and their state come from analyze-context's
    docket_corpus.py -- the parse the session-start briefing uses -- so '- **G#N**' rows
    and bare '#N' rows (bold closed after the id, or running on past it) are read the way
    the briefing reads them, and a row ENDS at the next row, heading, rule or top-level
    list item. That last rule matters: a column-0 '- **Hygiene ...**' note under a closed
    row is its own item, not the row's body, and moving it would archive live work.

WHAT NEVER MOVES
    Open and unknown rows (a no-entry glyph reads 'unknown' unless the project maps it in
    its docket-corpus.json); stubs; rows already in an archive; a row under --min-bytes
    (default 600, the floor a measured condensation of closed rows used: below it a stub
    saves too little to be worth the extra hop); a row already shorter than its own stub;
    a row whose lines a code fence or multi-line HTML comment crosses, or that sits inside
    one (the shared parser reads neither, so a '# comment' in a fence looks to it like a
    heading); a row markdown does not end cleanly -- after the head, a column-0 line that
    follows a blank line, opens an HTML block, a table or a fence, or a line directly below
    the row that markdown would join to it (a quote or list continuation, a setext
    underline) -- which is reported, never guessed at; a closed row with an open line in
    its body (a sub-bullet that reopened it); and a row that carries a standing decision.
    That last screen has two halves. analyze-context's rulings.py decides what a RULING
    is, read over the WHOLE file as the briefing reads it (a 'Ruled out' section heading
    makes the rows under it rulings), so every row the briefing's RULED OUT section or the
    wrap's ruling-loss check would count stays live. A wider net then keeps any closed row
    that still says what must or must not happen: 'do not re-<verb>', an owner who
    ratified, ruled, decided, said, asked for, declined or rejected something, a
    'Decision:' or 'decided', an ADOPTED / RATIFIED / POLICY / RULE / LOCKED / NEVER /
    MUST NOT / DO NOT in capitals, 'must not be reverted', or a thing that 'stays' live or
    thin. Keeping a row live is the observable, cheap error; archiving a live decision is
    the silent, expensive one. Lower-case 'never' and 'do not' are NOT in the net:
    narrative uses them constantly, and they held back 11 of 13 candidates in one docket.

WHERE THEY GO
    <docket dir>/archive/<docket stem>-closed-<YYYY-MM>.md, or --archive. A new file gets a
    short header. An existing one is APPENDED to under a '## Rotated <date>' heading, and
    its earlier bytes are never rewritten. Relative links inside a moved row are re-pointed
    for the archive's directory, but only a link that fails there and resolves from the
    docket (G#614); a link that resolves nowhere is left alone and reported.

STUBS
    A stub keeps the row's id, its marker and the start of its head, then a pointer in the
    docket's OWN existing stub style ('[full row -> X]', an arrow and a bold link, or an
    arrow and '[archive](X)'), so every reference to the id still resolves in the docket.
    The head is cut only where no bracket, parenthesis, code span, italic or HTML comment
    is open; an open bold is closed. It prefers the end of the second bold pair (a short
    head claim), then a sentence end, then a word end.

HOW IT WRITES (the Step 5 contract, in order; any miss stops the run)
    1. every check below runs in memory, and nothing is written if one fails;
    2. the archive is written (temp file, read back, then replace);
    3. the archive is RE-READ from disk and every moved row is looked for in it;
    4. only then is the docket written, re-read and re-parsed: the same rows, ids and
       states in the same order (a stub is still its row).
    Each file is compared with the bytes the plan was made from immediately before it is
    replaced; a change by another session, a failed write or a miss in 3 or 4 stops the
    run with the files as they were. A rollback only puts back bytes this run wrote: if
    another session wrote in between, nothing is overwritten and the report says to check.

LINE ENDINGS
    Bytes are read and written exactly: an LF docket stays LF, a CRLF docket stays CRLF,
    and no line outside a moved row changes. Moved rows take the archive's line ending (an
    appended CRLF archive stays CRLF); the identity check compares text with the CR before
    each LF dropped on both sides, and the report says when rows were converted.

EXIT STATUS
    0 dry run or write done (including 'nothing to rotate'); 1 a check failed and nothing
    was written, or a write was rolled back; 2 a usage or environment problem (no docket,
    several dockets and no --docket, a UTF-16 or non-UTF-8 file, analyze-context missing).
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
# The sibling skill, found the way session-evidence.sh finds it: installs keep skills side
# by side, so this path holds in the live tree, the committed mirror and the public copy.
SIBLING = HERE.parent.parent / "analyze-context" / "scripts"

ARROW, ELLIPSIS, DASH = "→", "…", "—"
BUDGET = 220        # a stub head aims to end at or before this many characters
HARD_MAX = 400      # and never runs past this one when no earlier point is clean
PAIR2_MAX = 280     # the second bold pair's end is preferred only when it closes this early

MIN_BYTES = 600     # a closed row smaller than this stays live (see WHAT NEVER MOVES)

# The wider standing-decision net (see WHAT NEVER MOVES). Recall-oriented on purpose.
DECISION_RES = (
    re.compile(r"\b(?:do|does)\s*(?:n[o']t|not)\s+re-?[a-z]", re.I),
    re.compile(r"\bowner\b[^.\n]{0,60}?\b(?:ratif\w*|rul(?:ed|ing)\w*|decid\w*|decision|"
               r"approv\w*|chose|sign(?:ed)?[- ]?off|said|says|asked|wants|declin\w*|"
               r"reject\w*|veto\w*)", re.I),
    re.compile(r"\b(?:per the owner|decision\s*[(:]|decided)\b", re.I),
    re.compile(r"\b(?:ADOPTED|RATIFIED|STANDING|STANDS|POLICY|REQUIRED|REQUIRES|REQUIRE|RULE|"
               r"RULES|LOCKED|BANNED|FORBIDDEN|NEVER|MUST NOT|MUST NEVER|DO NOT|DON'T)\b"),
    re.compile(r"\b(?:stays?|remains?)\s+(?:live|thin|open|off|out|as is|in place)\b", re.I),
    re.compile(r"\bmust (?:not|never) be (?:reverted|removed|lowered|raised|changed|re-?[a-z]+)",
               re.I),
)
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)\s*$")

ID_GRAMMARS = {"central-g", "hash-bullet", "hash-para", "numbered", "alpha-bullet"}
LIST_HEAD = re.compile(r"^(?:> ?)?(?:[-*+] |\d+\. )")
MIN_KEEP_RE = re.compile(r"^\s*(?:> ?)?(?:[-*+] |\d+\. )?(?:\*\*|__)?[^\s*]+(?:\*\*|__)?[ \t]*\S*")
STYLE_RES = (
    ("arrow-link", re.compile(r"\[full row " + ARROW + r" `[^`]+`\]\([^)]*\)[*_]*\s*$")),
    ("plain", re.compile(r"\[full row -> [^\]]+\]\s*$")),
    ("archive-link", re.compile(ARROW + r" \[archive\]\([^)]+\)")),
)
LINK_RE = re.compile(r"\]\(([^)#\s][^)]*)\)")

# Test seam for the write path: the selftest sets this to prove the rollback runs. Never
# set outside --selftest.
_FAULT = None


class EnvError(Exception):
    """A usage or environment problem: reported with exit 2, never as a failed check."""


# --------------------------------------------------------------------------------------
# Loading the shared parser and the ruling grammar
# --------------------------------------------------------------------------------------

def _load(name):
    """A sibling module compiled from source (no bytecode cache, the G#130 loader)."""
    p = SIBLING / (name + ".py")
    if not p.is_file():
        raise EnvError("could not rotate: %s is not installed beside this skill (looked in %s)"
                       % (p.name, SIBLING))
    mod = types.ModuleType("_rotate_docket_" + name)
    mod.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), mod.__dict__)
    return mod


def load_deps():
    dc = _load("docket_corpus")
    if not hasattr(dc, "parse_bytes"):
        raise EnvError("could not rotate: %s is older than this tool (it has no parse_bytes); "
                       "update analyze-context" % dc.__file__)
    rl = _load("rulings")
    if not hasattr(rl, "rulings_in_text"):
        raise EnvError("could not rotate: %s has no rulings_in_text" % rl.__file__)
    return dc, rl


# --------------------------------------------------------------------------------------
# Bytes, text and line endings
# --------------------------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


def decode(raw, name):
    """(text, has_bom). UTF-8 only: a file this tool cannot write back exactly is refused."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise EnvError("could not rotate: %s is UTF-16; only UTF-8 files are rewritten" % name)
    bom = raw[:3] == BOM
    try:
        return (raw[3:] if bom else raw).decode("utf-8"), bom
    except UnicodeDecodeError as e:
        raise EnvError("could not rotate: %s is not valid UTF-8 (%s)" % (name, e))


def encode(text, bom):
    return (BOM if bom else b"") + text.encode("utf-8")


def eol_of(text, default="\n"):
    """The line ending most of a text's line breaks use."""
    n = text.count("\n")
    if not n:
        return default
    return "\r\n" if text.count("\r\n") * 2 > n else "\n"


def lf(s):
    return s.replace("\r\n", "\n")


def uncr(line):
    return line[:-1] if line.endswith("\r") else line


def blank(line):
    return not line.strip()


# --------------------------------------------------------------------------------------
# Markdown-safe stubs
# --------------------------------------------------------------------------------------

def scan(s):
    """Walk markdown inline syntax. Returns (cut_points, bold_toggles, final_state).

    A cut point is (p, bold_open, sentence_end): s[:p] ends a word, and no bracket,
    parenthesis, code span, italic, HTML comment or quotation is open there. A bold may be
    open (the stub closes it). A stray closer never counts as open. Quotes are not markdown,
    so they only steer the cut (a stub ending '"last assigned:' reads wrong); balanced()
    ignores them. A straight quote after a digit is an inch mark, not an opener.
    """
    pts, toggles = [], []
    bold = italic = code = comment = quote = strike = False
    br = par = 0
    i, n = 0, len(s)
    while i < n:
        if s[i] == "\\" and not (code or comment):     # an escaped character is plain text
            i += 2
            continue
        if comment:
            if s.startswith("-->", i):
                comment = False
                i += 3
            else:
                i += 1
        elif code:
            if s[i] == "`":
                code = False
            i += 1
        elif s.startswith("<!--", i):
            comment = True
            i += 4
        elif s[i] == "`":
            code = True
            i += 1
        elif s.startswith("**", i):
            bold = not bold
            toggles.append(i)
            i += 2
        elif s.startswith("~~", i):
            strike = not strike
            i += 2
        elif s[i] == "*":
            italic = not italic
            i += 1
        elif s[i] == "[":
            br += 1
            i += 1
        elif s[i] == "]":
            br = max(0, br - 1)
            i += 1
        elif s[i] == "(":
            par += 1
            i += 1
        elif s[i] == ")":
            par = max(0, par - 1)
            i += 1
        elif s[i] == '"' and not (i and s[i - 1].isdigit()):
            quote = not quote
            i += 1
        elif s[i] == "“":
            quote = True
            i += 1
        elif s[i] == "”":
            quote = False
            i += 1
        else:
            i += 1
        p = i
        if (0 < p and not s[p - 1].isspace() and (p == n or s[p].isspace())
                and s[p - 1] != "\\" and not (code or comment or italic or quote or strike)
                and br == 0 and par == 0):
            end = s[:p].rstrip("*_`")
            pts.append((p, bold, end[-1:] in (".", ";", ":", "!", "?")))
    return pts, toggles, {"bold": bold, "italic": italic, "code": code, "comment": comment,
                          "bracket": br, "paren": par}


_CODE_SPAN = re.compile(r"`[^`\n]*`")
_COMMENT = re.compile(r"<!--.*?-->", re.S)


def balanced(s):
    """(ok, what is left open) for a finished stub line.

    Written apart from scan() on purpose: this is the pre-write check on what the cutter
    produced, and a check that reuses the cutter's own walk shares its blind spots.
    """
    left = []
    t = _COMMENT.sub("", s)
    if "<!--" in t:
        left.append("comment")
    t = _CODE_SPAN.sub("", t)
    if "`" in t:
        left.append("code")
    t = re.sub(r"\\.", "", t)                      # escaped characters are plain text
    if t.count("**") % 2:
        left.append("bold")
    if t.replace("**", "").count("*") % 2:
        left.append("italic")
    if t.count("~~") % 2:
        left.append("strikethrough")
    for opener, closer, name in (("[", "]", "bracket"), ("(", ")", "paren")):
        depth = 0
        for ch in t:
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth = max(0, depth - 1)
        if depth:
            left.append(name)
    return not left, left


def stub_head(head):
    """The start of a row's head, cut where markdown is closed, with an open bold closed."""
    pts, toggles, _ = scan(head)
    m = MIN_KEEP_RE.match(head)
    min_keep = m.end() if m else 0
    by_pos = {p: (p, b, e) for p, b, e in pts}
    chosen = None
    if len(toggles) >= 4:                       # the end of the second bold pair: a head claim
        p2 = toggles[3] + 2
        if p2 <= PAIR2_MAX and p2 in by_pos and p2 > min_keep:
            chosen = by_pos[p2]
    if chosen is None:
        eligible = [t for t in pts if t[0] > min_keep]
        within = [t for t in eligible if t[0] <= BUDGET]
        sentence = [t for t in within if t[2] and t[0] >= BUDGET // 2]
        if sentence:
            chosen = sentence[-1]
        elif within:
            chosen = within[-1]
        else:
            beyond = [t for t in eligible if t[0] <= HARD_MAX]
            chosen = beyond[0] if beyond else None
    if chosen is None:                          # nothing clean: keep just the id and marker
        cut = min_keep
        bold_open = head[:cut].count("**") % 2 == 1
    else:
        cut, bold_open = chosen[0], chosen[1]
    out = head[:cut].rstrip()
    if bold_open:
        out += "**"
    return out, cut < len(head.rstrip())


def pointer(style, rel):
    target = "<%s>" % rel if " " in rel else rel
    if style == "plain":
        return " [full row -> %s]" % rel
    if style == "archive-link":
        return " %s [archive](%s)" % (ARROW, target)
    return " %s **[full row %s `%s`](%s)**" % (ELLIPSIS, ARROW, rel, target)


def make_stub(head, style, rel):
    h, _truncated = stub_head(head)
    return h + pointer(style, rel)


def stub_style(lines):
    """The docket's own stub style: the most common one already in it (else arrow-link)."""
    counts = {name: 0 for name, _ in STYLE_RES}
    for ln in lines:
        ln = uncr(ln)
        for name, rx in STYLE_RES:
            if rx.search(ln):
                counts[name] += 1
                break
    best = max(counts, key=lambda k: (counts[k], k == "arrow-link"))
    return (best if counts[best] else "arrow-link"), counts


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------

REFDEF_RE = re.compile(r"^( {0,3}\[[^\]\n]+\]:[ \t]*)(<[^>\n]+>|\S+)", re.M)


def rewrite_links(text, from_dir, to_dir, source_first=True):
    """Re-point relative links in text moved from from_dir into to_dir (G#614).

    A moved row was written against from_dir, so a link that resolves there is re-pointed
    at the same target from to_dir -- even when a same-named file happens to exist in to_dir
    (source_first). --repair-links reads archives that may already be archive-relative, so it
    passes source_first=False: a link that already resolves at the destination stays.
    Inline links and reference definitions both count; an angle-bracket target keeps its
    brackets; a link inside a code span is never touched; a #fragment or ?query rides along.
    A target counts when it is a FILE, or a directory written with a trailing slash (prose
    such as '[[G#87]](a)' can name a folder by accident). A link that resolves nowhere is
    left alone and returned for the report.
    """
    changed, unresolved = [], []
    from_dir, to_dir = Path(from_dir), Path(to_dir)
    spans = [m.span() for m in _CODE_SPAN.finditer(text)]

    def in_code(pos):
        return any(a <= pos < b for a, b in spans)

    def target(link):
        """(new link or None, whether it resolved anywhere)."""
        angle = link.startswith("<") and link.endswith(">")
        inner = link[1:-1] if angle else link
        if inner.startswith(("http://", "https://", "mailto:", "#", "~", "/")) or \
                re.match(r"^[A-Za-z]:[\\/]", inner) or re.match(r"^[a-z][a-z0-9+.-]*:", inner):
            return None, True
        cut = min([k for k in (inner.find("#"), inner.find("?")) if k >= 0] or [len(inner)])
        path, tail = inner[:cut], inner[cut:]
        if not path:
            return None, True

        def ok(p):
            return p.is_file() or (path.endswith("/") and p.is_dir())

        at_dest, at_src = ok(to_dir / path), ok(from_dir / path)
        if at_dest and (not source_first or not at_src):
            return None, True
        if not at_src:
            return None, False
        try:
            new = os.path.relpath(str((from_dir / path).resolve()),
                                  str(to_dir.resolve())).replace("\\", "/")
        except ValueError:                      # another drive on Windows
            return None, False
        if path.endswith("/") and not new.endswith("/"):
            new += "/"
        if new == path:
            return None, True
        return ("<%s>" % (new + tail)) if angle else (new + tail), True

    def inline(m):
        if in_code(m.start()):
            return m.group(0)
        new, found = target(m.group(1))
        if new is None:
            if not found:
                unresolved.append(m.group(1))
            return m.group(0)
        changed.append((m.group(1), new))
        return "](%s)" % new

    def refdef(m):
        if in_code(m.start()):
            return m.group(0)
        new, found = target(m.group(2))
        if new is None:
            if not found:
                unresolved.append(m.group(2))
            return m.group(0)
        changed.append((m.group(2), new))
        return m.group(1) + new

    out = LINK_RE.sub(inline, text)
    spans = [m.span() for m in _CODE_SPAN.finditer(out)]
    return REFDEF_RE.sub(refdef, out), changed, unresolved


# --------------------------------------------------------------------------------------
# Planning (pure: reads bytes it is given, writes nothing)
# --------------------------------------------------------------------------------------

def _spans(row_of):
    spans = {}
    for i, r in enumerate(row_of):
        if r is not None:
            if id(r) in spans:
                spans[id(r)][1] = i
            else:
                spans[id(r)] = [i, i]
    return spans


def archived_ids(dc, root, archive_files):
    ids = set()
    for p in archive_files:
        raw = Path(p).read_bytes()
        rows, _ro, _l, _e = dc.parse_bytes(raw, root=root, kind="archive", rel=Path(p).name)
        ids |= {r["id"].casefold() for r in rows
                if r["grammar"] in ID_GRAMMARS and not r["key"].startswith("@")}
    return ids


def block_regions(lines):
    """[(first, last)] of every fenced code block and multi-line HTML comment (inclusive).

    The shared parser tracks neither, so a '# comment' inside a fence reads to it as a
    heading and a '- **#N**' inside one as a row. A row that a region crosses, or whose head
    sits inside one, is never moved.
    """
    out, i, n = [], 0, len(lines)
    while i < n:
        ln = uncr(lines[i])
        m = FENCE_RE.match(ln)
        if m:
            mark, j = m.group(1), i + 1
            while j < n:
                m2 = FENCE_RE.match(uncr(lines[j]))
                if (m2 and m2.group(1)[0] == mark[0] and len(m2.group(1)) >= len(mark)
                        and not uncr(lines[j]).strip()[len(m2.group(1)):].strip()):
                    break
                j += 1
            out.append((i, min(j, n - 1)))
            i = j + 1
            continue
        k = ln.find("<!--")
        if k >= 0 and ln.find("-->", k + 4) < 0:
            j = i + 1
            while j < n and "-->" not in lines[j]:
                j += 1
            out.append((i, min(j, n - 1)))
            i = j + 1
            continue
        i += 1
    return out


def crosses_block(regions, a, c):
    """A fence or comment overlaps lines a..c without lying wholly inside them."""
    return any(s <= c and e >= a and not (s >= a and e <= c) for s, e in regions)


def body_is_one_item(lines, a, c):
    """Markdown reads lines a..c as ONE item. After the head, a column-0 line may only be a
    lazy continuation: no blank line before it, and not the start of an HTML block, a table
    or a fence. Only a list row may carry indented lines after a blank line."""
    list_head = bool(LIST_HEAD.match(uncr(lines[a])))
    prev_blank = False
    for raw in lines[a + 1:c + 1]:
        ln = uncr(raw)
        if not ln.strip():
            prev_blank = True
            continue
        col0 = ln[:1] not in (" ", "\t")
        if col0 and (ln.startswith(("<", "|")) or FENCE_RE.match(ln)):
            return False
        if prev_blank and (col0 or not list_head):
            return False
        prev_blank = False
    return True


def ends_cleanly(lines, head_lines, a, b, c):
    """Nothing directly below the row (with no blank line between) is something markdown
    would join to it: a quote or list continuation, an HTML block, a setext underline."""
    if b > c:
        return True
    nxt = c + 1
    if nxt >= len(lines):
        return True
    ln = uncr(lines[nxt])
    if not ln.strip() or nxt in head_lines or HEADING_RE.match(ln):
        return True
    if SETEXT_RE.match(ln):                    # '---' under a stub turns it into a heading
        return False
    head = uncr(lines[a])
    return bool(LIST_HEAD.match(head) and not head.startswith(">")
                and re.match(r"^(?:[-*+] |\d+\. )", ln))


LEAD_RE = re.compile(r"^\s*(?:>\s*)*(?:[-*+] |\d+\. )?")


def plan(dc, rl, *, docket_raw, docket_rel, docket_dir, root, archive_path, archive_raw,
         archive_rel, archived, date_text, min_bytes=MIN_BYTES):
    """Everything the run would do, as data. Nothing touches disk here."""
    text, bom = decode(docket_raw, docket_rel)
    lines = text.split("\n")
    rows, row_of, dlines, cfg_err = dc.parse_bytes(docket_raw, root=root, kind="docket",
                                                    rel=docket_rel)
    if len(dlines) != len(lines):
        raise EnvError("could not rotate: the shared parser read %d lines, this tool %d"
                       % (len(dlines), len(lines)))
    style, style_counts = stub_style(lines)
    ptr_rel = os.path.relpath(str(archive_path), str(docket_dir)).replace("\\", "/")
    spans = _spans(row_of)
    regions = block_regions(lines)
    # Rulings are read over the WHOLE file, as the briefing reads them: a section heading
    # such as 'Ruled out' makes the rows under it rulings, which the row alone cannot show.
    ruling_lines = {h["line"] - 1 for h in rl.rulings_in_text(
        docket_rel, "\n".join(uncr(ln) for ln in lines))}
    head_lines = {spans[id(r)][0] for r in rows
                  if r["grammar"] in ID_GRAMMARS and not r["key"].startswith("@")}
    skipped = {k: [] for k in ("open", "unknown", "stub", "archived", "ruling", "decision",
                               "reopened", "small", "fence", "ambiguous", "short", "split")}
    rotations = []
    n_id_rows = 0
    for idx, r in enumerate(rows):
        if r["grammar"] not in ID_GRAMMARS or r["key"].startswith("@"):
            continue
        n_id_rows += 1
        a, b = spans[id(r)]
        if r["state"] != "closed":
            skipped["open" if r["state"] == "open" else "unknown"].append(r["id"])
            continue
        if r["stub"]:
            skipped["stub"].append(r["id"])
            continue
        if any(row_of[i] is not r for i in range(a, b + 1)):
            skipped["split"].append(r["id"])
            continue
        c = b
        while c > a and blank(lines[c]):
            c -= 1
        if crosses_block(regions, a, c):
            skipped["fence"].append(r["id"])
            continue
        if not body_is_one_item(lines, a, c) or not ends_cleanly(lines, head_lines, a, b, c):
            skipped["ambiguous"].append(r["id"])
            continue
        if r["id"].casefold() in archived:
            skipped["archived"].append(r["id"])
            continue
        body_lines = [uncr(ln) for ln in lines[a:c + 1]]
        body = "\n".join(body_lines)
        if len(body.encode("utf-8")) < min_bytes:
            skipped["small"].append(r["id"])
            continue
        if any(i in ruling_lines for i in range(a, c + 1)) or rl.rulings_in_text(docket_rel, body):
            skipped["ruling"].append(r["id"])
            continue
        if any(rx.search(body) for rx in DECISION_RES):
            skipped["decision"].append(r["id"])
            continue
        if any(dc.status_of(LEAD_RE.sub("", ln, count=1)) == "open"
               for ln in body_lines[1:] if ln.strip()):
            skipped["reopened"].append(r["id"])
            continue
        stub = make_stub(body_lines[0], style, ptr_rel)
        if len(stub) >= len(body):
            skipped["short"].append(r["id"])
            continue
        rotations.append({"row": r, "index": idx, "a": a, "c": c, "b": b, "body": body,
                          "stub": stub + ("\r" if lines[a].endswith("\r") else "")})

    # The docket with each moved row's lines (a..c) replaced by its stub; any blank lines
    # after a row (c+1..b) stay, so the stub occupies its row's place in the list.
    new_lines = list(lines)
    for rot in reversed(rotations):
        new_lines[rot["a"]:rot["c"] + 1] = [rot["stub"]]
    new_text = "\n".join(new_lines)
    new_docket_raw = encode(new_text, bom)

    # The archive block.
    if archive_raw is not None:
        a_text, a_bom = decode(archive_raw, archive_rel)
        dest_eol = eol_of(a_text, eol_of(text))
    else:
        a_text, a_bom = "", False
        dest_eol = eol_of(text)
    link_changes, link_unresolved, chunks, moved = [], [], [], []
    for rot in rotations:
        body, ch, un = rewrite_links(rot["body"], docket_dir, Path(archive_path).parent)
        link_changes += ch
        link_unresolved += un
        rot["archived_body"] = body
        moved.append(body)
        chunks.append(body)
        chunks.extend([""] * (rot["b"] - rot["c"]))
    while chunks and chunks[-1] == "":
        chunks.pop()
    heading = "## Rotated %s %s %d closed row%s" % (date_text, DASH, len(rotations),
                                                   "" if len(rotations) == 1 else "s")
    if archive_raw is None:
        back = os.path.relpath(str(Path(docket_dir) / Path(docket_rel).name),
                               str(Path(archive_path).parent)).replace("\\", "/")
        back = "<%s>" % back if " " in back else back
        name = Path(docket_rel).name
        head = ["# Closed docket rows %s %s" % (DASH, name), "",
                "Rows rotated out of [`%s`](%s) by update-context's `rotate-docket.py`. Each "
                "row is moved verbatim (relative links re-pointed for this directory); a "
                "one-line stub with the same id and marker, pointing here, stays in the "
                "docket." % (name, back), ""]
        block = head + [heading, ""] + chunks + [""]
        new_a_text = dest_eol.join(lf("\n".join(block)).split("\n"))
    else:
        prefix = a_text
        if prefix and not prefix.endswith("\n"):
            prefix += dest_eol
        block = ["", heading, ""] + chunks + [""]
        new_a_text = prefix + dest_eol.join(lf("\n".join(block)).split("\n"))
    new_archive_raw = encode(new_a_text, a_bom)
    # Counted per LINE, not by comparing the two files' majorities: a CRLF line inside an LF
    # docket is converted too, and the report must say so.
    converted = 0
    for rot in rotations:
        for i in range(rot["a"], rot["c"] + 1):
            if i == len(lines) - 1:
                continue                        # the file's last line carries no terminator
            if lines[i].endswith("\r") != (dest_eol == "\r\n"):
                converted += 1

    return {
        "text": text, "lines": lines, "rows": rows, "rotations": rotations,
        "skipped": skipped, "n_id_rows": n_id_rows, "style": style, "min_bytes": min_bytes,
        "style_counts": style_counts, "pointer_rel": ptr_rel, "cfg_err": cfg_err,
        "new_lines": new_lines, "new_docket_raw": new_docket_raw,
        "new_archive_raw": new_archive_raw, "moved": moved, "dest_eol": dest_eol,
        "converted": converted, "link_changes": link_changes,
        "link_unresolved": link_unresolved, "archive_raw": archive_raw,
    }


# --------------------------------------------------------------------------------------
# Checks (both directions, before anything is written)
# --------------------------------------------------------------------------------------

def seq(rows):
    return [(r["id"], r["state"], r["grammar"]) for r in rows]


def outside_unchanged(lines, new_lines, rotations):
    """Every line outside a moved row survives byte-identically and in order, and each
    moved span is replaced by exactly its own stub line."""
    rots = sorted(rotations, key=lambda r: r["a"])
    moved = set()
    for rot in rots:
        moved.update(range(rot["a"], rot["c"] + 1))
    kept_old = [ln for i, ln in enumerate(lines) if i not in moved]
    stub_at, shift = [], 0
    for rot in rots:
        stub_at.append(rot["a"] - shift)
        shift += rot["c"] - rot["a"]
    if any(i >= len(new_lines) for i in stub_at):
        return False
    at = set(stub_at)
    kept_new = [ln for i, ln in enumerate(new_lines) if i not in at]
    return kept_old == kept_new and [new_lines[i] for i in stub_at] == [r["stub"] for r in rots]


def checks(dc, pl, root, docket_rel, archive_rel):
    out = []
    rows, rots = pl["rows"], pl["rotations"]
    new_rows, _ro, _l, _e = dc.parse_bytes(pl["new_docket_raw"], root=root, kind="docket",
                                           rel=docket_rel)
    out.append(("the docket still reads as the same rows, ids and states, in order",
                seq(rows) == seq(new_rows)))
    idx = {rot["index"] for rot in rots}
    out.append(("every moved row now reads as a stub",
                len(new_rows) == len(rows) and all(new_rows[i]["stub"] for i in idx)))
    out.append(("no other row became or stopped being a stub",
                len(new_rows) == len(rows) and all(new_rows[i]["stub"] == rows[i]["stub"]
                                                   for i in range(len(rows)) if i not in idx)))
    out.append(("every line outside a moved row is unchanged, in order",
                outside_unchanged(pl["lines"], pl["new_lines"], rots)))
    bad = [rot["row"]["id"] for rot in rots if not balanced(uncr(rot["stub"]))[0]]
    out.append(("every new stub leaves no bold, italic, code, comment, bracket or "
                "parenthesis open" + (" (open in %s)" % ", ".join(bad) if bad else ""),
                not bad))
    new_docket_lf = lf(pl["new_docket_raw"].decode("utf-8", errors="replace"))
    out.append(("no moved row's body is left in the docket",
                not any(rot["body"] in new_docket_lf for rot in rots)))
    old_blank = sum(1 for ln in pl["lines"] if blank(ln))
    new_blank = sum(1 for ln in pl["new_lines"] if blank(ln))
    interior = sum(sum(1 for ln in rot["body"].split("\n") if blank(ln)) for rot in rots)
    out.append(("blank lines change only by those inside moved rows",
                old_blank - new_blank == interior))
    arch_lf = lf(pl["new_archive_raw"].decode("utf-8", errors="replace"))
    out.append(("every moved row is in the archive (CR before LF ignored)",
                all(lf(rot["archived_body"]) in arch_lf for rot in rots)))
    if pl["archive_raw"] is not None:
        out.append(("the archive's existing bytes are untouched (append only)",
                    pl["new_archive_raw"].startswith(pl["archive_raw"].rstrip(b"\r\n"))))
        old_a = dc.parse_bytes(pl["archive_raw"], root=root, kind="archive", rel=archive_rel)[0]
    else:
        old_a = []
    new_a = dc.parse_bytes(pl["new_archive_raw"], root=root, kind="archive", rel=archive_rel)[0]
    gained = [r["id"] for r in new_a if r["grammar"] in ID_GRAMMARS][
        len([r for r in old_a if r["grammar"] in ID_GRAMMARS]):]
    out.append(("the archive gained exactly the moved rows, in order",
                gained == [rot["row"]["id"] for rot in rots]))
    return out


# --------------------------------------------------------------------------------------
# Writing (the contract's order, with rollback)
# --------------------------------------------------------------------------------------

def atomic_write_bytes(path, data):
    """Temp sibling, read back, replace -- the real file is never opened for writing.

    The same contract as the central atomic_write_text (G#651), in bytes so line endings
    survive exactly; that helper is not installed with skills, so it cannot be imported.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        with open(tmp, "rb") as fh:
            if fh.read() != data:
                raise IOError("temp file did not round-trip; %s left untouched" % path)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def restore(path, raw):
    if raw is None:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    else:
        atomic_write_bytes(path, raw)


def apply(dc, pl, *, docket_path, archive_path, root, docket_rel, archive_rel):
    """Write in the contract's order. Returns (ok, message); an OS error never escapes.

    Each file is compared with the bytes this plan was made from immediately before it is
    replaced, and a rollback only puts back bytes THIS run wrote -- never over a write that
    another session made in between.
    """
    docket_path, archive_path = Path(docket_path), Path(archive_path)

    def archive_now():
        return archive_path.read_bytes() if archive_path.exists() else None

    def undo_archive(why, docket_note="docket untouched"):
        if archive_now() not in (pl["new_archive_raw"], data):
            return False, (why + "; the archive changed again after this run wrote it, so it "
                           "was NOT restored -- check it; " + docket_note)
        try:
            restore(archive_path, pl["archive_raw"])
        except OSError as e:
            return False, why + "; restoring the archive failed too (%s) -- check it" % e
        return False, why + "; archive restored, " + docket_note

    if docket_path.read_bytes() != pl["original_docket_raw"]:
        return False, "the docket changed on disk after it was read (another session?); re-run"
    if archive_now() != pl["archive_raw"]:
        return False, "the archive changed on disk after it was read (another session?); re-run"
    data = pl["new_archive_raw"]
    if _FAULT == "archive-short":           # selftest only: the re-read below must catch it
        data = data[:-40]
    try:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(archive_path, data)
    except OSError as e:
        return False, "could not write the archive (%s); nothing changed" % e
    raw_back = archive_now() or b""
    back = lf(raw_back.decode("utf-8", errors="replace"))
    missing = [rot["row"]["id"] for rot in pl["rotations"]
               if lf(rot["archived_body"]) not in back]
    if pl["archive_raw"] is not None and not raw_back.startswith(pl["archive_raw"].rstrip(b"\r\n")):
        missing.append("its earlier bytes")
    if missing:
        return undo_archive("the archive re-read from disk is missing %s" % ", ".join(missing))
    if _FAULT == "docket-changes":          # selftest only: another session edits the docket now
        docket_path.write_bytes(docket_path.read_bytes() + b"- **#99** added by another session\n")
    if docket_path.read_bytes() != pl["original_docket_raw"]:
        return undo_archive("the docket changed while the archive was written (another session?)")
    try:
        if _FAULT == "docket-raise":        # selftest only: a sharing violation on the docket
            raise PermissionError(13, "simulated: the docket is open in another program")
        atomic_write_bytes(docket_path, pl["new_docket_raw"])
    except OSError as e:
        return undo_archive("could not write the docket (%s)" % e)
    got = docket_path.read_bytes()
    if got != pl["new_docket_raw"]:
        return False, ("the docket changed right after this run wrote it (another session?); "
                       "neither file was restored, so that write is not overwritten -- check that "
                       "every moved row is a stub in %s and a body in %s"
                       % (docket_path.name, archive_path.name))
    after = dc.parse_bytes(got, root=root, kind="docket", rel=docket_rel)[0]
    if seq(after) != seq(pl["rows"]):
        try:
            atomic_write_bytes(docket_path, pl["original_docket_raw"])
        except OSError as e:
            return False, ("the docket re-parse did not match and restoring it failed (%s) -- "
                           "check it" % e)
        return undo_archive("the docket re-parse did not match", "docket restored")
    return True, "%s and rewrote %s" % (archive_path.name, docket_path.name)


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------

def git_root(start):
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(start),
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=20)
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def find_docket(dc, root):
    files = [f for f in dc.discover(project="root:%s" % root) if f["kind"] == "docket"]
    with_rows = []
    for f in files:
        raw = Path(f["path"]).read_bytes()
        rows = dc.parse_bytes(raw, root=root, kind="docket", rel=Path(f["path"]).name)[0]
        if any(r["grammar"] in ID_GRAMMARS and not r["key"].startswith("@") for r in rows):
            with_rows.append(Path(f["path"]))
    if len(with_rows) == 1:
        return with_rows[0]
    if not with_rows:
        raise EnvError("could not rotate: no docket file with row ids found under %s "
                       "(pass --docket)" % root)
    raise EnvError("could not rotate: several docket files under %s -- pass --docket one of: %s"
                   % (root, ", ".join(str(p) for p in with_rows)))


def run(args):
    dc, rl = load_deps()
    if args.docket:
        docket_path = Path(args.docket).resolve()
        if not docket_path.is_file():
            raise EnvError("could not rotate: %s is not a file" % args.docket)
        root = Path(args.root).resolve() if args.root else (
            git_root(docket_path.parent) or Path.cwd().resolve())
    else:
        root = Path(args.root).resolve() if args.root else (git_root(Path.cwd()) or Path.cwd().resolve())
        docket_path = find_docket(dc, root)
    stamp = args.stamp or datetime.date.today().strftime("%Y-%m")
    if not re.fullmatch(r"\d{4}-\d{2}", stamp):
        raise EnvError("--stamp must be YYYY-MM, got %r" % stamp)
    archive_path = (Path(args.archive).resolve() if args.archive else
                    docket_path.parent / "archive" / ("%s-closed-%s.md" % (docket_path.stem, stamp)))
    try:
        docket_rel = docket_path.relative_to(root).as_posix()
    except ValueError:
        docket_rel = docket_path.name
    try:
        archive_rel = archive_path.relative_to(root).as_posix()
    except ValueError:
        archive_rel = archive_path.name

    if args.repair_links:
        return repair_links(docket_path.parent, archive_path.parent, apply_=args.apply)

    docket_raw = docket_path.read_bytes()
    archive_raw = archive_path.read_bytes() if archive_path.exists() else None
    files = [Path(f["path"]) for f in dc.discover(project="root:%s" % root)
             if f["kind"] == "archive"]
    if archive_path.exists() and all(os.path.normcase(str(p.resolve())) !=
                                     os.path.normcase(str(archive_path)) for p in files):
        files.append(archive_path)
    archived = archived_ids(dc, root, files)
    date_text = args.date or datetime.date.today().isoformat()
    pl = plan(dc, rl, docket_raw=docket_raw, docket_rel=docket_rel,
              docket_dir=docket_path.parent, root=root, archive_path=archive_path,
              archive_raw=archive_raw, archive_rel=archive_rel, archived=archived,
              date_text=date_text, min_bytes=args.min_bytes)
    pl["original_docket_raw"] = docket_raw
    report(pl, docket_path, archive_path, archive_raw, len(files), root)
    res = checks(dc, pl, root, docket_rel, archive_rel)
    print()
    for name, ok in res:
        print("%s %s" % ("PASS" if ok else "FAIL", name))
    failed = [n for n, ok in res if not ok]
    print()
    if not pl["rotations"]:
        print("EFFECT   nothing to rotate: no closed row is eligible (see 'kept' above)")
        return 1 if failed else 0
    if failed:
        print("REFUSING TO WRITE - %d check(s) failed: %s" % (len(failed), "; ".join(failed)))
        return 1
    if not args.apply:
        print("DRY RUN - nothing written. Re-run with --apply.")
        return 0
    ok, msg = apply(dc, pl, docket_path=docket_path, archive_path=archive_path, root=root,
                    docket_rel=docket_rel, archive_rel=archive_rel)
    print(("WROTE " if ok else "REFUSED - ") + msg)
    return 0 if ok else 1


def report(pl, docket_path, archive_path, archive_raw, n_archives, root):
    rel = lambda p: os.path.relpath(str(p), str(root)).replace("\\", "/")
    eol = lambda e: "CRLF" if e == "\r\n" else "LF"
    b_old, b_new = len(pl["original_docket_raw"]), len(pl["new_docket_raw"])
    print("docket:      %s  (%s bytes, %s)" % (rel(docket_path), format(b_old, ","),
                                               eol(eol_of(pl["text"]))))
    if archive_raw is None:
        print("archive:     %s  (NEW)" % rel(archive_path))
    else:
        print("archive:     %s  (APPEND to %s bytes, %s)" % (rel(archive_path),
                                                            format(len(archive_raw), ","),
                                                            eol(pl["dest_eol"])))
    print("stub style:  %s  (existing stubs: %s)" % (
        pl["style"], ", ".join("%s %d" % kv for kv in pl["style_counts"].items())))
    if pl["cfg_err"]:
        print("config:      %s" % pl["cfg_err"])
    print("rows:        %d with an id; archives read: %d" % (pl["n_id_rows"], n_archives))
    ids = [rot["row"]["id"] for rot in pl["rotations"]]
    print("rotating:    %d%s" % (len(ids), ("  " + " ".join(ids)) if ids else ""))
    labels = (("stub", "already a stub"), ("archived", "already in an archive"),
              ("ruling", "carry a standing ruling (stay live)"),
              ("decision", "carry a standing decision (stay live)"),
              ("reopened", "closed head but an open line in the body (stay live)"),
              ("small", "under %d bytes (a stub would save too little)" % pl["min_bytes"]),
              ("short", "already shorter than their stub"),
              ("fence", "a code fence or HTML comment crosses the row (not guessed at)"),
              ("ambiguous", "markdown does not end the row cleanly (not guessed at)"),
              ("split", "rows whose lines are not contiguous"),
              ("unknown", "state unknown (no status, or glyph and word disagree)"),
              ("open", "open"))
    for key, label in labels:
        v = pl["skipped"][key]
        if v:
            shown = " ".join(v[:12]) + (" ..." if len(v) > 12 else "")
            print("kept:        %4d %s%s" % (len(v), label,
                                            "" if key in ("stub", "small", "short", "open")
                                            else "  " + shown))
    if pl["converted"]:
        print("line ends:   %d moved line(s) converted to %s to match the archive"
              % (pl["converted"], eol(pl["dest_eol"])))
    print("links:       %d re-pointed for the archive dir, %d resolve nowhere (left as is)"
          % (len(pl["link_changes"]), len(set(pl["link_unresolved"]))))
    for o, n in pl["link_changes"][:6]:
        print("             %s -> %s" % (o, n))
    print("docket:      %s -> %s bytes (%+d)" % (format(b_old, ","), format(b_new, ","),
                                                  b_new - b_old))
    print("archive:     %s -> %s bytes" % (format(len(archive_raw or b""), ","),
                                           format(len(pl["new_archive_raw"]), ",")))


def repair_links(docket_dir, archive_dir, apply_):
    """Re-point relative links in existing archive files that older rotations moved as is."""
    total, files = 0, 0
    for p in sorted(Path(archive_dir).glob("*.md")):
        raw = p.read_bytes()
        text, bom = decode(raw, p.name)
        out, changed, unres = rewrite_links(text, docket_dir, archive_dir, source_first=False)
        if changed:
            files += 1
            total += len(changed)
            print("%s: %d link(s) re-pointed" % (p.name, len(changed)))
            for o, n in changed[:8]:
                print("    %s -> %s" % (o, n))
            if apply_:
                atomic_write_bytes(p, encode(out, bom))
        if unres:
            print("%s: %d link(s) resolve nowhere (left as is)" % (p.name, len(set(unres))))
    print("\nre-pointed %d link(s) across %d file(s)%s"
          % (total, files, "" if apply_ else " (DRY RUN, nothing written)"))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docket", help="the docket file (default: the project's only docket file)")
    ap.add_argument("--archive", help="archive file (default: <docket dir>/archive/"
                                      "<stem>-closed-<YYYY-MM>.md)")
    ap.add_argument("--root", help="project root (default: the docket's git top level)")
    ap.add_argument("--stamp", help="archive month, YYYY-MM (default: this month)")
    ap.add_argument("--date", help="date for the archive heading (default: today)")
    ap.add_argument("--min-bytes", type=int, default=MIN_BYTES,
                    help="rows smaller than this stay live (default %d)" % MIN_BYTES)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    g.add_argument("--dry-run", action="store_true", help="report only; write nothing (default)")
    g.add_argument("--selftest", action="store_true", help="run the built-in fixtures")
    ap.add_argument("--repair-links", action="store_true",
                    help="re-point links in existing archive files (dry run unless --apply)")
    args = ap.parse_args(argv)
    try:
        if args.selftest:
            return selftest()
        return run(args)
    except EnvError as e:
        print(str(e), file=sys.stderr)
        return 2


# --------------------------------------------------------------------------------------
# Selftest: every arm is discriminating -- each would fail on the defect it names.
# --------------------------------------------------------------------------------------

def selftest():
    global _FAULT
    dc, rl = load_deps()
    passed = failed = 0

    def expect(cond, name):
        nonlocal passed, failed
        print("%s %s" % ("PASS" if cond else "FAIL", name))
        if cond:
            passed += 1
        else:
            failed += 1

    # Long enough that every row meant to move clears the --min-bytes floor on its own.
    filler = " More words that make the row longer than any stub it could leave." * 10
    tmp = Path(tempfile.mkdtemp(prefix="rotate-docket-selftest-"))
    try:
        # ---- Fixture A: bare #N rows, an existing arrow-link stub, a CRLF archive to append to
        a = tmp / "a"
        (a / "archive").mkdir(parents=True)
        (a / "notes.md").write_bytes(b"x")
        docket_a = (
            "# Docket\n\n<!-- last assigned: #9 -->\n\n"
            "- **#1** \U0001F7E2 **OPEN " + DASH + " an open row.** body\n"
            "- **#2** ✅ **DONE 2026-09-01 " + DASH + " shipped the widget (see [notes](notes.md));"
            " the gate reads 8/8 again.**" + filler + "\n"
            "- **Hygiene " + DASH + " a top-level note that is not part of #2 and is still open**\n"
            "- **#3 ✅ DONE 2026-09-02 (machine, owner-delegated): the whole head runs in bold"
            " past the id (with a long parenthetical that must never be cut in half, because a"
            " cut inside it would leave the paren open for the rest of the page) and it keeps"
            " going well past any budget" + filler + "**\n"
            "  - an indented sub-point owned by #3\n"
            "- **#4** ✅ **CLOSED 2026-09-03.** Do not re-propose the XLSX export for billing."
            + filler + "\n"
            "- **#5** ✅ **DONE.**\n"
            "- **#6** ⛔ **WONT " + DASH + " declined.**" + filler + "\n"
            "- **#7** ✅ **DONE 2026-08-01 " + DASH + " already archived.**" + filler + "\n"
            "- **#8** ✅ **DONE " + DASH + " shipped.** " + ELLIPSIS + " **[full row " + ARROW
            + " `archive/roadmap-closed-2026-08.md`](archive/roadmap-closed-2026-08.md)**\n"
            "- **#10** ✅ **DONE 2026-09-05 " + DASH + " the page wave stops at 7.** New effort goes"
            " to the hubs; the owner chose that on 2026-09-26." + filler + "\n"
            "- **#11** ✅ **DONE 2026-09-06 (machine, owner-delegated): shipped the gate.**"
            + filler + "\n"
            "- **#9** ✅ **DONE 2026-09-04 " + DASH + " a row whose body markdown ends.**"
            + filler + "\n\nA column-0 paragraph after a blank line: markdown ended the item.\n"
        )
        (a / "roadmap.md").write_bytes(docket_a.encode("utf-8"))
        (a / "archive" / "roadmap-closed-2026-08.md").write_bytes(
            ("# Old\n\n- **#7** ✅ **DONE 2026-08-01 " + DASH + " already archived.** old body\n")
            .encode("utf-8"))
        old_archive = "# Closed rows\r\n\r\n- **#0** ✅ **DONE.** an older row\r\n"
        (a / "archive" / "roadmap-closed-2026-09.md").write_bytes(old_archive.encode("utf-8"))

        def plan_for(root, stamp="2026-09"):
            dpath = root / "roadmap.md"
            apath = root / "archive" / ("roadmap-closed-%s.md" % stamp)
            files = [Path(f["path"]) for f in dc.discover(project="root:%s" % root)
                     if f["kind"] == "archive"]
            pl = plan(dc, rl, docket_raw=dpath.read_bytes(), docket_rel="roadmap.md",
                      docket_dir=root, root=root, archive_path=apath,
                      archive_raw=apath.read_bytes() if apath.exists() else None,
                      archive_rel="archive/" + apath.name,
                      archived=archived_ids(dc, root, files), date_text="2026-09-27")
            pl["original_docket_raw"] = dpath.read_bytes()
            return pl, dpath, apath

        pl, dpath, apath = plan_for(a)
        ids = [rot["row"]["id"] for rot in pl["rotations"]]
        expect(ids == ["#2", "#3", "#11"],
               "A: moves exactly the eligible closed rows (#2, #3, #11): %s" % ids)
        sk = pl["skipped"]
        # #10 must stay a decision the ruling GRAMMAR does not read, or the decision arm below
        # tests the grammar instead of the net. It did go stale once: #10 used to read OWNER
        # RATIFIED, which the rulings rebuild taught the grammar, so the net was never reached.
        row10 = next(ln for ln in docket_a.split("\n") if ln.startswith("- **#10**"))
        expect(not rl.rulings_in_text("roadmap.md", row10),
               "A premise: the ruling grammar does not read #10's owner decision")
        expect(sk["ruling"] == ["#4"], "A: a row carrying a standing ruling stays live")
        expect(sk["decision"] == ["#10"],
               "A: a row carrying an owner decision the ruling grammar does not read stays live")
        expect("#11" in ids, "A: ... but 'owner-delegated' alone is not a decision, so #11 moves")
        expect(sk["small"] == ["#5"], "A: a row under --min-bytes stays")
        pl0 = plan(dc, rl, docket_raw=(a / "roadmap.md").read_bytes(), docket_rel="roadmap.md",
                   docket_dir=a, root=a, archive_path=a / "archive" / "roadmap-closed-2026-09.md",
                   archive_raw=None, archive_rel="x", archived=set(), date_text="2026-09-27",
                   min_bytes=0)
        expect("#5" in pl0["skipped"]["short"],
               "A: with no floor, a row already shorter than its stub still stays")
        expect("#6" in sk["unknown"], "A: a no-entry row reads unknown and stays")
        expect(sk["archived"] == ["#7"], "A: a row already in an archive stays")
        expect("#8" in sk["stub"], "A: an existing stub stays")
        expect(sk["ambiguous"] == ["#9"], "A: a list row whose markdown body ended is not guessed at")
        expect("#1" in sk["open"], "A: an open row stays")
        new_a = pl["new_docket_raw"].decode("utf-8")
        expect("a top-level note that is not part of #2" in new_a,
               "A: a column-0 sibling note under a closed row stays in the docket")
        arch_new = pl["new_archive_raw"].decode("utf-8")
        expect("a top-level note that is not part of #2" not in arch_new,
               "A: ... and is not copied into the archive")
        expect("an indented sub-point owned by #3" in arch_new and
               "an indented sub-point owned by #3" not in new_a,
               "A: an indented sub-point moves with its row")
        expect(pl["style"] == "arrow-link", "A: the stub style is read from the docket's own stubs")
        stubs = [uncr(rot["stub"]) for rot in pl["rotations"]]
        expect(all(s.endswith("(archive/roadmap-closed-2026-09.md)**") for s in stubs),
               "A: stubs point at this month's archive in that style")
        expect(all(balanced(s)[0] for s in stubs),
               "A: no stub leaves bold, code, bracket or parenthesis open")
        s3 = stubs[1]
        expect("(with a long parenthetical" not in s3 or s3.count("(") == s3.count(")"),
               "A: the #3 stub never cuts inside its parenthetical")
        expect(s3.startswith("- **#3 ✅ DONE") and len(s3) < len(docket_a),
               "A: the #3 stub keeps the id, marker and status word")
        expect("](../notes.md)" in arch_new and "](notes.md)" in new_a,
               "A: a link moved into archive/ is re-pointed; the docket's copy is untouched")
        expect(pl["dest_eol"] == "\r\n" and "\r\n- **#2**" in arch_new and pl["converted"],
               "A: rows appended to a CRLF archive take CRLF, and the report says so")
        expect(pl["new_archive_raw"].startswith(old_archive.encode("utf-8")),
               "A: the archive's existing bytes are kept as its prefix")
        expect(b"\r" not in pl["new_docket_raw"], "A: the LF docket stays LF")
        res = dict(checks(dc, pl, a, "roadmap.md", "archive/roadmap-closed-2026-09.md"))
        expect(all(res.values()), "A: every pre-write check passes on a correct plan")

        # ---- rejects-bad: each check must fail on the defect it names
        def with_(**kw):
            q = dict(pl)
            q.update(kw)
            return dict(checks(dc, q, a, "roadmap.md", "archive/roadmap-closed-2026-09.md"))

        dropped = [ln for ln in pl["new_lines"] if "Hygiene" not in ln]
        expect(not with_(new_lines=dropped)["every line outside a moved row is unchanged, in order"],
               "rejects-bad: losing the sibling note fails the unchanged-lines check")
        bad_rot = [dict(r) for r in pl["rotations"]]
        bad_rot[1]["stub"] = bad_rot[1]["stub"].replace("**[full row", "(**[full row")
        key = [k for k in with_(rotations=bad_rot) if k.startswith("every new stub")][0]
        expect(not with_(rotations=bad_rot)[key], "rejects-bad: a stub with an open paren fails")
        holed = pl["new_archive_raw"].replace(b"an indented sub-point owned by #3", b"")
        expect(not with_(new_archive_raw=holed)["every moved row is in the archive (CR before LF ignored)"],
               "rejects-bad: an archive missing a moved body fails")
        rewritten = pl["new_archive_raw"].replace(b"an older row", b"an edited row")
        expect(not with_(new_archive_raw=rewritten)["the archive's existing bytes are untouched (append only)"],
               "rejects-bad: rewriting the archive's earlier bytes fails")
        flipped = pl["new_docket_raw"].replace("**#1** \U0001F7E2 **OPEN".encode("utf-8"),
                                              "**#1** ✅ **DONE".encode("utf-8"))
        expect(not with_(new_docket_raw=flipped)[
            "the docket still reads as the same rows, ids and states, in order"],
            "rejects-bad: a row whose state changed fails the row check")

        # ---- the write path, in the contract's order
        ok, msg = apply(dc, pl, docket_path=dpath, archive_path=apath, root=a,
                        docket_rel="roadmap.md", archive_rel="archive/roadmap-closed-2026-09.md")
        expect(ok and dpath.read_bytes() == pl["new_docket_raw"]
               and apath.read_bytes() == pl["new_archive_raw"], "A: --apply writes both files")
        pl2, _d, _a = plan_for(a)
        expect(not pl2["rotations"], "A: a second run finds nothing left to rotate")

        # ---- Fixture B: central G#N rows, plain stubs, a NEW archive, CRLF docket
        b = tmp / "b"
        (b / "archive").mkdir(parents=True)
        docket_b = ("# Roadmap\r\n\r\n<!-- next-goal-id: 5 -->\r\n\r\n"
                    "- **G#1** \U0001F7E0 **CANDIDATE** open\r\n"
                    "- **G#2** ✅ **RESOLVED 2026-01-01 " + DASH + " a closed row.** body." + filler + "\r\n"
                    "  continuation line owned by G#2\r\n"
                    "- **G#3** \U0001F7E2 **CANDIDATE** open\r\n"
                    "- **G#4** ✅ **RESOLVED " + DASH + " earlier.** [full row -> archive/roadmap-closed-2026-01.md]\r\n")
        (b / "roadmap.md").write_bytes(docket_b.encode("utf-8"))
        (b / "archive" / "roadmap-closed-2026-01.md").write_bytes(
            ("- **G#4** ✅ **RESOLVED " + DASH + " earlier.** body\n").encode("utf-8"))
        plb, dpb, apb = plan_for(b, "2026-02")
        expect([r["row"]["id"] for r in plb["rotations"]] == ["G#2"], "B: moves the closed G#N row")
        expect(plb["style"] == "plain", "B: plain stub style read from the docket")
        stub_b = uncr(plb["rotations"][0]["stub"])
        expect(stub_b == "- **G#2** ✅ **RESOLVED 2026-01-01 " + DASH + " a closed row.** "
               "[full row -> archive/roadmap-closed-2026-02.md]",
               "B: the stub ends at the second bold pair, then the plain pointer")
        nb = plb["new_docket_raw"]
        expect(nb.count(b"\r\n") == nb.count(b"\n") and plb["rotations"][0]["stub"].endswith("\r"),
               "B: a CRLF docket stays CRLF, stub line included")
        expect(plb["archive_raw"] is None and b"# Closed docket rows" in plb["new_archive_raw"]
               and plb["dest_eol"] == "\r\n", "B: a new archive gets a header and the docket's CRLF")
        expect(b"continuation line owned by G#2" in plb["new_archive_raw"]
               and b"continuation line owned by G#2" not in nb,
               "B: a continuation line moves with its row")
        resb = dict(checks(dc, plb, b, "roadmap.md", "archive/roadmap-closed-2026-02.md"))
        expect(all(resb.values()), "B: every pre-write check passes")

        # ---- rollback: a short archive write is caught by the re-read; nothing is left changed
        before_d, before_a = dpb.read_bytes(), apb.exists()
        _FAULT = "archive-short"
        try:
            ok, msg = apply(dc, plb, docket_path=dpb, archive_path=apb, root=b,
                            docket_rel="roadmap.md", archive_rel="archive/roadmap-closed-2026-02.md")
        finally:
            _FAULT = None
        expect(not ok and dpb.read_bytes() == before_d and apb.exists() == before_a,
               "rollback: a short archive write stops the run; docket untouched, archive removed")

        # ---- a concurrent edit between read and write stops the run
        dpb.write_bytes(before_d + b"- **G#9** CANDIDATE a row another session just added\r\n")
        ok, msg = apply(dc, plb, docket_path=dpb, archive_path=apb, root=b,
                        docket_rel="roadmap.md", archive_rel="archive/roadmap-closed-2026-02.md")
        expect(not ok and "changed on disk" in msg, "a docket edited after it was read stops the run")

        # ---- review findings (2026-09-27): each fixture is the reviewer's own reproduction
        def quick(name, docket):
            root = tmp / name
            (root / "archive").mkdir(parents=True, exist_ok=True)
            (root / "roadmap.md").write_bytes(docket.encode("utf-8"))
            return plan_for(root)[0]

        closed = lambda n, extra="": ("- **#%d** ✅ **DONE 2026-09-01 %s shipped.**%s%s"
                                      % (n, DASH, filler, extra))
        para = lambda n, extra="": ("**#%d** ✅ **DONE 2026-09-01 %s shipped.**%s%s"
                                    % (n, DASH, filler, extra))
        OPEN = "\U0001F7E2 **OPEN " + DASH + " next.** body"
        p = quick("r1", "# D\n\n" + para(5, " Run it:") + "\n```bash\n# run it nightly\n"
                  "python backup.py\n```\nFollow-up text of #5.\n\n**#6** " + OPEN + "\n")
        expect(p["skipped"]["fence"] == ["#5"] and not p["rotations"],
               "review H1: a fence inside a row, holding a '# line', keeps the row live")
        p = quick("r2", "# D\n\n" + closed(5) + "\n<!--\n## old notes (hidden)\n-->\n- **#6** "
                  + OPEN + "\n")
        expect(p["skipped"]["fence"] == ["#5"] and not p["rotations"],
               "review H1: a multi-line HTML comment crossing a row keeps it live")
        p = quick("r3", "# D\n\n```\n" + closed(41) + "\n```\n\n- **#42** " + OPEN + "\n")
        expect("#41" in p["skipped"]["fence"] and not p["rotations"],
               "review H1: a row inside a code fence is an example, not a row")
        p = quick("r4", "# D\n\n" + para(5) + "\n\n- **Hygiene " + DASH + " an open note**\n"
                  "- \U0001F7E2 **OPEN " + DASH + " a live glyph item**\n\n"
                  "<!-- last assigned: #6 -->\n\n**#6** " + OPEN + "\n")
        expect(p["skipped"]["ambiguous"] == ["#5"] and not p["rotations"],
               "review H2: a paragraph row followed by open list items is not guessed at")
        p = quick("r5", "# D\n\n" + closed(5) + "\n<!-- last assigned: #6 -->\n\n- **#6** "
                  + OPEN + "\n")
        expect(p["skipped"]["ambiguous"] == ["#5"],
               "review H2: an HTML block directly under a list row is not moved with it")
        p = quick("r6", "# D\n\n" + para(5) + "\nQ4 plan\n-------\n\n**#6** " + OPEN + "\n")
        expect(p["skipped"]["ambiguous"] == ["#5"],
               "review H2: a setext underline below the row keeps it live")
        p = quick("r7", "# D\n\n## Ruled out (owner rulings)\n\n- **#12** ❌ **REFUTED** "
                  "2026-08-01: an XLSX export for billing is ruled dead; CSV is the format."
                  + filler + "\n")
        expect(p["skipped"]["ruling"] == ["#12"],
               "review H3: a row under a 'Ruled out' heading is a ruling and stays live")
        p = quick("r8", "# D\n\n> " + closed(20) + "\n> continuation of the quoted row\n\n"
                  "- **#21** " + OPEN + "\n")
        expect(p["skipped"]["ambiguous"] == ["#20"],
               "review M3: a quoted row with a quote continuation is not split")
        p = quick("r9", "# D\n\n" + para(30, " Steps taken:") + "\n1. **Backed up** the data\n"
                  "2. **Ran** the job\n\n**#31** " + OPEN + "\n")
        expect(p["skipped"]["ambiguous"] == ["#30"],
               "review M3: a paragraph row followed directly by a list is not split")
        p = quick("r10", "# D\n\n" + closed(60) + "\n  - \U0001F7E1 **REOPENED 2026-09-20:** "
                  "still open.\n")
        expect(p["skipped"]["reopened"] == ["#60"], "review M4: a reopened body keeps the row live")
        phrases = ["Decision (owner, 2026-09-01): exports stay CSV-only.",
                   "Alex decided 2026-09-01: keep the legacy URL scheme.",
                   "Per the owner: never auto-merge on Fridays.",
                   "NEVER re-enable the nightly purge job.",
                   "RULE: the gate stays at 8/8.", "LOCKED 2026-09-01: CSV only.",
                   "Owner said no to the XLSX export.",
                   "Must not be reverted without a new measurement."]
        p = quick("r11", "# D\n\n" + "\n".join(closed(70 + k, " " + ph)
                                              for k, ph in enumerate(phrases)) + "\n")
        expect(len(p["skipped"]["decision"]) == len(phrases) and not p["rotations"],
               "review M5: eight common phrasings of a standing decision keep their rows (%d)"
               % len(p["skipped"]["decision"]))
        lk = tmp / "links"
        (lk / "archive").mkdir(parents=True)
        (lk / "scripts").mkdir()
        for f in ("notes.md", "my notes.md", "README.md", "archive/README.md"):
            (lk / f).write_bytes(b"x")
        out, ch, un = rewrite_links("see `[n5](notes.md)` and [n7](notes.md) [n1](<my notes.md>)"
                                    " [n6](README.md) [n3](scripts/)\n[r4]: notes.md",
                                    lk, lk / "archive")
        expect("`[n5](notes.md)`" in out, "review M6: a link inside a code span is not touched")
        expect("[n7](../notes.md)" in out and "(<../my notes.md>)" in out,
               "review M6: plain and angle-bracket links are re-pointed")
        expect("[n6](../README.md)" in out,
               "review M6: a same-named file in the archive does not capture the link")
        expect("[n3](../scripts/)" in out and "[r4]: ../notes.md" in out,
               "review M6: a directory link and a reference definition are re-pointed")

        # the write path under failure
        def write_case(name, fault):
            global _FAULT
            root = tmp / name
            (root / "archive").mkdir(parents=True)
            (root / "roadmap.md").write_bytes(("# D\n\n" + closed(1) + "\n- **#2** " + OPEN
                                               + "\n").encode("utf-8"))
            q, dp, ap = plan_for(root)
            before = dp.read_bytes()
            _FAULT = fault
            try:
                res = apply(dc, q, docket_path=dp, archive_path=ap, root=root,
                            docket_rel="roadmap.md", archive_rel="archive/" + ap.name)
            finally:
                _FAULT = None
            return res, dp, ap, before

        (ok, msg), dp, ap, before = write_case("w1", "docket-raise")
        expect(not ok and "could not write the docket" in msg and dp.read_bytes() == before
               and not ap.exists(),
               "review M2: a failed docket write restores the archive; no traceback")
        (ok, msg), dp, ap, before = write_case("w2", "docket-changes")
        expect(not ok and b"added by another session" in dp.read_bytes() and not ap.exists(),
               "review M1: a docket edited mid-run is left as the other session wrote it")
        expect(stub_style(["- **#1** ✅ x (" + ARROW + " [archive](archive/a.md))*"])[0]
               == "archive-link", "review L2: an archive-link stub is recognised mid-line")
        h7, _t = stub_head("- **#18** ✅ **DONE** " + "word " * 38 + "~~struck " + "x " * 90)
        expect(balanced(h7)[0] and "~~" not in h7, "review L1: never cut inside a strikethrough")

        # ---- stub heads, directly
        h, _t = stub_head("- **#12 ✅ DONE: (a parenthetical that opens early and runs " +
                          "on for a very long time " * 20 + ") tail")
        expect(balanced(h)[0] and h.startswith("- **#12 ✅"),
               "stub head: a parenthetical still open at the budget is never cut inside")
        h2, _t = stub_head("- **#13** ✅ DONE " + "word " * 30 + "`a code span (that runs on "
                           + "x " * 100 + "` tail")
        expect(balanced(h2)[0] and "`" not in h2, "stub head: never cut inside a code span")
        h3, _t = stub_head("- **#14** ✅ **DONE <!-- a comment that runs on " + "x " * 200 + "-->**")
        expect(balanced(h3)[0] and "<!--" not in h3, "stub head: never cut inside an HTML comment")
        h4, _t = stub_head("- **#15** ✅ **DONE " + "word " * 60 + "**")
        expect(h4.endswith("word**") and balanced(h4)[0],
               "stub head: a bold still open at the cut is closed")
        # The measured shape: the quoted colon is the LAST sentence end inside the budget, and
        # the head runs past the second-bold-pair shortcut, so without quote tracking the cut
        # lands on 'assigned:' and leaves the quotation open. (A fixture whose quote closes
        # well before the cut passes either way -- that was this arm's first, inert version.)
        h5, _t = stub_head("- **#16** ✅ **DONE 2026-09-27 (machine): `scripts/check-markers.py` "
                           "(run by the ship check) now compares the \"last assigned: #N\" line with "
                           "the highest row id in this file and fails when the line is BEHIND (the "
                           "next id would collide); a line AHEAD is fine. Measured on the live "
                           "docket: 301 rows, 0 findings, and the selftest scores 10/10 again.**")
        expect(h5.count('"') % 2 == 0 and "assigned:" not in h5[-12:],
               "stub head: never ends inside a quotation (%s)" % h5[-40:])
        h6, _t = stub_head("- **#17** ✅ **DONE: a 24\" monitor " + "word " * 60 + "**")
        expect(len(h6) > 60, "stub head: an inch mark (24\") opens no quotation")
        (tmp / "c" / "archive").mkdir(parents=True)
        (tmp / "c" / "a").mkdir()
        out, ch, un = rewrite_links("[a](nowhere.md) [[G#87]](a) [x](https://e.x/y.md)",
                                    tmp / "c", tmp / "c" / "archive")
        expect(not ch and "nowhere.md" in un and "[[G#87]](a)" in out,
               "links: prose naming a folder, a link resolving nowhere and a URL are left alone")
        (tmp / "c" / "doc.md").write_bytes(b"x")
        out, ch, un = rewrite_links("see [d](doc.md#part-2)", tmp / "c", tmp / "c" / "archive")
        expect(out == "see [d](../doc.md#part-2)",
               "links: a file link keeps its #fragment when re-pointed (%s)" % out)
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (passed, failed))
    print("selftest: %s" % ("ALL GREEN" if not failed else "FAILURES"))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
