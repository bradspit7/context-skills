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
means nothing is written in that run:

  SOURCE-ONLY   not at the destination                         copy                 copy
  EQUAL         same bytes                                     skip                 skip
  SOURCE-NEWER  bytes differ, source mtime > dest + 2 s        copy (backed up)     copy (backed up)
  DEST-NEWER    bytes differ, dest mtime > source + 2 s        keep, named          STOP, named
  CONFLICT      bytes differ, mtimes within 2 s                STOP, named          STOP, named
  DEST-ONLY     not at the source                              keep, named          keep, named
                                                               (arrival)            (departure)

A departure STOP means the other machine departed after this machine's last arrival: the STOP prints
the exact arrival command line, and the repair is that arrival, then the departure again.

MEMORY.md is never copied whole over an existing index; it is merged mechanically: the result starts
from the destination's file, every destination line stays, an entry's text follows the source only
when its note was copied in this run, each source-only entry goes after the nearest preceding source
entry already in the result (else after the last entry line), no two lines share a link target, a
source-only heading or prose line is named with a count and not merged, an entry whose note is absent
at the destination after the sync is named DANGLING, and an unchanged result is not written.

Every destination file is copied to <backup-root>/<bucket name>/<UTC stamp>/ and byte-compared before
it is overwritten; new bytes go to a temp file in the destination dir, then os.replace.

Exit codes: 0 synced or nothing to do; 3 STOP (nothing written); 2 refusal or usage (an ownership
refusal included); 1 an unexpected error, naming any file already written.
"""
import argparse
import datetime
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

EXIT_OK, EXIT_ERROR, EXIT_REFUSED, EXIT_STOP = 0, 1, 2, 3

SOURCE_ONLY, EQUAL, SOURCE_NEWER = "source-only", "equal", "source-newer"
DEST_NEWER, CONFLICT, DEST_ONLY = "dest-newer", "conflict", "dest-only"
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


# ---- the plan -----------------------------------------------------------------------------------

class Item(object):
    __slots__ = ("name", "src", "dst", "cls", "action", "why")

    def __init__(self, name, src, dst, cls, action, why=""):
        self.name, self.src, self.dst, self.cls, self.action, self.why = name, src, dst, cls, action, why


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


class IndexPlan(object):
    def __init__(self, mode, dst, data=None, src=None, report=None, dangling=()):
        self.mode = mode          # "none", "equal", "superset", "merge", "copy", "keep"
        self.dst, self.data, self.src = dst, data, src
        self.report = report or []
        self.dangling = list(dangling)

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

    def of(self, *classes):
        return [i for i in self.items if i.cls in classes]

    @property
    def stops(self):
        return [i for i in self.items if i.action == STOP]

    @property
    def copies(self):
        return [i for i in self.items if i.action == COPY]


def make_plan(direction, src, dst):
    plan = Plan(direction, src, dst)
    s_notes, plan.src_other = scan(src, skip=(OWNER,) if direction == "arrival" else ())
    d_notes, plan.dst_other = scan(dst, skip=(OWNER,) if direction == "departure" else ())
    ikey = os.path.normcase(INDEX)
    for key in sorted(set(s_notes) | set(d_notes)):
        if key == ikey:
            continue
        sname, dname = s_notes.get(key), d_notes.get(key)
        if sname is None:
            item = Item(dname, None, os.path.join(dst, dname), DEST_ONLY, KEEP)
        elif dname is None:
            item = Item(sname, os.path.join(src, sname), os.path.join(dst, sname), SOURCE_ONLY, COPY)
        else:
            item = classify(dname, os.path.join(src, sname), os.path.join(dst, dname), direction)
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
        return IndexPlan("copy", os.path.join(dst, sname), src=spath,
                         report=["COPY %s %s (no index at the destination)" % (SOURCE_ONLY, sname)])
    dpath = os.path.join(dst, dname)
    sdata, ddata = read_bytes(spath), read_bytes(dpath)
    if sdata == ddata:
        return IndexPlan("equal", dpath)
    merged, report, dangling = merge_index(sdata, ddata, copied, dst, present)
    if merged == ddata:
        report[0] += " -- the destination already holds every source entry; not written"
        return IndexPlan("superset", dpath, report=report, dangling=dangling)
    return IndexPlan("merge", dpath, data=merged, report=report, dangling=dangling)


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


def install(dst_path, backups, src_path=None, data=None):
    """Back the destination up (byte-compared), then write through a temp file and os.replace."""
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
            install(item.dst, backups, src_path=item.src)
            written.append(item.dst)
        ix = plan.index
        if ix is not None and ix.writes:
            if ix.mode == "copy":
                install(ix.dst, backups, src_path=ix.src)
            else:
                install(ix.dst, backups, data=ix.data)
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
    for i in plan.items:
        if i.cls == EQUAL:
            continue
        why = " (%s)" % i.why if i.why else ""
        if i.action == COPY:
            print("COPY %s %s%s" % (i.cls, i.name, " (destination backed up first)" if i.cls == SOURCE_NEWER else ""))
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
    c = {k: len(plan.of(k)) for k in (SOURCE_ONLY, EQUAL, SOURCE_NEWER, DEST_NEWER, CONFLICT, DEST_ONLY)}
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
    return ("%s%d copied (%d source-only, %d source-newer), %s, %d equal, %d kept dest-newer, %d kept dest-only"
            % (claimed, c[SOURCE_ONLY] + c[SOURCE_NEWER], c[SOURCE_ONLY], c[SOURCE_NEWER], index_word(plan),
               c[EQUAL], c[DEST_NEWER], c[DEST_ONLY]))


def arrival_line(a):
    cmd = "python %s --direction arrival --live %s --bucket %s --project %s" % (
        q(os.path.abspath(__file__)), q(os.path.abspath(a.live)), q(os.path.abspath(a.bucket)), q(a.project))
    if a.backup_root:
        cmd += " --backup-root %s" % q(os.path.abspath(a.backup_root))
    return cmd


def report_stop(plan, a):
    newer, conflicts = plan.of(DEST_NEWER), plan.of(CONFLICT)
    print("STOP: nothing was written.")
    if a.direction == "departure":
        if newer:
            print("  %d bucket note(s) are newer than this machine's copy: the other machine departed after this "
                  "machine's last arrival. Run the arrival first, then this departure again:" % len(newer))
        else:
            print("  Run the arrival first, then this departure again:")
        print("  ARRIVAL FIRST: %s" % arrival_line(a))
    if conflicts:
        print("  %d CONFLICT(s): both sides changed these notes within %d s of each other; report the named "
              "files to the owner (an arrival stops on them too)." % (len(conflicts), WINDOW))
    print("RESULT: bucket-sync %s STOP -- nothing written: %d dest-newer, %d conflict"
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

    try:
        refuse_if_unsafe(a.live, a.bucket, backup_root)
        owner_line, claims = check_owner(a.bucket, a.project, a.direction)
    except Refusal as e:
        for ln in e.lines:
            print(ln)
        print("RESULT: bucket-sync %s REFUSED -- %s; nothing written" % (a.direction, e))
        return EXIT_REFUSED

    try:
        plan = make_plan(a.direction, src, dst)
    except Exception as e:  # noqa: BLE001 -- reading failed before any write
        print("RESULT: bucket-sync %s ERROR -- %r while planning; files already written: none" % (a.direction, e))
        return EXIT_ERROR
    plan.owner_line = owner_line
    if claims:
        plan.claim = a.project
    print_plan(plan)

    if plan.stops:
        report_stop(plan, a)
        return EXIT_STOP
    if a.dry_run:
        print("RESULT: bucket-sync %s dry-run -- nothing written; would apply: %s" % (a.direction, summary(plan)))
        return EXIT_OK
    if plan.claim is None and not plan.copies and not (plan.index is not None and plan.index.writes):
        print("RESULT: bucket-sync %s nothing to do: %s" % (a.direction, summary(plan)))
        return EXIT_OK

    backups = Backups(backup_root, os.path.basename(os.path.normpath(a.bucket)))
    try:
        apply_plan(plan, backups)
    except ApplyError as e:
        print("RESULT: bucket-sync %s ERROR -- %r; files already written: %s; backups: %s"
              % (a.direction, e.cause, ", ".join(e.written) or "none", backups.dir or "none"))
        return EXIT_ERROR
    print("RESULT: bucket-sync %s synced: %s; backups: %s" % (a.direction, summary(plan), backups.dir or "none"))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
