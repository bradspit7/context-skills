#!/usr/bin/env python
"""land-build.py -- land a build helper's branch on the main checkout in one command, byte-checked.

A build helper (reflect-upgrades Step 5) returns a branch in its own linked worktree. Landing it by hand
is seven steps every session retyped, and prose fixed one hole at a time. Measured: the build's own test
was the only one run, so an estate lint its new test tripped stayed red; and the pre-commit byte check
`git diff --quiet <branch> -- <paths>` exits 1 on IDENTICAL bytes while the new files are not yet added
(git reads an untracked path as deleted). This does the whole step and checks against the COMMIT.

  python land-build.py <worktree> --item "<queue title>" --subject "<commit subject>"
                       --upgrade "<one plain sentence>" (--verify "<command>" | --no-verify)
                       [--body-file F] [--trailer "Key: value" ...] [--queue FILE] [--repo <checkout>]
                       [--no-codex-review | --codex-wait-min N] [--dry-run]

Run it from the main checkout (or name it with --repo). In order:
  1. resolves the worktree's branch and its main checkout (the first entry of `git worktree list`), and
     REFUSES, changing nothing, when: this does not run in that main checkout; the worktree is not a
     registered linked worktree with a branch, or holds uncommitted or untracked files (removing it would
     lose them); the branch holds nothing main's HEAD lacks; a path the branch changed (against the
     merge-base with HEAD) was also changed on main since that merge-base (overlap: the paths are named);
     the main checkout has uncommitted or untracked changes in any path the landing touches; the queue
     file does not hold exactly ONE heading `## YYYY-MM-DD · <item>` (an exact title, not a substring);
     or the branch edits the queue or the entry's partial files itself. A main that moved on OTHER files
     is fine; a sibling session's staged work in other paths stays staged and out of the commit;
  2. brings the branch's added, modified and deleted paths over from the branch's COMMITTED tree
     (`git restore --source=<tip> --staged --worktree`, `git rm` for deletions; renames are a deletion
     plus an addition);
  3. removes the queue entry byte-level (line endings untouched); when it carries a
     `- **Partial:** <patch> at <base>` bullet (park-worktree.py), removes that patch and its .base too;
  4. commits with a pathspec (`git commit -F <msg> -- <paths>`, never a bare commit): the subject, the
     optional body, a blank line, `Upgrade: <sentence>`, then each --trailer line. A commit a hook refuses
     undoes every write and counts as a refusal;
  5. checks the COMMIT: one new commit on the old HEAD, holding exactly the landed paths; every landed
     path equal to the branch tip (`git diff --quiet <tip> HEAD -- <path>`), every deleted one absent
     from HEAD, the queue blob equal to the edited bytes in the form git stores them (their eol conversion
     applied: under core.autocrlf=true a CRLF checkout commits an LF blob, and a CRLF blob stays as it is). On
     any difference it stops loudly and keeps the worktree and branch;
  6. removes the worktree (`git worktree unlock` first when locked) and deletes the branch (`-D`), only
     after step 5 passed and only while the branch still points at the tip that was landed;
  7. runs the --verify command from the main checkout through the platform shell (cmd.exe on Windows,
     /bin/sh elsewhere; a bare `bash` there resolves through PATH, so on Windows run this from Git Bash,
     where that is Git's bash), its output shown as it runs, then prints and exits with its exit code.
     Pass the project's quick verify loop, not only the build's own test: cross-cutting lints scan every
     test file, so a new test can turn a DIFFERENT suite red. --no-verify must be explicit and says loudly
     that nothing was verified.
Between steps 1 and 2, on --dry-run too, it checks the worktree's PARENT: every top-level entry newer than the
worktree (the mtime of its `.git` file), skipping the worktree and any repo or worktree, is printed with its
mtime under a `PARENT CHECK WARNING` line, repeated after the verify. A helper that wrote outside its worktree
(a `../` path) leaves a file there that no `git status` sees, and removing the worktree removes the last link to
this build. It warns and never refuses (other sessions write into the same parent), stats entries without
opening or deleting any, changes no exit code, and prints `PARENT CHECK UNKNOWN` when it cannot run.
Right before step 2 it starts an external review of the branch's diff against its merge-base, in the BACKGROUND,
when your setup has a review script at `~/.claude/codex-ask.py` (no such script is one skipped line). The
script's contract: `--kind review --cwd <main checkout> --prompt-file <the diff and what it delivers>`; stdout
ending in `CODEX-ASK <call-id> <exit> answer=<path>` (or `... refused=<reason>`, its reason on stderr); exit 6
when another call holds its lock, an OS lock on byte 0 of `<run dir>/lock` over a JSON record with `started` and
`timeout_min`, `<run dir>` coming from a `codex_budget.py` beside it (`run_dir()`); an appended record in
`<run dir>/calls.jsonl` per call; and `--outcome <call-id> changed|nothing-new` to record what a call changed.
Its output goes to the folder the start line names. The prompt names the exact base and tip shas; the landing
then commits exactly that tip, byte-checked (step 5). The review never gates the landing and never changes an
exit code. A held lock (exit 6) is waited out in the background: retried whenever the call log changes (a call
ended), or every few minutes, up to the holder's own bound (its record's start + timeout_min, read past byte 0,
plus a margin), so a held lock costs a refusal record per call that ends, not one per poll. After the verify (or
a landing that stopped) it waits up to --codex-wait-min minutes (default 15; the first three review calls took 6
to 9) and prints `CODEX REVIEW RETURNED <call-id> answer=<path>` with the reviewed range and whether the landing
committed it. Returned is not adjudicated: check each point against the landed files, fix forward what holds,
tell the user in one line per disagreement, then record the outcome. A lock still held at its bound is one
`CODEX REVIEW NOT RUN` line naming the command to run it by hand; any other refusal (a budget cap, a policy) is
one `CODEX REVIEW REFUSED` line; a review still running at the bound is left running, and its line names the
file its `CODEX-ASK` line will reach; script output without that line is `CODEX REVIEW UNKNOWN`, never a clean
review. --no-codex-review skips it, for: a trivial or mechanical diff (a typo, a rename, a regenerated or reverted
file) where a review has nothing to find; a diff already reviewed this session (a re-landing after a refused
first try); or content your project's own rules keep out of an external prompt.
--dry-run runs every step-1 check, prints the plan (paths, queue entry, partial files, commit message,
the verify command, the review) and changes nothing: it starts no review.

Exit: 0 landed and the verify passed (or --no-verify); the verify's own exit code when it failed AFTER
the landing was committed and cleaned up (the output says so); 2 usage (an empty --upgrade or subject,
neither --verify nor --no-verify, a malformed --trailer); 70 refused, nothing changed (dry-run included);
71 committed, but the commit does not match the branch (the worktree and branch are kept, the verify is
not run); 72 committed and byte-checked, but the worktree or branch could not be removed (the verify is
not run); 73 the commit failed AND restoring the main checkout did not complete (the message names what
is left).
"""
import argparse
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_QUEUE = "UPGRADE-QUEUE.md"
# = PARTIAL_LEAD in park-worktree.py, which writes the bullet this reads; tests/test-land-build.py asserts they agree.
PARTIAL_LEAD = "- **Partial:** "
HEADING = re.compile(r"^## \d{4}-\d{2}-\d{2} · (.*)$")
PARTIAL = re.compile(r"^(\S+\.patch) at ([0-9a-f]{7,40})$")
TRAILER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*: \S.*$")

# The optional external review script (see the docstring for its contract).
CODEX_ASK = Path.home() / ".claude" / "codex-ask.py"
# The script's last stdout line, per its contract.
CODEX_ASK_LINE = re.compile(r"^CODEX-ASK (\S+) (\d+) (answer|refused)=(.*)$")
CODEX_WAIT_MIN = 15.0
# Past this the prompt names the changed paths instead of pasting the diff.
CODEX_DIFF_MAX = 400000
EXIT_CODEX_LOCKED = 6            # codex-ask: another Codex call holds its lock
REVIEW_CHILD = "--codex-review-child"
# A held lock is retried up to its holder's own bound: the lock record's start + timeout_min, plus what codex-ask
# may spend around the call (a fallback ping of up to 300 s and two account reads of up to 30 s each).
LOCK_MARGIN_S = 360
LOCK_WAIT_FALLBACK_S = 50 * 60   # no readable lock record: codex-ask's default 45-minute call, and its margin
LOCK_WAIT_CAP_S = 60 * 60
LOCK_HEARTBEAT_S = 180           # retry at least this often while held, besides whenever the call log changes

EXIT_USAGE = 2
EXIT_REFUSED = 70
EXIT_MISMATCH = 71
EXIT_KEPT = 72
EXIT_UNDO_FAILED = 73


class Refused(Exception):
    """Nothing was changed; the message says why."""


class Mismatch(Exception):
    """The landing is committed, but the commit does not match the branch; worktree and branch kept."""


class Kept(Exception):
    """Committed and byte-checked, but the worktree or branch could not be removed."""


class UndoFailed(Exception):
    """The commit failed and the main checkout could not be fully restored."""


def tail_text(r, lines=30):
    """The END of a failed git call's output (stdout, then stderr): its last `lines` lines, led by how many earlier
    ones it leaves out. Never a head slice: git prints a child's output (a hook's, a filter's) first and its own
    verdict last, and a hook prints its passing checks before its failing one, so a head slice keeps the passes and
    cuts the failure. Measured on a 46-check hook: the first 400 characters were all `<label> ok` lines, the
    failing check was cut off, and the last label shown read as the culprit."""
    rows = []
    for stream in (r.stdout, r.stderr):
        rows += (stream or b"").decode("utf-8", "replace").strip().splitlines()
    dropped = len(rows) - lines
    if dropped > 0:
        rows = ["... (%d earlier line%s not shown)" % (dropped, "" if dropped == 1 else "s")] + rows[-lines:]
    return "\n  ".join(rows)


def git(cwd, *args, check=True, data=None):
    """Run git with literal pathspecs; bytes out (`data`, when given, is its stdin). check=True raises Refused with
    the end of git's own output (tail_text)."""
    r = subprocess.run(["git", "--literal-pathspecs", "-C", str(cwd)] + [str(a) for a in args], input=data,
                       capture_output=True)
    if check and r.returncode:
        raise Refused("git %s failed (rc %d): %s" % (" ".join(str(a) for a in args[:3]), r.returncode, tail_text(r)))
    return r


def out(r):
    return r.stdout.decode("utf-8", "replace").strip()


def zlist(r):
    """The NUL-separated fields of a -z listing, as str."""
    try:
        return [f for f in r.stdout.decode("utf-8").split("\0") if f]
    except UnicodeDecodeError:
        raise Refused("git listed a path that is not UTF-8: land this one by hand")


def norm(p):
    return os.path.normcase(os.path.normpath(str(p).replace("\\", "/")))


def same_path(a, b):
    def real(p):
        return norm(Path(p).resolve()) if Path(p).exists() else norm(p)
    return norm(a) == norm(b) or real(a) == real(b)


def worktrees(cwd):
    """[{path, branch, locked, prunable}] from `git worktree list --porcelain`; the main checkout first."""
    recs, cur = [], None
    for ln in out(git(cwd, "worktree", "list", "--porcelain")).replace("\r", "").splitlines():
        if ln.startswith("worktree "):
            cur = {"path": ln[len("worktree "):], "branch": "", "locked": False, "prunable": ""}
            recs.append(cur)
        elif cur is None:
            continue
        elif ln.startswith("branch "):
            cur["branch"] = ln[len("branch "):].replace("refs/heads/", "", 1)
        elif ln.startswith("locked"):
            cur["locked"] = True
        elif ln.startswith("prunable"):
            cur["prunable"] = ln[len("prunable"):].strip() or "prunable"
    return recs


def split_lines(raw):
    """bytes -> lines that each keep their own "\\n" (a "\\r" stays part of its line)."""
    parts = raw.split(b"\n")
    return [p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def cut_entry(raw, item):
    """(new queue bytes, the entry's lines, [partial patch rel paths]) for the ONE heading exactly titled `item`."""
    lines = split_lines(raw)

    def title(ln):
        m = HEADING.match(ln.rstrip(b"\r\n").decode("utf-8", "replace"))
        return m.group(1) if m else None

    heads = [i for i, ln in enumerate(lines) if title(ln) == item]
    if len(heads) != 1:
        raise Refused("--item %r matches %d '## YYYY-MM-DD · <title>' headings exactly (it must match "
                      "exactly one)" % (item, len(heads)))
    h = heads[0]
    end = next((i for i in range(h + 1, len(lines)) if lines[i].startswith(b"## ")), len(lines))
    start = h
    if end == len(lines):
        # The last entry: its blank separator sits before it, not after.
        while start > 0 and not lines[start - 1].strip():
            start -= 1
    entry = lines[h:end]
    patches = []
    for ln in entry[1:]:
        text = ln.rstrip(b"\r\n").decode("utf-8", "replace")
        if not text.startswith(PARTIAL_LEAD):
            continue
        m = PARTIAL.match(text[len(PARTIAL_LEAD):].strip())
        rel = PurePosixPath(m.group(1)) if m else None
        if rel is None or rel.is_absolute() or ".." in rel.parts or ":" in m.group(1):
            raise Refused("the entry's Partial bullet does not read '<patch inside the checkout> at <base>': %s" % text)
        patches.append(rel.as_posix())
    return b"".join(lines[:start] + lines[end:]), entry, patches


def blob_ids(top, rel, data):
    """The blob ids a commit of `data`, written at `rel`, can hold: the bytes as they are, and the bytes through
    rel's clean filters and eol conversion (core.autocrlf, .gitattributes), the form `git add` stores. Under
    core.autocrlf=true with no eol attribute a CRLF checkout of an LF queue commits the converted form; a blob that
    already holds CRLF is committed as it is (the index's safer-autocrlf rule, which `hash-object --path` does not
    apply, so the converted form alone would refuse it)."""
    ids = set()
    for how in (["--no-filters"], ["--path", rel]):
        r = git(top, "hash-object", "--stdin", *how, check=False, data=data)
        if r.returncode == 0 and out(r):
            ids.add(out(r))
    return ids


def message(a):
    parts = [a.subject.strip()]
    if a.body_file:
        body = Path(a.body_file).read_bytes().decode("utf-8").replace("\r\n", "\n").strip("\n")
        if body:
            parts.append(body)
    parts.append("\n".join(["Upgrade: " + a.upgrade.strip()] + [t.strip() for t in a.trailer]))
    return "\n\n".join(parts) + "\n"


def plan(a):
    """Every check; nothing changed. Returns what the landing needs."""
    here = Path(out(git(a.repo or os.getcwd(), "rev-parse", "--show-toplevel")))
    target = Path(a.worktree)
    if not target.is_dir():
        raise Refused("%s is not a directory" % target)
    recs = worktrees(target)
    top = Path(recs[0]["path"])
    if not same_path(here, top):
        raise Refused("run this from the main checkout %s (or pass --repo %s); it runs in %s" % (top, top, here))
    if same_path(target, top):
        raise Refused("%s is the main checkout, not a build worktree" % target)
    rec = next((r for r in recs[1:] if same_path(r["path"], target)), None)
    if rec is None:
        raise Refused("%s is not a worktree registered to %s" % (target, top))
    wt = Path(rec["path"])
    if rec["prunable"]:
        raise Refused("%s is prunable (%s): nothing left to land" % (wt, rec["prunable"]))
    if not rec["branch"]:
        raise Refused("%s has a detached HEAD: land a branch" % wt)
    branch = rec["branch"]
    tip = out(git(top, "rev-parse", "--verify", "refs/heads/%s^{commit}" % branch))
    dirty_wt = out(git(wt, "status", "--porcelain", "--untracked-files=all"))
    if dirty_wt:
        raise Refused("the worktree %s has uncommitted or untracked files (removing it would lose them; commit "
                      "or delete them first):\n  %s" % (wt, "\n  ".join(dirty_wt.splitlines()[:12])))

    head = out(git(top, "rev-parse", "--verify", "HEAD"))
    on = git(top, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    if on.returncode:
        raise Refused("the main checkout %s has a detached HEAD: check its branch out first" % top)
    mb = git(top, "merge-base", head, tip, check=False)
    if mb.returncode or not out(mb):
        raise Refused("%s shares no history with HEAD %s" % (branch, head[:7]))
    base = out(mb)
    if base == tip:
        raise Refused("nothing to land: every commit on %s is already in HEAD %s" % (branch, head[:7]))
    fields = zlist(git(top, "diff", "--name-status", "--no-renames", "-z", base, tip))
    changes = list(zip(fields[0::2], fields[1::2]))
    if not changes:
        raise Refused("nothing to land: %s changes no path against its merge-base %s" % (branch, base[:7]))
    branch_paths = [p for _k, p in changes]
    main_paths = set(zlist(git(top, "diff", "--name-only", "--no-renames", "-z", base, head)))
    overlap = sorted(p for p in branch_paths if p in main_paths)
    if overlap:
        raise Refused("%d path(s) the branch changed were also changed on main since %s -- merge main into the "
                      "branch first, then land:\n  %s" % (len(overlap), base[:7], "\n  ".join(overlap)))

    qrel = PurePosixPath(a.queue.replace("\\", "/"))
    if qrel.is_absolute() or ".." in qrel.parts or ":" in a.queue:
        raise Refused("--queue must be a file inside the checkout, given relative to it: %s" % a.queue)
    queue_rel = qrel.as_posix()
    queue = top / queue_rel
    if not queue.is_file():
        raise Refused("%s does not exist" % queue)
    queue_old = queue.read_bytes()
    queue_new, entry, patches = cut_entry(queue_old, a.item)
    partial_paths = []
    for rel in patches:
        for p in (rel, PurePosixPath(rel).with_suffix(".base").as_posix()):
            if git(top, "cat-file", "-e", "HEAD:" + p, check=False).returncode == 0:
                partial_paths.append(p)
            elif (top / p).exists():
                raise Refused("the Partial file %s exists but is not committed: commit or delete it first" % p)
    own = [p for p in [queue_rel] + partial_paths if p in branch_paths]
    if own:
        raise Refused("the branch edits %s itself; the landing owns the queue entry and its partial files"
                      % ", ".join(own))

    landed = [p for k, p in changes if k != "D"]
    deleted = [p for k, p in changes if k == "D"]
    paths = landed + deleted + [queue_rel] + partial_paths
    dirty = zlist(git(top, "status", "--porcelain", "-z", "--untracked-files=all", "--", *paths))
    if dirty:
        raise Refused("the main checkout has uncommitted or untracked changes in a path this landing touches:"
                      "\n  %s" % "\n  ".join(dirty[:12]))
    return {"top": top, "wt": wt, "rec": rec, "branch": branch, "tip": tip, "head": head,
            "main_branch": out(on), "base": base, "changes": changes, "landed": landed, "deleted": deleted,
            "queue_rel": queue_rel, "queue_old": queue_old, "queue_new": queue_new, "entry": entry,
            "partial_paths": partial_paths, "paths": paths, "message": message(a)}


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def parent_unknown(why):
    print("PARENT CHECK UNKNOWN: %s -- the check could not run, so a file this build wrote outside its worktree "
          "would go unseen: look in the parent yourself before the worktree goes" % why)
    return "PARENT CHECK UNKNOWN (repeated): %s" % why


def parent_check(wt):
    """Print what changed in the worktree's PARENT since the worktree was created; return the line to repeat after
    the verify ("" when clean). It stats entries only: it never opens, moves or deletes one.

    A helper told to write only in its worktree can still write one level up (a `../` path: 2 of 3 helpers did, in
    one session), into a shared parent that is no repo, so no `git status` sees the file, and removing the
    worktree removes the only thing tying it to this build. So, before anything changes, this names every
    top-level entry of the parent newer than the worktree's creation, skipping the worktree itself and every repo
    or worktree (a `.git` file or dir). It WARNS and never refuses: other sessions write into the same parent
    while a build runs, so a stray may be theirs, and a refusal would strand a good build behind it.
    The creation time is the mtime of the worktree's own `.git` FILE, which `git worktree add` writes before its
    checkout and nothing rewrites in normal use (`git worktree repair` or `move` can): not st_ctime (change time on
    POSIX), not the admin dir's `gitdir` (documented as touched whenever the worktree is accessed) or HEAD (moves
    with every commit). Either input missing prints UNKNOWN, never clean.
    """
    wt = Path(wt)
    parent = wt.parent
    try:
        st = os.stat(wt / ".git")
    except OSError as e:
        return parent_unknown("no creation time for %s (its .git: %s)" % (wt, e.strerror or e))
    if not stat.S_ISREG(st.st_mode):
        return parent_unknown("no creation time for %s (its .git is not the file a linked worktree has)" % wt)
    born = st.st_mtime
    try:
        entries = sorted(os.scandir(parent), key=lambda x: x.name)
    except OSError as e:
        return parent_unknown("could not list %s (%s)" % (parent, e.strerror or e))
    newer, unreadable, repos, older, others = [], [], 0, 0, 0
    for e in entries:
        if os.path.normcase(e.name) == os.path.normcase(wt.name):
            continue
        others += 1
        if os.path.lexists(os.path.join(e.path, ".git")):
            repos += 1
            continue
        try:
            m = e.stat(follow_symlinks=False).st_mtime
        except OSError as err:
            unreadable.append("  %-19s  %s  (mtime UNKNOWN: %s)" % ("?", e.path, err.strerror or err))
            continue
        if m <= born:
            older += 1
            continue
        newer.append("  %s  %s%s" % (stamp(m), e.path, os.sep if e.is_dir(follow_symlinks=False) else ""))
    counts = ("%d newer, %d unreadable, %d repo/worktree skipped, %d older skipped, of %d entries besides the "
              "worktree in %s" % (len(newer), len(unreadable), repos, older, others, parent))
    listed = newer + unreadable
    if not listed:
        print("PARENT CHECK clean: nothing next to the worktree changed after it was created (%s): %s"
              % (stamp(born), counts))
        return ""
    n = "%d entr%s" % (len(listed), "y" if len(listed) == 1 else "ies")
    print("PARENT CHECK WARNING: %s next to the worktree changed after it was created (%s)%s. A build that wrote "
          "outside its worktree (a ../ path) leaves its file here, where no git status sees it, and removing the "
          "worktree removes the last link to this build; another session may own it, so this landing never opens or "
          "deletes one. Look before the worktree goes: %s" % (
              n, stamp(born), " or could not be read" if unreadable else "", counts))
    for ln in listed:
        print(ln)
    return "PARENT CHECK WARNING (repeated): %s in %s changed after the worktree was created; listed above" % (
        n, parent)


def repeat_parent(p):
    """The parent check's warning again, after the verify: a long verify log would scroll the first one away."""
    if p.get("parent_note"):
        print(p["parent_note"])


def knob(name, default):
    """A number from the environment, honoured only with LAND_BUILD_TEST=1 (tests shorten the lock waits)."""
    if os.environ.get("LAND_BUILD_TEST") == "1" and os.environ.get(name):
        return float(os.environ[name])
    return default


def codex_ask_path():
    """codex-ask.py, or the stand-in a test names (LAND_BUILD_CODEX_ASK, honoured only with LAND_BUILD_TEST=1)."""
    if os.environ.get("LAND_BUILD_TEST") == "1" and os.environ.get("LAND_BUILD_CODEX_ASK"):
        return Path(os.environ["LAND_BUILD_CODEX_ASK"])
    return CODEX_ASK


def codex_run_dir(script):
    """codex-ask's run dir (its lock and call log), from the codex_budget module beside it, which codex-ask itself
    imports for that path; ~/.claude/run/codex when there is none."""
    try:
        spec = importlib.util.spec_from_file_location("codex_budget_for_land_build", str(script.parent / "codex_budget.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return str(mod.run_dir())
    except Exception:
        return str(Path.home() / ".claude" / "run" / "codex")


def review_prompt(p, a):
    """What the review is asked about (codex-ask adds its own "Review." lead): what lands, then the branch's diff."""
    top = p["top"]
    diff = git(top, "diff", "--no-color", "--no-ext-diff", p["base"], p["tip"]).stdout.decode("utf-8", "replace")
    head = ["A build is about to land on %s in this folder (%s): branch %s." % (p["main_branch"], top.name, p["branch"]),
            "Reviewed revisions: base %s (the merge-base) and candidate %s (the branch tip; the landing commits "
            "exactly its bytes and checks them)." % (p["base"], p["tip"]),
            "Commit subject: " + a.subject.strip(),
            "What it delivers: " + a.upgrade.strip(), ""]
    if len(diff) > CODEX_DIFF_MAX:
        stat = out(git(top, "diff", "--no-color", "--stat", p["base"], p["tip"]))
        return "\n".join(head + [
            "The diff is %d characters, too long to paste. The changed paths are below: once the landing commits they "
            "hold the branch's bytes in this folder, and `git show %s:<path>` reads the base." % (len(diff), p["base"]),
            "", stat]) + "\n"
    return "\n".join(head + ["The diff:", "", "```diff", diff.rstrip("\n"), "```"]) + "\n"


def detached():
    """Popen options that let the review outlive this process, and open no console window on Windows (G#85)."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def lock_deadline(run_dir, since):
    """When to stop waiting out a held lock: the holder's own bound (its lock record's start + timeout_min, read past
    byte 0, the byte the holder keeps locked) plus LOCK_MARGIN_S; with no readable record, LOCK_WAIT_FALLBACK_S after
    `since`. Never past LOCK_WAIT_CAP_S after `since`."""
    cap = since + knob("LAND_BUILD_LOCK_CAP_S", LOCK_WAIT_CAP_S)
    try:
        with open(Path(run_dir) / "lock", "rb") as fh:
            fh.seek(1)
            rec = json.loads("{" + fh.read().decode("utf-8"))
        end = float(rec["started"]) + float(rec["timeout_min"]) * 60 + knob("LAND_BUILD_LOCK_MARGIN_S", LOCK_MARGIN_S)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        end = since + LOCK_WAIT_FALLBACK_S
    return min(end, cap)


def await_lock_change(run_dir, deadline):
    """Sleep until codex-ask's call log changes (a holder ends by appending its record, then frees the lock), the
    heartbeat passes, or the deadline does. Watching the log, not retrying on a timer, keeps a held lock from costing
    a refusal record in the call log every few seconds."""
    log = Path(run_dir) / "calls.jsonl"

    def size():
        try:
            return log.stat().st_size
        except OSError:
            return -1
    mark, until = size(), min(deadline, time.time() + knob("LAND_BUILD_LOCK_HEARTBEAT_S", LOCK_HEARTBEAT_S))
    while time.time() < until:
        time.sleep(1)
        if size() != mark:
            time.sleep(2)  # the holder appends its record just before it frees the lock
            return


def review_child(d):
    """The detached review: run codex-ask, and while another Codex call holds its lock (exit 6), wait that call out
    up to its own bound. Each attempt appends to codex-ask.out / .err, so the last CODEX-ASK line is the final one."""
    d = Path(d)
    try:
        spec = json.loads((d / "review.json").read_text(encoding="utf-8"))
        argv, run_dir = spec["argv"], spec["run_dir"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        with open(d / "codex-ask.err", "ab") as fe:
            fe.write(("land-build review child: unreadable review.json (%s)\n" % e).encode("utf-8"))
        return 1
    since = time.time()
    while True:
        with open(d / "codex-ask.out", "ab") as fo, open(d / "codex-ask.err", "ab") as fe:
            rc = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=fo, stderr=fe).returncode
        if rc != EXIT_CODEX_LOCKED:
            return rc
        deadline = lock_deadline(run_dir, since)
        if time.time() >= deadline:
            return rc
        await_lock_change(run_dir, deadline)


def codex_start(p, a):
    """Start the Codex review in the background; None when none runs. It never raises: a review that cannot start
    is one line, and the landing goes on."""
    if a.no_codex_review:
        print("NO CODEX REVIEW (--no-codex-review): this landing gets no Codex review")
        return None
    script = codex_ask_path()
    if not script.is_file():
        print("CODEX REVIEW skipped: no codex-ask.py at %s -- the landing goes on without a review" % script)
        return None
    try:
        d = Path(tempfile.mkdtemp(prefix="land-build-codex-"))
        prompt = d / "prompt.md"
        prompt.write_bytes(review_prompt(p, a).encode("utf-8"))
        argv = [sys.executable, str(script), "--kind", "review", "--cwd", str(p["top"]), "--prompt-file", str(prompt)]
        (d / "review.json").write_text(json.dumps({"argv": argv, "run_dir": codex_run_dir(script)}), encoding="utf-8")
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), REVIEW_CHILD, str(d)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=str(p["top"]), **detached())
    except Exception as e:  # the review is advisory: nothing about it may stop the landing
        print("CODEX REVIEW could not start (%s: %s) -- the landing goes on without a review" % (type(e).__name__, e))
        return None
    print("CODEX REVIEW started in the background (pid %d): codex-ask.py --kind review on %s..%s; its output goes "
          "to %s" % (proc.pid, p["base"][:7], p["tip"][:7], d))
    sys.stdout.flush()
    return {"proc": proc, "dir": d, "out": d / "codex-ask.out", "err": d / "codex-ask.err", "script": script,
            "prompt": prompt}


def codex_lines(path):
    """Every `CODEX-ASK ...` line in codex-ask's stdout (one per attempt), as matches."""
    try:
        rows = Path(path).read_bytes().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    return [m for m in (CODEX_ASK_LINE.match(r.strip()) for r in rows) if m]


def last_line(path):
    try:
        rows = [r.strip() for r in Path(path).read_bytes().decode("utf-8", "replace").splitlines() if r.strip()]
    except OSError:
        return ""
    return rows[-1] if rows else ""


def codex_finish(p, a):
    """Wait up to --codex-wait-min for the review and print what the main thread needs to adjudicate it. Its
    result never changes the exit code."""
    c = p.get("codex")
    if not c:
        return
    proc = c["proc"]
    try:
        proc.wait(timeout=a.codex_wait_min * 60)
    except subprocess.TimeoutExpired:
        print("CODEX REVIEW still running after %g min (pid %d; it may be waiting out another Codex call's lock), left "
              "running in the background: when it ends, the last line of %s reads `CODEX-ASK <call-id> <exit> "
              "answer=<path>`. Read that answer, check each point against the landed files, then record: python %s "
              "--outcome <call-id> changed|nothing-new --note \"...\"" % (a.codex_wait_min, proc.pid, c["out"],
                                                                       c["script"]))
        return
    lines = codex_lines(c["out"])
    if not lines:
        print("CODEX REVIEW UNKNOWN: codex-ask exited %d without its `CODEX-ASK` line, so nothing says whether a "
              "review ran -- see %s and %s; the landing is unaffected" % (proc.returncode, c["out"], c["err"]))
        return
    m = lines[-1]
    call_id, code, how, rest = m.group(1), int(m.group(2)), m.group(3), m.group(4).strip()
    if how == "answer" and code == 0 and proc.returncode == 0:
        landed = ("the tip this landing committed, byte for byte" if p.get("byte_checked") else
                  "NOT what this landing committed (it stopped before its byte check passed)")
        print("CODEX REVIEW RETURNED %s answer=%s" % (call_id, rest))
        print("  reviewed %s..%s, %s. Returned is not adjudicated: check each point against the landed files, fix "
              "forward what holds, tell the owner one line per disagreement, then: python %s --outcome %s "
              "changed|nothing-new --note \"...\"" % (p["base"][:7], p["tip"][:7], landed, c["script"], call_id))
    elif how == "refused" and code == EXIT_CODEX_LOCKED:
        print("CODEX REVIEW NOT RUN: another Codex call held codex-ask's lock through %d attempt(s), up to that call's "
              "own time bound -- this landing has no review; to run it by hand: python %s --kind review --cwd \"%s\" "
              "--prompt-file \"%s\"" % (len(lines), c["script"], p["top"], c["prompt"]))
    elif how == "refused":
        print("CODEX REVIEW REFUSED (codex-ask exit %d): %s -- the landing is unaffected"
              % (code, last_line(c["err"]) or rest.replace("_", " ")))
    else:
        print("CODEX REVIEW FAILED %s (codex-ask exit %d, process rc %d): no usable answer; see %s -- the landing is "
              "unaffected" % (call_id, code, proc.returncode, c["err"]))


def show(p, a):
    counts = {k: sum(1 for kk, _ in p["changes"] if kk[:1] == k) for k in "AMD"}
    print("DRY RUN -- nothing changed.")
    print("would land %s (%s) onto %s (%s), merge-base %s: %d path(s), %d added, %d modified, %d deleted" % (
        p["branch"], p["tip"][:7], p["main_branch"], p["head"][:7], p["base"][:7], len(p["changes"]),
        counts["A"], counts["M"], counts["D"]))
    for kind, path in p["changes"]:
        print("  %s %s" % (kind, path))
    heading = p["entry"][0].rstrip(b"\r\n").decode("utf-8", "replace")
    print("queue: remove %r (%d line(s)) from %s" % (heading, len(p["entry"]), p["queue_rel"]))
    for path in p["partial_paths"]:
        print("partial: remove %s" % path)
    print("commit message:")
    for ln in p["message"].splitlines():
        print("  | %s" % ln)
    print("then: remove the worktree %s, delete the branch %s, %s" % (
        p["wt"], p["branch"], "run the verify: %s" % a.verify if a.verify else "run NO verify (--no-verify)"))
    print("codex review: %s" % ("none (--no-codex-review)" if a.no_codex_review else
                                "%s --kind review on the branch's diff, started before the commit in the background, "
                                "waited on up to %g min after the verify" % (codex_ask_path(), a.codex_wait_min)))
    return 0


def undo(p):
    """Put every touched path back to HEAD (they were clean before), and drop added files."""
    top = p["top"]
    in_head = [x for x in p["paths"] if git(top, "cat-file", "-e", "HEAD:" + x, check=False).returncode == 0]
    added = [x for x in p["paths"] if x not in in_head]
    problems = []
    if in_head:
        r = git(top, "restore", "--source=HEAD", "--staged", "--worktree", "--", *in_head, check=False)
        if r.returncode:
            problems.append("restore: " + tail_text(r))
    if added:
        git(top, "rm", "-q", "--cached", "--ignore-unmatch", "--", *added, check=False)
        for x in added:
            f = top / x
            f.unlink(missing_ok=True)
            d = f.parent
            while d != top and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent
    left = zlist(git(top, "status", "--porcelain", "-z", "--untracked-files=all", "--", *p["paths"], check=False))
    if problems or left:
        raise UndoFailed("the landing commit failed, and the main checkout is NOT fully restored: %s" % (
            "; ".join(problems + ["left: " + ", ".join(left[:12])] if left else problems)))


def land(p, a):
    top, tip = p["top"], p["tip"]
    tmp = Path(tempfile.mkdtemp(prefix="land-build-"))
    try:
        msgfile = tmp / "message.txt"
        msgfile.write_bytes(p["message"].encode("utf-8"))
        try:
            if p["landed"]:
                git(top, "restore", "--source=" + tip, "--staged", "--worktree", "--", *p["landed"])
            if p["deleted"]:
                git(top, "rm", "-q", "--", *p["deleted"])
            if p["partial_paths"]:
                git(top, "rm", "-q", "--", *p["partial_paths"])
            (top / p["queue_rel"]).write_bytes(p["queue_new"])
            git(top, "commit", "-q", "-F", msgfile, "--", *p["paths"])
        except Refused as e:
            undo(p)
            raise Refused("the landing commit failed, and the main checkout was restored: %s" % e)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # The byte check reads the COMMIT, never the working tree: a hook can rewrite what gets committed.
    commit = out(git(top, "rev-parse", "HEAD", check=False))
    problems = []
    parent = git(top, "rev-parse", "--verify", "-q", "HEAD^", check=False)
    if out(parent) != p["head"]:
        problems.append("HEAD's parent is %s, not the HEAD %s the landing planned on" % (out(parent)[:7] or "?",
                                                                                         p["head"][:7]))
    held = set(zlist(git(top, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "HEAD", check=False)))
    if held != set(p["paths"]):
        problems.append("the commit holds %s, not the landed paths %s" % (
            sorted(held - set(p["paths"])) or "fewer", sorted(set(p["paths"]) - held) or "more"))
    for path in p["landed"]:
        if git(top, "diff", "--quiet", tip, "HEAD", "--", path, check=False).returncode != 0:
            problems.append("%s in the commit differs from %s at %s" % (path, p["branch"], tip[:7]))
    for path in p["deleted"] + p["partial_paths"]:
        if git(top, "cat-file", "-e", "HEAD:" + path, check=False).returncode == 0:
            problems.append("%s is still in the commit" % path)
    # The queue is written with the checkout's own line endings and committed through git's eol conversion, so it
    # is compared in the form git STORES, not as working-tree bytes: under core.autocrlf=true and no eol attribute
    # the working file is CRLF and the blob LF, and a byte compare refused every correct landing (exit 71, no
    # verify; measured in two projects, 2026-10-13 and 2026-10-15). Still exact: a blob git would not store from these bytes fails.
    qblob = out(git(top, "rev-parse", "-q", "--verify", "HEAD:" + p["queue_rel"], check=False))
    if not qblob or qblob not in blob_ids(top, p["queue_rel"], p["queue_new"]):
        problems.append("the committed %s is not the edited queue byte for byte (as git stores it)" % p["queue_rel"])
    if problems:
        raise Mismatch("commit %s does not match %s (%s): %s -- the worktree %s and branch %s are kept; inspect "
                       "with git diff %s HEAD" % (commit[:7], p["branch"], tip[:7], "; ".join(problems), p["wt"],
                                                  p["branch"], tip[:7]))
    p["byte_checked"] = True  # the commit holds exactly the tip the review was handed
    counts = {k: sum(1 for kk, _ in p["changes"] if kk[:1] == k) for k in "AMD"}
    print("LANDED %s as %s on %s: %d path(s), %d added, %d modified, %d deleted; queue entry %r removed%s" % (
        p["branch"], commit[:7], p["main_branch"], len(p["changes"]), counts["A"], counts["M"], counts["D"],
        a.item, "; partial files removed: %s" % ", ".join(p["partial_paths"]) if p["partial_paths"] else ""))
    print("byte check: %d landed path(s) equal %s (%s) in the COMMITTED tree; %d deleted path(s) absent from HEAD"
          % (len(p["landed"]), p["branch"], tip[:7], len(p["deleted"]) + len(p["partial_paths"])))

    # Removal only once the commit provably holds the branch's bytes, and only the tip that was landed.
    wt = p["wt"]
    if p["rec"]["locked"]:
        r = git(top, "worktree", "unlock", wt, check=False)
        if r.returncode:
            raise Kept("could not unlock %s: %s" % (wt, tail_text(r)))
    rm = git(top, "worktree", "remove", wt, check=False)
    if rm.returncode:
        raise Kept("could not remove %s: %s" % (wt, tail_text(rm)))
    now = out(git(top, "rev-parse", "--verify", "-q", "refs/heads/" + p["branch"], check=False))
    if now != tip:
        raise Kept("%s moved to %s after %s was landed: branch kept" % (p["branch"], now[:7] or "?", tip[:7]))
    br = git(top, "branch", "-D", p["branch"], check=False)
    if br.returncode:
        raise Kept("could not delete %s: %s" % (p["branch"], tail_text(br)))
    print("removed: worktree %s, branch %s" % (wt, p["branch"]))

    if not a.verify:
        print("NO VERIFY RAN (--no-verify): the landing is committed (%s) but unverified -- run the project's "
              "verify loop yourself" % commit[:7])
        repeat_parent(p)
        return 0
    print("VERIFY: %s" % a.verify)
    sys.stdout.flush()
    sys.stderr.flush()
    verify_rc = subprocess.run(a.verify, shell=True, cwd=str(top)).returncode
    if verify_rc < 0:
        verify_rc = 128 - verify_rc
    if verify_rc:
        print("VERIFY FAILED rc %d -- the landing is already committed (%s): fix forward" % (verify_rc, commit[:7]))
    else:
        print("VERIFY PASSED rc 0")
    repeat_parent(p)
    return verify_rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [REVIEW_CHILD] and len(argv) == 2:
        return review_child(argv[1])
    ap = argparse.ArgumentParser(description="Land a build helper's branch on the main checkout in one command.")
    ap.add_argument("worktree", help="the build helper's linked worktree")
    ap.add_argument("--item", required=True, help="the queue entry's exact title (after '## YYYY-MM-DD · ')")
    ap.add_argument("--subject", required=True, help="the commit subject")
    ap.add_argument("--upgrade", required=True, help="the Upgrade: trailer's one plain sentence")
    ap.add_argument("--body-file", help="a file holding the commit body (UTF-8)")
    ap.add_argument("--trailer", action="append", default=[], help="an extra 'Key: value' trailer line, repeatable")
    v = ap.add_mutually_exclusive_group(required=True)
    v.add_argument("--verify", metavar="COMMAND", help="the project's verify loop, run from the main checkout")
    v.add_argument("--no-verify", action="store_true", help="run no verify (says so loudly)")
    ap.add_argument("--queue", default=DEFAULT_QUEUE, help="the queue file, relative to the checkout (default: %s)"
                    % DEFAULT_QUEUE)
    ap.add_argument("--repo", help="the main checkout (default: the current directory)")
    ap.add_argument("--dry-run", action="store_true", help="check everything, print the plan, change nothing")
    c = ap.add_mutually_exclusive_group()
    c.add_argument("--no-codex-review", action="store_true",
                   help="start no Codex review: for a trivial or mechanical diff, one Codex already reviewed this "
                        "session, or content the project's rules keep out of an external prompt")
    c.add_argument("--codex-wait-min", type=float, default=CODEX_WAIT_MIN, metavar="N",
                   help="after the verify, wait up to N minutes for the review (default %g; 0 waits not at all)"
                        % CODEX_WAIT_MIN)
    a = ap.parse_args(argv)
    if a.codex_wait_min < 0:
        ap.error("--codex-wait-min must be 0 or more")
    if not a.upgrade.strip() or "\n" in a.upgrade.strip():
        ap.error("--upgrade must be one non-empty line: the sentence the Upgrade: trailer records")
    if not a.subject.strip() or "\n" in a.subject.strip():
        ap.error("--subject must be one non-empty line")
    if a.verify is not None and not a.verify.strip():
        ap.error("--verify is empty: name the project's verify loop, or pass --no-verify")
    for t in a.trailer:
        if not TRAILER.match(t.strip()) or t.strip().lower().startswith("upgrade:"):
            ap.error("--trailer %r is not one 'Key: value' line (and Upgrade: comes from --upgrade)" % t)
    if a.body_file:
        try:
            body = Path(a.body_file).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            ap.error("--body-file: %s" % e)
        if re.search(r"^Upgrade:", body, re.M):
            ap.error("--body-file holds an Upgrade: line; the trailer comes from --upgrade, once")
    p = {}
    try:
        p = plan(a)
        # Before anything changes: a warning, never a refusal, and no exit code of its own.
        p["parent_note"] = parent_check(p["wt"])
        if a.dry_run:
            return show(p, a)
        # Before the commit, and never waited on here: the review never gates the landing.
        p["codex"] = codex_start(p, a)
        rc = land(p, a)
    except Refused as e:
        print("REFUSED: %s" % e)
        rc = EXIT_REFUSED
    except Mismatch as e:
        print("MISMATCH: %s" % e)
        rc = EXIT_MISMATCH
    except Kept as e:
        print("KEPT: %s -- the landing is committed and byte-checked; remove it by hand, then run the verify" % e)
        rc = EXIT_KEPT
    except UndoFailed as e:
        print("UNDO FAILED: %s" % e)
        rc = EXIT_UNDO_FAILED
    codex_finish(p, a)
    return rc


if __name__ == "__main__":
    sys.exit(main())
