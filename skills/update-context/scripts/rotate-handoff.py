#!/usr/bin/env python3
"""rotate-handoff -- move finished HANDOFF prose (sections, single items, old pickup points)
into an archive file, under update-context's Step 5 rotation contract.

It is the sibling of rotate-docket.py (closed docket rows) and imports that tool for the
shared machinery: byte decoding, line-ending detection, the fence / HTML-comment region
scan, the relative-link re-pointing and the atomic temp-file write. Nothing is copied.

    python ~/.claude/skills/update-context/scripts/rotate-handoff.py \\
        --source HANDOFF.md --archive archive/HANDOFF-history-2026-11.md \\
        --section "Session 2026-11-01"                    dry run
    ... --apply                                           write
    ... --item "- **Done:** the old export"               one top-level list item or paragraph
    ... --sections-matching "^Pickup point" --keep-newest 3   keep the first 3, move the rest
    ... --pointer "Older sessions archived -> archive/HANDOFF-history-2026-11.md"
    ... --selftest

SELECTORS (each repeatable, any mix in one run)
    --section TEXT     a heading whose text (hashes and surrounding spaces dropped) is
                       exactly TEXT, through the line before the next heading of the same or
                       a higher level. TEXT may also be the whole heading line ('## X').
    --item TEXT        the one top-level block whose first line starts with TEXT: a column-0
                       list item with its continuation and nested lines, or a paragraph.
    --sections-matching REGEX --keep-newest N
                       of the headings REGEX finds (re.search on the heading text), keep the
                       first N in file order (--newest-last: the last N) and move the rest.
                       Fewer than N+1 matches moves nothing from that selector.

THE CONTRACT (in this order; any miss stops the run)
    1. every check runs in memory and nothing is written if one fails;
    2. the moved blocks are appended verbatim to the archive under '## Rotated <date>'
       (a new archive gets a short header; an existing one's earlier bytes are never
       rewritten);
    3. the archive is RE-READ from disk and each block is looked for: the whole block,
       plus at least three distinctive strings from its head, middle and tail;
    4. only then is the source written without the blocks (the --pointer sentence, when
       given, stands once where the first moved block stood).
    On a miss in 3 the source is untouched; the archive is put back only when it still
    holds exactly what this run wrote, and the report says it may hold an appended copy.

REFUSALS (exit 1, nothing written, the reason named)
    a selector matching zero blocks or more than one; a block that a code fence or a
    multi-line HTML comment crosses, or that sits inside one; a block holding either half
    of a machine-read marker pair (<!-- NAME --> ... <!-- /NAME -->); a source carrying
    <!-- rotation-hold: until YYYY-MM-DD ... --> whose date has not passed; a source whose
    name matches *WORKFLOW*, *PIPELINE*, *RUNBOOK* or *PLAYBOOK*; two selectors whose
    blocks overlap; and a standing ruling that the rotation would make disappear.

RULINGS
    analyze-context's rulings.py decides what a ruling is and how each file counts
    (a standing file: every ruling; an archive: only its standing sections; a file the
    briefing does not read: none). The rulings counted in the source and the archive now
    are compared, with rulings.py's own kept_as_ruling(), against those counted in the
    planned bytes. Any ruling not kept refuses the run and is printed. A source the
    briefing would not read is treated as standing (the safe direction).

LINE ENDINGS
    Bytes in, bytes out. Every source line outside a moved block keeps its exact bytes;
    the appended text takes the archive's own line ending (a new archive: the source's).

EXIT STATUS
    0 a clean dry run, nothing to rotate, or a write done; 1 a refusal or a failed check;
    2 bad usage or an unreadable file (argparse exits 2 on an unknown argument).
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fnmatch
import importlib.util
import io
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _import_sibling(name, path):
    """Import a hyphen-named sibling from its source bytes (no bytecode cache is written)."""
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    with open(str(path), "rb") as fh:
        src = fh.read()
    exec(compile(src, str(path), "exec"), mod.__dict__)
    return mod


RD_PATH = HERE / "rotate-docket.py"
if not RD_PATH.is_file():
    sys.stderr.write("rotate-handoff: rotate-docket.py is not installed beside this tool (%s)\n"
                     % RD_PATH)
    sys.exit(2)
rd = _import_sibling("_rotate_handoff_rd", RD_PATH)

HEADING_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
CLOSING_HASHES = re.compile(r"(?:^|[ \t]+)#+[ \t]*$")
LIST_ITEM_RE = re.compile(r"^(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
MARKER_OPEN_RE = re.compile(r"<!--\s*([A-Za-z][A-Za-z0-9_.:-]*)\s*-->")
HOLD_RE = re.compile(r"<!--\s*rotation-hold:\s*until\s+(\S+)", re.I)
PROTECTED_NAMES = ("*WORKFLOW*", "*PIPELINE*", "*RUNBOOK*", "*PLAYBOOK*")
PROBE_MIN = 3


class Refusal(Exception):
    """A reason this run will not write anything (exit 1)."""


# --------------------------------------------------------------------------------------
# Small file helpers (bytes only)
# --------------------------------------------------------------------------------------

def read_bytes(p):
    with open(str(p), "rb") as fh:
        return fh.read()


def read_back(p):
    """The archive's bytes as they are on disk now (the re-read probe reads through this)."""
    return read_bytes(p)


def _rel(path, root):
    try:
        return os.path.relpath(str(path), str(root)).replace("\\", "/")
    except ValueError:
        return ""


def find_root(start):
    """The nearest ancestor holding a .git entry (no git process is run), else start."""
    d = Path(start).resolve()
    for cand in [d] + list(d.parents):
        if (cand / ".git").exists():
            return cand
    return d


# --------------------------------------------------------------------------------------
# Block finding (pure: lines in, line spans out)
# --------------------------------------------------------------------------------------

def headings(lines, regions):
    """[(index, level, text)] of every ATX heading outside a fence or multi-line comment."""
    inside = set()
    for s, e in regions:
        inside.update(range(s, e + 1))
    out = []
    for i, ln in enumerate(lines):
        if i in inside:
            continue
        m = HEADING_RE.match(rd.uncr(ln))
        if m:
            text = CLOSING_HASHES.sub("", m.group(2) or "").strip()
            out.append((i, len(m.group(1)), text))
    return out


def last_line(lines):
    """Index of the last real line (a trailing '' after the final newline is not one)."""
    n = len(lines) - 1
    return n - 1 if n > 0 and lines[n] == "" else n


def section_span(lines, heads, k):
    """(a, c, b) of the section headed by heads[k]: first line, last non-blank, last line."""
    a, level, _t = heads[k]
    b = last_line(lines)
    for i, lv, _x in heads[k + 1:]:
        if lv <= level:
            b = i - 1
            break
    c = b
    while c > a and rd.blank(lines[c]):
        c -= 1
    return a, c, b


def item_span(lines, a, heads_at, end):
    """(a, c, b) of the top-level block that starts at line a."""
    is_list = bool(LIST_ITEM_RE.match(rd.uncr(lines[a])))
    c = a
    j = a + 1
    while j <= end:
        ln = rd.uncr(lines[j])
        if j in heads_at or ln.startswith("<!--") or rd.FENCE_RE.match(ln) and not ln[:1].isspace():
            break
        if rd.blank(ln):
            k = j
            while k <= end and rd.blank(lines[k]):
                k += 1
            if is_list and k <= end and k not in heads_at and rd.uncr(lines[k])[:1] in (" ", "\t"):
                j = k
                continue
            break
        if not ln[:1].isspace() and LIST_ITEM_RE.match(ln):
            break                                   # the next top-level item (or a list after a paragraph)
        c = j
        j += 1
    b = c
    while b + 1 <= end and rd.blank(lines[b + 1]):
        b += 1
    return a, c, b


def block_starts(lines, heads_at, end):
    """Line indexes where a top-level block may start: a column-0 list item, or a paragraph's
    first line (after a blank, a heading or the top of the file)."""
    out = set()
    for i in range(end + 1):
        ln = rd.uncr(lines[i])
        if rd.blank(ln) or ln[:1].isspace() or i in heads_at:
            continue
        if LIST_ITEM_RE.match(ln) or i == 0 or rd.blank(lines[i - 1]) or (i - 1) in heads_at:
            out.add(i)
    return out


def one(desc, matches):
    """The single match of a selector; zero or several is a refusal."""
    if len(matches) != 1:
        where = ", ".join("line %d" % (m[0] + 1) for m in matches[:6])
        raise Refusal("%s matches %d blocks%s; it must match exactly one"
                      % (desc, len(matches), (" (" + where + ")") if matches else ""))
    return matches[0]


def select(lines, regions, args):
    """[(desc, a, c, b)] for every selector, in the order given. Raises Refusal."""
    heads = headings(lines, regions)
    heads_at = {h[0] for h in heads}
    end = last_line(lines)
    blocks = []
    for sel in args.section or []:
        want = sel.strip()
        idx = [k for k, (i, _lv, t) in enumerate(heads)
               if t == want or rd.uncr(lines[i]).strip() == want]
        span = one("--section %r" % sel, [section_span(lines, heads, k) for k in idx])
        blocks.append(("--section %r" % sel,) + span)
    starts = block_starts(lines, heads_at, end)
    for sel in args.item or []:
        hits = [i for i in sorted(starts) if rd.uncr(lines[i]).startswith(sel)]
        span = one("--item %r" % sel, [item_span(lines, i, heads_at, end) for i in hits])
        blocks.append(("--item %r" % sel,) + span)
    for rx in args.sections_matching or []:
        try:
            pat = re.compile(rx)
        except re.error as e:
            raise Refusal("--sections-matching %r is not a valid regex (%s)" % (rx, e))
        idx = [k for k, (_i, _lv, t) in enumerate(heads) if pat.search(t)]
        if not idx:
            raise Refusal("--sections-matching %r matches no heading" % rx)
        order = list(reversed(idx)) if args.newest_last else idx
        for k in sorted(order[args.keep_newest:]):
            blocks.append(("--sections-matching %r (%s)" % (rx, heads[k][2]),)
                          + section_span(lines, heads, k))
    return blocks


# --------------------------------------------------------------------------------------
# The refusals that read the source as a whole
# --------------------------------------------------------------------------------------

def protected_name(name):
    up = name.upper()
    return next((p for p in PROTECTED_NAMES if fnmatch.fnmatchcase(up, p)), None)


def hold_reason(text, today):
    for m in HOLD_RE.finditer(text):
        raw = m.group(1).rstrip("-").strip()
        try:
            until = datetime.date.fromisoformat(raw[:10])
        except ValueError:
            return "a rotation-hold marker carries a date this tool cannot read (%r)" % raw
        if until >= today:
            return "the source carries a rotation-hold until %s (today is %s)" % (until, today)
    return None


def marker_pairs_in(block_text, source_text):
    """Names of machine-read marker pairs (<!-- NAME --> ... <!-- /NAME -->) in the source
    of which the block holds either half."""
    names = set()
    for m in MARKER_OPEN_RE.finditer(source_text):
        name = m.group(1)
        close = re.compile(r"<!--\s*/" + re.escape(name) + r"\s*-->")
        if close.search(source_text, m.end()):
            if m.group(0) in block_text or close.search(block_text):
                names.add(name)
    return sorted(names)


# --------------------------------------------------------------------------------------
# The probe (the same function checks the planned bytes and the bytes re-read from disk)
# --------------------------------------------------------------------------------------

def probe_strings(body):
    """At least PROBE_MIN distinctive strings from the head, middle and tail of a block."""
    rows = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if len(rows) >= PROBE_MIN:
        picks = [rows[0], rows[len(rows) // 2], rows[-1]]
    else:                       # one or two lines: every line, plus three cuts of the longest
        longest = max(rows, key=len) if rows else ""
        w = max(8, min(60, len(longest) // 3))
        mid = max(0, len(longest) // 2 - w // 2)
        picks = rows + [longest[:w], longest[mid:mid + w], longest[-w:]]
    return [p[:80] for p in picks if p]


def probe(archive_raw_now, archive_raw_before, bodies):
    """Misses, as text: [] when every block and every probe string is in the archive bytes."""
    try:
        back = rd.lf(archive_raw_now.decode("utf-8"))
    except UnicodeDecodeError:
        return ["the archive is not valid UTF-8 when re-read"]
    misses = []
    for n, body in enumerate(bodies, 1):
        flat = rd.lf(body)
        if flat not in back:
            misses.append("block %d (whole block)" % n)
        strings = probe_strings(flat)
        lost = [s for s in strings if s not in back]
        if len(strings) < PROBE_MIN or lost:
            misses.append("block %d (%d of %d probe strings missing)" % (n, len(lost), len(strings)))
    if archive_raw_before is not None and not archive_raw_now.startswith(archive_raw_before.rstrip(b"\r\n")):
        misses.append("the archive's earlier bytes")
    return misses


# --------------------------------------------------------------------------------------
# Rulings (analyze-context's rulings.py decides; this compares now with the plan)
# --------------------------------------------------------------------------------------

_DEPS = []


def deps():
    """(docket_corpus, rulings), loaded once per process by rotate-docket's own loader."""
    if not _DEPS:
        _DEPS.extend(rd.load_deps())
    return _DEPS[0], _DEPS[1]


def _config_text(root, name):
    p = Path(root) / name
    if not p.is_file():
        return None
    try:
        return read_bytes(p).decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def ruling_loss(dc, rl, root, src_path, src_text_now, src_text_new, arch_path, arch_text_now,
                arch_text_new):
    """[ruling dict] that the source and archive count now and the planned bytes do not keep."""
    cfg = rl._snapshot(dc, *[_config_text(root, n) for n in rl.CONFIG_NAMES])
    src_rel = _rel(src_path, root) or Path(src_path).name
    arch_rel = _rel(arch_path, root)
    src_kind = rl.source_kind(src_rel, cfg) if not src_rel.startswith("..") else ""
    src_kind = src_kind or "standing"       # a source the briefing does not read: the safe side
    arch_kind = rl.source_kind(arch_rel, cfg) if arch_rel and not arch_rel.startswith("..") else ""

    def counted(rel, kind, text):
        if not kind or text is None:
            return []
        return [r for r in rl.rulings_in_text(rel, rd.lf(text)) if rl._counted(kind, r)]

    before = counted(src_rel, src_kind, src_text_now) + counted(arch_rel, arch_kind, arch_text_now)
    after = counted(src_rel, src_kind, src_text_new) + counted(arch_rel, arch_kind, arch_text_new)
    idx = rl.build_index(after)
    # Each ruling is judged with the contrastive words and notes of its OWN old copy, exactly as
    # rulings.py's removal path does (_contrast_fn, _notes_fn): without them a similar neighbouring
    # ruling ("Memcached cache ...: do not re-propose it") vouches for one that is leaving ("Redis ...").
    ccache = {}
    olds = {}
    for rel, text in ((src_rel, src_text_now), (arch_rel, arch_text_now)):
        if rel and text is not None and rel.casefold() not in olds:
            body = rd.lf(text)
            olds[rel.casefold()] = (rl._contrast_fn(rel, body, ccache, rel),
                                    rl._notes_fn(rel, body, ccache, rel))
    lost = []
    for r in before:
        of, nof = olds.get(str(r.get("path", "")).casefold(), (None, None))
        contrast = (lambda r=r, of=of: of(r)) if of else None
        if not rl.kept_as_ruling(r, idx, contrast, nof)[0]:
            lost.append(r)
    return lost, (src_kind, arch_kind or "not read")


# --------------------------------------------------------------------------------------
# Planning (pure: bytes in, planned bytes and checks out; nothing touches disk)
# --------------------------------------------------------------------------------------

def render(lines, bom):
    return rd.encode("\n".join(lines), bom)


def keep_eof_terminator(text, lines, removed, new_lines):
    """new_lines, ending with a '' when a moved block took the last line of a file with no final
    newline. The retained line that now ends the file keeps the terminator it had ("Stay.\\r\\n"
    stays "Stay.\\r\\n", "Stay.\\n" stays "Stay.\\n"); stripping its CR instead left a CRLF source
    one CR short and the CR check refused the rotation."""
    if not text.endswith("\n") and (len(lines) - 1) in removed and new_lines:
        return new_lines + [""]
    return new_lines


def plan(args, src_path, arch_path, src_raw, arch_raw, today, date_text):
    name = Path(src_path).name
    bad = protected_name(name)
    if bad:
        raise Refusal("%s matches %s: a workflow, pipeline, runbook or playbook is not rotated"
                      % (name, bad))
    text, bom = rd.decode(src_raw, name)
    held = hold_reason(text, today)
    if held:
        raise Refusal(held)
    lines = text.split("\n")
    regions = rd.block_regions(lines)
    blocks = select(lines, regions, args)
    reasons = []
    for desc, a, c, b in blocks:
        if rd.crosses_block(regions, a, c):
            reasons.append("%s (lines %d-%d): a code fence or multi-line HTML comment crosses "
                           "it or holds it" % (desc, a + 1, c + 1))
        body = "\n".join(rd.uncr(x) for x in lines[a:c + 1])
        pairs = marker_pairs_in(body, rd.lf(text))
        if pairs:
            reasons.append("%s (lines %d-%d): holds a machine-read marker pair (%s)"
                           % (desc, a + 1, c + 1, ", ".join(pairs)))
    srt = sorted(blocks, key=lambda x: x[1])
    for x, y in zip(srt, srt[1:]):
        if y[1] <= x[2]:
            reasons.append("%s and %s overlap (lines %d-%d and %d-%d)"
                           % (x[0], y[0], x[1] + 1, x[2] + 1, y[1] + 1, y[2] + 1))
    if reasons:
        raise Refusal("; ".join(reasons))
    if not blocks:
        return {"blocks": []}

    # The new source: drop each block; the pointer stands once where the first one stood.
    drop = {}
    for n, (desc, a, c, b) in enumerate(srt):
        tail_blank = a == 0 or rd.blank(lines[a - 1])
        hi = b if (tail_blank and not (n == 0 and args.pointer)) else c
        drop[a] = hi
    new_lines, i, removed = [], 0, set()
    first_a = srt[0][1]
    while i < len(lines):
        if i in drop:
            if i == first_a and args.pointer:
                cr = "\r" if lines[i].endswith("\r") else ""
                new_lines.append(args.pointer + cr)
            removed.update(range(i, drop[i] + 1))
            i = drop[i] + 1
            continue
        new_lines.append(lines[i])
        i += 1
    new_lines = keep_eof_terminator(text, lines, removed, new_lines)
    new_src_raw = render(new_lines, bom)

    # The archive text.
    src_eol = rd.eol_of(text)
    if arch_raw is not None:
        a_text, a_bom = rd.decode(arch_raw, Path(arch_path).name)
        dest_eol = rd.eol_of(a_text, src_eol)
    else:
        a_text, a_bom, dest_eol = "", False, src_eol
    bodies, changes, unresolved = [], [], []
    for desc, a, c, b in srt:
        body = "\n".join(rd.uncr(x) for x in lines[a:c + 1])
        body, ch, un = rd.rewrite_links(body, Path(src_path).parent, Path(arch_path).parent)
        bodies.append(body)
        changes += ch
        unresolved += un
    heading = "## Rotated %s %s %d block%s from %s" % (date_text, rd.DASH, len(srt),
                                                    "" if len(srt) == 1 else "s", name)
    chunks = []
    for body in bodies:
        chunks += [body, ""]
    if arch_raw is None:
        back = os.path.relpath(str(src_path), str(Path(arch_path).parent)).replace("\\", "/")
        back = "<%s>" % back if " " in back else back
        block = ["# Rotated prose %s %s" % (rd.DASH, name), "",
                 "Blocks moved verbatim out of [`%s`](%s) by update-context's `rotate-handoff.py` "
                 "(relative links re-pointed for this directory)." % (name, back), "",
                 heading, ""] + chunks
        new_a_text = dest_eol.join("\n".join(block).split("\n"))
    else:
        prefix = a_text
        if prefix and not prefix.endswith("\n"):
            prefix += dest_eol
        new_a_text = prefix + dest_eol.join("\n".join(["", heading, ""] + chunks).split("\n"))
    new_arch_raw = rd.encode(new_a_text, a_bom)

    return {"blocks": srt, "lines": lines, "text": text, "new_lines": new_lines,
            "removed": removed, "new_src_raw": new_src_raw, "new_arch_raw": new_arch_raw,
            "bodies": bodies, "changes": changes, "unresolved": unresolved,
            "src_raw": src_raw, "arch_raw": arch_raw, "a_text": a_text, "new_a_text": new_a_text,
            "dest_eol": dest_eol, "src_eol": src_eol}


def checks(pl, args):
    """[(label, ok)] over the planned bytes, before anything is written."""
    out = []
    lines, new_lines, removed = pl["lines"], pl["new_lines"], pl["removed"]
    kept_old = [ln for i, ln in enumerate(lines) if i not in removed]
    kept_new = list(new_lines)
    last_cut = not pl["text"].endswith("\n") and (len(lines) - 1) in removed
    if last_cut and kept_new and kept_new[-1] == "":
        kept_new = kept_new[:-1]        # the '' that carries the last retained line's terminator
    if args.pointer:
        first = pl["blocks"][0][1]
        at = sum(1 for i in range(first) if i not in removed)
        kept_new = kept_new[:at] + kept_new[at + 1:]
    same = kept_old == kept_new
    out.append(("every source line outside a moved block keeps its exact bytes, in order", same))
    cr_old = pl["src_raw"].count(b"\r")
    cr_gone = sum(lines[i].count("\r") for i in removed)
    cr_ptr = 1 if args.pointer and lines[pl["blocks"][0][1]].endswith("\r") else 0
    out.append(("the source's CR bytes change only by the moved lines' own (%d -> %d)"
                % (cr_old, pl["new_src_raw"].count(b"\r")),
                pl["new_src_raw"].count(b"\r") == cr_old - cr_gone + cr_ptr))
    src_lf = rd.lf(pl["text"])
    new_lf = rd.lf(pl["new_src_raw"].decode("utf-8", errors="replace"))
    bodies_src = ["\n".join(rd.uncr(x) for x in lines[a:c + 1]) for _d, a, c, _b in pl["blocks"]]
    out.append(("no moved block is left in the source",
                all(new_lf.count(b) == src_lf.count(b) - bodies_src.count(b) for b in bodies_src)))
    misses = probe(pl["new_arch_raw"], pl["arch_raw"], pl["bodies"])
    out.append(("every block is in the planned archive (whole, and %d probe strings each)%s"
                % (PROBE_MIN, (": missing " + "; ".join(misses)) if misses else ""), not misses))
    want_eol = pl["dest_eol"]
    added = pl["new_a_text"][len(pl["a_text"]):]
    eol_ok = (added.count("\r\n") == added.count("\n")) if want_eol == "\r\n" else ("\r\n" not in added)
    out.append(("the appended archive text uses one line ending (%s)"
                % ("CRLF" if want_eol == "\r\n" else "LF"), eol_ok))
    return out


# --------------------------------------------------------------------------------------
# Writing (the contract's order)
# --------------------------------------------------------------------------------------

def apply(pl, src_path, arch_path):
    """(ok, message). The source is written only after the archive re-read holds every block."""
    src_path, arch_path = Path(src_path), Path(arch_path)

    def arch_now():
        return read_bytes(arch_path) if arch_path.exists() else None

    if read_bytes(src_path) != pl["src_raw"]:
        return False, "the source changed on disk after it was read (another session?); nothing written"
    if arch_now() != pl["arch_raw"]:
        return False, "the archive changed on disk after it was read (another session?); nothing written"
    try:
        arch_path.parent.mkdir(parents=True, exist_ok=True)
        rd.atomic_write_bytes(arch_path, pl["new_arch_raw"])
    except OSError as e:
        return False, "could not write the archive (%s); the source is untouched" % e
    try:
        back = read_back(arch_path)
    except OSError as e:
        back, misses = b"", ["the archive could not be re-read (%s)" % e]
    else:
        misses = probe(back, pl["arch_raw"], pl["bodies"])
    if misses:
        note = "the archive may hold an appended copy -- check %s" % arch_path
        try:
            if arch_now() == pl["new_arch_raw"]:
                rd.restore(arch_path, pl["arch_raw"])
                note = ("the archive may hold an appended copy: it was put back to its earlier "
                        "bytes, check %s" % arch_path)
        except OSError:
            pass
        return False, ("the archive re-read from disk is missing %s; the SOURCE IS UNTOUCHED; %s"
                       % ("; ".join(misses), note))
    if read_bytes(src_path) != pl["src_raw"]:
        return False, ("the source changed while the archive was written (another session?); "
                       "the source is untouched and the archive may hold an appended copy -- check %s"
                       % arch_path)
    try:
        rd.atomic_write_bytes(src_path, pl["new_src_raw"])
    except OSError as e:
        return False, ("could not write the source (%s); it is untouched and the archive holds "
                       "the appended copy -- check %s" % (e, arch_path))
    if read_bytes(src_path) != pl["new_src_raw"]:
        return False, "the source re-read does not match what was written -- check %s" % src_path
    return True, "appended %d block(s) to %s and rewrote %s" % (len(pl["blocks"]), arch_path.name,
                                                                 src_path.name)


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------

def utf8_console():
    """Run once by the entry point, before anything prints: a cp1252 console would otherwise
    crash on the first non-ASCII byte. Defined above every print so the console-encoding lint
    sees it first in source order; an in-process caller of main() keeps its own streams."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def suggested_pointer(pl, src_path, arch_path):
    rel = os.path.relpath(str(arch_path), str(Path(src_path).parent)).replace("\\", "/")
    return "%d block(s) rotated %s %s [%s](%s)." % (len(pl["blocks"]), pl.get("date", ""),
                                                   rd.ARROW, Path(arch_path).name,
                                                   "<%s>" % rel if " " in rel else rel)


def run(args):
    src_path = Path(args.source).resolve()
    arch_path = Path(args.archive).resolve()
    if not src_path.is_file():
        print("could not rotate: no source file %s" % src_path, file=sys.stderr)
        return 2
    if os.path.normcase(str(src_path)) == os.path.normcase(str(arch_path)):
        print("could not rotate: --source and --archive are the same file", file=sys.stderr)
        return 2
    if not (args.section or args.item or args.sections_matching):
        print("could not rotate: give at least one --section, --item or --sections-matching",
              file=sys.stderr)
        return 2
    if args.sections_matching and args.keep_newest is None:
        print("could not rotate: --sections-matching needs --keep-newest N", file=sys.stderr)
        return 2
    if args.keep_newest is not None and args.keep_newest < 0:
        print("could not rotate: --keep-newest must be 0 or more", file=sys.stderr)
        return 2
    try:
        today = datetime.date.fromisoformat(args.date) if args.date else datetime.date.today()
    except ValueError:
        print("could not rotate: --date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    src_raw = read_bytes(src_path)
    arch_raw = read_bytes(arch_path) if arch_path.exists() else None
    print("source:  %s" % src_path)
    print("archive: %s%s" % (arch_path, "" if arch_raw is not None else " (new file)"))
    try:
        pl = plan(args, src_path, arch_path, src_raw, arch_raw, today, today.isoformat())
    except Refusal as e:
        print("REFUSED: %s. Nothing was written." % e)
        return 1
    if not pl["blocks"]:
        print("nothing to rotate (every --sections-matching selector has %d or fewer matches). "
              "Nothing was written." % args.keep_newest)
        return 0
    pl["date"] = today.isoformat()
    for n, (desc, a, c, _b) in enumerate(pl["blocks"], 1):
        first = rd.uncr(pl["lines"][a]).strip()
        print("block %d: %s -- lines %d-%d, %d bytes: %s" % (
            n, desc, a + 1, c + 1, len(pl["bodies"][n - 1].encode("utf-8")),
            first if len(first) <= 90 else first[:87] + "..."))
    for o, nw in pl["changes"]:
        print("link re-pointed for the archive: %s -> %s" % (o, nw))
    for u in sorted(set(pl["unresolved"])):
        print("link resolves nowhere (left as is): %s" % u)

    dc, rl = deps()
    root = find_root(src_path.parent)
    lost, kinds = ruling_loss(
        dc, rl, root, src_path, pl["text"], pl["new_src_raw"].decode("utf-8", errors="replace"),
        arch_path, pl["a_text"] if arch_raw is not None else None, pl["new_a_text"])
    results = checks(pl, args)
    results.append(("no standing ruling disappears (source read as %s, archive as %s)" % kinds,
                    not lost))
    for label, ok in results:
        print("%s %s" % ("PASS" if ok else "FAIL", label))
    for r in lost:
        print('RULING WOULD LEAVE (%s line %d): "%s"' % (r["path"], r["line"], r["summary"]))
    if not all(ok for _l, ok in results):
        print("REFUSED: a check failed. Nothing was written.")
        return 1
    if not args.pointer:
        print("suggested pointer: %s" % suggested_pointer(pl, src_path, arch_path))
    if not args.apply:
        print("DRY RUN: nothing written (add --apply to write).")
        return 0
    ok, msg = apply(pl, src_path, arch_path)
    print(("DONE: " if ok else "STOPPED: ") + msg)
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="the document to rotate out of (required)")
    ap.add_argument("--archive", help="the archive file to append to (required)")
    ap.add_argument("--section", action="append", help="exact heading text of a section to move")
    ap.add_argument("--item", action="append", help="literal start of one top-level block to move")
    ap.add_argument("--sections-matching", action="append", metavar="REGEX",
                    help="move every matching section except the newest --keep-newest")
    ap.add_argument("--keep-newest", type=int, help="how many matching sections stay")
    ap.add_argument("--newest-last", action="store_true",
                    help="the newest sections are the LAST in the file (default: the first)")
    ap.add_argument("--pointer", help="one sentence left where the first moved block stood")
    ap.add_argument("--date", help="YYYY-MM-DD for the archive heading and the hold check "
                                   "(default: today)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    g.add_argument("--selftest", action="store_true", help="run the built-in check")
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    if not args.source or not args.archive:
        ap.print_usage(sys.stderr)
        print("rotate-handoff: --source and --archive are required", file=sys.stderr)
        return 2
    try:
        return run(args)
    except rd.EnvError as e:
        print(str(e), file=sys.stderr)
        return 2


# --------------------------------------------------------------------------------------
# Selftest: a small end-to-end check in a temp directory (the full suite is
# tests/test-rotate-handoff.py in the repository that ships this tool).
# --------------------------------------------------------------------------------------

def selftest():
    passed = failed = 0

    def expect(cond, name):
        nonlocal passed, failed
        print("%s %s" % ("PASS" if cond else "FAIL", name))
        passed, failed = passed + bool(cond), failed + (not cond)

    def call(argv):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(argv)
        return rc, buf.getvalue()

    tmp = Path(tempfile.mkdtemp(prefix="rotate-handoff-selftest-"))
    try:
        src, arch = tmp / "HANDOFF.md", tmp / "archive" / "HANDOFF-history.md"
        doc = ("# Handoff\r\n\r\n## Current\r\n\r\nLive work.\r\n\r\n"
               "## Session 2026-01-02\r\n\r\nFinished: the export path, verified 3/3.\r\n"
               "- detail one\r\n- detail two\r\n\r\n## Notes\r\n\r\n- keep me\r\n")
        with open(str(src), "wb") as fh:
            fh.write(doc.encode("utf-8"))
        base = ["--source", str(src), "--archive", str(arch), "--section", "Session 2026-01-02"]
        rc, out = call(base)
        expect(rc == 0 and "DRY RUN" in out and not arch.exists() and read_bytes(src) == doc.encode(),
               "a dry run exits 0 and writes nothing")
        rc, out = call(base + ["--apply"])
        got_a = read_bytes(arch) if arch.exists() else b""
        got_s = read_bytes(src)
        expect(rc == 0 and b"Finished: the export path, verified 3/3.\r\n- detail one\r\n- detail two"
               in got_a, "--apply appends the section verbatim (CRLF kept) to a new archive")
        expect(b"Session 2026-01-02" not in got_s and got_s.count(b"\r") == got_s.count(b"\n")
               and b"- keep me\r\n" in got_s, "the source loses the section and stays CRLF")
        rc, out = call(base + ["--apply"])
        expect(rc == 1 and "matches 0 blocks" in out and read_bytes(src) == got_s
               and read_bytes(arch) == got_a, "a second identical --apply refuses and changes nothing")
        rc, out = call(["--source", str(src), "--archive", str(arch), "--item", "- detail"])
        expect(rc == 1 and "REFUSED" in out, "an item selector that matches nothing refuses")
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    print("\n%d passed, %d failed" % (passed, failed))
    print("selftest: %s" % ("ALL GREEN" if not failed else "FAILED"))
    return 0 if not failed else 1


if __name__ == "__main__":
    utf8_console()
    sys.exit(main())
