#!/usr/bin/env python3
"""rulings -- the owner's standing rulings (ruled-out options, do-not-re-propose blocks) in THIS project.

WHY
    A briefing is built from current state. A killed option has no row, no status and no artifact
    of its own -- it is a sentence inside some other row -- so once that sentence is buried or
    deleted the briefing is accurate and the session asks the owner a question he already
    answered. Measured: a docket row rewritten from NEW to BUILT dropped the block that said both
    remaining options were dead (confirmed by the owner), and the next morning's session proposed
    both options back to the owner, one of them twice. This prints the rulings mechanically, and
    flags a ruling that a rewrite silently dropped.

MODES
    (default)  the briefing section '== RULED OUT (owner rulings - do not re-propose) ==': the
               standing rulings, newest first, capped (--cap, default 12) with a remainder count
               per file; then the rulings REMOVED by the last --history commits (default 30) that
               touched the sources and that no source holds AS A RULING now, with how far back
               that window reaches. A project with sources but no ruling prints one 'none -- read N
               source(s)' line; a config problem prints 'could not check'; only a directory with no
               context layer prints nothing.
    --all      the same, uncapped.
    --json     the same data as JSON (with sources, errors and each removal's verdict).
    --lost     the wrap check '== RULING LOSS ==': one THRESHOLD per ruling that HEAD's copy of one
               of HEAD's own sources carries -- a source the working tree changed, deleted, renamed,
               undeclared or excluded -- or that a commit in the same window removed, and that no
               source holds as a ruling now, unless an acknowledgement clears it. It says how many
               commits it read and how far back they reach. Prints nothing outside git.
    A removal is shown at every briefing and wrap while its commit is inside the window; after that it
    is no longer shown. The wrap that makes a drop always sees it (--lost compares HEAD with the
    working tree), so it is handled there.

SOURCES
    standing   the project's docket files (docket_corpus kinds docket, roadmap, config), its
               HANDOFF*.md (root and context/), its memory index (MEMORY.md in continuation/memory,
               context/memory and ~/.claude/projects/<slug>/memory), every file rulings-sources.json
               declares (a design spec's rulings table: read by this tool only, so it never becomes
               a docket for other tools; "by": "delegated" prints [delegated]), and an archive's
               section headed 'Standing rulings' / 'Do not re-...' (printed [archive]). Any other
               archive or note is corpus only: it can show where a removed ruling's text went. A file
               in a submodule, or outside the repository, is named as not checked for removals.
    kept       a ruling is kept when it is still a RULING in a source: its core (its words in order,
               with a list number, table pipes, a trailing note and punctuation folded away) is a
               current ruling's core; or its own marker clause names its subject and is a current
               ruling's clause; or ONE current ruling -- or one ruling section, its items together --
               carries half its word 4-grams with a gram through each marker, or 60% of its
               distinctive words and every marker kind it had, AND carries its dates and numbers, 60%
               of its contrastive words (the words no other ruling of its old copy has: a sibling that
               stood beside it cannot vouch for it) and 60% of each list item's words. A list that
               lost items is 'pruned' (the items are named); text that survives only in its own file
               or a standing file, no longer read as a ruling, is 'unruled'; only in an archive or
               note is 'moved'; a source that left the configs takes its rulings with it ('left');
               nowhere is 'lost'.
    ack        a deliberate removal is acknowledged in a standing file of this repository:
                   <!-- ruling-withdrawn: "a phrase copied from the ruling" why it was dropped -->
               It clears a removal only when the phrase names that ruling (3+ words; two of the
               ruling's distinctive words, or its only one, and at least half of them), the ack was
               written in the same change as the removal or later (git blame dates it), and it matches
               exactly one of the run's removals (or one ruling recorded twice, cleared together). Every cleared removal is named; an ambiguous, too-generic, too-partial
               or undatable ack clears nothing and says so.
    history    git log --raw -z (blob ids, no textual diff: no user diff config, binary heuristic or
               path quoting can hide a change) over every name and location a source can have; each
               changed file's two copies are read through one git cat-file --batch and compared here.
               A path counts by what it WAS before the commit -- by name and location under the
               configs that commit found -- so a deleted or renamed-away source is read and a file
               counts as declared only from the commit that declared it; an archive counts only
               inside its standing sections. The lines around a change are scanned in the copy BEFORE
               it; a changed heading, fence, rule, table separator or HTML comment boundary compares
               the two copies' rulings whole. A config edit that drops a source removes its rulings.
               A merge is read against each parent whose copy differs.

GRAMMAR (measured on six projects' real dockets, 2026-09-24 and 2026-09-27; tests/test-rulings.py pins
both directions for every marker alternative, tests/mutations/rulings.py kills each one)
    unit             a paragraph, or a list item with its wrapped lines, joined: a marker, a quote or
                     a sentence can wrap. A table row and a heading are one line each. Markers match
                     with bold / underscore delimiters read as spaces: 'Do **not** re-propose' counts.
    do-not-re        'do not / don't / never' + re-propose|raise|ask|litigate|suggest|pitch|apply|
                     surface; 'stop re-...ing'; 'stop proposing'; 'never propose'; the passive
                     'not (be) re-proposed|raised|asked|litigated|pitched|applied|surfaced'.
                     NOT re-file / re-open / re-research / re-run: measured as operational guards.
    owner-ruling     'OWNER RULED|RULING|DECLINED|CONFIRMED|RATIFIED [(x)] <date>'; '[OWNER RULING]';
                     'RULED [+ EXECUTED] <date>'; a sentence-initial 'Owner ruling.' / 'Owner ruling,';
                     'by|per|on (the) owner('s) ruling'; 'owner(-)ruled|ruling|ratified [(x)] <date>';
                     'owner declined' / 'declined by the owner'; 'user declined'; 'he (has)
                     (explicitly) declined'; 'confirmed (dead) by the owner'; 'SHELVED ... (owner)';
                     'policy ADOPTED'; in a memory index only, 'MM-DD owner ruling'. A dated form takes
                     a colon, parenthesis or dash before its date.
    voided-by-owner  'VOIDED ... owner' inside one clause
    dead-lever       'dead lever(s)'
    section          a top-level item or table body row under a heading that names rulings ('owner
                     rulings', "the owner's rulings", 'owner-rulings', 'standing rulings', 'locked
                     decisions', 'decisions locked', 'ruled out', 'do not re-propose|raise|ask|open|
                     litigate|file'), nested sub-headings included, up to the next heading of the same
                     or a higher level
    label            a bold 'Locked decisions' / 'Decisions locked' / 'Standing rulings' / 'Owner
                     rulings' / 'Ruled out' label (a status glyph may lead) with content after it
    NOT markers: a bare no-entry sign, 'killed', 'REFUTED', 'ruled out' in prose, 'verbatim',
    'OWNER DECISION', an undated capital 'OWNER-RULED' or 'OWNER RULINGS', 'an OWNER ruling', an
    undated 'owner-ratified', a reference to a dated ruling, 'she declined'.
    A marker inside a code span, a fenced block, an HTML comment (one line or several), a
    double-quoted, curly-quoted or italic span, strikethrough, or right after a single quote is a
    MENTION, never a ruling. So is a hyphenated compound ('a do-not-re-propose block'). An inch mark
    (24") opens no quote; an asterisk inside a code span opens no italic.

OUTPUT
    Every ruling is a dated CLAIM with its source line: its own date, else its section's, else its
    heading's, else '(undated; line last changed <date>)' from git blame, else '(undated)'. Tags:
    [delegated], [archive], [row says SUPERSEDED <date> -- re-check] (the owner's own reversal later
    in the same row), '(+N more item(s): read path:line)' for a list the cut hid, '(also: ...)' for a
    duplicate merged into it; a removal adds where its text went, the items a list lost, or the ack
    that could not clear it. Each summary is at most 180 characters (160 in a THRESHOLD), cut
    around the marker; a docket line can carry personal data, so nothing is ever printed whole and
    nothing is written to a file. These are STATE lines: nothing here starts with FINDING. A failure
    prints 'could not check', never silence.

EXIT STATUS
    0 always, except 2 for a usage error.
"""
from __future__ import annotations

import argparse
import bisect
import difflib
import json
import os
import re
import subprocess
import sys
import time
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HEADER = "== RULED OUT (owner rulings - do not re-propose) =="
LOSS_HEADER = "== RULING LOSS (owner rulings in HEAD or in recent commits, gone from the briefing's sources) =="
ROUTE = ("(state lines, not FINDINGs -- carry them into the briefing's Locked decisions as dated claims with their "
         "source: re-check the premise before relying on one, and never re-propose one without new evidence; "
         "a [delegated] line is a ruling made under the owner's delegation, re-openable on evidence)")
STANDING_KINDS = ("docket", "roadmap", "config", "handoff")
RULINGS_CONFIG = "rulings-sources.json"
CONFIG_NAMES = (RULINGS_CONFIG, "docket-corpus.json")   # the two files that decide what a source is
# History is read as blob ids only: no textual diff, so no user diff config (a prefix, a merge mode, an
# external or text-conversion diff), no binary heuristic and no path quoting can hide a change.
_LOG_ARGS = ["log", "--diff-merges=separate", "--no-renames", "--raw", "-z", "--no-abbrev", "--no-color",
             "--no-textconv", "--no-ext-diff", "--no-relative", "--no-show-signature", "--date=short",
             "--format=%x1e%H%x1f%ad"]
_CONFIG_KEYS = frozenset(("sources", "comment"))
_SOURCE_KEYS = frozenset(("path", "by", "note"))
BY_VALUES = ("owner", "delegated")
NAMES_SHOWN = 6        # sources named on the zero-state line before '+N more'
DEFAULT_CAP = 12
DEFAULT_HISTORY = 30
SUMMARY_MAX = 180
THRESHOLD_SUMMARY_MAX = 160
MERGE_GAP = 200        # marker matches this close on one line are one ruling, not two
WINDOW_MAX = 300       # never read further than this either side of a marker
SHINGLE = 4
TOKEN_MIN = 5          # a ruling with fewer distinctive words is matched verbatim or by 4-grams only
TOKEN_SHARE = 0.6      # ...else it is kept when a current ruling carries this share of its words
CLAUSE_MIN_TOKENS = 2  # a clause kept word for word names its subject with this many distinctive words, not
                       # dates ('this approach' or 'owner declined (date)' names nothing: critic C1, C2)
BLAME_TIMEOUT = 20     # seconds for one file's git blame (the undated-ruling date fallback)

# ---------------------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------------------

# The do-not-re verbs are the ones that re-OPEN A DECISION. 're-file', 're-open' and 're-research'
# are not among them: measured over six projects' dockets they were operational guards (a billing
# re-submission, a duplicate row, a closed search) in 18 of 19 lines, two of which printed patient
# surnames into every briefing. An owner ruling phrased with one of them is still found by its
# owner-ruling marker, its section heading or its label.
_BASE = r"(?:propose|raise|ask|litigate|suggest|pitch|apply|surface)"
_ING = r"(?:proposing|raising|asking|litigating|suggesting|pitching|applying|surfacing)"
_ED = r"(?:proposed|raised|asked|litigated|pitched|applied|surfaced)"
_DATE = r"\d{4}-\d{2}-\d{2}"
_SEP = r"[\s:(\[\u2014\u2013-]*"           # what may stand between a dated form and its date
_OPT = r"(?:\s*\([a-z0-9]{1,3}\))?"        # an option label: 'OWNER RATIFIED (c) 2026-09-26'

# Markers are matched on _plain(line): bold / underscore delimiters are spaces there, so emphasis INSIDE
# a marker ('Do **not** re-propose', '**Never** re-propose') is still the marker (review 2 FL-CUR#2).
MARKERS = (
    ("do-not-re", re.compile(
        r"\b(?:do\s+not|don['\u2019]?t|never)\s+re-?" + _BASE + r"\b"
        r"|\bstop\s+re-?" + _ING + r"\b"
        r"|\bstop\s+proposing\b|\bnever\s+propose\b"
        r"|\bnot\s+(?:to\s+)?(?:be\s+)?re-?" + _ED + r"\b", re.I)),
    ("owner-ruling", re.compile(
        r"\bOWNER[- ](?:DECLINED|CONFIRMED)\b" + _OPT + _SEP + _DATE
        + r"|\[OWNER RULING\]"
        r"|\bRULED(?:\s*(?:\+|AND)\s*EXECUTED)?\b" + _SEP + _DATE
        + r"|(?:^|(?<=[.!?]\s))Owner\s+rulings?(?=\s*[.,:;!\u2014-])"
        r"|(?i:\b(?:by|per|on)\s+(?:the\s+)?owner(?:['\u2019]s)?\s+ruling\b)"
        r"|(?i:\bowner[- ](?:ruled|ruling|ratified)\b" + _OPT + _SEP + _DATE + r")"
        r"|(?i:\bowner[- ]declined\b|\bdeclined\s+by\s+the\s+owner\b)"
        r"|(?i:\buser\s+(?:has\s+)?(?:explicitly\s+)?declined\b|\bhe\s+(?:has\s+)?(?:explicitly\s+)?declined\b)"
        r"|(?i:\bconfirmed\s+(?:dead\s+)?by\s+the\s+owner\b)"
        r"|\bSHELVED\b[^.;!?]{0,60}?\((?i:owner)\)"
        r"|\bpolicy\s+ADOPTED\b")),
    ("voided-by-owner", re.compile(r"\bvoided\b[^.;!?]{0,60}?\bowner\b", re.I)),
    ("dead-lever", re.compile(r"\bdead\s+levers?\b", re.I)),
)
# Read only in a memory index (MEMORY.md), where a line is short and dated 'MM-DD': elsewhere the
# same shape is a reference to a ruling ('the 09-15 owner ruling forbids that'), not the ruling.
MEMORY_MARKERS = (
    ("owner-ruling", re.compile(r"(?i:(?<![\d-])\d{2}-\d{2}\s+owner\s+ruling\b)")),
)
# A row that carries its own reversal after the ruling: printed with a 're-check' tag, never dropped.
# Only the owner's reversal counts ('SUPERSEDED ... (owner)', 'stands only as history'): a bare
# SUPERSEDED after a live ruling was measured retracting a DIFFERENT sentence of the same row, and
# 'no longer' / 'WITHDRAWN' appear on live rulings.
SUPERSEDED_RE = re.compile(r"\bSUPERSEDED\b[^.;]{0,40}\((?i:owner)\)|(?i:\bstands\s+only\s+as\s+history\b)")
LIST_SEP_RE = re.compile(r"\s+\u00b7\s+|;\s+")
LIST_MIN_ITEMS = 3
DUP_SHARE = 0.8        # two rulings are one when each carries this share of the other's words
# A heading that says its items STAND ('Standing rulings', 'Do not re-raise'): the one section an
# archive of closed rows keeps as standing (a killed option stays killed when its row closes).
STANDING_SECTION_RE = re.compile(
    r"\bstanding\s+rulings?\b|\bdo\s+not\s+re-?(?:propose|raise|ask|open|litigate|file)\b", re.I)
# A deliberate removal, acknowledged where the next session reads it:
#   <!-- ruling-withdrawn: "a phrase copied from the ruling" why it was dropped -->
# It lives in an HTML comment (a mention, never itself a ruling) in any standing file.
ACK_RE = re.compile(r"<!--\s*ruling-withdrawn:\s*[\"“]([^\"”]+)[\"”]", re.I)
ACK_MIN_WORDS = 3
ACK_MIN_TOKENS = 2     # ...and this many of ITS ruling's distinctive words (all of them when it has fewer)
ACK_SHARE = 0.5        # ...and this share of ITS ruling's distinctive words: a phrase a family of rulings
                       # shares names none of them, even when the others left the window (review 3, K4)
ACK_TAG = "ruling-withdrawn:"
REMOVED_SHOWN = 5      # removed rulings listed before 'and N more'
STANDING_HEAD_RE = re.compile(r"^\s{0,3}#{1,6}\s.*(?:standing\s+rulings?|do\s+not\s+re-?(?:propose|raise|ask|open|litigate|file))",
                              re.I | re.M)
ARCHIVE_KINDS = ("archive", "handoff-archive")
SECTION_RE = re.compile(
    r"\b(?:owner(?:['\u2019]s)?|standing)(?:\s+|-)rulings?\b|\bdecisions?\s+locked\b|\blocked\s+decisions?\b"
    r"|\bruled[- ]out\b|\bdo\s+not\s+re-?(?:propose|raise|ask|open|litigate|file)\b", re.I)
_GLYPH = r"(?:[☀-➿⬀-⯿\U0001F300-\U0001FAFF]️?\s*)?"
# A bold ruling label that carries content after it: '**Locked decisions:** a; b'. A status glyph
# may lead ('✅ **Owner rulings this session:** ...'); a label with nothing after it, colon inside
# or outside the bold, is a heading-like stub, not a ruling.
LABEL_RE = re.compile(
    r"^\s{0,3}(?:>\s*)?(?:[-*+]\s+|\d{1,4}[.)]\s+)?" + _GLYPH + r"\*\*\s*(?:locked\s+decisions?|decisions?\s+locked|"
    r"standing\s+rulings?|owner\s+rulings?|ruled[- ]out)\b[^*]*\*\*\s*:?\s*[^\s:]", re.I)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
ITEM_RE = re.compile(r"^\s{0,3}(?:>\s*)?(?:[-*+]|\d{1,4}[.)])\s+\S")
TOP_ITEM_RE = re.compile(r"^(?:>\s*)?(?:[-*+]|\d{1,4}[.)])\s+\S")   # column 0: a sub-point is detail
TABLE_RE = re.compile(r"^\s{0,3}\|")
TABLE_SEP_RE = re.compile(r"^\s{0,3}\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
HR_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
DATE_RE = re.compile(r"(?<!\d)(" + _DATE + r")(?!\d)")
BOUNDARY_RE = re.compile(r"[.!?;](?:[*_)\]\"'\u201d\u2019]*)(?=\s)")
# Inside the marker's sentence, what ends a row's own furniture before the ruling: a status word's ' -- ',
# a table cell, a label's ': '. The ruling's SEGMENT starts after the last one (review 3, F1, F4, F6).
SEGMENT_RE = re.compile(r"\s(?:--|\u2014|\u2013|\|)(?=\s)|:(?=\s)")
LEAD_RE = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+|\|\s*)?")
CELL_RE = re.compile(r"\s\|\s")            # a table cell boundary: printed as ' · ' in a summary only


class _Para(object):
    """Quote / strikethrough state carried across the lines of one paragraph."""

    def __init__(self):
        self.quote = self.curly = self.strike = False


def _code_spans(line):
    """(start, end) of inline code spans: a run of N backticks closed by the next run of exactly N."""
    runs = [(m.start(), m.end()) for m in re.finditer(r"`+", line)]
    spans, i = [], 0
    while i < len(runs):
        a, b = runs[i]
        n = b - a
        for j in range(i + 1, len(runs)):
            if runs[j][1] - runs[j][0] == n:
                spans.append((a, runs[j][1]))
                i = j
                break
        i += 1
    return spans


def _italic_spans(line, opaque=()):
    """(start, end) of single-asterisk italic spans (a '**' run is bold, never italic). An asterisk
    inside an opaque span (code, comment) is text: a glob like `docs/*.md` opens nothing."""
    out, opener = [], None
    for m in re.finditer(r"(?<!\*)\*(?!\*)", line):
        i = m.start()
        if any(a <= i < b for a, b in opaque):
            continue
        prev = line[i - 1] if i > 0 else " "
        nxt = line[i + 1] if i + 1 < len(line) else " "
        if opener is None:
            if not nxt.isspace() and not prev.isalnum():
                opener = i
        elif not prev.isspace() and not nxt.isalnum():
            out.append((opener, i + 1))
            opener = None
    return out


def _mask(line, para):
    """A per-character list: True where the character sits in a MENTION (code, comment, quote,
    italic, strikethrough). Updates `para` for the next line of the same paragraph."""
    n = len(line)
    mask = [False] * n
    opaque = _code_spans(line) + [(m.start(), m.end()) for m in re.finditer(r"<!--.*?-->", line)]
    opq = [False] * n                   # inside a code span or a one-line comment (text, never a delimiter)
    for a, b in opaque:
        for k in range(a, b):
            mask[k] = opq[k] = True
    i = 0
    while i < n:
        if opq[i]:
            i += 1
            continue
        c = line[i]
        if c == "~" and line.startswith("~~", i):
            para.strike = not para.strike
            mask[i] = mask[i + 1] = True
            i += 2
            continue
        if c == '"' and not para.quote and i > 0 and line[i - 1].isdigit():
            pass            # an inch mark ('24" wide') opens no quote
        elif c == '"':
            if para.curly:
                para.curly = False      # a mixed pair, curly open and straight close
            else:
                para.quote = not para.quote
            mask[i] = True
        elif c == "\u201c":
            para.curly = True
        elif c == "\u201d":
            mask[i] = True
            para.curly = para.quote = False     # ...and straight open, curly close (review 3, F11)
        if para.quote or para.curly or para.strike:
            mask[i] = True
        i += 1
    for a, b in _italic_spans(line, opaque):
        for k in range(a, b):
            mask[k] = True
    return mask


def _mention(line, start, mask):
    if start < len(mask) and mask[start]:
        return True
    j = start - 1
    while j >= 0 and line[j] in "*_":
        j -= 1
    return j >= 0 and line[j] in "'\u2018"


_EMPH_RE = re.compile(r"\*{2,}|_{2,}")


def _plain(line):
    """`line` with every bold / underscore delimiter run replaced by as many spaces: same length, so every
    position still points at the same column, and emphasis inside a marker no longer breaks it."""
    return _EMPH_RE.sub(lambda m: " " * len(m.group()), line)


def _groups(line, mask, memory=False):
    """Marker matches on one line, merged into ruling groups: [(start, end, marker, spans, kinds)]."""
    found = []
    plain = _plain(line)
    for name, rx in MARKERS + (MEMORY_MARKERS if memory else ()):
        for m in rx.finditer(plain):
            if not _mention(line, m.start(), mask):
                found.append((m.start(), m.end(), name))
    found.sort()
    groups = []
    for s, e, name in found:
        if groups and s - groups[-1][1] <= MERGE_GAP:
            g = groups[-1]
            groups[-1] = (g[0], max(g[1], e), g[2], g[3] + [(s, e)], g[4] | {name})
        else:
            groups.append((s, e, name, [(s, e)], {name}))
    return groups


def _heading_rules(text):
    m = SECTION_RE.search(_plain(text))
    if not m:
        return False
    return not _mention(text, m.start(), _mask(text, _Para()))


def _starts_unit(ln):
    """True when line `ln` cannot continue the paragraph above it."""
    return bool(not ln.strip() or HEADING_RE.match(ln) or FENCE_RE.match(ln) or ITEM_RE.match(ln)
                or TABLE_RE.match(ln) or HR_RE.match(ln))


def _units(lines):
    """The scan units of a markdown text: (kind, index, indices, text, starts). kind is 'heading',
    'table' (one row) or 'unit' (a paragraph, or a list item with its continuation lines, joined
    with single spaces: a sentence, a quote or a marker can wrap onto the next line). `starts[k]`
    is where line indices[k] begins in `text`. Blank lines, rules and fenced blocks yield nothing."""
    fence = None
    i, n = 0, len(lines)
    while i < n:
        ln = lines[i]
        fm = FENCE_RE.match(ln)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            i += 1
            continue
        if fm:
            fence = fm.group(1)
            i += 1
            continue
        if not ln.strip() or HR_RE.match(ln):
            i += 1
            continue
        if HEADING_RE.match(ln) or TABLE_RE.match(ln):
            yield ("heading" if HEADING_RE.match(ln) else "table"), i, [i], ln, [0]
            i += 1
            continue
        idx, parts, starts, pos = [i], [ln.rstrip()], [0], len(ln.rstrip()) + 1
        j = i + 1
        while j < n and not _starts_unit(lines[j]):
            idx.append(j)
            starts.append(pos)
            parts.append(lines[j].strip())
            pos += len(parts[-1]) + 1
            j += 1
        yield "unit", i, idx, " ".join(parts), starts
        i = j


def _blank_comments(lines):
    """`lines` with every MULTI-line HTML comment blanked, its delimiters included, each line keeping
    its length (so every position still points at the same column): text commented out across lines
    is a mention, never a ruling. A comment that closes on its own line is left to _mask; an opener
    inside a fenced block or a code span is text, not a comment ([[G#426]]: protected regions first)."""
    out, fence, inside = [], None, False
    for ln in lines:
        if not inside:
            fm = FENCE_RE.match(ln)
            if fence:
                if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                    fence = None
                out.append(ln)
                continue
            if fm:
                fence = fm.group(1)
                out.append(ln)
                continue
        spans = _code_spans(ln)
        chars, i = list(ln), 0
        while i < len(ln):
            if inside:
                k = ln.find("-->", i)
                end = len(ln) if k < 0 else k + 3
                for j in range(i, end):
                    chars[j] = " "
                if k < 0:
                    break
                inside, i = False, end
                continue
            k = ln.find("<!--", i)
            if k < 0:
                break
            if any(a <= k < b for a, b in spans):
                i = k + 4
                continue
            close = ln.find("-->", k + 4)
            if close >= 0:
                i = close + 3           # a one-line comment: _mask handles it
                continue
            inside, i = True, k
        out.append("".join(chars))
    return out


def scan_text(text, first_line=1, only=None, memory=False):
    """Every ruling in a markdown text: [{line, lines, marker, start, end, spans, text, section_date,
    heading_date}]. `line` is the physical line of the marker (of the unit's first line for a section
    or label ruling); `lines` every physical line of its unit; `text` the unit, wrapped lines joined.
    `only` (a set of line numbers) restricts the result to rulings whose unit touches one of those
    lines, plus the items of a ruling section whose heading line is in it (a retitled or deleted
    heading un-rules them); headings and fences are still tracked across the whole text."""
    out = []
    lines = _blank_comments(text.splitlines())
    stack = []          # open ruling sections, outermost first: (level, date, says-standing, touched)
    heads = []          # open headings that carry a date: (level, date)
    for kind, i, idx, unit, starts in _units(lines):
        if kind == "heading":
            h = HEADING_RE.match(unit)
            level = len(h.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            while heads and heads[-1][0] >= level:
                heads.pop()
            d = DATE_RE.search(h.group(2))
            own = d.group(1) if d else ""
            if own:
                heads.append((level, own))
            if _heading_rules(h.group(2)):
                stands = bool(STANDING_SECTION_RE.search(_plain(h.group(2)))) or bool(stack and stack[-1][2])
                touched = bool(only is not None and first_line + i in only) or bool(stack and stack[-1][3])
                stack.append((level, own or (stack[-1][1] if stack else ""), stands, touched, first_line + i))
            continue
        hit = only is None or any(first_line + k in only for k in idx)
        if not hit and not (stack and stack[-1][3]):
            continue            # region mode: a unit nowhere near a removed line
        base = {"text": unit, "lines": [first_line + k for k in idx],
                "section_date": stack[-1][1] if stack else "", "heading_date": heads[-1][1] if heads else "",
                "standing_section": bool(stack and stack[-1][2]),
                "section_line": stack[-1][4] if stack else 0}
        groups = _groups(unit, _mask(unit, _Para()), memory)
        if groups:
            if not hit:
                continue        # a marker ruling does not depend on its section heading
            for s, e, name, spans, kinds in groups:
                k = bisect.bisect_right(starts, s) - 1
                out.append(dict(base, line=first_line + idx[k], marker=name, start=s, end=e, spans=spans,
                                kinds=sorted(kinds)))
            continue
        if stack and _section_item(lines, i, kind):
            out.append(dict(base, line=first_line + i, marker="section", start=0, end=0, spans=[], kinds=["section"]))
        elif hit and LABEL_RE.match(unit):
            out.append(dict(base, line=first_line + i, marker="label", start=0, end=0, spans=[], kinds=["label"]))
    return out


def _section_item(lines, i, kind):
    """A top-level list item, or a table body row (a row followed by a separator is the header)."""
    if kind == "unit":
        return bool(TOP_ITEM_RE.match(lines[i]))
    if kind == "table" and not TABLE_SEP_RE.match(lines[i]):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        return not TABLE_SEP_RE.match(nxt)
    return False


# ---------------------------------------------------------------------------------------
# Summaries, dates, retention
# ---------------------------------------------------------------------------------------

_NORM = str.maketrans({"*": None, "_": None, "`": None, "~": None, "[": None, "]": None, "\u201c": '"',
                       "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2014": "-", "\u2013": "-"})


_LINK_TARGET = re.compile(r"\]\([^)\s]*\)|\]\[[^\]]*\]")


def normalize(s):
    """Lower-case, markdown emphasis, code ticks and link brackets dropped, a link's (target) or [ref]
    dropped (a link added, removed or moved is not a changed ruling, review FL-CUR#4), quotes and dashes
    folded, whitespace collapsed."""
    return " ".join(_LINK_TARGET.sub("]", s).translate(_NORM).lower().split())


_CORE_WORD = re.compile(r"[\w'\u2019-]+")


def _core(fragment):
    """A normalize()d fragment with its non-substantive markup folded away, for an EXACT comparison:
    a leading list number, a trailing parenthetical note and every punctuation mark (table pipes and
    middots included). What is left is the ruling's words, in order (review FL-CUR#0)."""
    s = re.sub(r"^\d{1,4}[.)]\s+", "", fragment.strip())
    s = s.rstrip(" .;:!?,")
    s = re.sub(r"\s*\([^()]{0,80}\)$", "", s)
    words = (w.strip("'\u2019-") for w in _CORE_WORD.findall(s))
    return " ".join(w for w in words if w)


def _clean(s):
    s = re.sub(r"<!--.*?-->", " ", s)   # a comment is a mention, never ruling text (review 3, F5)
    s = re.sub(r"~~.*?~~", " ", s)      # ...and so is struck-through text (critic C5)
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", s)
    return " ".join(s.split())


def _window(line, s, e):
    """(a, b, a0): the clause(s) holding line[s:e] -- sentence bounds, a too-short sentence extended
    backwards to `a` -- and `a0`, where the marker's own sentence starts (never extended: that sentence
    alone is the ruling's CLAUSE)."""
    lo = max(0, s - WINDOW_MAX)
    starts = [m.end() for m in BOUNDARY_RE.finditer(line, lo, s)]
    a = a0 = starts[-1] if starts else lo
    m = BOUNDARY_RE.search(line, e)
    b = m.end() if m and m.end() <= e + WINDOW_MAX else min(len(line), e + WINDOW_MAX)
    k = len(starts) - 1
    while len(_clean(line[a:b])) < 60 and a > lo:
        k -= 1
        a = starts[k] if k >= 0 else lo
    return a, b, a0


def _cut(text, pos, limit):
    """At most `limit` characters of `text`, keeping the part around character `pos`."""
    if len(text) <= limit:
        return text
    start = max(0, pos - 50)
    end = start + limit
    if end > len(text):
        end = len(text)
        start = end - limit
    body = text[start:end]
    if start > 0:
        body = "..." + body[3:]
    if end < len(text):
        body = body[:-3] + "..."
    return body


def _date(text, a, b, spans, section_date="", heading_date=""):
    """A marker ruling's date, in this order: a date inside the marker's own clause text[a:b]
    (the one nearest the marker); the nearest date in an EARLIER sentence of the same unit; the
    ruling section's date; the nearest date in a LATER sentence; the nearest enclosing heading's
    date. A later sentence comes after the section because it usually dates a different event
    ('... Do not re-raise it. Re-checked 2026-09-20.')."""
    inside, before, after = [], [], []
    for m in DATE_RE.finditer(text):
        p = m.start()
        if a <= p < b:
            d = min((0 if s <= p < e else min(abs(p - e), abs(s - m.end()))) for s, e in spans)
            inside.append((d, m.group(1)))
        elif p < a and a - p <= 400:
            before.append((a - p, m.group(1)))
        elif p >= b and p - b <= 400:
            after.append((p - b, m.group(1)))
    for group in (inside, before):
        if group:
            return min(group)[1]
    if section_date:
        return section_date
    if after:
        return min(after)[1]
    return heading_date


def _cells(s):
    """A summary with table-cell pipes shown as ' · ' (same length, so a cut position holds)."""
    return re.sub(r"\s*\|\s*$", "", CELL_RE.sub(" · ", s))


def rulings_in_text(rel, text, first_line=1, limit=SUMMARY_MAX, only=None):
    """[{path, line, lines, marker, date, summary, fragment, kinds, anchors}] for every ruling in
    `text` (restricted as scan_text's `only` says)."""
    out = []
    memory = rel.rsplit("/", 1)[-1].lower() == "memory.md"
    for h in scan_text(text, first_line, only, memory):
        ln = h["text"]
        if h["spans"]:
            a, b, a0 = _window(ln, h["start"], h["end"])
            raw = ln[a:b]
            clause = normalize(LEAD_RE.sub("", _clean(ln[a0:b]), count=1))
            s0 = max([a0] + [m.end() for m in SEGMENT_RE.finditer(ln, a0, h["start"])])
            segment = normalize(LEAD_RE.sub("", _clean(ln[s0:b]), count=1)) if s0 > a0 else ""
            # a list after the marker ('Do NOT re-propose: a · b · c.'), to its sentence's end however
            # long: the window stops at WINDOW_MAX, a list's last items do not
            end = BOUNDARY_RE.search(ln, h["end"])
            tail = ln[h["end"]:end.end() if end else len(ln)]
            pos = len(_clean(ln[a:h["start"]]))
            date = _date(ln, a, b, h["spans"], h["section_date"], h["heading_date"])
        else:
            raw = LEAD_RE.sub("", ln, count=1)
            clause = segment = ""
            lab = LABEL_RE.match(ln) if h["marker"] == "label" else None
            tail = ln[lab.end() - 1:] if lab else raw
            pos = 0
            d = DATE_RE.search(ln)
            date = d.group(1) if d else (h["section_date"] or h["heading_date"])
        # a list-shaped ruling's items, each with its own words: a dropped item is a dropped killed
        # option, so a match that keeps the ruling must keep each item (review FK-HIST#7)
        parts = [_clean(x).strip(" :*_.") for x in LIST_SEP_RE.split(tail)]
        parts = [x for x in parts if x]
        list_items = ([{"text": _cut(x, 0, 60), "tokens": ruling_tokens(normalize(x))} for x in parts]
                      if len(parts) >= LIST_MIN_ITEMS else [])
        clean = LEAD_RE.sub("", _clean(raw), count=1)
        pos = max(0, pos - (len(_clean(raw)) - len(clean)))
        summary = _cut(_cells(clean), pos, limit)
        # the row's own reversal AFTER the ruling: tagged for a re-check, never dropped
        sup = SUPERSEDED_RE.search(ln, h["end"])
        superseded = ""
        if sup:
            d = DATE_RE.search(ln, sup.start(), sup.end() + 40)
            superseded = d.group(1) if d else "undated"
        # a list-shaped ruling ('Do NOT re-propose: a · b · c · ...'): the items the cut hid, counted
        # over the whole unit and never printed (a summary is never the whole line)
        items = [x for x in LIST_SEP_RE.split(ln[h["start"]:]) if _clean(x).strip()]
        hidden = 0
        if len(items) >= LIST_MIN_ITEMS:
            hidden = sum(1 for x in items if _clean(x).strip()[:24] not in summary)
        fragment = normalize(_cut(clean, pos, 400))
        tokens = ruling_tokens(fragment)
        for it in list_items:
            tokens |= it["tokens"]      # a long list's every item, not only the 400 characters kept
        out.append({"path": rel, "line": h["line"], "lines": h["lines"], "marker": h["marker"], "date": date,
                    "summary": summary, "superseded": superseded, "hidden_items": hidden,
                    "fragment": fragment, "tokens": tokens, "clause": clause, "segment": segment, "items": list_items,
                    "kinds": h["kinds"], "standing_section": h["standing_section"],
                    # the ruling section it sits in (its items vouch for each other together)
                    "section_key": "%s:%d" % (rel, h["section_line"]) if h.get("section_line") else "",
                    # each marker's own words: a kept ruling must still carry every one of them
                    "anchors": [normalize(ln[s:e]) for s, e in h["spans"]]})
    return out


_STOP = frozenset((
    "about after again also been before being both could does doing done each from have having here into "
    "just more most much only other over same should some such than that their them then there these they "
    "this those through under until very were what when where which while will with would your yours "
    "never owner owners ruled ruling rulings confirmed declined voided "
    "re-propose re-proposed re-raise re-raised re-ask re-asked re-open re-litigate re-file re-filed "
    "repropose reraise reask reopen").split())
_TOKEN_STRIP = ".,;:!?()[]{}\"'<>|*=\u00b7-"


def ruling_tokens(fragment):
    """The distinctive words of a normalize()d ruling: 4+ characters or carrying a digit, minus
    stop words and the marker vocabulary every ruling shares."""
    out = set()
    for w in fragment.split():
        w = w.strip(_TOKEN_STRIP)
        if (len(w) >= 4 or any(c.isdigit() for c in w)) and w not in _STOP:
            out.add(w)
    return out


def _anchored(words, reference, anchors):
    """True when, for EVERY marker in `anchors`, some word 4-gram that covers part of the marker AND
    part of its context is in `reference`. Checked over every such gram, never a sample: the marker
    sentence is exactly what a rewrite that keeps the context drops ('... charts written. Do not
    re-raise.' losing only its last sentence), and a bare 'do not re-raise.' elsewhere proves nothing."""
    plain = [w.strip(_TOKEN_STRIP) for w in words]
    for a in anchors:
        aw = [w.strip(_TOKEN_STRIP) for w in a.split()]
        if not aw:
            continue
        at = next((i for i in range(len(plain) - len(aw) + 1) if plain[i:i + len(aw)] == aw), None)
        if at is None:
            continue                    # the marker's words cannot be located: nothing to require
        end = at + len(aw)
        grams = [" ".join(words[g:g + SHINGLE]) for g in range(max(0, at - SHINGLE + 1), min(end, len(words) - SHINGLE + 1))
                 if g < at or g + SHINGLE > end]
        if grams and not any(g in reference for g in grams):
            return False
    return True


ALL_KINDS = tuple(name for name, _rx in MARKERS)
ITEM_SHARE = 0.6       # a list item is still there when the matching ruling carries this share of its words


def _toks(r):
    """A ruling's distinctive words: its fragment's and, for a list, every item's (rulings_in_text)."""
    return r.get("tokens") or ruling_tokens(r["fragment"])


_NOT_FACT = re.compile(r"^[a-z]*#|\.[a-z0-9]{1,6}:\d+$")


def _facts(tokens):
    """The date- and number-bearing words of a ruling that are not the ROW's: row ids (#12, G#848) and
    file:line references (roadmap.md:3, review 3, F1). A hyphenated id is the ruling's (postgres-15,
    tier-2: critic C7). What makes two rulings worded alike DIFFERENT
    rulings (two nights' guards differ in exactly these, review FK-HIST#8)."""
    return {w for w in tokens if any(c.isdigit() for c in w) and not _NOT_FACT.search(w)}


def _grams(words):
    """A sample of at most ~24 word 4-grams of a fragment (all of them for a short one)."""
    if len(words) < SHINGLE + 2:
        return []
    grams = [" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)]
    return grams[::max(1, len(grams) // 24)]


def build_index(rulings):
    """The current rulings, ready to compare a removed one with: {'entries': one per ruling (fragment,
    core, tokens, facts, kinds) plus one per ruling SECTION -- its items' words together, vouching for
    every marker kind, because the heading is the marker (a list promoted to a section, review
    FL-CUR#1) -- 'cores': every ruling's core, 'clauses': every ruling's own clause, as cores}."""
    entries, cores, clauses, groups = [], set(), set(), {}
    for r in rulings:
        toks = _toks(r)
        e = {"fragment": r["fragment"], "core": _core(r["fragment"]), "tokens": toks, "facts": _facts(toks),
             "kinds": set(r.get("kinds", ())), "parts": None, "path": (r.get("path") or "").casefold(),
             "list": bool(r.get("items"))}
        entries.append(e)
        cores.add(e["core"])
        for cl in (r.get("clause"), r.get("segment")):
            if cl:
                clauses.add(_core(cl))
        if r.get("section_key"):
            g = groups.setdefault(r["section_key"], {"fragment": "", "core": "", "tokens": set(), "facts": set(),
                                                     "kinds": set(ALL_KINDS) | {"section", "label"}, "parts": []})
            g["tokens"] |= toks
            g["facts"] |= e["facts"]
            g["parts"].append(r["fragment"])
    for g in groups.values():
        g["fragment"] = " · ".join(g["parts"])
    cores.discard("")
    clauses.discard("")
    return {"entries": entries + list(groups.values()), "cores": cores, "clauses": clauses}


def kept_as_ruling(r, idx, contrast=None):
    """(kept, missing items): is ruling `r` -- from a HEAD copy or an old commit -- still a ruling among
    the current ones (`idx`, build_index)? Kept, in this order, when:
      its core (words in order, markup folded away) is a current ruling's core (review FL-CUR#0);
      its own marker clause, or the marker's own segment (after a status word, a table cell, ' -- ' or
        ': '), names its subject (2+ distinctive words, not dates) and is a current ruling's clause or segment: a row
        rewritten around a ruling sentence it kept verbatim (review FL-HIST#0; review 3, F1, F4);
      ONE current ruling -- or one ruling section, its items together -- carries half its word 4-grams
        with a gram through each marker (a status flip), or 60% of its distinctive words and every
        marker kind it had (a reworded list, however short, matched against a list: review 3, F7; critic
        C6), or -- for an item of a ruling section -- its whole text set off by a boundary mark in another
        such item of the same file (text added around it: a sub-bullet, a note, a date, review 3, F5, F6;
        critic C5); AND that
        one carries every date or number it had (never its row's id or a file:line reference, review 3,
        F1), 60% of its CONTRASTIVE words -- `contrast`, its words no other ruling of its old copy
        has (a set, or a callable returning one; default: all its words), so a sibling that stood
        beside it cannot vouch for it (review FK-CUR#0, #1); a ruling with NO contrastive word (a
        sibling had all of them) is kept only by its core or clause (review 3, K1) -- and, for a list,
        60% of each item's words (review FK-HIST#7).
    `missing` names the items the closest such match lacks. Two rulings in DIFFERENT files that differ
    by one subject word still read as one: no similarity threshold tells that from a rewording."""
    frag = r["fragment"]
    if not frag:
        return True, []
    core = _core(frag)
    if core in idx["cores"]:
        return True, []
    for cl in (r.get("clause") or "", r.get("segment") or ""):
        if cl and len(_subject(cl)) >= CLAUSE_MIN_TOKENS and _core(cl) in idx["clauses"]:
            return True, []
    words = frag.split()
    sample = _grams(words)
    mine = _toks(r)
    facts = _facts(mine)
    body = re.sub(r"^\d{1,4}[.)]\s+", "", frag).strip().rstrip(" .;:!?,")
    in_section, here = "section" in r.get("kinds", ()), (r.get("path") or "").casefold()
    want = set(r.get("kinds", ())) - {"section", "label"}
    items = r.get("items") or []
    con, best = None, None
    for c in idx["entries"]:
        if not facts <= c["facts"]:
            continue
        by_grams = (bool(sample) and c["parts"] is None
                    and sum(1 for g in sample if g in c["fragment"]) * 2 >= len(sample)
                    and _anchored(words, c["fragment"], r.get("anchors", ())))
        short_list = bool(items) and (c.get("list") or c["parts"] is not None)
        by_tokens = ((len(mine) >= TOKEN_MIN or short_list) and len(mine & c["tokens"]) >= TOKEN_SHARE * len(mine)
                     and want <= c["kinds"])
        by_words = (c["parts"] is None and bool(body) and in_section and "section" in c["kinds"]
                    and c.get("path") == here and _whole_in(body, c["fragment"]))
        if not (by_grams or by_tokens or by_words):
            continue
        if con is None:
            con = contrast() if callable(contrast) else (contrast if contrast is not None else mine)
        if not con or len(con & c["tokens"]) < TOKEN_SHARE * len(con):
            continue                    # the words that made it THIS ruling are not in that one -- or it
                                        # has none (a sibling had every word): only its core keeps it
        missing = [it for it in items
                   if it["tokens"] and len(it["tokens"] & c["tokens"]) < ITEM_SHARE * len(it["tokens"])]
        if not missing:
            return True, []
        if best is None or len(missing) < len(best):
            best = missing
    return False, [it["text"] for it in best or []]


_EDGE = ".;:!?,()[]|-"


def _subject(clause):
    """A clause's distinctive words that name something: dates and bare numbers never do (critic C1)."""
    return {w for w in ruling_tokens(clause) if not re.fullmatch(r"[\d.:/-]+", w)}


def _whole_in(body, text):
    """True when `body` (a ruling's normalize()d text, its end punctuation dropped) is in `text` as a whole
    segment: each side is the text's edge or a boundary mark (a sentence end, ':', ' -- ', a bracket, a
    table cell). Text was added AROUND the ruling ('Keep the single queue -- reconfirmed', a date in front,
    a sub-bullet, review 3, F5, F6); a phrase that CONTINUES it is another ruling ('the cache' is not 'the
    cache question': the TOKEN_MIN guard)."""
    i = text.find(body)
    while i >= 0:
        before, after = text[:i].rstrip(), text[i + len(body):].lstrip()
        if (not before or before[-1] in _EDGE) and (not after or after[0] in _EDGE):
            return True
        i = text.find(body, i + 1)
    return False


def _core_text(norm):
    """A normalize()d text reduced to its words, the way _core reduces a fragment."""
    words = (w.strip("'\u2019-") for w in _CORE_WORD.findall(norm))
    return " ".join(w for w in words if w)


def _wordish(c):
    return c.isalnum() or c in "_'\u2019-"


def _run_in(text, run):
    """True when `run` appears in `text` as whole words (never 'cloud' inside 'cloudflare', review P3)."""
    if not run:
        return False
    i, n = text.find(run), len(run)
    while i >= 0:
        if not (i > 0 and _wordish(text[i - 1])) and not (i + n < len(text) and _wordish(text[i + n])):
            return True
        i = text.find(run, i + 1)
    return False


def text_survives(r, norm, cored=""):
    """True when ruling `r`'s words are still in `norm` (the normalize()d text of a file or the corpus),
    whether or not they still read as a ruling there: its fragment as whole words, its core as a
    whole-word run of `cored` (_core_text of the same text; a string or a callable), its self-contained
    clause, or half its word 4-grams with a gram through each marker."""
    frag = r["fragment"]
    if not frag or _run_in(norm, frag):
        return True
    core = _core(frag)
    if core:
        ct = cored() if callable(cored) else cored
        if ct and (" %s " % core) in (" %s " % ct):
            return True
    for cl in (r.get("clause") or "", r.get("segment") or ""):
        if cl and len(_subject(cl)) >= CLAUSE_MIN_TOKENS and _run_in(norm, cl):
            return True
    words = frag.split()
    sample = _grams(words)
    return bool(sample) and sum(1 for g in sample if g in norm) * 2 >= len(sample) \
        and _anchored(words, norm, r.get("anchors", ()))


def _items_text(missing):
    """'N item(s) ("a", "b", "c" and M more)' for a list ruling's dropped items."""
    shown = ", ".join('"%s"' % t for t in missing[:3])
    more = " and %d more" % (len(missing) - 3) if len(missing) > 3 else ""
    return "%d item(s) (%s%s)" % (len(missing), shown, more)


def _contrast_fn(path, text, cache, key):
    """A lazy contrast for the rulings of ONE old copy: of(r) -> r's words that no other ruling of the
    copy has. The copy is scanned whole only when a fuzzy match needs it (once per copy per run)."""
    def of(r):
        if key not in cache:
            counts = {}
            for x in rulings_in_text(path, text):
                for t in _toks(x):
                    counts[t] = counts.get(t, 0) + 1
            cache[key] = counts
        return {t for t in _toks(r) if cache[key].get(t, 0) <= 1}
    return of


# ---------------------------------------------------------------------------------------
# The project
# ---------------------------------------------------------------------------------------

def _corpus_module():
    """docket_corpus from this directory, loaded without a bytecode cache."""
    p = Path(__file__).resolve().parent / "docket_corpus.py"
    mod = types.ModuleType("docket_corpus")
    mod.__file__ = str(p)
    exec(compile(p.read_text(encoding="utf-8"), str(p), "exec"), mod.__dict__)
    return mod


def _git(root, args, timeout=60):
    try:
        r = subprocess.run(["git", "-C", str(root), "-c", "core.quotepath=false"] + list(args),
                           capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, (r.stderr.strip().splitlines() or ["git exited %d" % r.returncode])[-1]
    return r.stdout, ""


def _decode(raw):
    """Text of a file: UTF-16 by its BOM, UTF-8 with or without a BOM (PowerShell 5.1 writes both).
    The same two-line rule as docket_corpus._decode, which lives on an object this module only
    reaches inside Project."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


def _read(path):
    try:
        return _decode(Path(path).read_bytes())
    except OSError:
        return ""


def _safe_rel(p):
    """A repo-relative POSIX path, or None when it is empty, absolute or climbs out with '..'."""
    s = str(p or "").replace("\\", "/").strip()
    if not s or s.startswith("/") or re.match(r"^[A-Za-z]:", s) or ".." in s.split("/"):
        return None
    return s


def parse_rulings_config(text, name=RULINGS_CONFIG):
    """([(rel, by)], [error]) from the text of a rulings-sources.json. Never raises.

    {"sources": [{"path": "docs/x.md", "by": "delegated", "note": "..."}, "docs/y.md"], "comment": "..."}
    A path is a literal repo-relative file (no glob). 'by' is "owner" (the default) or "delegated"
    (a ruling the agent made under the owner's delegation: printed [delegated], re-openable on
    evidence). An unknown key is an error, never a silent default: a typo'd "source" would
    otherwise declare nothing and print nothing."""
    try:
        cfg = json.loads(text)
    except ValueError as e:
        return [], ["%s is not readable JSON: %s" % (name, e)]
    if not isinstance(cfg, dict):
        return [], ["%s must hold a JSON object" % name]
    errs = []
    unknown = sorted(set(cfg) - _CONFIG_KEYS)
    if unknown:
        errs.append("%s: unknown key(s) %s" % (name, unknown))
    srcs = cfg.get("sources", [])
    if not isinstance(srcs, list):
        return [], errs + ["%s: 'sources' must be a list" % name]
    out = []
    for n, s in enumerate(srcs):
        if isinstance(s, str):
            s = {"path": s}
        if not isinstance(s, dict):
            errs.append("%s: sources[%d] must be a path or an object" % (name, n))
            continue
        bad = sorted(set(s) - _SOURCE_KEYS)
        if bad:
            errs.append("%s: sources[%d] unknown key(s) %s" % (name, n, bad))
        rel = _safe_rel(s.get("path"))
        if rel is None:
            errs.append("%s: sources[%d] path %r is empty, absolute or outside the project; ignored"
                        % (name, n, s.get("path")))
            continue
        by = s.get("by", "owner")
        if by not in BY_VALUES:
            errs.append("%s: sources[%d] 'by' must be one of %s; read as 'owner'" % (name, n, list(BY_VALUES)))
            by = "owner"
        out.append((rel, by))
    return out, errs


class Project(object):
    """This project's sources, its corpus, and how to show a path."""

    def __init__(self, cwd=None):
        dc = _corpus_module()
        self.dc = dc
        cwd = str(Path(cwd or os.getcwd()).resolve())
        _, chosen = dc.select("here", cwd=cwd)
        self.ok = bool(chosen)
        if not self.ok:
            return
        p = chosen[0]
        self.root = Path(p["root"]).resolve()
        self.name = p["name"]
        self._rels = {}         # rel() resolves a path (slow on Windows): once per path per run
        # The configs as the working tree holds them (HEAD's are read on first need): together they
        # decide what a source is, for the history pathspec and for source_kind.
        self.work_config = _snapshot(dc, *[_read(self.root / n) if (self.root / n).is_file() else None
                                           for n in CONFIG_NAMES])
        self._head_config = None
        top, _err = _git(self.root, ["rev-parse", "--show-toplevel"])
        self.git = bool(top)
        # A submodule's files are another repository's: this one has no history of them.
        self.submodules = []
        if self.git and (self.root / ".gitmodules").is_file():
            out, _e = _git(self.root, ["config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$"])
            for ln in (out or "").splitlines():
                parts = ln.split(None, 1)
                if len(parts) == 2:
                    self.submodules.append(parts[1].strip().replace("\\", "/").rstrip("/").casefold())
        files, _cfg, self.config_error = dc._project_files(p)
        # Every reason this run could not read what it should have: printed as 'could not check',
        # never swallowed (a stored-and-dropped config error emptied a whole section once).
        self.errors = [self.config_error] if self.config_error else []
        mem_dirs = [self.root / m for m in dc.MEMORY_LEVELS if (self.root / m).is_dir()]
        home = dc._home_memory(p["main"])
        if home is not None:
            mem_dirs.append(Path(home))
        seen, self.standing, self.corpus_files = set(), [], []
        self.by = {}        # _key(path) -> "delegated" for a rulings-sources.json source declared so

        def add(path, standing):
            k = _key(path)
            if k in seen:
                return
            seen.add(k)
            self.corpus_files.append(Path(path))
            if standing:
                self.standing.append(Path(path))

        for path, kind, _rel in files:
            if kind in STANDING_KINDS:
                add(path, True)
        # context/HANDOFF*.md: a layout the briefing supports but docket_corpus never lists (it is
        # read here, not added there, so no docket id changes).
        ctx = self.root / "context"
        if ctx.is_dir():
            for nm in sorted(os.listdir(str(ctx))):
                if nm.lower().startswith("handoff") and nm.lower().endswith(".md") and (ctx / nm).is_file():
                    add(ctx / nm, True)
        # rulings-sources.json: files that hold rulings but are not dockets (a design spec's rulings
        # table). Read by this tool only, so the file never becomes a docket for other tools.
        cfgp = self.root / RULINGS_CONFIG
        if cfgp.is_file():
            decl, errs = parse_rulings_config(_read(cfgp))
            self.errors.extend(errs)
            for rel, by in decl:
                path = self.root / rel
                if not path.is_file():
                    self.errors.append("%s: path %r matched nothing" % (RULINGS_CONFIG, rel))
                    continue
                add(path, True)
                if by == "delegated":
                    self.by[_key(path)] = by
        for d in mem_dirs:
            if (d / "MEMORY.md").is_file():
                add(d / "MEMORY.md", True)
        # an archive of closed rows is not a standing source, except a section whose heading says its
        # items stand ('Standing rulings', 'Do not re-raise'): read in archive_rulings()
        self.archives = [Path(path) for path, kind, _rel in files if kind in ARCHIVE_KINDS]
        for path, kind, _rel in files:
            add(path, False)
        for d in mem_dirs:
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = []
            for nm in names:
                if nm.lower().endswith(".md") and (d / nm).is_file():
                    add(d / nm, False)
        self._corpus = self._current = self._index = self._acks = self._archive = self._cored_corpus = None
        self._norm, self._scanned, self._cored = {}, {}, {}
        self.ack_notes = []     # acknowledgements that withdraw nothing, and why (printed as state lines)

    def rel(self, path):
        k = str(path)
        got = self._rels.get(k)
        if got is None:
            got = self._rels[k] = self._rel(Path(path))
        return got

    def _rel(self, path):
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            pass
        try:
            return "~/" + path.resolve().relative_to(Path.home().resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def in_repo(self, path):
        try:
            Path(path).resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def in_git(self, path):
        """In THIS repository's history: inside the root and under no submodule (review FK-HIST#10)."""
        if not (self.git and self.in_repo(path)):
            return False
        rel = self.rel(path).casefold()
        return not any(rel == s or rel.startswith(s + "/") for s in self.submodules)

    def normalized(self, path):
        k = _key(path)
        if k not in self._norm:
            self._norm[k] = normalize(_read(path))
        return self._norm[k]

    def corpus(self):
        if self._corpus is None:
            self._corpus = "\n".join(self.normalized(p) for p in self.corpus_files)
        return self._corpus

    def archive_rulings(self):
        """Rulings in an archive section whose heading says its items stand (built once)."""
        if self._archive is None:
            self._archive = []
            for p in self.archives:
                text = _read(p)
                if not STANDING_HEAD_RE.search(_plain(text)):
                    continue            # cheap skip: most archives have no such heading at all
                for r in rulings_in_text(self.rel(p), text):
                    if r["standing_section"]:
                        r["archive"] = True
                        self._archive.append(r)
        return self._archive

    def rulings_of(self, path):
        """rulings_in_text of one standing file, scanned once per run."""
        k = _key(path)
        if k not in self._scanned:
            self._scanned[k] = rulings_in_text(self.rel(path), _read(path))
        return self._scanned[k]

    def current(self):
        """Every ruling the briefing's sources hold NOW: the standing files plus the standing
        sections of archives (built once, on first need)."""
        if self._current is None:
            self._current = [r for p in self.standing for r in self.rulings_of(p)]
            self._current += self.archive_rulings()
        return self._current

    def index(self):
        """build_index of the current rulings (built once)."""
        if self._index is None:
            self._index = build_index(self.current())
        return self._index

    def cored(self, path):
        k = _key(path)
        if k not in self._cored:
            self._cored[k] = _core_text(self.normalized(path))
        return self._cored[k]

    def cored_corpus(self):
        if self._cored_corpus is None:
            self._cored_corpus = _core_text(self.corpus())
        return self._cored_corpus

    def acks(self):
        """[{phrase, text, rel, line, sha}] for every <!-- ruling-withdrawn: "..." --> in a standing file of
        this repository; `sha` is the commit that introduced the line ("" when it is not committed yet).
        A phrase of fewer than ACK_MIN_WORDS words or ACK_MIN_TOKENS distinctive ones names no one ruling,
        and an ack whose line git cannot date cannot be bound to a change: each withdraws nothing, and
        self.ack_notes says so."""
        if self._acks is None:
            self._acks = []
            for p in self.standing:
                text = _read(p)
                found = []
                for m in ACK_RE.finditer(text):
                    raw, phrase = m.group(1), normalize(m.group(1))
                    where = "%s:%d" % (self.rel(p), text.count("\n", 0, m.start()) + 1)
                    if len(phrase.split()) < ACK_MIN_WORDS or not ruling_tokens(phrase):
                        self.ack_notes.append('ack "%s" at %s is too short to name a ruling (%d+ words, one of them '
                                              'distinctive): it withdraws nothing' % (_cut(raw, 0, 60), where, ACK_MIN_WORDS))
                    elif not self.in_git(p):
                        self.ack_notes.append('ack "%s" at %s is outside this repository\'s history, so it cannot be '
                                              'dated: it withdraws nothing' % (_cut(raw, 0, 60), where))
                    else:
                        found.append({"phrase": phrase, "text": raw, "rel": self.rel(p),
                                      "line": int(where.rsplit(":", 1)[1])})
                if found:
                    shas = _blame_shas(self, self.rel(p), [a["line"] for a in found])
                    for a in found:
                        if a["line"] in shas:
                            a["sha"] = shas[a["line"]]
                            self._acks.append(a)
                        else:
                            self.ack_notes.append('ack "%s" at %s:%d could not be dated (git blame): it withdraws '
                                                  'nothing this run' % (_cut(a["text"], 0, 60), a["rel"], a["line"]))
        return self._acks

    def verdict(self, r, contrast=None):
        """What became of a ruling that a HEAD copy or an old commit carried (`contrast`: see
        kept_as_ruling):
        ("kept", "")        still a ruling in a source the briefing reads;
        ("pruned", items)   still a ruling, but list items it killed are in no ruling now;
        ("unruled", rel)    its text is still in `rel` -- a standing file, or its own file -- but no
                            longer reads as a ruling (a retitled heading, a deleted marker);
        ("moved", rel)      its text survives only in `rel`, a file the briefing does not read as
                            standing (an archive, a note);
        ("lost", "")        nowhere.
        Acknowledgements are applied afterwards, to the whole run's removals at once (apply_acks)."""
        kept, missing = kept_as_ruling(r, self.index(), contrast)
        if kept:
            return "kept", ""
        if missing:
            return "pruned", _items_text(missing)
        if text_survives(r, self.corpus(), self.cored_corpus):
            standing = {_key(p) for p in self.standing}
            own = str(r.get("path", "")).casefold()
            # the ruling's own file first: text still where it was (a standing file, or an archive whose
            # standing heading was retitled) is un-ruled there, never 'moved' into it
            for p in sorted(self.corpus_files, key=lambda p: self.rel(p).casefold() != own):
                if text_survives(r, self.normalized(p), lambda p=p: self.cored(p)):
                    same = self.rel(p).casefold() == own
                    return ("unruled" if (same or _key(p) in standing) else "moved"), self.rel(p)
        return "lost", ""

    def head_config(self):
        """The configs as HEAD holds them (an empty snapshot outside git or before the first commit)."""
        if self._head_config is None:
            got = _blobs(self.root, ["HEAD:" + n for n in CONFIG_NAMES]) if self.git else {}
            self._head_config = _snapshot(self.dc, *[got.get("HEAD:" + n) for n in CONFIG_NAMES])
        return self._head_config

    def outside(self):
        """Standing files outside this repository's history (the home memory index, a submodule's
        files): their rulings print, but no history here can show one being removed."""
        return [p for p in self.standing if not self.in_git(p)]

    def source_names(self):
        names = [self.rel(p) for p in self.standing]
        if len(names) > NAMES_SHOWN:
            return ", ".join(names[:NAMES_SHOWN]) + " +%d more" % (len(names) - NAMES_SHOWN)
        return ", ".join(names)


def _key(path):
    return os.path.normcase(os.path.realpath(str(path)))


def _blame_dates(proj, rel, lines):
    """{line: 'YYYY-MM-DD'}: the committer date of each line's last change, from ONE git blame per
    file (-L per line). An uncommitted line, a timeout or any failure gives no entry."""
    args = ["blame", "--line-porcelain"]
    for n in sorted(set(lines)):
        args += ["-L", "%d,%d" % (n, n)]
    out, _e = _git(proj.root, args + ["--", rel], timeout=BLAME_TIMEOUT)
    got, cur, when = {}, None, None
    for ln in (out or "").splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            cur = None if set(m.group(1)) == {"0"} else int(m.group(2))
            continue
        if cur is None:
            continue
        if ln.startswith("committer-time "):
            when = int(ln.split()[1])
        elif ln.startswith("committer-tz ") and when is not None:
            tz = ln.split()[1]
            off = (1 if tz[0] == "+" else -1) * (int(tz[1:3]) * 3600 + int(tz[3:5]) * 60)
            got[cur] = time.strftime("%Y-%m-%d", time.gmtime(when + off))
            when = None
    return got


def _blame_shas(proj, rel, lines):
    """{line: the commit that introduced it, '' when not committed yet} from ONE git blame of the
    working-tree file. A file git does not track yet is all uncommitted; a line blame could not date is
    missing (an ack on it is not bound to anything, so it clears nothing)."""
    args = ["blame", "--line-porcelain"]
    for n in sorted(set(lines)):
        args += ["-L", "%d,%d" % (n, n)]
    out, _e = _git(proj.root, args + ["--", rel], timeout=BLAME_TIMEOUT)
    if out is None:
        tracked, _e = _git(proj.root, ["ls-files", "--", rel])
        return {n: "" for n in lines} if tracked is not None and not tracked.strip() else {}
    got = {}
    for ln in out.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            got[int(m.group(2))] = m.group(1) if m.group(1).strip("0") else ""
    return got


def _ack_after(proj, a, sha, cache):
    """True when ack `a` was written in the same change as the removal commit `sha` made (None: a
    working-tree removal) or later. An ack never clears a removal made after it: that is how one comment
    silently withdrew every later drop sharing its phrase (review FK-HIST#6)."""
    if a["sha"] == "":
        return True                     # not committed yet: written with, or after, any removal
    if sha is None:
        return False                    # a committed ack predates a removal still in the working tree
    key = (sha, a["sha"])
    if key not in cache:
        out, _e = _git(proj.root, ["merge-base", "--is-ancestor", sha, a["sha"]])
        cache[key] = out is not None
    return cache[key]


def _ack_names(phrase, r):
    """(how many of ruling `r`'s distinctive words the ack `phrase` carries, how many it has): its clause's
    when the clause names it (ACK_MIN_TOKENS+), else its fragment's."""
    clause = ruling_tokens(r.get("clause") or "")
    need = clause if len(clause) >= ACK_MIN_TOKENS else ruling_tokens(r["fragment"])
    return len(ruling_tokens(phrase) & need), len(need)


def apply_acks(proj, rems):
    """(still, cleared) for a run's removals (each with `fragment` and `sha`, None for a working-tree
    one). An acknowledgement clears a removal when its phrase is in the ruling's words, it was written
    with the removal or later (_ack_after), and it matches exactly ONE of this run's removals: a phrase
    that matches several clears none of them, and each carries a note naming it (review FK-CUR#2). The
    one it matches it clears only when the phrase carries ACK_SHARE of that ruling's distinctive words:
    the run sees only its window, so a phrase a family of rulings shares can match one of them here
    while it was written for another that left the window; it clears nothing and says so (review 3, K4)."""
    acks = proj.acks()
    cache, hits = {}, {}
    for k, r in enumerate(rems):
        words = " %s " % _core(r["fragment"])
        for i, a in enumerate(acks):
            if " %s " % _core(a["phrase"]) not in words:
                continue
            if _ack_after(proj, a, r.get("sha"), cache):
                hits.setdefault(i, []).append(k)
            else:
                r.setdefault("early", []).append(a)     # say why it does not clear (review 3, F10)
    cleared = {}
    for i, ks in hits.items():
        same = {_core(rems[k].get("segment") or rems[k].get("clause") or rems[k]["fragment"]) for k in ks}
        if len(ks) == 1 or len(same) == 1:      # one ruling, or its one sentence recorded twice (review 3, F9; critic C8)
            for k in ks:
                got, need = _ack_names(acks[i]["phrase"], rems[k])
                if got >= min(ACK_MIN_TOKENS, need) and got >= ACK_SHARE * need:
                    cleared.setdefault(k, acks[i])
                else:
                    rems[k].setdefault("vague", []).append((acks[i], got, need))
        else:
            for k in ks:
                rems[k].setdefault("ambiguous", []).append((acks[i], len(ks)))
    still = [r for k, r in enumerate(rems) if k not in cleared]
    return still, [dict(rems[k], ack=cleared[k]) for k in sorted(cleared)]


def _amb(r):
    """The notes on a removal that an acknowledgement could not clear: one matching several removals, or
    one naming too little of this ruling (review 3, K4)."""
    return "".join(' [ack "%s" at %s:%d matches %d removals: make it specific]'
                   % (_cut(a["text"], 0, 60), a["rel"], a["line"], n) for a, n in r.get("ambiguous", [])) + \
        "".join(' [ack "%s" at %s:%d names too little of it (%d of its %d distinctive words): quote more of the ruling]'
                % (_cut(a["text"], 0, 60), a["rel"], a["line"], got, need) for a, got, need in r.get("vague", [])) + \
        "".join(' [ack "%s" at %s:%d was committed before this removal, so it does not clear it]'
                % (_cut(a["text"], 0, 60), a["rel"], a["line"]) for a in r.get("early", []))


def _acked_line(cleared, show_all=False):
    """'(N removal(s) acknowledged as withdrawn: "<ruling>" by <file>:<line>; ...)': each withdrawal
    named, so a stale ack that clears a new drop is visible rather than a bare count."""
    shown = cleared if show_all else cleared[:REMOVED_SHOWN]
    body = "; ".join('"%s" by %s:%d' % (_cut(r["summary"], 0, 90), r["ack"]["rel"], r["ack"]["line"]) for r in shown)
    more = "; and %d more" % (len(cleared) - len(shown)) if len(cleared) > len(shown) else ""
    return "(%d removal(s) acknowledged as withdrawn: %s%s)" % (len(cleared), body, more)


def _duplicate_of(r, kept):
    """The kept ruling `r` repeats, or None. Two rulings are one only when EACH carries at least 80%
    of the other's distinctive words AND their dates and number-bearing words agree: two nights'
    guards worded alike differ in exactly those (measured: a 60% one-way match merged two different
    nights into one line)."""
    mine = ruling_tokens(r["fragment"])
    if len(mine) < TOKEN_MIN:
        return None
    digits = {w for w in mine if any(c.isdigit() for c in w)}
    for k in kept:
        other = ruling_tokens(k["fragment"])
        if len(other) < TOKEN_MIN or k.get("date") != r.get("date"):
            continue
        shared = len(mine & other)
        if (shared >= DUP_SHARE * len(mine) and shared >= DUP_SHARE * len(other)
                and digits == {w for w in other if any(c.isdigit() for c in w)}):
            return k
    return None


def standing(proj):
    groups = [(proj.rel(p), proj.in_git(p), proj.by.get(_key(p), ""), [dict(r) for r in proj.rulings_of(p)])
              for p in proj.standing]
    arch = {}
    for r in proj.archive_rulings():
        arch.setdefault(r["path"], []).append(dict(r))
    groups += [(rel, True, "", rs) for rel, rs in arch.items()]
    out = []
    for rel, inrepo, by, rs in groups:
        undated = [r["line"] for r in rs if not r["date"]]
        blame = _blame_dates(proj, rel, undated) if undated and proj.git and inrepo else {}
        for r in rs:
            r["by"] = by
            r["blame"] = "" if r["date"] else blame.get(r["line"], "")
            out.append(r)
    seen, uniq = set(), []
    for r in out:
        key = normalize(r["summary"])
        if key in seen:
            continue
        seen.add(key)
        dup = _duplicate_of(r, uniq)
        if dup is not None:
            dup.setdefault("also", []).append("%s:%d" % (r["path"], r["line"]))
            continue
        uniq.append(r)
    # newest first; an undated ruling sorts by its line's last change (blame), so an undated ruling
    # is never pushed behind the cap merely for being undated; the sort is stable, so ties keep
    # file and line order
    uniq.sort(key=lambda r: r["date"] or r.get("blame", ""), reverse=True)
    return uniq


def _blobs(root, names):
    """{name: text or None} for object names -- blob ids or '<rev>:<path>' -- read through ONE
    `git cat-file --batch` (a spawn per copy costs seconds on a 30-commit window), decoded by _decode
    (UTF-16, a BOM). A missing object, a non-blob, or any failure gives None."""
    names = list(dict.fromkeys(n for n in names if n and "\n" not in n))
    if not names:
        return {}
    try:
        r = subprocess.run(["git", "-C", str(root), "cat-file", "--batch"],
                           input=("\n".join(names) + "\n").encode("utf-8"), capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {n: None for n in names}
    out, pos, got = r.stdout, 0, {}
    for n in names:
        nl = out.find(b"\n", pos)
        if nl < 0:
            got[n] = None
            continue
        parts = out[pos:nl].decode("utf-8", "replace").split()
        pos = nl + 1
        if len(parts) == 3 and parts[1] == "blob" and parts[2].isdigit():
            size = int(parts[2])
            got[n] = _decode(out[pos:pos + size])
            pos += size + 1
        else:
            got[n] = None               # '<name> missing', or not a blob
    return got


# ---------------------------------------------------------------------------------------
# What a path WAS: sources by name and location, under a given tree's configs
# ---------------------------------------------------------------------------------------

def _dirs(dc):
    """(level dirs, memory dirs, archive dirs) as casefolded 'a/b/' prefixes, taken from docket_corpus's
    own constants, so a path is judged exactly as docket_corpus reads a working tree."""
    lv = tuple(((d + "/") if d else "").casefold() for d in dc.LEVELS)
    mem = tuple((d + "/").casefold() for d in dc.MEMORY_LEVELS)
    arch = tuple((((d + "/") if d else "") + "archive/").casefold() for d in dc.ARCHIVE_PARENTS)
    return lv, mem, arch


def _snapshot(dc, rulings_text=None, corpus_text=None):
    """The configs as one tree holds them: {'declared': casefolded rulings-sources.json paths, 'by':
    {path: by}, 'paths' / 'exclude': docket-corpus.json's patterns, 'dc': the docket_corpus module}.
    A missing or malformed text declares nothing (the working tree's own errors are printed elsewhere)."""
    snap = {"declared": set(), "by": {}, "paths": [], "exclude": [], "dc": dc}
    if rulings_text:
        for rel, by in parse_rulings_config(rulings_text)[0]:
            snap["declared"].add(rel.casefold())
            snap["by"][rel.casefold()] = by
    if corpus_text:
        try:
            cfg = json.loads(corpus_text)
        except ValueError:
            cfg = {}
        if isinstance(cfg, dict):
            for key in ("paths", "exclude"):
                vals = cfg.get(key, [])
                for pat in vals if isinstance(vals, list) else []:
                    s = _safe_rel(pat) if key == "paths" else str(pat).replace("\\", "/").strip()
                    if s:
                        snap[key].append(s.casefold())
    return snap


_GLOBS = {}


def _glob_re(pattern):
    """A compiled match for a docket-corpus.json 'paths' glob as Path.glob reads it: '*' and '?' stay inside
    one path segment and '**' spans any number of them (fnmatch's '*' crosses '/', so a nested file the
    briefing never read was judged a source: a THRESHOLD on a clean tree, review 3, F2)."""
    key = pattern.casefold().replace("\\", "/").strip("/")
    if key not in _GLOBS:
        segs, rx = key.split("/"), ""
        for k, seg in enumerate(segs):
            last = k == len(segs) - 1
            if seg == "**":
                rx += ".*" if last else "(?:[^/]+/)*"
                continue
            i = 0
            while i < len(seg):
                c = seg[i]
                j = seg.find("]", i + 1) if c == "[" else -1
                if c == "*":
                    rx += "[^/]*"
                elif c == "?":
                    rx += "[^/]"
                elif j > i:
                    body = seg[i + 1:j]
                    rx += "[%s]" % (("^" + body[1:]) if body.startswith("!") else body)
                    i = j
                else:
                    rx += re.escape(c)
                i += 1
            rx += "" if last else "/"
        _GLOBS[key] = re.compile(rx)
    return _GLOBS[key]


def source_kind(rel, cfg):
    """How the briefing reads repo path `rel` under config snapshot `cfg`: "standing", "archive" (only
    its standing sections count) or "" (not read). The rules docket_corpus._project_files applies to a
    working tree -- plus context/HANDOFF*.md, which this tool adds -- applied to a NAME, so a path that
    is gone (deleted, renamed away, or seen only in an old commit) is judged the way it was read then
    (review FK-HIST#0, #4)."""
    dc = cfg["dc"]
    low = str(rel).replace("\\", "/").casefold()
    if low in cfg["declared"]:
        return "standing"               # a declaration wins over an exclude, as the briefing reads it (review 3, K3)
    if dc.excluded(low, cfg["exclude"]):
        return ""
    d, _, b = low.rpartition("/")
    d = d + "/" if d else ""
    if not b.endswith(".md") or b.startswith("docket-inbox-"):
        return ""
    lv, mem, arch = _dirs(dc)
    if d in lv and (dc.is_docket_name(b) or b.startswith("roadmap")):
        return "standing"
    if d in mem and (b == "memory.md" or b.startswith("roadmap") or dc.is_docket_name(b, strict=True)):
        return "standing"
    if d in ("", "context/") and b.startswith("handoff"):
        return "standing"
    if any(_glob_re(p).fullmatch(low) for p in cfg["paths"]):
        return "standing"
    if d in arch and b.startswith(("roadmap", "docket", "handoff")):
        return "archive"
    return ""


def _history_pathspec(proj):
    """Every name and location a source can have (so a deleted, renamed-away or retitled source is in
    the log), both config files, and every path HEAD's or the working tree's configs declare. Case-
    insensitive: a directory listing can spell a path differently from the index."""
    lv, mem, arch = _dirs(proj.dc)
    pats = []
    for d in lv:
        pats += [d + "roadmap*.md", d + "*docket*.md"]
    for d in mem:
        pats += [d + "roadmap*.md", d + "*docket*.md", d + "memory.md"]
    pats += ["handoff*.md", "context/handoff*.md"]
    for d in arch:
        pats += [d + "roadmap*.md", d + "docket*.md", d + "handoff*.md"]
    spec = [":(glob,icase)" + p for p in pats] + [":(literal,icase)" + n for n in CONFIG_NAMES]
    lits, globs = set(), set()
    for snap in (proj.head_config(), proj.work_config):
        lits |= snap["declared"]
        globs |= set(snap["paths"])
    return spec + [":(literal,icase)" + p for p in sorted(lits)] + [":(glob,icase)" + p for p in sorted(globs)]


def _zero(oid):
    return not oid or not oid.strip("0")


def _raw_records(log):
    """[(sha, date, [(old blob, new blob, status, path)])] from `git log --raw -z`. A merge appears
    once per parent whose copy differs, each entry carrying THAT parent's blob."""
    out = []
    for rec in log.split("\x1e"):
        if not rec.strip("\0\n "):
            continue
        head, _, body = rec.partition("\0")
        sha, _, cdate = head.partition("\x1f")
        toks = body.split("\0")
        ents, i = [], 0
        while i < len(toks):
            meta = toks[i].strip("\n")
            if meta.startswith(":") and i + 1 < len(toks):
                f = meta[1:].split()
                if len(f) >= 5:
                    ents.append((f[2], f[3], f[4][:1], toks[i + 1]))
                i += 2
            else:
                i += 1
        out.append((sha.strip(), cdate.strip(), ents))
    return out


def _short(root, shas):
    """{sha: its abbreviation as git prints it}, from one `git rev-parse --short` (--no-abbrev, which
    the raw blob ids need, also spells %h in full)."""
    if not shas:
        return {}
    out, _e = _git(root, ["rev-parse", "--short"] + list(shas))
    got = (out or "").split()
    return {s: (got[i] if len(got) == len(shas) else s[:7]) for i, s in enumerate(shas)}


def _structural(ln):
    """A line whose change can re-scope lines it never touched: a heading, a fence, a rule, a table
    separator, or an HTML comment boundary left open or closed."""
    return bool(HEADING_RE.match(ln) or FENCE_RE.match(ln) or HR_RE.match(ln) or TABLE_SEP_RE.match(ln)
                or ln.count("<!--") != ln.count("-->"))


def _changed(old, new):
    """(touched, structural) for two copies' lines: the 1-based lines of `old` that a change removed or
    replaced, plus the lines either side of a pure insertion; and whether any changed line, on either
    side, is structural. The common head and tail are trimmed before the line diff."""
    n, m, lo = len(old), len(new), 0
    while lo < n and lo < m and old[lo] == new[lo]:
        lo += 1
    hi = 0
    while hi < n - lo and hi < m - lo and old[n - 1 - hi] == new[m - 1 - hi]:
        hi += 1
    a, b = old[lo:n - hi], new[lo:m - hi]
    touched, structural = set(), False
    if not a and not b:
        return touched, structural
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if i2 > i1:
            touched.update(range(lo + i1 + 1, lo + i2 + 1))
        else:
            touched.update((lo + i1, lo + i1 + 1))      # the lines either side of the insertion point
        if not structural and any(_structural(x) for x in a[i1:i2] + b[j1:j2]):
            structural = True
    touched.discard(0)
    return touched, structural


def _removed_between(path, before, after, kind, limit=SUMMARY_MAX):
    """The rulings of `before` (one file's copy before a commit) that the change to `after` touched:
    around the changed lines, scanned in the copy BEFORE (a deleted table row keeps its heading); when a
    structural line changed, the two copies' rulings compared whole, because such an edit un-rules
    lines it never touched (review FK-HIST#1). An archive counts only inside its standing sections."""
    touched, structural = _changed(before.splitlines(), after.splitlines())
    if not touched:
        return []

    def stands(x):
        return kind != "archive" or x["standing_section"]
    if structural:
        keep = {_core(x["fragment"]) for x in rulings_in_text(path, after, limit=limit) if stands(x)}
        return [x for x in rulings_in_text(path, before, limit=limit) if stands(x) and _core(x["fragment"]) not in keep]
    return [x for x in rulings_in_text(path, before, limit=limit, only=touched) if stands(x)]


def _counted(kind, r):
    """Whether a source of `kind` reads ruling `r` as one: a standing file all of them, an archive only
    those inside its standing sections."""
    return kind == "standing" or (kind == "archive" and bool(r["standing_section"]))


def _dropped_by_config(proj, sha, before, limit=SUMMARY_MAX):
    """The rulings that the config edit in commit `sha` stopped reading: a file's rulings counted under
    the first parent's configs (`before`) and not under the commit's own -- an entry removed, an exclude
    added (review critic P2), or a declared file that is an archive by its own name undeclared, so only
    its standing sections still count (review 3, K2) -- read from the first parent's copy."""
    got = _blobs(proj.root, ["%s:%s" % (sha, n) for n in CONFIG_NAMES])
    after = _snapshot(proj.dc, got.get("%s:%s" % (sha, CONFIG_NAMES[0])), got.get("%s:%s" % (sha, CONFIG_NAMES[1])))
    old, _e = _git(proj.root, ["ls-tree", "-r", "-z", "--name-only", sha + "^"])
    new, _e = _git(proj.root, ["ls-tree", "-r", "-z", "--name-only", sha])
    if old is None:
        return []
    present = {p.casefold() for p in (new or "").split("\0") if p}
    gone = []
    for p in (x for x in old.split("\0") if x):
        k = source_kind(p, before)
        if not k:
            continue
        k2 = source_kind(p, after) if p.casefold() in present else ""
        if k2 != k and k2 != "standing":            # archive -> standing reads more, never less
            gone.append((p, k, k2))
    texts = _blobs(proj.root, ["%s^:%s" % (sha, p) for p, _k, _k2 in gone])
    out = []
    for p, k, k2 in gone:
        text = texts.get("%s^:%s" % (sha, p))
        for r in rulings_in_text(p, text, limit=limit) if text else []:
            if _counted(k, r) and not _counted(k2, r):
                r["left"] = p
                out.append(r)
    return out


def _in_every(r, path, others, got):
    """True when ruling `r` is in every other parent's copy of `path` (`others`: {path: that parent's blob}
    per parent diff of one merge). A parent missing from a diff has the merge's own copy, so it lacks the
    ruling too; an unreadable copy counts as having it (the THRESHOLD side)."""
    key = " %s " % _core(r["fragment"])
    for d in others:
        o = d.get(path)
        if o is None or _zero(o):
            return False
        text = got.get(o)
        if text is not None and key not in " %s " % _core_text(normalize(text)):
            return False
    return True


def removed(proj, count, limit=SUMMARY_MAX):
    """(rulings, errors, commits read, oldest date read): the rulings that the last `count` commits
    touching the briefing's sources removed, and that no source holds as a ruling now.

    Read from `git log --raw -z` and each changed file's two copies, compared here (_removed_between).
    A path counts by what it WAS before the commit -- by name and location under the configs as that
    commit found them (its first parent's) -- so a deleted or renamed-away source is read, an archive
    counts only inside its standing sections, and a file counts as a declared source only from the
    commit that declared it (review critic Case 7). A config edit that drops a source is read as
    removing its rulings. A merge is read against each parent whose copy differs. A copy git cannot
    read is counted and reported, never skipped silently."""
    if not proj.git:
        return [], [], 0, ""
    log, err = _git(proj.root, _LOG_ARGS + ["-n", str(count), "--"] + _history_pathspec(proj), timeout=120)
    if log is None:
        return [], ["git log: %s" % err], 0, ""
    recs = _raw_records(log)
    shas = list(dict.fromkeys(r[0] for r in recs))
    shorts = _short(proj.root, shas)
    dates = [r[1] for r in recs if r[1]]
    names = ["%s^:%s" % (s, n) for s in shas for n in CONFIG_NAMES]
    oids = [o for _s, _d, ents in recs for old, new, _st, _p in ents for o in (old, new) if not _zero(o)]
    got = _blobs(proj.root, names + oids)
    snaps = {s: _snapshot(proj.dc, got.get("%s^:%s" % (s, CONFIG_NAMES[0])), got.get("%s^:%s" % (s, CONFIG_NAMES[1])))
             for s in shas}
    # a merge is read once per parent (review 3, F3; critic C3, C4 -- see below)
    sides = {}
    for gi, (sha, _d, ents) in enumerate(recs):
        sides.setdefault(sha, []).append((gi, {pth: o for o, _n, _s, pth in ents}))
    cands, unread, ccache = [], 0, {}
    for gi, (sha, cdate, ents) in enumerate(recs):  # newest first: the first commit to show a removal made it
        short = shorts.get(sha, sha[:7])
        others = [d for gj, d in sides[sha] if gj != gi]
        config_edit = False
        for old, new, _st, path in ents:
            if "/" not in path and path.casefold() in CONFIG_NAMES:
                config_edit = True
                continue
            if _zero(old):
                continue                            # an added copy removed nothing
            kind = source_kind(path, snaps[sha])
            if not kind:
                continue
            before = got.get(old)
            after = "" if _zero(new) else got.get(new)
            if before is None or after is None:
                unread += 1
                continue
            of = _contrast_fn(path, before, ccache, old)
            for r in _removed_between(path, before, after, kind, limit):
                r["_merge_side"] = bool(others) and not _in_every(r, path, others, got)
                r["_contrast"] = (lambda r=r, of=of: of(r))
                cands.append((short, cdate, r))
        if config_edit:
            cands += [(short, cdate, r) for r in _dropped_by_config(proj, sha, snaps[sha], limit)]
    # a merge's removal of a ruling another parent no longer had belongs to the commit that removed it there
    # -- when this window reads that commit; otherwise no one else owns it and the merge does (critic C3, C4)
    owned = {_core(r["fragment"]) for _s, _d, r in cands if not r.get("_merge_side")}
    out, seen = [], set()
    for short, cdate, r in cands:
        key = _core(r["fragment"])
        if r.pop("_merge_side", False) and key in owned:
            continue
        if key in seen:
            continue
        seen.add(key)
        v, where = proj.verdict(r, r.pop("_contrast", None))
        if v == "kept":
            continue
        if r.get("left") and v == "lost" and (proj.root / r["left"]).is_file():
            v, where = "left", r["left"]
        r.update(sha=short, commit_date=cdate, verdict=v, where=where)
        out.append(r)
    errs = ["%d changed cop%s could not be read (git cat-file)" % (unread, "y" if unread == 1 else "ies")] if unread else []
    return out, errs, len(shas), (min(dates) if dates else "")


# ---------------------------------------------------------------------------------------
# The two outputs
# ---------------------------------------------------------------------------------------

def _home_short(path):
    try:
        return "~/" + Path(path).resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def _when(r):
    """A ruling's date as printed: every ruling is a DATED claim, or says plainly that it is not."""
    if r.get("date"):
        return "(%s) " % r["date"]
    if r.get("blame"):
        return "(undated; line last changed %s) " % r["blame"]
    return "(undated) "


def _tags(r):
    """The bracketed facts printed after a ruling's date."""
    out = ""
    if r.get("by") == "delegated":
        out += "[delegated] "
    if r.get("archive"):
        out += "[archive] "
    if r.get("superseded"):
        out += "[row says SUPERSEDED %s -- re-check] " % r["superseded"]
    return out


def _more(r):
    """What follows a printed summary: the items its cut hid, and the duplicates merged into it."""
    out = ""
    if r.get("hidden_items"):
        out += " (+%d more item(s): read %s:%d)" % (r["hidden_items"], r["path"], r["line"])
    if r.get("also"):
        out += " (also: %s)" % ", ".join(r["also"])
    return out


def _where(r):
    """Where a removed ruling's text went, when it went somewhere."""
    if r.get("verdict") == "moved":
        return " [now only in %s]" % r["where"]
    if r.get("verdict") == "unruled":
        return " [still in %s, no longer read as a ruling]" % r["where"]
    if r.get("verdict") == "left":
        return " [%s is no longer one of the briefing's sources]" % r["where"]
    if r.get("verdict") == "pruned":
        return " [dropped %s from it]" % r["where"]
    return ""


def _reach(since):
    """How far back the history window reached, as printed after its commit count."""
    return " (back to %s)" % since if since else ""


def briefing(proj, cap, history, show_all, as_json):
    rules = standing(proj)
    rem, rerrs, _n, since = removed(proj, history)
    rem, cleared = apply_acks(proj, rem)
    err = "; ".join(rerrs)
    if as_json:
        keep = ("path", "line", "marker", "date", "blame", "summary", "by")
        print(json.dumps({"project": proj.name,
                          "sources": [proj.rel(p) for p in proj.standing],
                          "errors": list(proj.errors),
                          "standing": [{k: r.get(k, "") for k in keep} for r in rules],
                          "removed": [dict({k: r.get(k, "") for k in keep}, sha=r["sha"], commit_date=r["commit_date"],
                                           verdict=r.get("verdict", ""), where=r.get("where", ""))
                                      for r in rem],
                          "acknowledged": len(cleared),
                          "removed_error": err}, indent=2))
        return
    # The section prints on every run of a project that has something to read: 'none', 'not
    # scanned' and 'config broken' must never share one empty output (all three looked identical,
    # and the third hid a whole project's rulings). A directory with no docket, handoff or memory
    # index and no config error has no context layer, so there is nothing to report.
    if not proj.standing and not proj.errors:
        return
    print()
    print(HEADER)
    for e in proj.errors:
        print("RULED OUT: could not check -- %s" % e[:200])
    if not rules:
        print("RULED OUT: none -- read %d source(s): %s" % (len(proj.standing), proj.source_names()))
    if rules:
        print("%d standing ruling(s) in this project, newest first:" % len(rules))
        shown = rules if show_all else rules[:cap]
        for r in shown:
            print("  %s:%d %s%s%s%s" % (r["path"], r["line"], _when(r), _tags(r), r["summary"], _more(r)))
        rest = rules[len(shown):]
        if rest:
            counts = {}
            for r in rest:
                counts[r["path"]] = counts.get(r["path"], 0) + 1
            by = ", ".join("%s (%d)" % kv for kv in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
            print('  and %d more -- read: %s; all of them: python "%s" --all'
                  % (len(rest), by, _home_short(Path(__file__).resolve())))
    if rem:
        print("REMOVED by the last %d commit(s)%s and no longer a ruling in any source the briefing reads -- possibly "
              "reworded or withdrawn: check the commit, then restore it to a standing section, or acknowledge it "
              "with <!-- %s \"<a phrase from it>\" <why> --> in a standing file:" % (history, _reach(since), ACK_TAG))
        for r in (rem if show_all else rem[:REMOVED_SHOWN]):
            print("  %s %s %s:%d %s%s%s%s" % (r["sha"], r["commit_date"], r["path"], r["line"], _when(r), r["summary"],
                                              _where(r), _amb(r)))
        if len(rem) > REMOVED_SHOWN and not show_all:
            print('  and %d more -- python "%s" --all' % (len(rem) - REMOVED_SHOWN, _home_short(Path(__file__).resolve())))
    if cleared:
        print(_acked_line(cleared, show_all))
    for note in proj.ack_notes:
        print("(%s)" % note)
    for e in rerrs:
        print("REMOVED: could not check -- %s" % e[:200])
    out_git = proj.outside()
    if out_git and rules:
        print("(removal not checked for %d standing file(s) outside git: %s)"
              % (len(out_git), ", ".join(proj.rel(p) for p in out_git)))
    print(ROUTE)


def _head_sources(proj):
    """HEAD's own sources that the working tree changed or no longer reads: ([(rel, kind, blob, left)],
    error). Judged from HEAD's tree and HEAD's configs, so a deleted, renamed, undeclared or excluded
    source is in the list (left=True) and an archive counts only inside its standing sections (review
    FK-HIST#5, critic P1, P2). git's own spelling of each path is kept (the index's, not a directory
    listing's)."""
    tree, err = _git(proj.root, ["ls-tree", "-r", "-z", "--full-tree", "HEAD"])
    if tree is None:
        return None, "git ls-tree: %s" % err
    diff, err = _git(proj.root, ["diff", "--name-only", "-z", "--no-renames", "HEAD"])
    if diff is None:
        return None, "git diff: %s" % err
    changed = {p.casefold() for p in diff.split("\0") if p}
    # a HEAD standing file now read only as an archive has left too: its rulings outside a standing
    # section no longer count (review 3, K2)
    now_standing = {proj.rel(p).casefold() for p in proj.standing if proj.in_git(p)}
    now = now_standing | {proj.rel(p).casefold() for p in proj.archives if proj.in_git(p)}
    cfg = proj.head_config()
    out = []
    for rec in tree.split("\0"):
        meta, _, path = rec.partition("\t")
        f = meta.split()
        if len(f) != 3 or f[1] != "blob":
            continue                    # a submodule is a commit here: its files are another repository's
        kind = source_kind(path, cfg)
        if not kind:
            continue
        low = path.casefold()
        gone = low not in (now_standing if kind == "standing" else now)
        if low in changed or gone:
            out.append((path, kind, f[2], gone))
    return out, ""


def lost(proj, history=DEFAULT_HISTORY):
    if not proj.git:
        return
    head_ok, _e = _git(proj.root, ["rev-parse", "-q", "--verify", "HEAD^{commit}"])
    if head_ok is None:
        return          # no commit yet: HEAD carries nothing that could be lost
    print()
    print(LOSS_HEADER)
    for e in proj.errors:
        print("RULING LOSS: could not check -- %s" % e[:200])
    heads, err = _head_sources(proj)
    if heads is None:
        print("RULING LOSS: could not check -- %s" % err[:200])
        return
    # every HEAD copy through ONE cat-file, decoded by _decode (a UTF-16 or BOM file, review FK-HIST#3)
    copies = _blobs(proj.root, [b for _r, _k, b, _l in heads])
    found, notes, checked, seen, unread = [], [], 0, set(), 0
    for rel, kind, blob, left in heads:
        head = copies.get(blob)
        if head is None:
            unread += 1
            continue
        # an archive line outside a standing section never stood
        rs = [r for r in rulings_in_text(rel, head, limit=THRESHOLD_SUMMARY_MAX) if _counted(kind, r)]
        counts = {}                     # for each word, how many of this copy's rulings carry it
        for x in rs:
            for t in _toks(x):
                counts[t] = counts.get(t, 0) + 1
        for r in rs:
            checked += 1
            key = _core(r["fragment"])
            if key in seen:
                continue
            seen.add(key)
            v, where = proj.verdict(r, {t for t in _toks(r) if counts.get(t, 0) <= 1})
            if v == "kept":
                continue
            if left and v == "lost" and (proj.root / rel).is_file():
                v, where = "left", rel
            r.update(verdict=v, where=where, sha=None, head_rel=rel)
            found.append(r)
    if unread:
        notes.append("RULING LOSS: could not check -- %d HEAD cop%s could not be read (git cat-file)"
                     % (unread, "y" if unread == 1 else "ies"))
    # The recent commits: the SAME window the briefing reads (the last `history` commits touching the
    # standing files). No 'last wrap' marker: a HANDOFF touch is not a wrap, so that marker skipped
    # commits no wrap had checked. A removal stays a THRESHOLD, wrap after wrap, while its commit is
    # inside the window; the scope line prints how far back that reaches.
    rem, rerrs, nread, since = removed(proj, history, limit=THRESHOLD_SUMMARY_MAX)
    for e in rerrs:
        notes.append("RULING LOSS: could not check the recent commits -- %s" % e[:200])
    for r in rem:
        key = _core(r["fragment"])
        if key not in seen:
            seen.add(key)
            found.append(r)
    still, cleared = apply_acks(proj, found)
    lines = []
    for r in still:
        if r["sha"] is None:
            lines.append('THRESHOLD %s %s that HEAD carries (line %d%s): "%s" -- %s%s'
                         % (r["head_rel"], _lost_what(r["verdict"], r["where"]), r["line"],
                            ", %s" % r["date"] if r["date"] else "", r["summary"], FIX, _amb(r)))
        else:
            lines.append('THRESHOLD %s %s in %s (%s; old line %d%s): "%s" -- %s%s'
                         % (r["path"], _lost_what(r["verdict"], r["where"]), r["sha"], r["commit_date"], r["line"],
                            ", %s" % r["date"] if r["date"] else "", r["summary"], FIX, _amb(r)))
    for ln in lines + notes:
        print(ln)
    if cleared:
        print(_acked_line(cleared))
    for note in proj.ack_notes:
        print("(%s)" % note)
    scope = ("%d changed standing file(s) compared with HEAD (%d ruling(s) there); %d commit(s) read (the last %d "
             "that touched the standing files%s)" % (len(heads), checked, nread, history,
                                                     ", back to %s" % since if since else ""))
    if cleared:
        scope += "; %d acknowledged as withdrawn" % len(cleared)
    out_git = proj.outside()
    if out_git:
        scope += "; not checked: %d standing file(s) outside git (%s)" % (
            len(out_git), ", ".join(proj.rel(p) for p in out_git))
    if lines or notes or proj.errors:
        print("(%s)" % scope)
    else:
        print("(clean -- no ruling is missing from the working tree; %s)" % scope)


FIX = 'restore it, or acknowledge it: <!-- ruling-withdrawn: "<phrase>" why -->'


def _lost_what(verdict, where):
    if verdict == "pruned":
        return "dropped %s from an owner ruling" % where
    if verdict == "left":
        return "took an owner ruling out of the briefing's sources (%s is no longer one of them)" % where
    if verdict == "moved":
        return "moved an owner ruling out of the briefing's sources (now only in %s)" % where
    if verdict == "unruled":
        return "un-ruled an owner ruling (its text is still in %s, no longer read as a ruling)" % where
    return "dropped an owner ruling"


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="rulings.py",
        description="The owner's standing rulings in this project (the briefing's RULED OUT section), "
                    "or with --lost the wrap check for a ruling a rewrite dropped. Read-only.")
    ap.add_argument("--all", action="store_true", help="list every standing ruling (no cap)")
    ap.add_argument("--json", action="store_true", help="print the standing and removed rulings as JSON")
    ap.add_argument("--lost", action="store_true",
                    help="wrap check: THRESHOLD for each ruling HEAD or a commit since the last wrap carried "
                         "that the working tree no longer holds")
    ap.add_argument("--cap", type=int, default=DEFAULT_CAP, help="rulings shown before the remainder count "
                                                                "(default %d)" % DEFAULT_CAP)
    ap.add_argument("--history", type=int, default=DEFAULT_HISTORY,
                    help="commits read for removed rulings (default %d)" % DEFAULT_HISTORY)
    a = ap.parse_args(argv)
    try:
        proj = Project()
        if not proj.ok:
            return 0
        if a.lost:
            lost(proj, max(1, a.history))
        else:
            briefing(proj, max(0, a.cap), max(1, a.history), a.all, a.json)
    except Exception as e:  # a state line, never a crash: say it could not check
        print()
        print(LOSS_HEADER if a.lost else HEADER)
        print("%s: could not check -- %s: %s" % ("RULING LOSS" if a.lost else "RULED OUT", type(e).__name__,
                                                str(e)[:200]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
