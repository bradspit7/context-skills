#!/usr/bin/env python
"""bucket-sync.py -- the out-of-band memory leg of device-sync (arrival) and device-handoff (departure).

    python bucket-sync.py --direction arrival|departure --live <live memory dir> --bucket <bucket dir>
                          --project <name> [--dry-run] [--backup-root <dir>]
    python bucket-sync.py --claim --project <name> --bucket <bucket dir> [--dry-run]

Bundled byte-identically in device-sync/scripts/ and device-handoff/scripts/ (like probe-sync.sh).
Spec: docs/superpowers/specs/2026-10-14-bucket-sync-design.md in the central upgrades repo.

The direction fixes source and destination: arrival copies bucket -> live, departure live -> bucket.
Arrival writes only the live dir, departure only the bucket. Only the top-level regular *.md files of
each dir are in scope; subdirectories, other files and *.bak are never read or written.

OWNERSHIP, checked before planning, so a refusal writes nothing. The probe finds a bucket by a case-
and punctuation-blind name, so `MyApp` and `my-app` find the same one; the bucket says whose it is in
a top-level `.bucket-owner` file holding one line `project: <name>` (UTF-8, LF), and --project (the
probe's project-name:) must equal that name exactly. A different name, or a malformed marker, is
refused. A bucket with no marker and no top-level *.md file is claimed by the first departure (the
marker is its first write); an arrival from it has nothing to copy and writes nothing to it. A bucket
with no marker that holds notes is UNCLAIMED and refused in both directions: the refusal names its
notes and prints the --claim line, which writes only the marker (and refuses a bucket recorded for
another project). The marker is never copied and is not counted among the out-of-scope entries.

PLAN FIRST, THEN APPLY. Every note is classified before anything is written, and any STOP in the plan
means nothing is written in that run.

THE LAST-SYNCED RECORD. Each machine keeps, beside its backups and never in the bucket, one record per
project, live dir and bucket: <backup-root>/.last-synced/<bucket name>-<16 hex>.json, a JSON map from each
note's normcased name to the sha256 of the bytes both sides held when that note was last equal at the end
of a successful run on this machine (MEMORY.md included, though its merge never consults it). With a
record, a note that differs is classified by which side changed since then (B the record's hash):

  SOURCE-CHANGED       only the source changed since B                   copy (backed up)  copy (backed up)
  DEST-CHANGED         only the destination changed since B              keep, named       STOP, named
  CONFLICT             both changed since B, or on both sides and not    STOP, named       STOP, named
                       in the record (two separate creations)
  DELETED-HERE         in B, gone from live, the bucket still B          named, not copied back / bucket kept
  DELETED-IN-BUCKET    in B, gone from the bucket, live still B          live kept / named, not uploaded
  EDITED-AFTER-DELETE  in B, gone from one side, the other changed       copied to the side that lacks it
                       since B                                           (nothing there to overwrite), by
                                                                         the run whose direction allows it
                                                                         (arrival)         (departure)

No run deletes a file. A note on one side only that is not in the record is SOURCE-ONLY / DEST-ONLY below.
The record is written (temp file + os.replace) only after a successful run, a nothing-to-do run included,
never after a STOP, a refusal, an error or a --dry-run: a note equal on both sides at the end takes its
hash, a note gone from both sides is dropped, and any other note keeps its entry. On the record's first
write a note left differing takes the hash of the copy the newer-wins rule ruled older (the one it would
have overwritten), so its later changes are judged against the version both sides started from. An
unreadable record is refused (exit 2), never read as empty: an empty record would read every note as
never synced. With NO record (a first sync, or another live dir or --backup-root) the plan says so on its
RECORD line and every note is classified by the newer-wins rule below, as before the record existed:

  SOURCE-ONLY   not at the destination                         copy                 copy
  EQUAL         same bytes                                     skip                 skip
  SOURCE-NEWER  bytes differ, source mtime > dest + 2 s        copy (backed up)     copy (backed up)
  DEST-NEWER    bytes differ, dest mtime > source + 2 s        keep, named          STOP, named
  CONFLICT      bytes differ, mtimes within 2 s                STOP, named          STOP, named
  DEST-ONLY     not at the source                              keep, named          keep, named
                                                               (arrival)            (departure)

A departure STOP on a bucket change means the other machine departed after this machine's last arrival:
the STOP prints the exact arrival command line, and the repair is that arrival, then the departure again.
With a record that arrival stops too on any note both machines changed, so it cannot overwrite unsent work
here; without one it decides by mtime.

MEMORY.md is never copied whole over an existing index; it is merged mechanically: the result starts
from the destination's file, every destination line stays, an entry's text follows the source only
when its note was copied in this run, each source-only entry goes after the nearest preceding source
entry already in the result (else after the last entry line), no two lines share a link target, a
source-only heading or prose line is named with a count and not merged, an entry whose note is absent
at the destination after the sync is named DANGLING, and an unchanged result is not written.

Immediately before each write the destination is read again and compared with what the plan saw; if a
sync client changed it mid-run (or put a file where the plan saw none), the run aborts there, exit 1, with
that note named, it not overwritten and nothing further written. Every destination file is copied to
<backup-root>/<bucket name>/<UTC stamp>/ and byte-compared before it is overwritten; new bytes go to a temp
file in the destination dir, then os.replace. TEST-ONLY: when the environment variable
BUCKET_SYNC_TEST_MIDRUN_WRITE names a note, its destination is written with fixed bytes just before that
re-check, as a download landing mid-run would (tests/test-bucket-sync.py R3); never set it otherwise.

Exit codes: 0 synced or nothing to do; 3 STOP (nothing written); 2 refusal or usage (an ownership
refusal and an unreadable last-synced record included); 1 an unexpected error, a destination changed
mid-run, or a record that could not be written, naming any file already written.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from urllib.parse import unquote

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WINDOW = 2.0                      # seconds; robocopy's FAT-time tolerance
INDEX = "MEMORY.md"
ENTRY_RE = re.compile(r"^\s*- \[[^\]]*\]\(([^)]+)\)")
TOMBSTONE = "SUPERSEDED"           # a top-level bucket file naming it retires the bucket (as probe-sync.sh reads it)
DEFAULT_BACKUP_ROOT = os.path.join("~", ".claude", "bucket-sync-backups")
OWNER = ".bucket-owner"            # top level of the bucket: one line "project: <name>"
OWNER_RE = re.compile(r"project: ([^\r\n]*)(?:\r?\n)?")
NAMES_SHOWN = 5                    # an UNCLAIMED refusal names this many notes, then counts the rest
RECORD_DIR = ".last-synced"        # under the backup root: this machine's last-synced records
RECORD_FORMAT = "bucket-sync last-synced record 1"
SHA_RE = re.compile(r"[0-9a-f]{64}")
NOT_A_FILE = "not-a-regular-file"  # a destination state: something is there, but no note
MIDRUN_ENV = "BUCKET_SYNC_TEST_MIDRUN_WRITE"     # TEST-ONLY, see midrun_hook()
MIDRUN_BYTES = b"written mid-run by the bucket-sync test hook\n"

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_STOP = 0, 1, 2, 3

SOURCE_ONLY, EQUAL, SOURCE_NEWER = "source-only", "equal", "source-newer"
DEST_NEWER, CONFLICT, DEST_ONLY = "dest-newer", "conflict", "dest-only"
SOURCE_CHANGED, DEST_CHANGED = "source-changed", "dest-changed"
DELETED_HERE, DELETED_IN_BUCKET, EDITED_AFTER_DELETE = "deleted-here", "deleted-in-bucket", "edited-after-delete"
COPY, SKIP, KEEP, STOP = "COPY", "SKIP", "KEEP", "STOP"


class Refusal(Exception):
    """A precondition failed: exit 2, nothing written. `lines` are printed before the RESULT line."""

    def __init__(self, msg, lines=()):
        Exception.__init__(self, msg)
        self.lines = list(lines)


class ApplyError(Exception):
    """A write failed part-way: exit 1, naming what was already written."""

    def __init__(self, cause, written):
        Exception.__init__(self, cause)
        self.cause = cause
        self.written = written


# ---- reading ------------------------------------------------------------------------------------

def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def state(path):
    """What the plan and the pre-install re-check compare: None (nothing there), NOT_A_FILE, or the sha256."""
    if not os.path.lexists(path):
        return None
    if os.path.islink(path) or not os.path.isfile(path):
        return NOT_A_FILE
    return sha(read_bytes(path))


def scan(d, skip=()):
    """({normcase(name): name} for the top-level regular *.md files, count of everything else but `skip`)."""
    notes, other = {}, 0
    with os.scandir(d) as it:
        for e in it:
            if e.name.endswith(".md") and e.is_file(follow_symlinks=False):
                notes[os.path.normcase(e.name)] = e.name
            elif e.name not in skip:
                other += 1
    return notes, other


def norm(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def inside(child, parent):
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


# ---- refusals -----------------------------------------------------------------------------------

def refuse_if_unsafe(live, bucket, backup_root):
    for label, d in (("live memory dir", live), ("bucket", bucket)):
        if not os.path.isdir(d):
            raise Refusal("the %s is not an existing directory: %s" % (label, d))
    rl, rb = norm(live), norm(bucket)
    same = rl == rb
    try:
        same = same or os.path.samefile(live, bucket)
    except OSError:
        pass
    if same:
        raise Refusal("live and bucket are the same directory (%s): a junction or one shared store is "
                      "branch 3, with no copy leg" % rb)
    if inside(rl, rb) or inside(rb, rl):
        raise Refusal("one directory resolves inside the other (live %s, bucket %s): a junction/symlink "
                      "into the other is branch 3, with no copy leg" % (rl, rb))
    refuse_if_retired(bucket)
    rk = norm(backup_root)
    for label, r in (("bucket", rb), ("live memory dir", rl)):
        if inside(rk, r):
            raise Refusal("--backup-root %s lies inside the %s; backups must live outside both dirs" % (rk, label))


def refuse_if_retired(bucket):
    with os.scandir(bucket) as it:
        tombs = sorted(e.name for e in it if TOMBSTONE in e.name and e.is_file())
    if tombs:
        raise Refusal("the bucket is retired: its top level holds a %s tombstone (%s)" % (TOMBSTONE, tombs[0]))


# ---- ownership ----------------------------------------------------------------------------------

def q(path):
    return '"%s"' % path


def claim_line(project, bucket):
    return "python %s --claim --project %s --bucket %s" % (
        q(os.path.abspath(__file__)), q(project), q(os.path.abspath(bucket)))


def read_owner(bucket):
    """The project name the bucket's marker records, or None when there is no marker. Refusal if malformed."""
    path = os.path.join(bucket, OWNER)
    if not os.path.lexists(path):
        return None
    want = "expected one line 'project: <name>' (UTF-8); fix or remove it by hand, then run again"
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refusal("the bucket's ownership marker is malformed: %s is not a regular file; %s" % (path, want))
    try:
        with open(path, "rb") as f:
            raw = f.read(4097)
    except OSError as e:
        raise Refusal("the bucket's ownership marker could not be read (%s: %r)" % (path, e))
    try:
        m = OWNER_RE.fullmatch(raw.decode("utf-8")) if len(raw) <= 4096 else None
    except UnicodeDecodeError:
        m = None
    name = m.group(1) if m else ""
    if not name or name != name.strip():
        raise Refusal("the bucket's ownership marker is malformed: %s holds %r; %s" % (path, raw[:80], want))
    return name


def check_owner(bucket, project, direction):
    """Before planning. (the OWNER line for the plan, whether this run claims the bucket); Refusal otherwise."""
    rec = read_owner(bucket)
    path = os.path.join(bucket, OWNER)
    if rec is not None:
        if rec != project:
            raise Refusal("the bucket belongs to another project: %s records '%s', this run is for '%s'"
                          % (path, rec, project),
                          ["FOREIGN: the probe found this bucket by name, and names compare case- and punctuation-blind.",
                           "  If this project's folder was renamed, the owner edits %s by hand. Otherwise give this "
                           "project its own bucket, under a name no other project's normalizes to, and name it with "
                           "a 'sync-bucket: <folder name>' line in the recipe note." % OWNER])
        return "OWNER %s records project: %s (this project)" % (OWNER, rec), False
    notes = sorted(scan(bucket)[0].values())
    if notes:
        shown = ", ".join(notes[:NAMES_SHOWN])
        if len(notes) > NAMES_SHOWN:
            shown += " and %d more" % (len(notes) - NAMES_SHOWN)
        raise Refusal("UNCLAIMED bucket (no %s marker, %d top-level *.md files)" % (OWNER, len(notes)),
                      ["UNCLAIMED: %s has no %s marker and holds %d top-level *.md file(s): %s"
                       % (os.path.abspath(bucket), OWNER, len(notes), shown),
                       "  Another project may own it. If it is this project's bucket, claim it, then run this "
                       "sync again:",
                       "  CLAIM: %s" % claim_line(project, bucket)])
    if direction == "departure":
        return ("OWNER the bucket has no %s marker and no notes: this departure claims it for project: %s"
                % (OWNER, project)), True
    return ("OWNER the bucket has no %s marker and no notes: an arrival writes nothing to it (the next "
            "departure claims it)" % OWNER), False


def write_marker(bucket, project):
    """The marker, through a temp file in the bucket and os.replace. Never over an existing marker."""
    path = os.path.join(bucket, OWNER)
    if os.path.lexists(path):
        raise IOError("%s appeared after the plan was made; not overwritten" % path)
    replace_via_temp(path, data=("project: %s\n" % project).encode("utf-8"))
    return path


# ---- the last-synced record ---------------------------------------------------------------------

class Record(object):
    """This machine's record for one project, live dir and bucket: normcased note name -> sha256."""

    def __init__(self, path, notes):
        self.path, self.notes = path, notes


def record_path(backup_root, project, live, bucket):
    """<backup-root>/.last-synced/<bucket name>-<16 hex of project, live dir and bucket>.json"""
    ident = "\0".join((project, norm(live), norm(bucket)))
    tag = sha(ident.encode("utf-8", "surrogateescape"))[:16]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", os.path.basename(os.path.normpath(bucket))) or "bucket"
    return os.path.join(backup_root, RECORD_DIR, "%s-%s.json" % (name, tag))


def unreadable(path, why):
    return Refusal("the last-synced record is unreadable (%s: %s)" % (path, why),
                   ["UNREADABLE RECORD: %s: %s" % (path, why),
                    "  It holds what both sides held at this machine's last sync. Read as empty, every note would "
                    "count as never synced, so the run is refused instead.",
                    "  To recover: compare this project's live notes with the bucket's by hand, then move that file "
                    "aside; the next run decides by mtime once and writes a new record."])


def read_record(path, project, live, bucket):
    """The Record, or None when there is none. Refusal when it is there but cannot be trusted."""
    if not os.path.lexists(path):
        return None
    try:
        doc = json.loads(read_bytes(path).decode("utf-8"))
    except (OSError, ValueError) as e:            # unreadable, not UTF-8, not JSON
        raise unreadable(path, "%s: %s" % (type(e).__name__, e))
    if not isinstance(doc, dict) or doc.get("format") != RECORD_FORMAT:
        raise unreadable(path, "not a %r document" % RECORD_FORMAT)
    if (doc.get("project"), doc.get("live"), doc.get("bucket")) != (project, norm(live), norm(bucket)):
        raise unreadable(path, "it records another project, live dir or bucket")
    notes = doc.get("notes")
    if not isinstance(notes, dict):
        raise unreadable(path, "no notes map")
    for k, v in notes.items():
        if not k or "/" in k or "\\" in k or not isinstance(v, str) or not SHA_RE.fullmatch(v):
            raise unreadable(path, "the entry %r is not a note name and a sha256" % k)
    return Record(path, dict(notes))


def end_state(d):
    """{normcased name: (sha256, mtime)} for the top-level notes of d, read after the run."""
    out = {}
    for k, name in scan(d)[0].items():
        p = os.path.join(d, name)
        out[k] = (sha(read_bytes(p)), os.stat(p).st_mtime)
    return out


def next_notes(record, live_end, bucket_end):
    """The record's notes after a successful run."""
    notes = dict(record.notes) if record is not None else {}
    for k in set(live_end) | set(bucket_end) | set(notes):
        lv, bk = live_end.get(k), bucket_end.get(k)
        if lv is not None and bk is not None and lv[0] == bk[0]:
            notes[k] = lv[0]                        # equal at the end of the run
        elif lv is None and bk is None:
            notes.pop(k, None)                      # gone from both sides: a later note of that name is new
        elif record is None and lv is not None and bk is not None and k != os.path.normcase(INDEX):
            # The record's first write, and the run left this note differing (an arrival keeps a newer live
            # note): the copy newer-wins ruled older is the version the newer one was edited from.
            older = bk if lv[1] > bk[1] + WINDOW else lv if bk[1] > lv[1] + WINDOW else None
            if older is not None:
                notes[k] = older[0]
        # any other note (left differing, or on one side only) keeps its entry, or has none
    return notes


def write_record(path, project, live, bucket, notes, old):
    """Through a temp file and os.replace, and only when it changes. 'written' or 'unchanged'."""
    doc = {"format": RECORD_FORMAT, "project": project, "live": norm(live), "bucket": norm(bucket),
           "notes": dict(sorted(notes.items()))}
    data = (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")
    if old is not None and os.path.isfile(path) and read_bytes(path) == data:
        return "unchanged"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    replace_via_temp(path, data=data)
    return "written"


# ---- the plan -----------------------------------------------------------------------------------

class Item(object):
    __slots__ = ("name", "src", "dst", "cls", "action", "why", "seen")

    def __init__(self, name, src, dst, cls, action, why=""):
        self.name, self.src, self.dst, self.cls, self.action, self.why = name, src, dst, cls, action, why
        self.seen = None           # for a COPY: the destination's state() when the plan was made


def stamp(t):
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def classify(name, src, dst, direction):
    """One note present on both sides."""
    if read_bytes(src) == read_bytes(dst):
        return Item(name, src, dst, EQUAL, SKIP)
    smt, dmt = os.stat(src).st_mtime, os.stat(dst).st_mtime
    when = "source %s, destination %s" % (stamp(smt), stamp(dmt))
    if smt > dmt + WINDOW:
        return Item(name, src, dst, SOURCE_NEWER, COPY, when)
    if dmt > smt + WINDOW:
        # arrival: the newer live note is this machine's unsent work; departure: the other machine's
        return Item(name, src, dst, DEST_NEWER, STOP if direction == "departure" else KEEP, when)
    return Item(name, src, dst, CONFLICT, STOP, "bytes differ, mtimes within %d s: %s" % (WINDOW, when))


def against_record(name, src, dst, has_src, has_dst, direction, base):
    """A note judged against this machine's last-synced hash `base` (None: the record has no entry for it).

    Only called for a note in the record, or for one on both sides: a note on one side only that is not in
    the record is SOURCE-ONLY / DEST-ONLY, as without a record."""
    s = sha(read_bytes(src)) if has_src else None
    d = sha(read_bytes(dst)) if has_dst else None
    if has_src and has_dst:
        if s == d:
            return Item(name, src, dst, EQUAL, SKIP)
        if base is None:
            two = Item(name, src, dst, CONFLICT, STOP, "on both sides with different bytes, and this machine's "
                       "last-synced record never saw them equal: two separate creations")
            return two
        if s == base:  # only the destination changed since the last sync
            keep = KEEP if direction == "arrival" else STOP
            return Item(name, src, dst, DEST_CHANGED, keep, "changed at the destination since the last sync; the "
                        "source's copy did not change")
        if d == base:  # only the source changed since the last sync
            return Item(name, src, dst, SOURCE_CHANGED, COPY, "changed at the source since the last sync")
        both = Item(name, src, dst, CONFLICT, STOP, "both sides changed since the last sync")
        return both
    live_has = has_dst if direction == "arrival" else has_src
    gone = DELETED_IN_BUCKET if live_has else DELETED_HERE
    where = "from the bucket" if live_has else "on this machine"
    if has_src:                # the destination lacks it
        if s == base:  # a deletion at the destination: named, never copied back
            return Item(name, src, dst, gone, SKIP,
                        "deleted %s since the last sync; not copied back: deletions are not propagated" % where)
        return Item(name, src, dst, EDITED_AFTER_DELETE, COPY,
                    "deleted %s since the last sync, but the source's copy changed since: copied so that edit "
                    "is not lost; nothing is there to overwrite" % where)
    if d == base:  # a deletion at the source: the destination's copy stays
        return Item(name, None, dst, gone, KEEP,
                    "deleted %s since the last sync; this copy is kept: deletions are not propagated" % where)
    return Item(name, None, dst, EDITED_AFTER_DELETE, KEEP,
                "deleted %s since the last sync, but this copy changed since; kept, and the next run in the "
                "other direction carries it across" % where)


class IndexPlan(object):
    def __init__(self, mode, dst, data=None, src=None, report=None, dangling=()):
        self.mode = mode          # "none", "equal", "superset", "merge", "copy", "keep"
        self.dst, self.data, self.src = dst, data, src
        self.report = report or []
        self.dangling = list(dangling)
        self.seen = None          # for a write: the destination's state() when the plan was made

    @property
    def writes(self):
        return self.mode in ("merge", "copy")


class Plan(object):
    def __init__(self, direction, src, dst):
        self.direction, self.src, self.dst = direction, src, dst
        self.items = []
        self.index = None
        self.src_other = self.dst_other = 0
        self.owner_line = None
        self.claim = None          # the project name a departure claims an unmarked empty bucket for
        self.record = None         # this machine's last-synced Record, or None when it has none
        self.record_path = None

    def of(self, *classes):
        return [i for i in self.items if i.cls in classes]

    @property
    def stops(self):
        return [i for i in self.items if i.action == STOP]

    @property
    def copies(self):
        return [i for i in self.items if i.action == COPY]


def make_plan(direction, src, dst, record=None):
    plan = Plan(direction, src, dst)
    plan.record = record
    s_notes, plan.src_other = scan(src, skip=(OWNER,) if direction == "arrival" else ())
    d_notes, plan.dst_other = scan(dst, skip=(OWNER,) if direction == "departure" else ())
    ikey = os.path.normcase(INDEX)
    for key in sorted(set(s_notes) | set(d_notes)):
        if key == ikey:
            continue
        sname, dname = s_notes.get(key), d_notes.get(key)
        spath = os.path.join(src, sname) if sname else None
        dpath = os.path.join(dst, dname or sname)
        if record is not None and (key in record.notes or (sname and dname)):
            item = against_record(dname or sname, spath, dpath, sname is not None, dname is not None, direction,
                                  record.notes.get(key))
        elif sname is None:
            item = Item(dname, None, os.path.join(dst, dname), DEST_ONLY, KEEP)
        elif dname is None:
            item = Item(sname, os.path.join(src, sname), os.path.join(dst, sname), SOURCE_ONLY, COPY)
        else:
            item = classify(dname, os.path.join(src, sname), os.path.join(dst, dname), direction)
        if item.action == COPY:
            item.seen = state(item.dst)
        plan.items.append(item)
    copied = set(os.path.normcase(i.name) for i in plan.copies)
    present = (set(d_notes) | copied) - {ikey}
    plan.index = plan_index(src, dst, s_notes.get(ikey), d_notes.get(ikey), copied, present)
    return plan


# ---- the MEMORY.md merge ------------------------------------------------------------------------

def split_lines(text):
    return re.findall(r"[^\n]*\n|[^\n]+$", text)


def entry_key(line):
    m = ENTRY_RE.match(line.lstrip("﻿"))
    return m.group(1).strip() if m else None


def note_of(target):
    """The top-level note name a link target points at, normcased, or None."""
    t = unquote(target.split("#", 1)[0].strip().strip("<>"))
    if t.startswith("./"):
        t = t[2:]
    if not t or "/" in t or "\\" in t or ":" in t:
        return None
    return os.path.normcase(t)


def exists_after(target, dst, present):
    t = target.split("#", 1)[0].strip().strip("<>")
    if not t or "://" in t or t.startswith("mailto:"):
        return True
    n = note_of(target)
    if n is not None:
        return n in present or n == os.path.normcase(INDEX)
    return os.path.exists(os.path.join(dst, unquote(t[2:] if t.startswith("./") else t)))


def body(line):
    return line.rstrip("\r\n")


def ending(line):
    return line[len(body(line)):]


def merge_index(sdata, ddata, copied, dst, present):
    """(merged bytes, report lines, dangling targets). The result starts from the destination."""
    st = sdata.decode("utf-8", "surrogateescape")
    dt = ddata.decode("utf-8", "surrogateescape")
    nl = "\r\n" if "\r\n" in dt else "\n"
    s_lines, d_lines = split_lines(st), split_lines(dt)

    s_order, s_text, s_other = [], {}, []
    for ln in s_lines:
        k = entry_key(ln)
        if k is None:
            if ln.strip():
                s_other.append(ln.strip())
        elif k not in s_text:
            s_text[k] = body(ln)
            s_order.append(k)

    out, d_keys, dups, replaced = [], set(), [], 0
    for ln in d_lines:
        k = entry_key(ln)
        if k is not None:
            if k in d_keys:
                dups.append(k)
            d_keys.add(k)
            if k in s_text and note_of(k) in copied and body(ln) != s_text[k]:
                ln = s_text[k] + ending(ln)        # the line follows the note that won
                replaced += 1
        out.append(ln)  # every destination line is kept, an entry included

    def position(key):
        for i, ln in enumerate(out):
            if entry_key(ln) == key:
                return i
        return None

    def last_entry():
        for i in range(len(out) - 1, -1, -1):
            if entry_key(out[i]) is not None:
                return i
        return None

    added = 0
    for i, k in enumerate(s_order):
        if k in d_keys:
            continue
        at = None
        for j in range(i - 1, -1, -1):
            at = position(s_order[j])
            if at is not None:
                break
        if at is None:
            at = last_entry()
        line = s_text[k] + nl
        if at is None:
            if out and not out[-1].endswith("\n"):
                out[-1] += nl
            out.append(line)
        else:
            if not out[at].endswith("\n"):
                out[at] += nl
            out.insert(at + 1, line)
        d_keys.add(k)
        added += 1

    d_stripped = set(ln.strip() for ln in d_lines)
    s_only_other = [x for x in s_other if x not in d_stripped]
    merged = "".join(out).encode("utf-8", "surrogateescape")

    report = ["INDEX %s: %d dest lines kept, +%d source lines added%s"
              % (INDEX, len(d_lines), added, ", %d replaced by the copied note's line" % replaced if replaced else "")]
    if s_only_other:
        report.append("INDEX   %d source-only non-entry line(s) not merged (headings/prose), e.g. %r"
                      % (len(s_only_other), s_only_other[0][:80]))
    if dups:
        report.append("INDEX   %d duplicate link target(s) already in the destination index, left as they are: %s"
                      % (len(dups), ", ".join(sorted(set(dups)))))
    dangling = [k for k in (entry_key(ln) for ln in out) if k is not None and not exists_after(k, dst, present)]
    return merged, report, dangling


def plan_index(src, dst, sname, dname, copied, present):
    if sname is None and dname is None:
        return IndexPlan("none", None)
    if sname is None:
        return IndexPlan("keep", os.path.join(dst, dname),
                         report=["INDEX %s: none at the source; the destination's is kept" % INDEX])
    spath = os.path.join(src, sname)
    if dname is None:
        ix = IndexPlan("copy", os.path.join(dst, sname), src=spath,
                       report=["COPY %s %s (no index at the destination)" % (SOURCE_ONLY, sname)])
        ix.seen = state(ix.dst)
        return ix
    dpath = os.path.join(dst, dname)
    sdata, ddata = read_bytes(spath), read_bytes(dpath)
    if sdata == ddata:
        return IndexPlan("equal", dpath)
    merged, report, dangling = merge_index(sdata, ddata, copied, dst, present)
    if merged == ddata:
        report[0] += " -- the destination already holds every source entry; not written"
        return IndexPlan("superset", dpath, report=report, dangling=dangling)
    ix = IndexPlan("merge", dpath, data=merged, report=report, dangling=dangling)
    ix.seen = sha(ddata)
    return ix


# ---- writing ------------------------------------------------------------------------------------

class Backups(object):
    """<root>/<bucket name>/<UTC stamp>/, created on the first overwrite."""

    def __init__(self, root, bucket_name):
        self.base = os.path.join(root, bucket_name)
        self.dir = None
        self.saved = []

    def save(self, path):
        if self.dir is None:
            now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            cand, n = os.path.join(self.base, now), 0
            while True:
                try:
                    os.makedirs(cand)
                    break
                except FileExistsError:
                    n += 1
                    cand = os.path.join(self.base, "%s-%d" % (now, n))
            self.dir = cand
        target = os.path.join(self.dir, os.path.basename(path))
        shutil.copy2(path, target)
        if read_bytes(target) != read_bytes(path):
            raise IOError("backup of %s does not match its bytes; nothing overwritten" % path)
        self.saved.append(target)
        return target


class DestinationChanged(Exception):
    """The destination is no longer what the plan saw (a sync client wrote it mid-run): abort, nothing more."""

    def __init__(self, path, seen, now):
        Exception.__init__(self, "%s changed at the destination after the plan was made (the plan saw %s, now %s); "
                           "it was not overwritten and nothing further was written"
                           % (os.path.basename(path), describe(seen), describe(now)))


def describe(st):
    return "no file" if st is None else "something that is not a note" if st == NOT_A_FILE else "sha256 " + st[:12]


def midrun_hook(path):
    """TEST-ONLY (tests/test-bucket-sync.py R3): when BUCKET_SYNC_TEST_MIDRUN_WRITE names this destination's note,
    write MIDRUN_BYTES to it here, between the plan and its write, as a download landing mid-run would."""
    name = os.environ.get(MIDRUN_ENV)
    if name and os.path.normcase(os.path.basename(path)) == os.path.normcase(name):
        with open(path, "wb") as f:
            f.write(MIDRUN_BYTES)


def recheck(path, seen):
    """Immediately before a write: the destination must still be what the plan saw."""
    midrun_hook(path)
    now = state(path)
    if now != seen:
        raise DestinationChanged(path, seen, now)


def install(dst_path, backups, seen, src_path=None, data=None):
    """Re-check the destination against the plan, back it up (byte-compared), then write through a temp file."""
    recheck(dst_path, seen)
    if os.path.lexists(dst_path):
        backups.save(dst_path)
    replace_via_temp(dst_path, src_path=src_path, data=data)


def replace_via_temp(dst_path, src_path=None, data=None):
    """New bytes (a copy of src_path, or data) to a temp file in the destination's dir, then os.replace."""
    fd, tmp = tempfile.mkstemp(prefix=".bucket-sync-", suffix=".tmp", dir=os.path.dirname(dst_path))
    try:
        if data is None:
            os.close(fd)
            shutil.copy2(src_path, tmp)            # copy2 keeps the source mtime for the next comparison
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        os.replace(tmp, dst_path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def apply_plan(plan, backups):
    written = []
    try:
        if plan.claim is not None:                 # the claim is the first write, so a later failure leaves it
            written.append(write_marker(plan.dst, plan.claim))
        for item in plan.copies:
            install(item.dst, backups, item.seen, src_path=item.src)
            written.append(item.dst)
        ix = plan.index
        if ix is not None and ix.writes:
            if ix.mode == "copy":
                install(ix.dst, backups, ix.seen, src_path=ix.src)
            else:
                install(ix.dst, backups, ix.seen, data=ix.data)
            written.append(ix.dst)
    except Exception as e:
        raise ApplyError(e, written)
    return written


# ---- output -------------------------------------------------------------------------------------

def print_plan(plan):
    print("bucket-sync %s: %s -> %s" % (plan.direction, plan.src, plan.dst))
    if plan.owner_line:
        print(plan.owner_line)
    if plan.claim is not None:
        print("CLAIM %s (project: %s) -- the first write of this departure" % (OWNER, plan.claim))
    if plan.record is None:
        print("RECORD none: this machine has no last-synced record for this live dir and bucket (%s), so notes that "
              "differ are decided by the newer-wins rule (mtime); a successful run writes one" % plan.record_path)
    else:
        print("RECORD %s: %d note(s) as last synced on this machine; a note that differs is judged by which side "
              "changed since" % (plan.record.path, len(plan.record.notes)))
    for i in plan.items:
        if i.cls == EQUAL:
            continue
        why = " (%s)" % i.why if i.why else ""
        if i.action == COPY:
            note = " (destination backed up first)" if i.cls in (SOURCE_NEWER, SOURCE_CHANGED) else ""
            print("COPY %s %s%s" % (i.cls, i.name, why if i.cls == EDITED_AFTER_DELETE else note))
        else:
            print("%s %s %s%s" % (i.action, i.cls, i.name, why))
    ix = plan.index
    if ix is not None:
        for ln in ix.report:
            print(ln)
        for t in ix.dangling:
            print("DANGLING %s (a %s entry; no such note at the destination after this sync; left alone)" % (t, INDEX))
    print("out of scope (never read or written): source %d, destination %d -- subdirectories, non-.md files, *.bak; "
          "the bucket's %s marker is not counted here: it is read for ownership and never copied"
          % (plan.src_other, plan.dst_other, OWNER))


def counts(plan):
    c = {k: len(plan.of(k)) for k in (SOURCE_ONLY, EQUAL, SOURCE_NEWER, DEST_NEWER, CONFLICT, DEST_ONLY,
                                      SOURCE_CHANGED, DEST_CHANGED, DELETED_HERE, DELETED_IN_BUCKET)}
    c["copied-after-delete"] = len([i for i in plan.copies if i.cls == EDITED_AFTER_DELETE])
    c["kept-after-delete"] = len(plan.of(EDITED_AFTER_DELETE)) - c["copied-after-delete"]
    return c


def index_word(plan):
    ix = plan.index
    if ix is None or ix.mode == "none":
        return "no index"
    return {"equal": "index equal", "superset": "index unchanged (already a superset)", "keep": "index kept",
            "copy": "index copied (none at the destination)", "merge": "index merged"}[ix.mode]


def summary(plan):
    c = counts(plan)
    claimed = "bucket claimed for project '%s', " % plan.claim if plan.claim is not None else ""
    more_copied = "".join(", %d %s" % (n, k) for k, n in (("source-changed", c[SOURCE_CHANGED]),
                                                          ("edited-after-delete", c["copied-after-delete"])) if n)
    more_named = "".join(", %d %s" % (n, k) for k, n in (("kept dest-changed", c[DEST_CHANGED]),
                                                         ("kept edited-after-delete", c["kept-after-delete"]),
                                                         ("deleted-here named", c[DELETED_HERE]),
                                                         ("deleted-in-bucket named", c[DELETED_IN_BUCKET])) if n)
    return ("%s%d copied (%d source-only, %d source-newer%s), %s, %d equal, %d kept dest-newer, %d kept dest-only%s"
            % (claimed, len(plan.copies), c[SOURCE_ONLY], c[SOURCE_NEWER], more_copied, index_word(plan),
               c[EQUAL], c[DEST_NEWER], c[DEST_ONLY], more_named))


def arrival_line(a):
    cmd = "python %s --direction arrival --live %s --bucket %s --project %s" % (
        q(os.path.abspath(__file__)), q(os.path.abspath(a.live)), q(os.path.abspath(a.bucket)), q(a.project))
    if a.backup_root:
        cmd += " --backup-root %s" % q(os.path.abspath(a.backup_root))
    return cmd


def report_stop(plan, a):
    newer, conflicts = plan.of(DEST_NEWER, DEST_CHANGED), plan.of(CONFLICT)
    print("STOP: nothing was written.")
    if a.direction == "departure":
        if newer:
            print("  %d bucket note(s) hold a change this machine has not received: the other machine departed "
                  "after this machine's last arrival. Run the arrival first, then this departure again:" % len(newer))
        else:
            print("  The arrival stops on the same CONFLICT(s), writing nothing; it is printed for the step that "
                  "runs it:")
        print("  ARRIVAL FIRST: %s" % arrival_line(a))
    if conflicts:
        print("  %d CONFLICT(s): both sides changed these notes (%s); an arrival stops on them too. Report the named "
              "files to the owner: make the two copies equal by hand, then sync again."
              % (len(conflicts), "since this machine's last sync" if plan.record is not None
                 else "within %d s of each other" % WINDOW))
    print("RESULT: bucket-sync %s STOP -- nothing written: %d dest-newer or dest-changed, %d conflict"
          % (a.direction, len(newer) if a.direction == "departure" else 0, len(conflicts)))


# ---- main ---------------------------------------------------------------------------------------

def bad_name(name):
    return not name or name != name.strip() or "\n" in name or "\r" in name


def run_claim(a):
    """--claim: write only the bucket's marker. Same name already recorded = nothing to do; another = refused."""
    path = os.path.join(a.bucket, OWNER)
    try:
        if not os.path.isdir(a.bucket):
            raise Refusal("the bucket is not an existing directory: %s" % a.bucket)
        refuse_if_retired(a.bucket)
        rec = read_owner(a.bucket)
        if rec is not None and rec != a.project:
            raise Refusal("%s records project '%s', not '%s'; a claim never replaces another project's marker"
                          % (path, rec, a.project))
    except Refusal as e:
        for ln in e.lines:
            print(ln)
        print("RESULT: bucket-sync claim REFUSED -- %s; nothing written" % e)
        return EXIT_REFUSED
    print("bucket-sync claim: %s (%d top-level *.md file(s); none is read or written)"
          % (a.bucket, len(scan(a.bucket)[0])))
    if rec == a.project:
        print("RESULT: bucket-sync claim nothing to do -- %s already records project: %s" % (path, rec))
        return EXIT_OK
    if a.dry_run:  # --claim --dry-run
        print("RESULT: bucket-sync claim dry-run -- nothing written; would write %s (project: %s)" % (path, a.project))
        return EXIT_OK
    try:
        write_marker(a.bucket, a.project)
    except Exception as e:  # noqa: BLE001 -- report it; the temp file is already removed
        print("RESULT: bucket-sync claim ERROR -- %r; nothing written" % e)
        return EXIT_ERROR
    print("RESULT: bucket-sync claim claimed -- wrote %s (project: %s); no note touched" % (path, a.project))
    return EXIT_OK


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="bucket-sync.py",
        description="Sync a project's live memory dir with its out-of-band bucket, plan first, then apply; "
                    "or, with --claim, record the project that owns the bucket.")
    ap.add_argument("--direction", choices=("arrival", "departure"),
                    help="arrival: bucket -> live; departure: live -> bucket (required for a sync run)")
    ap.add_argument("--live", help="the live memory dir (the probe's live-memory-dir:; required for a sync run)")
    ap.add_argument("--bucket", required=True, help="the bucket dir (the probe's bucket-match: path)")
    ap.add_argument("--project",
                    help="this project's name (the probe's project-name:); the bucket's %s must record it" % OWNER)
    ap.add_argument("--claim", action="store_true",
                    help="write only the bucket's %s for --project (no --direction, --live or --backup-root)" % OWNER)
    ap.add_argument("--dry-run", action="store_true", help="print the plan and write nothing")
    ap.add_argument("--backup-root", default=None,
                    help="where overwritten files are backed up (default ~/.claude/bucket-sync-backups)")
    a = ap.parse_args(argv)
    if a.claim:
        extra = [f for f, v in (("--direction", a.direction), ("--live", a.live), ("--backup-root", a.backup_root))
                 if v is not None]
        if extra:
            ap.error("--claim takes only --project, --bucket and --dry-run (got %s)" % ", ".join(extra))
        if a.project is None:
            ap.error("--claim needs --project NAME")
    else:
        missing = [f for f, v in (("--direction", a.direction), ("--live", a.live), ("--project", a.project))
                   if v is None]
        if missing:
            ap.error("a sync run needs %s" % ", ".join(missing))
    if bad_name(a.project):
        ap.error("--project must be a non-empty name with no surrounding whitespace and no line break")
    if a.claim:
        return run_claim(a)

    backup_root = os.path.expanduser(a.backup_root or DEFAULT_BACKUP_ROOT)
    src, dst = (a.bucket, a.live) if a.direction == "arrival" else (a.live, a.bucket)

    rpath = record_path(backup_root, a.project, a.live, a.bucket)
    try:
        refuse_if_unsafe(a.live, a.bucket, backup_root)
        owner_line, claims = check_owner(a.bucket, a.project, a.direction)
        record = read_record(rpath, a.project, a.live, a.bucket)
    except Refusal as e:
        for ln in e.lines:
            print(ln)
        print("RESULT: bucket-sync %s REFUSED -- %s; nothing written" % (a.direction, e))
        return EXIT_REFUSED

    try:
        plan = make_plan(a.direction, src, dst, record)
    except Exception as e:  # noqa: BLE001 -- reading failed before any write
        print("RESULT: bucket-sync %s ERROR -- %r while planning; files already written: none" % (a.direction, e))
        return EXIT_ERROR
    plan.owner_line = owner_line
    plan.record_path = rpath
    if claims:
        plan.claim = a.project
    print_plan(plan)

    if plan.stops:
        report_stop(plan, a)
        return EXIT_STOP
    if a.dry_run:
        print("RESULT: bucket-sync %s dry-run -- nothing written; would apply: %s" % (a.direction, summary(plan)))
        return EXIT_OK

    backups = Backups(backup_root, os.path.basename(os.path.normpath(a.bucket)))
    verdict = "synced"
    if plan.claim is None and not plan.copies and not (plan.index is not None and plan.index.writes):
        verdict = "nothing to do"
    else:
        try:
            apply_plan(plan, backups)
        except ApplyError as e:
            cause = str(e.cause) if isinstance(e.cause, DestinationChanged) else repr(e.cause)
            print("RESULT: bucket-sync %s ERROR -- %s; files already written: %s; backups: %s"
                  % (a.direction, cause, ", ".join(e.written) or "none", backups.dir or "none"))
            return EXIT_ERROR
    # only a run that completed: what both sides hold equal now is what this machine last synced
    try:
        notes = next_notes(record, end_state(a.live), end_state(a.bucket))
        rec = "last-synced record %s" % write_record(rpath, a.project, a.live, a.bucket, notes, record)
    except Exception as e:  # noqa: BLE001 -- the sync itself is done; say the record is not
        print("RESULT: bucket-sync %s ERROR -- %s (%s), but the last-synced record %s could not be written (%r); the "
              "next run compares against the previous record, or decides by mtime if there was none; backups: %s"
              % (a.direction, verdict, summary(plan), rpath, e, backups.dir or "none"))
        return EXIT_ERROR
    if verdict == "nothing to do":
        print("RESULT: bucket-sync %s nothing to do: %s; %s" % (a.direction, summary(plan), rec))
    else:
        print("RESULT: bucket-sync %s synced: %s; backups: %s; %s"
              % (a.direction, summary(plan), backups.dir or "none", rec))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
