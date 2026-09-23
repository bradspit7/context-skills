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
    (default)  the briefing section '== RULED OUT (owner rulings - do not re-propose) ==':
               the standing rulings in this project's docket files, HANDOFF*.md and memory index,
               newest first, capped (--cap, default 12) with a remainder count per file; then the
               rulings REMOVED from those files by the last --history commits (default 30) that are
               found nowhere in the project now. Prints NOTHING when there is neither.
    --all      the same, uncapped.
    --json     the same data as JSON.
    --lost     the wrap check '== RULING LOSS ==': every ruling that the HEAD copy of a changed
               docket/handoff file carries, and every ruling removed by a commit since the last
               wrap (the last commit that touched a HANDOFF), that the working tree no longer holds
               ANYWHERE in the project (a moved ruling is kept) -> one THRESHOLD line each. A clean
               run says what it compared. Prints nothing outside git.

SOURCES (via docket_corpus, beside this file)
    standing   the project's docket files (docket_corpus kinds docket, roadmap, config), its
               HANDOFF*.md, and its memory index: MEMORY.md in continuation/memory, context/memory
               and ~/.claude/projects/<slug>/memory. An archive of closed rows is not a standing
               source, but it counts when deciding whether a ruling still exists (a rotated row
               keeps its ruling).
    retained   a ruling still exists when its clause is found, after normalising markdown and
               whitespace, anywhere in the project's corpus (every docket_corpus file, every
               memory-dir note, the handoffs) -- verbatim, or at least half of its word 4-grams
               (so a status flip on the same row keeps it) -- or when a ruling the project holds
               now carries at least 60% of its distinctive words (a handoff's "do not re-propose"
               list rewritten at a wrap keeps its items). Measured on one project's real history:
               without that last match every handoff rewrite of such a list read as a removal.

GRAMMAR (measured over the real dockets of 13 projects before shipping; tests/test-rulings.py
pins both directions for every marker)
    do-not-re        'do not / don't / never' + re-propose|raise|ask|litigate|suggest|pitch|
                     research|file|open; 'stop re-asking' (and the other -ing forms); the passive
                     'not (be) re-proposed|raised|asked|litigated|pitched|filed'
    owner-ruling     'OWNER RULED|RULING|DECLINED|CONFIRMED' in capitals WITH a date after it;
                     '[OWNER RULING]'; 'by|per|on (the) owner('s) ruling'; 'owner ruled|ruling
                     <date>'; 'owner declined' / 'declined by the owner'; 'confirmed (dead) by
                     the owner'
    voided-by-owner  'VOIDED ... owner' inside one clause
    dead-lever       'dead lever(s)'
    section          a top-level list item or table body row under a heading that names rulings
                     ('owner rulings', 'standing rulings', 'locked decisions', 'decisions locked',
                     'ruled out', 'do not re-propose|raise|ask|open|litigate|file'), up to the
                     next heading of the same or a higher level
    label            a line that opens with a bold 'Locked decisions' / 'Decisions locked' /
                     'Standing rulings' / 'Owner rulings' / 'Ruled out' label
    NOT markers, because their measured precision was too low: a bare no-entry sign (a row
    status and general emphasis in some projects), 'killed', 'REFUTED', 'ruled out' in prose,
    'verbatim', 'OWNER DECISION' (it also labels decisions still pending), an undated capital
    'OWNER-RULED' (docket rows that DISCUSS rulings use it).
    A marker inside a code span, a fenced block, an HTML comment, a double-quoted or italic span,
    strikethrough, or right after a single quote is a MENTION (a row discussing such guards, an
    example), never a ruling. So is a hyphenated compound ('a do-not-re-propose block').

OUTPUT
    Every ruling is printed as a dated CLAIM with its source line, never as bare emphasis: a
    standing "do not re-propose X" built on a premise nobody measured is the one line a resumer
    trusts most, so the reader must be able to go and re-check it. Each summary is at most 180
    characters (160 in a THRESHOLD), cut around the marker; a docket line can carry personal
    data, so nothing is ever printed whole and nothing is written to a file.
    These are STATE lines: nothing here starts with FINDING (the briefing counts '^FINDING' lines
    to block synthesis). A failure prints 'could not check', never silence.

EXIT STATUS
    0 always, except 2 for a usage error.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HEADER = "== RULED OUT (owner rulings - do not re-propose) =="
LOSS_HEADER = "== RULING LOSS (owner rulings in HEAD or in commits since the last wrap, gone from the working tree) =="
ROUTE = ("(state lines, not FINDINGs -- carry them into the briefing's Locked decisions; each is a dated claim "
         "with its source: re-check the premise before relying on it, never re-propose it without new evidence)")
STANDING_KINDS = ("docket", "roadmap", "config", "handoff")
DEFAULT_CAP = 12
DEFAULT_HISTORY = 30
SINCE_WRAP_MAX = 30
SUMMARY_MAX = 180
THRESHOLD_SUMMARY_MAX = 160
MERGE_GAP = 200        # marker matches this close on one line are one ruling, not two
WINDOW_MAX = 300       # never read further than this either side of a marker
SHINGLE = 4
TOKEN_MIN = 5          # a ruling with fewer distinctive words is matched verbatim or by 4-grams only
TOKEN_SHARE = 0.6      # ...else it is kept when a current ruling carries this share of its words
CONT_MAX = 2           # continuation lines appended to a ruling whose own line is a short lead-in

# ---------------------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------------------

_BASE = r"(?:propose|raise|ask|litigate|suggest|pitch|research|file|open)"
_ING = r"(?:proposing|raising|asking|litigating|suggesting|pitching|researching|filing)"
_ED = r"(?:proposed|raised|asked|litigated|pitched|filed)"
_DATE = r"\d{4}-\d{2}-\d{2}"

MARKERS = (
    ("do-not-re", re.compile(
        r"\b(?:do\s+not|don['\u2019]?t|never)\s+(?:\*\*)?re-?" + _BASE + r"\b"
        r"|\bstop\s+re-?" + _ING + r"\b"
        r"|\bnot\s+(?:to\s+)?(?:be\s+)?re-?" + _ED + r"\b", re.I)),
    ("owner-ruling", re.compile(
        r"\bOWNER[- ](?:RULED|RULING|DECLINED|CONFIRMED)\b[\s:(\[\u2014\u2013-]*" + _DATE
        + r"|\[OWNER RULING\]"
        r"|(?i:\b(?:by|per|on)\s+(?:the\s+)?owner(?:['\u2019]s)?\s+ruling\b)"
        r"|(?i:\bowner\s+(?:ruled|ruling)\b[\s:(\[]*" + _DATE + r")"
        r"|(?i:\bowner[- ]declined\b|\bdeclined\s+by\s+the\s+owner\b)"
        r"|(?i:\bconfirmed\s+(?:dead\s+)?by\s+the\s+owner\b)")),
    ("voided-by-owner", re.compile(r"\bvoided\b[^.;!?]{0,60}?\bowner\b", re.I)),
    ("dead-lever", re.compile(r"\bdead\s+levers?\b", re.I)),
)
SECTION_RE = re.compile(
    r"\b(?:owner|standing)\s+rulings?\b|\bdecisions?\s+locked\b|\blocked\s+decisions?\b|\bruled[- ]out\b"
    r"|\bdo\s+not\s+re-?(?:propose|raise|ask|open|litigate|file)\b", re.I)
LABEL_RE = re.compile(
    r"^\s{0,3}(?:>\s*)?(?:[-*+]\s+|\d{1,4}[.)]\s+)?\*\*\s*(?:locked\s+decisions?|decisions?\s+locked|"
    r"standing\s+rulings?|owner\s+rulings?|ruled[- ]out)\b[^*]*\*\*\s*:?\s*\S", re.I)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
ITEM_RE = re.compile(r"^\s{0,3}(?:>\s*)?(?:[-*+]|\d{1,4}[.)])\s+\S")
TOP_ITEM_RE = re.compile(r"^(?:>\s*)?(?:[-*+]|\d{1,4}[.)])\s+\S")   # column 0: a sub-point is detail
TABLE_RE = re.compile(r"^\s{0,3}\|")
TABLE_SEP_RE = re.compile(r"^\s{0,3}\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
HR_RE = re.compile(r"^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$")
DATE_RE = re.compile(r"(?<!\d)(" + _DATE + r")(?!\d)")
BOUNDARY_RE = re.compile(r"[.!?;](?:[*_)\]\"'\u201d\u2019]*)(?=\s)")
LEAD_RE = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+)?")


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


def _italic_spans(line):
    """(start, end) of single-asterisk italic spans (a '**' run is bold, never italic)."""
    out, opener = [], None
    for m in re.finditer(r"(?<!\*)\*(?!\*)", line):
        i = m.start()
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
    for a, b in opaque:
        for k in range(a, b):
            mask[k] = True
    i = 0
    while i < n:
        if mask[i] and any(a <= i < b for a, b in opaque):
            i += 1
            continue
        c = line[i]
        if c == "~" and line.startswith("~~", i):
            para.strike = not para.strike
            mask[i] = mask[i + 1] = True
            i += 2
            continue
        if c == '"':
            para.quote = not para.quote
            mask[i] = True
        elif c == "\u201c":
            para.curly = True
        elif c == "\u201d":
            mask[i] = True
            para.curly = False
        if para.quote or para.curly or para.strike:
            mask[i] = True
        i += 1
    for a, b in _italic_spans(line):
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


def _groups(line, mask):
    """Marker matches on one line, merged into ruling groups: [(start, end, marker, spans)]."""
    found = []
    for name, rx in MARKERS:
        for m in rx.finditer(line):
            if not _mention(line, m.start(), mask):
                found.append((m.start(), m.end(), name))
    found.sort()
    groups = []
    for s, e, name in found:
        if groups and s - groups[-1][1] <= MERGE_GAP:
            g = groups[-1]
            groups[-1] = (g[0], max(g[1], e), g[2], g[3] + [(s, e)])
        else:
            groups.append((s, e, name, [(s, e)]))
    return groups


def _heading_rules(text):
    m = SECTION_RE.search(text)
    if not m:
        return False
    return not _mention(text, m.start(), _mask(text, _Para()))


def scan_text(text, first_line=1):
    """Every ruling in a markdown text: [{line, marker, start, end, spans, text, heading_date}]."""
    out = []
    lines = text.splitlines()
    para = _Para()
    fence = None
    section = 0
    heading_date = ""
    for i, ln in enumerate(lines):
        n = first_line + i
        fm = FENCE_RE.match(ln)
        if fence:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            para = _Para()
            continue
        if not ln.strip() or HR_RE.match(ln):
            para = _Para()
            continue
        h = HEADING_RE.match(ln)
        if h:
            para = _Para()
            level = len(h.group(1))
            if section and level <= section:
                section = 0
            if _heading_rules(h.group(2)):
                section = level
                d = DATE_RE.search(h.group(2))
                heading_date = d.group(1) if d else ""
            continue
        if ITEM_RE.match(ln) or TABLE_RE.match(ln):
            para = _Para()
        mask = _mask(ln, para)
        groups = _groups(ln, mask)
        if groups:
            for s, e, name, spans in groups:
                out.append({"line": n, "marker": name, "start": s, "end": e, "spans": spans, "text": ln,
                            "heading_date": "", "cont": _cont(lines, i)})
            continue
        if section and _section_item(lines, i):
            out.append({"line": n, "marker": "section", "start": 0, "end": 0, "spans": [], "text": ln,
                        "heading_date": heading_date, "cont": _cont(lines, i)})
        elif LABEL_RE.match(ln):
            out.append({"line": n, "marker": "label", "start": 0, "end": 0, "spans": [], "text": ln,
                        "heading_date": "", "cont": _cont(lines, i)})
    return out


def _cont(lines, i):
    """Up to CONT_MAX lines that continue line i's paragraph (not a new item, heading, table or fence)."""
    out = []
    for ln in lines[i + 1:i + 1 + CONT_MAX]:
        if (not ln.strip() or HEADING_RE.match(ln) or FENCE_RE.match(ln) or ITEM_RE.match(ln)
                or TABLE_RE.match(ln) or HR_RE.match(ln)):
            break
        out.append(ln)
    return out


def _section_item(lines, i):
    ln = lines[i]
    if TOP_ITEM_RE.match(ln):
        return True
    if TABLE_RE.match(ln) and not TABLE_SEP_RE.match(ln):
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        return not TABLE_SEP_RE.match(nxt)          # a row followed by a separator is the header
    return False


# ---------------------------------------------------------------------------------------
# Summaries, dates, retention
# ---------------------------------------------------------------------------------------

_NORM = str.maketrans({"*": None, "_": None, "`": None, "~": None, "\u201c": '"', "\u201d": '"',
                       "\u2018": "'", "\u2019": "'", "\u2014": "-", "\u2013": "-"})


def normalize(s):
    """Lower-case, markdown emphasis and code ticks dropped, quotes and dashes folded, whitespace collapsed."""
    return " ".join(s.translate(_NORM).lower().split())


def _clean(s):
    s = re.sub(r"\*\*|__|`", "", s)
    s = re.sub(r"(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", s)
    return " ".join(s.split())


def _window(line, s, e):
    """The clause(s) holding line[s:e]: sentence bounds, a too-short sentence extended backwards."""
    lo = max(0, s - WINDOW_MAX)
    starts = [m.end() for m in BOUNDARY_RE.finditer(line, lo, s)]
    a = starts[-1] if starts else lo
    m = BOUNDARY_RE.search(line, e)
    b = m.end() if m and m.end() <= e + WINDOW_MAX else min(len(line), e + WINDOW_MAX)
    k = len(starts) - 1
    while len(_clean(line[a:b])) < 60 and a > lo:
        k -= 1
        a = starts[k] if k >= 0 else lo
    return a, b


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


def _date(line, spans, heading_date=""):
    best, dist = "", None
    for m in DATE_RE.finditer(line):
        d = min((0 if (s <= m.start() < e) else min(abs(m.start() - e), abs(s - m.end()))) for s, e in spans)
        if d <= 400 and (dist is None or d < dist):
            best, dist = m.group(1), d
    return best or heading_date


def rulings_in_text(rel, text, first_line=1, limit=SUMMARY_MAX):
    """[{path, line, marker, date, summary, fragment}] for every ruling in `text`."""
    out = []
    for h in scan_text(text, first_line):
        ln = h["text"]
        if h["spans"]:
            a, b = _window(ln, h["start"], h["end"])
            raw = ln[a:b]
            pos = len(_clean(ln[a:h["start"]]))
            date = _date(ln, h["spans"], h["heading_date"])
        else:
            b = len(ln)
            raw = LEAD_RE.sub("", ln, count=1)
            pos = 0
            d = DATE_RE.search(ln)
            date = d.group(1) if d else h["heading_date"]
        # A short lead-in that runs to the end of its line ('rulings -- do not re-propose either:')
        # carries its content on the next lines of the same paragraph.
        for more in h.get("cont", ()):
            if b < len(ln) or len(_clean(raw)) >= 100:
                break
            raw = raw.rstrip() + " " + more.strip()
        clean = LEAD_RE.sub("", _clean(raw), count=1)
        pos = max(0, pos - (len(_clean(raw)) - len(clean)))
        out.append({"path": rel, "line": h["line"], "marker": h["marker"], "date": date,
                    "summary": _cut(clean, pos, limit),
                    "fragment": normalize(_cut(clean, pos, 400))})
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


def retained(fragment, corpus, current=None):
    """True when the ruling still exists: its clause is in `corpus` (both already normalize()d),
    verbatim or by at least half of its word 4-grams (a status flip on the same row); or, when
    `current` (token sets of the rulings the project holds NOW, or a callable returning them) is
    given, some current ruling carries at least 60% of its distinctive words (a ruling list that was
    reworded, re-ordered or had an item added). A dropped block matches neither."""
    if not fragment:
        return True
    if fragment in corpus:
        return True
    words = fragment.split()
    if len(words) >= SHINGLE + 2:
        grams = [" ".join(words[i:i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)]
        step = max(1, len(grams) // 24)
        sample = grams[::step]
        if sum(1 for g in sample if g in corpus) * 2 >= len(sample):
            return True
    if current is not None:
        mine = ruling_tokens(fragment)
        if len(mine) >= TOKEN_MIN:
            need = TOKEN_SHARE * len(mine)
            for other in (current() if callable(current) else current):
                if len(mine & other) >= need:
                    return True
    return False


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


def _read(path):
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    return raw.decode("utf-8", errors="replace")


class Project(object):
    """This project's sources, its corpus, and how to show a path."""

    def __init__(self, cwd=None):
        dc = _corpus_module()
        cwd = str(Path(cwd or os.getcwd()).resolve())
        _, chosen = dc.select("here", cwd=cwd)
        self.ok = bool(chosen)
        if not self.ok:
            return
        p = chosen[0]
        self.root = Path(p["root"]).resolve()
        self.name = p["name"]
        top, _err = _git(self.root, ["rev-parse", "--show-toplevel"])
        self.git = bool(top)
        files, _cfg, self.config_error = dc._project_files(p)
        mem_dirs = [self.root / m for m in dc.MEMORY_LEVELS if (self.root / m).is_dir()]
        home = dc._home_memory(p["main"])
        if home is not None:
            mem_dirs.append(Path(home))
        seen, self.standing, self.corpus_files = set(), [], []

        def add(path, standing):
            k = os.path.normcase(os.path.realpath(str(path)))
            if k in seen:
                return
            seen.add(k)
            self.corpus_files.append(Path(path))
            if standing:
                self.standing.append(Path(path))

        for path, kind, _rel in files:
            if kind in STANDING_KINDS:
                add(path, True)
        for d in mem_dirs:
            if (d / "MEMORY.md").is_file():
                add(d / "MEMORY.md", True)
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
        self._corpus = None
        self._tokens = None

    def rel(self, path):
        path = Path(path)
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

    def corpus(self):
        if self._corpus is None:
            self._corpus = "\n".join(normalize(_read(p)) for p in self.corpus_files)
        return self._corpus

    def current_tokens(self):
        """Token sets of every ruling the project's files hold NOW (built once, on first need)."""
        if self._tokens is None:
            self._tokens = [ruling_tokens(r["fragment"]) for p in self.corpus_files
                            for r in rulings_in_text(self.rel(p), _read(p))]
        return self._tokens

    def handoff_rels(self):
        return [self.rel(p) for p in self.standing
                if self.in_repo(p) and Path(p).name.lower().startswith("handoff")]

    def standing_rels(self):
        return [self.rel(p) for p in self.standing if self.in_repo(p)]


def standing(proj):
    out = []
    for p in proj.standing:
        out.extend(rulings_in_text(proj.rel(p), _read(p)))
    seen, uniq = set(), []
    for r in out:
        key = normalize(r["summary"])
        if key not in seen:
            seen.add(key)
            uniq.append(r)
    # newest first, undated last; the sort is stable, so ties keep file and line order
    uniq.sort(key=lambda r: r["date"], reverse=True)
    return uniq


def _hunks(log):
    """Removed lines from `git log --format=%x1e%h%x1f%ad -p -U0` output: (sha, date, path, line, text)."""
    for rec in log.split("\x1e"):
        if not rec.strip():
            continue
        head, _, body = rec.partition("\n")
        sha, _, cdate = head.partition("\x1f")
        path, old, rem, in_header = None, 0, 0, True
        for ln in body.split("\n"):
            if ln.startswith("diff --git "):
                path, in_header, rem = None, True, 0
                continue
            if in_header:
                if ln.startswith("--- "):
                    path = ln[6:].rstrip("\t") if ln.startswith("--- a/") else None
                elif ln.startswith("@@"):
                    in_header = False
                else:
                    continue
            if ln.startswith("@@"):
                m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@", ln)
                if m:
                    old, rem = int(m.group(1)), int(m.group(2) or "1")
                continue
            if rem > 0 and ln.startswith("-"):
                if path:
                    yield sha.strip(), cdate.strip(), path, old, ln[1:]
                old += 1
                rem -= 1


def removed(proj, rels, rev_args, limit=SUMMARY_MAX):
    """Rulings on lines removed by the commits `rev_args` selects, found nowhere in the corpus now."""
    if not proj.git or not rels:
        return [], ""
    # :(literal,icase): a directory listing's spelling can differ in case from the index's on a
    # case-insensitive filesystem, and a case-sensitive pathspec would then read no history at all.
    log, err = _git(proj.root, ["log"] + list(rev_args) + ["--format=%x1e%h%x1f%ad", "--date=short", "-p", "-U0",
                                                           "--no-color", "--no-ext-diff", "--no-renames", "--"]
                    + [":(literal,icase)" + r for r in rels], timeout=120)
    if log is None:
        return [], err
    corpus = proj.corpus()
    out, seen = [], set()
    for sha, cdate, path, line, text in _hunks(log):
        for r in rulings_in_text(path, text, first_line=line, limit=limit):
            if r["fragment"] in seen or retained(r["fragment"], corpus, proj.current_tokens):
                continue
            seen.add(r["fragment"])
            r.update(sha=sha, commit_date=cdate)
            out.append(r)
    return out, ""


# ---------------------------------------------------------------------------------------
# The two outputs
# ---------------------------------------------------------------------------------------

def _home_short(path):
    try:
        return "~/" + Path(path).resolve().relative_to(Path.home().resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


def briefing(proj, cap, history, show_all, as_json):
    rules = standing(proj)
    rem, err = removed(proj, proj.standing_rels(), ["-n", str(history)])
    if as_json:
        keep = ("path", "line", "marker", "date", "summary")
        print(json.dumps({"project": proj.name,
                          "standing": [{k: r[k] for k in keep} for r in rules],
                          "removed": [dict({k: r[k] for k in keep}, sha=r["sha"], commit_date=r["commit_date"])
                                      for r in rem],
                          "removed_error": err}, indent=2))
        return
    if not rules and not rem and not err:
        return
    print()
    print(HEADER)
    if rules:
        print("%d standing ruling(s) in this project, newest first:" % len(rules))
        shown = rules if show_all else rules[:cap]
        for r in shown:
            print("  %s:%d %s%s" % (r["path"], r["line"], "(%s) " % r["date"] if r["date"] else "", r["summary"]))
        rest = rules[len(shown):]
        if rest:
            counts = {}
            for r in rest:
                counts[r["path"]] = counts.get(r["path"], 0) + 1
            by = ", ".join("%s (%d)" % kv for kv in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))
            print('  and %d more -- read: %s; all of them: python "%s" --all'
                  % (len(rest), by, _home_short(Path(__file__).resolve())))
    if rem:
        print("REMOVED by the last %d commit(s) and found nowhere in the project now -- restore it, or ignore it "
              "if the removal was deliberate:" % history)
        for r in (rem if show_all else rem[:5]):
            print("  %s %s %s:%d %s%s" % (r["sha"], r["commit_date"], r["path"], r["line"],
                                          "(%s) " % r["date"] if r["date"] else "", r["summary"]))
        if len(rem) > 5 and not show_all:
            print('  and %d more -- python "%s" --all' % (len(rem) - 5, _home_short(Path(__file__).resolve())))
    if err:
        print("REMOVED: could not check -- git log: %s" % err[:200])
    print(ROUTE)


def lost(proj):
    if not proj.git:
        return
    head_ok, _e = _git(proj.root, ["rev-parse", "-q", "--verify", "HEAD^{commit}"])
    if head_ok is None:
        return          # no commit yet: HEAD carries nothing that could be lost
    corpus = proj.corpus()
    rels = proj.standing_rels()
    changed_out, err = _git(proj.root, ["diff", "--name-only", "-z", "HEAD"])
    print()
    print(LOSS_HEADER)
    if changed_out is None:
        print("RULING LOSS: could not check -- git diff: %s" % err[:200])
        return
    changed = [c for c in changed_out.split("\0") if c]
    # Case-insensitive: on Windows the on-disk spelling a directory listing returns can differ
    # from the index's, and git show needs the index's (git's own spelling is what we keep).
    relset = {r.casefold() for r in rels}
    candidates = [c for c in changed
                  if c.casefold() in relset or (not (proj.root / c).exists() and _is_source_name(c))]
    lines, checked, seen = [], 0, set()
    for rel in candidates:
        head, _e = _git(proj.root, ["show", "HEAD:%s" % rel])
        if head is None:
            continue
        for r in rulings_in_text(rel, head, limit=THRESHOLD_SUMMARY_MAX):
            checked += 1
            if r["fragment"] in seen or retained(r["fragment"], corpus, proj.current_tokens):
                continue
            seen.add(r["fragment"])
            lines.append('THRESHOLD %s dropped an owner ruling that HEAD carries (line %d%s): "%s" -- carry it forward '
                         "(or into a standing ruled-out section) before committing, or state in the audit that "
                         "dropping it is deliberate" % (rel, r["line"], ", %s" % r["date"] if r["date"] else "",
                                                        r["summary"]))
    wrap_note = "no HANDOFF commit to mark the last wrap"
    handoffs = proj.handoff_rels()
    if handoffs:
        wrap_sha, _e = _git(proj.root, ["log", "-1", "--format=%h", "--"]
                            + [":(literal,icase)" + h for h in handoffs])
        wrap_sha = (wrap_sha or "").strip()
        if wrap_sha:
            n_out, _e = _git(proj.root, ["rev-list", "--count", "%s..HEAD" % wrap_sha])
            n = int((n_out or "0").strip() or "0")
            wrap_note = "%d commit(s) since the last wrap %s" % (n, wrap_sha)
            if n:
                rem, rerr = removed(proj, rels, ["-n", str(SINCE_WRAP_MAX), "%s..HEAD" % wrap_sha],
                                    limit=THRESHOLD_SUMMARY_MAX)
                if rerr:
                    lines.append("RULING LOSS: could not check the commits since the last wrap -- git log: %s"
                                 % rerr[:200])
                for r in rem:
                    if r["fragment"] in seen:
                        continue
                    seen.add(r["fragment"])
                    lines.append('THRESHOLD %s lost an owner ruling in %s (%s, committed since the last wrap %s; '
                                 'old line %d%s): "%s" -- restore it (or move it to a standing ruled-out section), '
                                 "or state in the audit that dropping it is deliberate"
                                 % (r["path"], r["sha"], r["commit_date"], wrap_sha, r["line"],
                                    ", %s" % r["date"] if r["date"] else "", r["summary"]))
    for ln in lines:
        print(ln)
    scope = "%d changed docket/handoff file(s) compared with HEAD (%d ruling(s) there); %s" % (
        len(candidates), checked, wrap_note)
    if any(ln.startswith("THRESHOLD") for ln in lines):
        print("(%s)" % scope)
    else:
        print("(clean -- no ruling is missing from the working tree; %s)" % scope)


def _is_source_name(rel):
    b = rel.rsplit("/", 1)[-1].lower()
    return b.endswith(".md") and (b.startswith(("handoff", "roadmap", "docket")) or b.endswith("docket.md")
                                  or b == "memory.md") and not b.startswith("docket-inbox-")


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
            lost(proj)
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
