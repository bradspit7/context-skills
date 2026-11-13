#!/usr/bin/env python
"""land-build.py -- land a build helper's branch on the main checkout in one command, byte-checked.

A build helper (reflect-upgrades Step 5) returns a branch in its own linked worktree. Landing it by hand
is seven steps every session retyped, and prose fixed one hole at a time. Measured: the build's own test
was the only one run, so an estate lint its new test tripped stayed red; and the pre-commit byte check
`git diff --quiet <branch> -- <paths>` exits 1 on IDENTICAL bytes while the new files are not yet added
(git reads an untracked path as deleted). This does the whole step and checks against the COMMIT.

  python land-build.py <worktree> (--item "<queue title>" | --no-item "<why there is no queue entry>")
                       --subject "<commit subject>" [--upgrade "<one plain sentence>"]
                       (--verify "<command>" | --no-verify) [--pre-verify "<lint command>"]
                       [--body-file F] [--trailer "Key: value" ...] [--queue FILE] [--repo <checkout>]
                       [--no-codex-review | --codex-wait-min N] [--dry-run]

--item takes the entry's title (the text after `## YYYY-MM-DD · `) or that whole heading as written,
`YYYY-MM-DD · <title>`; either must match exactly ONE heading, and --upgrade is required with it. --no-item lands
a branch that has no queue entry (a fix-forward of a landed build, a design build): no queue edit, no `Upgrade:`
trailer (--upgrade is refused with it), and every other check below kept; its one-line reason is printed.

Run it from the main checkout (or name it with --repo). In order:
  1. resolves the worktree's branch and its main checkout (the first entry of `git worktree list`), and
     REFUSES, changing nothing, when: this does not run in that main checkout; the worktree is not a
     registered linked worktree with a branch, or holds uncommitted or untracked files (removing it would
     lose them); the branch holds nothing main's HEAD lacks; a path the branch changed (against the
     merge-base with HEAD) was also changed on main since that merge-base (overlap: the paths are named);
     the main checkout has uncommitted or untracked changes in any path the landing touches; with --item,
     the queue file does not hold exactly ONE heading `## YYYY-MM-DD · <item>` (an exact title or whole
     heading, not a substring); or the branch edits the queue or the entry's partial files itself. The one
     queue edit a branch may carry is the landing's own: the --item entry deleted exactly as cutting it from
     the queue at the branch's base would (and the Partial files that entry names, deleted); that edit is
     left to the landing, which cuts the entry from main's current queue once (a helper did this "as earlier
     builds did", measured 2026-11-01). With --no-item any queue edit on the branch refuses. A main that
     moved on OTHER files is fine; a sibling session's staged work in other paths stays staged and out of
     the commit;
  2. brings the branch's added, modified and deleted paths over from the branch's COMMITTED tree
     (`git restore --source=<tip> --staged --worktree`, `git rm` for deletions; renames are a deletion
     plus an addition);
  3. removes the queue entry byte-level (line endings untouched) and stages it; when it carries a
     `- **Partial:** <patch> at <base>` bullet (park-worktree.py), removes that patch and its .base too;
  4. commits a TEMPORARY index (GIT_INDEX_FILE): main's HEAD as step 1 read it, plus each landed path exactly as
     the tip's tree holds it, mode included, minus the deleted and Partial paths, plus the staged queue; never the
     real index, so a sibling's staged work stays out, and never a pathspec commit, which re-reads the working tree
     and under core.filemode=false (Windows) lands a branch's 100755 file as 100644 (measured 2026-10-30).
     The commit is made with plumbing bound to that one HEAD: `git commit-tree -p <it>`, then `git update-ref HEAD
     <new> <it>`, a compare-and-swap. A main another session moved since step 1 is refused (exit 70) with nothing
     landed; run it again, and step 1 checks the branch against the new main. (`git commit` took HEAD as the parent
     when IT started, so a sibling's commit after the snapshot got a landing commit holding the snapshot's tree, which
     undid the sibling's change: Codex 2026-11-02.) What `git commit` gave is kept, in its order: the pre-commit hook
     on the temporary index (the tree is written after it, so a hook's own `git add` is committed), the session
     stamp's --trailer, prepare-commit-msg (`<file> message`) and commit-msg on the message file, -F's whitespace
     cleanup, author and committer from the usual config, signing when commit.gpgsign is true, the reflog entry
     `commit: <subject>`, then post-commit (its exit code ignored, as git does). Hooks run through `git hook run`
     (git 2.36 or later). What differs: the hooks get a temp message file, not .git/COMMIT_EDITMSG (which a
     sibling's commit would share); commit.cleanup is not read (always -F's default, whitespace); a message a hook
     empties is not refused; an in-progress merge's MERGE_HEAD is never made a parent; no auto-maintenance runs.
     The message: the subject, the optional body, a blank line, `Upgrade: <sentence>` (none with --no-item),
     then each --trailer line. Commands that fire hooks (hook run, update-ref, branch) run without
     --literal-pathspecs, which git would export to the hooks as GIT_LITERAL_PATHSPECS=1 (a hook's `git ls-files
     "*.py"` then matched nothing: measured 2026-10-28, 2026-11-01); a pathspec they take is `:(literal)`-prefixed
     instead. A commit a hook refuses undoes every write and counts as a refusal;
  5. checks the COMMIT: one new commit on the old HEAD, holding exactly the landed paths; every landed
     path equal to the branch tip, blob AND mode (`git diff --quiet <tip> HEAD -- <path>`; a difference names
     both modes or both blobs), every deleted one absent from HEAD, the queue blob equal to the edited bytes in
     the form git stores them (their eol conversion applied: under core.autocrlf=true a CRLF checkout commits an
     LF blob, and a CRLF blob stays as it is). On any difference it stops loudly and keeps the worktree and branch;
  6. removes the worktree (`git worktree unlock` first when locked) and deletes the branch (`-D`), only
     after step 5 passed and only while the branch still points at the tip that was landed. What could not be
     removed is a `LEFTOVER:` line naming it, the likely holder and the command that removes it (git unregisters
     a worktree before it fails on a held folder, which is then left empty: `rmdir`), repeated after the verify. A
     folder that cannot be read is a leftover too, saying why, never a removed one (only a folder that is not there
     is gone); the command unlocks first only while git still lists the worktree as locked.
     A leftover OUTSIDE the main checkout (the skill's `../<repo>-<topic>` layout), a moved branch or a branch
     git would not delete changes nothing the verify reads, so the verify still runs and its code is the exit
     code (three landings, 2026-10-27 to 2026-11-02, each skipped the gating verify over an empty folder).
     Only a worktree folder left INSIDE the main checkout stops before the verify (exit 72), which would read
     what is left of it as a second copy of the tree;
  7. runs the --verify command from the main checkout through the platform shell (cmd.exe on Windows,
     /bin/sh elsewhere; a bare `bash` there resolves through PATH, so on Windows run this from Git Bash,
     where that is Git's bash), its output shown as it runs, then prints and exits with its exit code.
     Pass the project's quick verify loop, not only the build's own test: cross-cutting lints scan every
     test file, so a new test can turn a DIFFERENT suite red. --no-verify must be explicit and says loudly
     that nothing was verified.
--pre-verify "<command>" runs the project's lint command IN THE BUILD WORKTREE, after step 1 and the parent check
and before the review and step 2, through the same platform shell as --verify.
The worktree holds the helper's commits and nothing uncommitted (step 1), so a lint that scans only the files git
tracks sees the branch's new files: run in the main checkout before the commit it could not (measured: thirteen
lints green before a helper's commit, one red after it). A non-zero exit refuses the landing with exit 74, naming
the command and showing the end of its output; nothing on main changed and the worktree and branch are kept. The
command is the project's own (for example `bash run-tests.sh --lints`); this tool hardcodes none.
After a passing pre-verify every plan check runs again: a path this landing touches edited on main meanwhile, or a
new commit on the branch, refuses with exit 70 and the edit is left as it is.
Without the flag a landing is as before and prints one `PRE-VERIFY: none` line; --dry-run names the planned one.
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
committed it. Returned is not adjudicated. The two lines after it are two CONDITIONS, the ordinary case first:
`Outside closing mode (the usual case):` check each point against the landed files, fix forward what holds, tell
the user one line per disagreement, then record the outcome; `If a wrap or departure has been requested (closing
mode):` record only the call id and the answer path, with no adjudication, fix, landing or new run (from then on
a late result supplies information and never authorizes new work). land-build cannot tell which holds, so neither
line states closing mode as the current state (the old wording led with `in closing mode (...)`, which read as a
fact at mid-session landings). A lock still held at its bound is one
`CODEX REVIEW NOT RUN` line naming the command to run it by hand; any other refusal (a budget cap, a policy) is
one `CODEX REVIEW REFUSED` line; a review still running at the bound is left running, and its line names the
file its `CODEX-ASK` line will reach (in closing mode it is recorded as running, never stopped or adjudicated);
script output without that line is `CODEX REVIEW UNKNOWN`, never a clean
review. --no-codex-review skips it, for: a trivial or mechanical diff (a typo, a rename, a regenerated or reverted
file) where a review has nothing to find; a diff already reviewed this session (a re-landing after a refused
first try); or content your project's own rules keep out of an external prompt.
--dry-run runs every step-1 check, prints the plan (paths, queue entry, partial files, commit message,
the verify command, the review) and changes nothing: it starts no review.

A git call that fails is reported by its END (a hook prints its verdict last) and, when its output is longer than
that tail, also by every earlier line matching FAIL, ERROR, `not ok`, Traceback or failed (with the few lines after
each), printed ahead of the tail, and by a file outside the repo holding its full stdout and stderr, whose path is
printed: a hook can print its failing check early and 170 passing ones after it (measured 2026-10-22, 2026-11-01).

Exit: 0 landed and the verify passed (or --no-verify), even with a LEFTOVER outside the main checkout (a
non-zero code for a passed verify would read as a failed landing to every `&&` and invite a second landing of a
committed one; the LEFTOVER line, repeated last, is how a leftover is reported); the verify's own exit code when
it failed AFTER the landing was committed (the output says so); 2 usage (an empty --upgrade or subject, --upgrade
with --no-item, neither --item nor --no-item, neither --verify nor --no-verify, a malformed --trailer); 70
refused, nothing changed (dry-run included); 71 committed, but the commit does not match the branch (the worktree
and branch are kept, the verify is not run); 72 committed and byte-checked, but the worktree's folder is left
INSIDE the main checkout (the verify is not run: it would read that folder); 73 the commit failed AND restoring
the main checkout did not complete (the message names what is left); 74 the --pre-verify command failed in the
build worktree, nothing changed; 75 the machine is short of memory, nothing changed.

MEMORY AND THE TIER LOCK (optional). Right after the step-1 checks, on --dry-run too, a landing that will run a
--verify or --pre-verify (each one a test tier, which can take a long time) reads this machine's memory headroom
through an optional module at ~/.claude/machine_load.py (LAND_BUILD_MACHINE_LOAD names another copy, honoured only
with LAND_BUILD_TEST=1). Its contract: `check_headroom(what)` returns (verdict, line), the verdict "LOW" under the
machine's floor and anything else otherwise, and `holder_line()` returns a line naming the test tier that holds a
machine-wide tier lock, or "" when none does. The line is printed as one `MEMORY:` line; on a "LOW" verdict the
landing is refused with exit 75 and nothing changed (measured: several landings' test tiers at once preceded a blue
screen). With no such module, or one that cannot be loaded or raises, it prints `MEMORY: could not be read` and the
landing goes on: a failed read never reads as room, and never blocks. Before the pre-verify and before the verify,
when another test tier holds the tier lock, one `TIER LOCK:` line names it, so a landing that waits for it is not
mistaken for a hung one (the pre-verify's own output is captured, so its waiting line would show only on failure).
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

# Commit stamp: this helper's own commits carry a Claude-Session trailer naming the Claude Code session
# that ran it (CLAUDE_CODE_SESSION_ID / CLAUDE_CODE_HOST_SESSION_ID), so a project can tell which session
# made a commit. Kept byte-identical in land-build.py and park-worktree.py.
SESSION_TRAILER_KEY = "Claude-Session"
SESSION_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def session_stamp(env=None):
    """(config, trailer): git's `-c` arguments and the `--trailer` arguments that stamp a NEW
    commit with this session's Claude-Session trailer, or ([], []) when there is no valid id.
    The ids are CLAUDE_CODE_SESSION_ID (a UUID, required) and CLAUDE_CODE_HOST_SESSION_ID
    (local_<UUID>, optional; a malformed one stamps nothing). With neither set, as when someone
    runs the helper by hand, nothing is added. The per-key settings override any general
    trailer.* config: the trailer lands at the end and replaces one the message already holds."""
    env = os.environ if env is None else env
    cli = env.get("CLAUDE_CODE_SESSION_ID") or ""
    app = env.get("CLAUDE_CODE_HOST_SESSION_ID") or ""
    if not re.fullmatch(SESSION_UUID, cli) or (
            app and not re.fullmatch("local_" + SESSION_UUID, app)):
        return [], []
    k = SESSION_TRAILER_KEY
    config = ["-c", "trailer.%s.where=end" % k, "-c", "trailer.%s.ifExists=replace" % k,
              "-c", "trailer.%s.ifMissing=add" % k]
    return config, ["--trailer", "%s: %s" % (k, cli + (" " + app if app else ""))]

# The optional external review script (see the docstring for its contract).
CODEX_ASK = Path.home() / ".claude" / "codex-ask.py"
# The script's last stdout line, per its contract.
CODEX_ASK_LINE = re.compile(r"^CODEX-ASK (\S+) (\d+) (answer|refused)=(.*)$")
CODEX_WAIT_MIN = 15.0
# Past this the prompt names the changed paths instead of pasting the diff.
CODEX_DIFF_MAX = 400000
EXIT_CODEX_LOCKED = 6            # codex-ask: another Codex call holds its lock
REVIEW_CHILD = "--codex-review-child"
DETACHED_FLAGS = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0
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
EXIT_PRE_VERIFY = 74
EXIT_HEADROOM = 75

# The machine's memory headroom and its test-tier lock (MEMORY AND THE TIER LOCK in the docstring): an optional
# module; none at this path is one `MEMORY: could not be read` line, never a refusal. LAND_BUILD_MACHINE_LOAD, honoured
# only with LAND_BUILD_TEST=1, names another copy (a test's, never this machine's real reading).
MACHINE_LOAD = Path.home() / ".claude" / "machine_load.py"


class PreVerifyFailed(Exception):
    """The --pre-verify command exited non-zero in the build worktree; nothing on main was changed."""


class Refused(Exception):
    """Nothing was changed; the message says why."""


class Mismatch(Exception):
    """The landing is committed, but the commit does not match the branch; worktree and branch kept."""


class Kept(Exception):
    """Committed and byte-checked, but the worktree or branch could not be removed."""


class UndoFailed(Exception):
    """The commit failed and the main checkout could not be fully restored."""


class HeadroomLow(Exception):
    """The machine's memory headroom is under its floor; nothing was changed."""


# A failed call's output lines that name a failure, printed ahead of its tail when the tail leaves them out.
FAILURE_LINE = re.compile(r"FAIL|ERROR|not ok|Traceback|failed")
FAILURE_AFTER = 3    # the lines kept after each failure line
FAILURE_MAX = 40     # failure lines (with the lines after them) shown at most; the saved file holds every line


def save_output(r, what):
    """Write a failed call's full stdout and stderr to a new file in the system temp dir, outside every checkout;
    its path, or "" when it could not be written."""
    try:
        fd, path = tempfile.mkstemp(prefix="land-build-output-", suffix=".log")
        with os.fdopen(fd, "wb") as fh:
            fh.write(("%s\nexit %s\n--- stdout ---\n" % (what, r.returncode)).encode("utf-8"))
            fh.write(r.stdout or b"")
            fh.write(b"\n--- stderr ---\n")
            fh.write(r.stderr or b"")
        return path
    except OSError:
        return ""


def tail_text(r, lines=30, what="git"):
    """The END of a failed call's output (stdout, then stderr): its last `lines` lines, led by how many earlier
    ones it leaves out. Never a head slice: git prints a child's output (a hook's, a filter's) first and its own
    verdict last, and a hook prints its passing checks before its failing one, so a head slice keeps the passes and
    cuts the failure. Measured on a 46-check hook: the first 400 characters were all `<label> ok` lines, the
    failing check was cut off, and the last label shown read as the culprit.
    Nor the tail alone: a hook can print its failing check EARLY and pass dozens after it (measured 2026-10-22: 44
    lines hidden, 2026-11-01: 172; the FAIL line sat in the hidden ones both times). So when lines are left out,
    every earlier line matching FAILURE_LINE comes first, numbered, each with the FAILURE_AFTER lines after it, and
    the call's full stdout and stderr go to a file outside the checkout, whose path is printed."""
    rows = []
    for stream in (r.stdout, r.stderr):
        rows += (stream or b"").decode("utf-8", "replace").strip().splitlines()
    dropped = len(rows) - lines
    if dropped <= 0:
        return "\n  ".join(rows)
    keep = set()
    for i, row in enumerate(rows[:dropped]):
        if FAILURE_LINE.search(row):
            keep.update(range(i, min(i + FAILURE_AFTER + 1, dropped)))
    picked = sorted(keep)
    head = []
    if picked:
        head.append("failure lines among the %d earlier lines (FAIL, ERROR, not ok, Traceback, failed, each with up "
                    "to %d after it%s):" % (dropped, FAILURE_AFTER, "; the first %d" % FAILURE_MAX
                                            if len(picked) > FAILURE_MAX else ""))
        prev = None
        for i in picked[:FAILURE_MAX]:
            if prev is not None and i != prev + 1:
                head.append("  ...")
            head.append("  %d: %s" % (i + 1, rows[i]))
            prev = i
    path = save_output(r, what)
    return "\n  ".join(head + ["... (%d earlier line%s not shown)" % (dropped, "" if dropped == 1 else "s"),
                               "full output (%d lines): %s" % (len(rows), path) if path else
                               "full output: could not be saved to the temp dir"] + rows[-lines:])


# git commands that can fire a hook. They run WITHOUT --literal-pathspecs: git exports that flag to every hook as
# GIT_LITERAL_PATHSPECS=1, and a hook's `git ls-files "*.py"` then matches nothing (measured 2026-10-28 and
# 2026-11-01: 0 of 288 files, and the landing was refused). Their pathspecs are protected one by one with
# `:(literal)` instead, and an inherited GIT_LITERAL_PATHSPECS is dropped (it would read `:(literal)` as a name).
# `update-ref` fires reference-transaction and `hook run` runs one, so the landing commit's own steps are among them.
HOOK_COMMANDS = ("commit", "merge", "am", "rebase", "cherry-pick", "revert", "branch", "checkout", "switch", "push",
                 "update-ref", "hook")


def subcommand(args):
    """git's subcommand in args: the first argument past the global options (`-c key=value` takes two)."""
    i = 0
    while i < len(args):
        if args[i] == "-c":
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i]
    return ""


def git(cwd, *args, check=True, data=None, env=None):
    """Run git; bytes out (`data`, when given, is its stdin; `env`, when given, its environment). Literal pathspecs
    throughout: the global flag, or for a hook-firing command (HOOK_COMMANDS) a `:(literal)` prefix on every
    argument after `--`. check=True raises Refused with the end of git's own output (tail_text)."""
    args = [str(a) for a in args]
    sub = subcommand(args)
    if sub in HOOK_COMMANDS:
        # In `git hook run <name> -- <args>` what follows `--` is the hook's arguments, not pathspecs.
        if "--" in args and sub != "hook":
            k = args.index("--")
            args = args[:k + 1] + [":(literal)" + a for a in args[k + 1:]]
        env = {k: v for k, v in (os.environ if env is None else env).items() if k != "GIT_LITERAL_PATHSPECS"}
        argv = ["git", "-C", str(cwd)] + args
    else:
        argv = ["git", "--literal-pathspecs", "-C", str(cwd)] + args
    r = subprocess.run(argv, input=data, capture_output=True, env=env)
    if check and r.returncode:
        shown = args[args.index(sub):] if sub else args
        raise Refused("git %s failed (rc %d): %s" % (" ".join(shown[:3]), r.returncode,
                                                     tail_text(r, what=" ".join(argv))))
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
    """(new queue bytes, the entry's lines, [partial patch rel paths]) for the ONE heading `item` names exactly: by
    its title (the text after `## YYYY-MM-DD · `) or by the whole heading as written, `YYYY-MM-DD · <title>`, which
    the skill's own examples and a reader copying the heading both pass (refused as `matches 0` three times,
    2026-10-15/19 and 2026-10-30, two projects). The whole heading must match date and title; neither form
    is a substring match."""
    lines = split_lines(raw)

    def names(ln):
        text = ln.rstrip(b"\r\n").decode("utf-8", "replace")
        m = HEADING.match(text)
        return (m.group(1), text[len("## "):]) if m else ()

    heads = [i for i, ln in enumerate(lines) if item in names(ln)]
    if len(heads) != 1:
        raise Refused("--item %r matches %d '## YYYY-MM-DD · <title>' headings exactly (it must match "
                      "exactly one, by its title or by the whole heading 'YYYY-MM-DD · <title>')" % (item, len(heads)))
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
    """The commit message: subject, optional body, then the trailers -- `Upgrade:` first, except with --no-item: a
    fix-forward or design build delivers no queued upgrade, and the ledger derives *built* from that trailer."""
    parts = [a.subject.strip()]
    if a.body_file:
        body = Path(a.body_file).read_bytes().decode("utf-8").replace("\r\n", "\n").strip("\n")
        if body:
            parts.append(body)
    trailers = ([] if a.no_item else ["Upgrade: " + a.upgrade.strip()]) + [t.strip() for t in a.trailer]
    if trailers:
        parts.append("\n".join(trailers))
    return "\n\n".join(parts) + "\n"


def blob_at(top, rev, rel):
    """The bytes of `rel` in `rev`'s tree, or None when it holds no such file."""
    r = git(top, "cat-file", "blob", "%s:%s" % (rev, rel), check=False)
    return r.stdout if r.returncode == 0 else None


def own_removal(top, p, changes, item):
    """`changes` without the branch's own removal of the --item entry, which the landing makes itself; Refused for
    any other edit to the queue or the entry's Partial files.

    A helper that deleted its own entry "as earlier builds did" got the landing refused (measured 2026-11-01): a
    revert commit and a re-run per build. The branch's queue is the landing's own edit when it equals cut_entry()
    applied to the queue at the branch's BASE (the entry deleted exactly as the landing would, nothing else), and a
    Partial file is when the branch deleted it. Those changes are dropped here, so the landing cuts the entry from
    main's CURRENT queue once (keeping whatever main queued since the base) and an edit to a queue main also moved
    is no overlap. Anything else -- another entry edited, an entry added, a different entry deleted, a Partial file
    edited -- is still refused: the queue is the main thread's."""
    kinds = {path: kind for kind, path in changes}
    owned = [x for x in [p["queue_rel"]] + p["partial_paths"] if x in kinds]
    if not owned:
        return changes
    bad = [x for x in p["partial_paths"] if x in kinds and kinds[x] != "D"]
    if p["queue_rel"] in kinds:
        base_q, tip_q = blob_at(top, p["base"], p["queue_rel"]), blob_at(top, p["tip"], p["queue_rel"])
        try:
            same = base_q is not None and tip_q is not None and cut_entry(base_q, item)[0] == tip_q
        except Refused:
            same = False
        if not same:
            bad.insert(0, p["queue_rel"])
    if bad:
        raise Refused("the branch edits %s itself; the landing owns the queue entry and its partial files (the one "
                      "edit a branch may carry is the landing's own: the --item entry deleted exactly as the landing "
                      "deletes it, and its Partial files deleted)" % ", ".join(bad))
    return [(kind, path) for kind, path in changes if path not in owned]


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

    qrel = PurePosixPath(a.queue.replace("\\", "/"))
    if qrel.is_absolute() or ".." in qrel.parts or ":" in a.queue:
        raise Refused("--queue must be a file inside the checkout, given relative to it: %s" % a.queue)
    queue_rel = qrel.as_posix()
    queue = top / queue_rel
    queue_old = queue_new = None
    entry, partial_paths = [], []
    if a.no_item:
        # No queue entry to own, so no queue edit to make: one on the branch is the main thread's to land.
        if queue_rel in [x for _k, x in changes]:
            raise Refused("the branch edits %s itself; with --no-item the landing makes no queue edit, so land a "
                          "queue change on main, not through a build branch" % queue_rel)
    else:
        if not queue.is_file():
            raise Refused("%s does not exist" % queue)
        queue_old = queue.read_bytes()
        queue_new, entry, patches = cut_entry(queue_old, a.item)
        for rel in patches:
            for p in (rel, PurePosixPath(rel).with_suffix(".base").as_posix()):
                if git(top, "cat-file", "-e", "HEAD:" + p, check=False).returncode == 0:
                    partial_paths.append(p)
                elif (top / p).exists():
                    raise Refused("the Partial file %s exists but is not committed: commit or delete it first" % p)
        changes = own_removal(top, {"queue_rel": queue_rel, "partial_paths": partial_paths, "base": base, "tip": tip},
                              changes, a.item)
        if not changes:
            raise Refused("nothing to land: %s only deletes its own queue entry, which the landing would do" % branch)

    branch_paths = [p for _k, p in changes]
    main_paths = set(zlist(git(top, "diff", "--name-only", "--no-renames", "-z", base, head)))
    overlap = sorted(p for p in branch_paths if p in main_paths)
    if overlap:
        raise Refused("%d path(s) the branch changed were also changed on main since %s -- merge main into the "
                      "branch first, then land:\n  %s" % (len(overlap), base[:7], "\n  ".join(overlap)))

    landed = [p for k, p in changes if k != "D"]
    deleted = [p for k, p in changes if k == "D"]
    paths = landed + deleted + ([] if a.no_item else [queue_rel]) + partial_paths
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
            "What it delivers: " + (a.upgrade.strip() if not a.no_item else
                                    "(it has no queue entry) " + a.no_item.strip()), ""]
    if len(diff) > CODEX_DIFF_MAX:
        stat = out(git(top, "diff", "--no-color", "--stat", p["base"], p["tip"]))
        return "\n".join(head + [
            "The diff is %d characters, too long to paste. The changed paths are below: once the landing commits they "
            "hold the branch's bytes in this folder, and `git show %s:<path>` reads the base." % (len(diff), p["base"]),
            "", stat]) + "\n"
    return "\n".join(head + ["The diff:", "", "```diff", diff.rstrip("\n"), "```"]) + "\n"


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
        # Detached so it outlives this process, with no console window on Windows (G#85); bytes in, nothing decoded.
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), REVIEW_CHILD, str(d)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                cwd=str(p["top"]), creationflags=DETACHED_FLAGS, start_new_session=os.name != "nt")
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
              "answer=<path>`." % (a.codex_wait_min, proc.pid, c["out"]))
        # Two conditions, the ordinary case first: land-build cannot tell whether closing mode is on, so no line may
        # read as saying it is (measured 2026-10-30).
        print("  Outside closing mode (the usual case): read that answer, check each point against the landed files, "
              "then record: python %s --outcome <call-id> changed|nothing-new --note \"...\"" % c["script"])
        print("  If a wrap or departure has been requested (closing mode): record only that it is still running (pid "
              "%d, its line goes to %s) -- it is not stopped, and nothing is adjudicated for it now" % (proc.pid, c["out"]))
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
        print("  reviewed %s..%s, %s. Returned is not adjudicated." % (p["base"][:7], p["tip"][:7], landed))
        # Two conditions, the ordinary case first: land-build cannot tell whether closing mode is on, so no line may
        # read as saying it is (followed literally, the old first line would have skipped findings that reproduced).
        print("  Outside closing mode (the usual case): check each point against the landed files, fix forward what "
              "holds, tell the owner one line per disagreement, then: python %s --outcome %s changed|nothing-new "
              "--note \"...\"" % (c["script"], call_id))
        # Closing mode (once a wrap or departure has been requested, the session finishes it and starts no new
        # work): a late result supplies information and never authorizes development, so in closing mode it is
        # recorded, not adjudicated.
        print("  If a wrap or departure has been requested (closing mode): record only the call id %s and the answer "
              "path %s -- no adjudication, fix, landing or new run for it now" % (call_id, rest))
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


def machine_load():
    """(module, None), or (None, why it could not be loaded). Never raises."""
    path = MACHINE_LOAD
    if os.environ.get("LAND_BUILD_TEST") == "1" and os.environ.get("LAND_BUILD_MACHINE_LOAD"):
        path = Path(os.environ["LAND_BUILD_MACHINE_LOAD"])
    try:
        spec = importlib.util.spec_from_file_location("machine_load", str(path))
        if spec is None or spec.loader is None:
            raise ImportError("no module at %s" % path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as e:  # noqa: BLE001 -- said as a reading that could not be made, never as room
        return None, "%s could not be loaded: %s: %s" % (path, type(e).__name__, e)


def check_memory(a):
    """The MEMORY: line, before anything starts a tier; HeadroomLow under the machine's floor. A landing that runs
    no verify and no pre-verify starts no tier and is not checked."""
    if not (a.verify or a.pre_verify):
        return
    mod, why = machine_load()
    verdict = None
    if mod is not None:
        try:
            verdict, line = mod.check_headroom("this landing's test tiers")
        except Exception as e:  # noqa: BLE001
            why = "machine_load.check_headroom raised %s: %s" % (type(e).__name__, e)
    if verdict is None:
        print("MEMORY: could not be read (%s), so nothing says there is room for this landing's test tiers; not "
              "blocking on it" % why)
        return
    print("MEMORY: " + line)
    if verdict == "LOW":
        raise HeadroomLow("the machine is short of memory (the MEMORY line above), so this landing does not start "
                          "its test tiers; nothing changed, and the worktree and branch are kept. Land again once "
                          "there is room")


def say_tier(what):
    """One TIER LOCK: line when another test tier holds the machine-wide lock, so a wait is not read as a hang."""
    mod, _ = machine_load()
    if mod is None:
        return
    try:
        line = mod.holder_line()
    except Exception:  # noqa: BLE001 -- an informational line only
        return
    if line:
        print("TIER LOCK: %s; %s waits its turn if it runs a test tier" % (line, what))
        sys.stdout.flush()


NO_PRE_VERIFY = ("PRE-VERIFY: none -- no lint roster was run on the branch before the landing (--pre-verify "
                 "\"<command>\" runs the project's lints in the build worktree first)")


def run_pre_verify(p, a):
    """--pre-verify: the project's own lint command, run IN THE BUILD WORKTREE before anything on main changes. The
    worktree holds the helper's commits (step 1 refused uncommitted or untracked files), so a lint that scans only
    the files git tracks sees the branch's new ones: the same lints run in the main checkout before the landing
    commit cannot (a lint green before a helper's commit went red after it). The command is the project's, never
    this tool's: land-build is shared, and knows no project's runner. A non-zero exit refuses the landing
    (EXIT_PRE_VERIFY) naming the command and showing its output's end; nothing on main has changed, and the
    worktree and branch are kept."""
    if not a.pre_verify:
        print(NO_PRE_VERIFY)
        return
    print("PRE-VERIFY: %s  (in the build worktree %s)" % (a.pre_verify, p["wt"]))
    say_tier("the pre-verify")
    sys.stdout.flush()
    sys.stderr.flush()
    r = subprocess.run(a.pre_verify, shell=True, cwd=str(p["wt"]), capture_output=True)
    rc = r.returncode if r.returncode >= 0 else 128 - r.returncode
    if rc:
        raise PreVerifyFailed("the pre-verify \"%s\" exited %d in the build worktree %s, so the landing is refused: "
                              "nothing on main changed, and the worktree and branch %s are kept. Fix the branch and "
                              "land again. Its output ends:\n  %s" % (a.pre_verify, rc, p["wt"], p["branch"],
                                                                       tail_text(r, what="pre-verify")))
    print("PRE-VERIFY PASSED rc 0 (in the build worktree, on %s at %s)" % (p["branch"], p["tip"][:7]))


def replan(p, a):
    """After a pre-verify ran: every plan check again, so no long step sits between the last look at main and the
    landing's first write. The pre-verify can take minutes while other sessions share the main checkout; an
    uncommitted edit they made meanwhile to a path this landing touches (the queue, most likely) would otherwise be
    overwritten, since main's HEAD did not move and the byte check compares against the old plan. A branch whose tip
    moved is refused too: the lints passed on a different tree. Returns the fresh plan, carrying what main()
    attached to the first one (parent_note)."""
    try:
        fresh = plan(a)
    except Refused as e:
        raise Refused("the main checkout or the build branch changed while the pre-verify ran, so the landing is "
                      "refused and nothing on main was changed: %s" % e)
    if fresh["tip"] != p["tip"]:
        raise Refused("%s moved from %s to %s while the pre-verify ran: its lints passed on a different tree, so "
                      "the landing is refused and nothing on main was changed; land again"
                      % (p["branch"], p["tip"][:7], fresh["tip"][:7]))
    fresh.update((k, v) for k, v in p.items() if k not in fresh)
    return fresh


def show(p, a):
    counts = {k: sum(1 for kk, _ in p["changes"] if kk[:1] == k) for k in "AMD"}
    print("DRY RUN -- nothing changed.")
    print("would land %s (%s) onto %s (%s), merge-base %s: %d path(s), %d added, %d modified, %d deleted" % (
        p["branch"], p["tip"][:7], p["main_branch"], p["head"][:7], p["base"][:7], len(p["changes"]),
        counts["A"], counts["M"], counts["D"]))
    for kind, path in p["changes"]:
        print("  %s %s" % (kind, path))
    if a.no_item:
        print("queue: none -- no queue entry (--no-item: %s); no Upgrade: trailer" % a.no_item.strip())
    else:
        heading = p["entry"][0].rstrip(b"\r\n").decode("utf-8", "replace")
        print("queue: remove %r (%d line(s)) from %s" % (heading, len(p["entry"]), p["queue_rel"]))
    for path in p["partial_paths"]:
        print("partial: remove %s" % path)
    if a.pre_verify:
        print("pre-verify: run in the build worktree %s, before anything on main changes; a non-zero exit refuses "
              "the landing (exit %d): %s" % (p["wt"], EXIT_PRE_VERIFY, a.pre_verify))
    else:
        print("pre-verify: none -- no lint roster will be run on the branch before the landing")
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


def landing_index(p, idx):
    """The environment that commits a TEMPORARY index at `idx`: main's HEAD as step 1 read it (p["head"], which
    commit_landing also makes the commit's parent and the ref update's expected value), each landed path exactly as
    the tip's tree holds it (blob and MODE), the deleted and Partial paths removed, and the queue as the real index
    staged it.

    Not a pathspec commit: `git commit -- <paths>` re-reads those paths from the working tree, and under
    core.filemode=false (Windows) the working tree has no exec bit, so a branch's 100755 file landed as 100644 and a
    mode change was dropped; the byte check then refused the landing before its verify (measured 2026-10-30,
    measured here: the real index held 100755 after the restore, the pathspec commit 100644). Not the real index
    either: it holds a sibling session's staged work, which must stay out (file-inbox.py commits the same way). And
    never committed by `git commit`, which takes HEAD as the parent when it starts: a main that moved after this
    snapshot would get the snapshot's tree, undoing what moved it (commit_landing)."""
    top = p["top"]
    env = dict(os.environ, GIT_INDEX_FILE=str(idx))
    git(top, "read-tree", p["head"], env=env)
    want = set(p["landed"])
    rows = []
    for rec in zlist(git(top, "ls-tree", "-r", "-z", "--full-tree", p["tip"])):
        meta, _tab, path = rec.partition("\t")
        if path in want:
            rows.append(rec)
            want.discard(path)
    if want:
        raise Refused("the tip %s holds no entry for %s" % (p["tip"][:7], ", ".join(sorted(want))))
    if p["queue_new"] is not None:
        rows += zlist(git(top, "ls-files", "-s", "-z", "--", p["queue_rel"]))
    if rows:
        git(top, "update-index", "-z", "--index-info", data="".join(r + "\0" for r in rows).encode("utf-8"), env=env)
    gone = p["deleted"] + p["partial_paths"]
    if gone:
        git(top, "update-index", "--force-remove", "--", *gone, env=env)
    return env


def run_hook(top, config, name, env, *args):
    """Run the project's `name` hook as `git commit` runs it: through `git hook run` (core.hooksPath and hook config
    honoured, the checkout's top as its directory, its stdout sent to stderr), with GIT_INDEX_FILE the temporary
    index and GIT_EDITOR=":" (git commit's own hook environment), never with GIT_LITERAL_PATHSPECS ("hook" is one of
    HOOK_COMMANDS). A missing hook is skipped. Refused, naming the hook, when it fails."""
    r = git(top, *config, "hook", "run", "--ignore-missing", name, *(("--",) + args if args else ()), check=False,
            env=dict(env, GIT_EDITOR=":"))
    if r.returncode:
        raise Refused("the %s hook refused the commit (rc %d): %s" % (name, r.returncode,
                                                                     tail_text(r, what="git hook run " + name)))


def commit_landing(p, env, msgfile):
    """Commit the temporary index (`env`) as ONE commit whose parent is the HEAD step 1 read (p["head"]), and move
    main to it only while main is still there. Returns the session stamp's git config (for the post-commit hook);
    raises Refused, with main unmoved, for a refusing hook, a failed commit, or a main that moved.

    Not `git commit`, which takes HEAD as the parent when IT starts, not when the index was read: a sibling session's
    commit in between (several sessions can share one checkout, and an inbox filer may commit to main at any time) got a
    landing commit on the sibling's HEAD holding the snapshot's tree, which undid the sibling's change, and the parent
    check reported MISMATCH only once main held it (Codex 2026-11-02). Here the snapshot (landing_index), the parent
    (`commit-tree -p`) and the ref update (`update-ref HEAD <new> <old>`, a compare-and-swap) all name p["head"], the
    HEAD every check in step 1 was made against, so a main that moved refuses and nothing lands. Refused, not
    retried: a retry would redo step 1's checks against the new main and run the hooks again on a new tree, which is
    what running land-build again does.

    `git commit`'s own steps, kept in its order: pre-commit on the temporary index; the tree written AFTER it (git
    commit re-reads the index after that hook, so a hook's `git add` is committed); the session stamp through `git
    interpret-trailers --in-place --no-divider` with its config (git commit's --trailer); prepare-commit-msg with
    `<file> message` (git commit -F's source) and commit-msg, on the message file; the message read back and cleaned
    as -F's default (`git stripspace`, whitespace); `commit-tree -S` when commit.gpgsign is true (commit-tree does not
    read it, measured on git 2.53), and a refusal when git cannot read it as a boolean, as git commit refuses (a
    failed lookup is not "unsigned": `ture` exits 128 with empty stdout); the reflog entry `commit: <subject>`; and
    the ref update run with the temporary index too, so a reference-transaction hook sees the committed index, as it
    did under git commit, never the real one with a sibling's staged work (Codex 2026-11-02)."""
    top, base = p["top"], p["head"]
    # Stamped at commit time, before the verify: a landing whose verify then fails keeps its owner.
    config, trailer = session_stamp()
    run_hook(top, config, "pre-commit", env)
    tree = out(git(top, "write-tree", env=env))
    if trailer:
        git(top, *config, "interpret-trailers", "--in-place", "--no-divider", *trailer, msgfile.as_posix())
    run_hook(top, config, "prepare-commit-msg", env, msgfile.as_posix(), "message")
    run_hook(top, config, "commit-msg", env, msgfile.as_posix())
    msg = git(top, "stripspace", data=msgfile.read_bytes()).stdout
    gs = git(top, "config", "--type=bool", "--get", "commit.gpgsign", check=False)
    if gs.returncode == 1 and not out(gs):   # unset
        sign = []
    elif gs.returncode == 0 and out(gs) in ("true", "false"):
        sign = ["-S"] if out(gs) == "true" else []
    else:
        raise Refused("git could not read commit.gpgsign as true or false, so the landing commit was not made (git "
                      "commit refuses it too): %s" % tail_text(gs, what="git config --type=bool commit.gpgsign"))
    new = out(git(top, "commit-tree", tree, "-p", base, *sign, data=msg))
    subject = msg.split(b"\n", 1)[0].decode("utf-8", "replace")
    ref = git(top, "update-ref", "-m", "commit: " + subject, "HEAD", new, base, check=False, env=env)
    if ref.returncode:
        now = out(git(top, "rev-parse", "-q", "--verify", "HEAD", check=False))
        if now != base:
            raise Refused("main moved while this landing was being committed: HEAD is %s, not the %s every check and "
                          "the commit were made on, so the commit was not put on main (on the new HEAD it would undo "
                          "what moved it); run land-build again, which checks the branch against the new main"
                          % (now[:7] or "?", base[:7]))
        raise Refused("git could not move main to the landing commit: %s" % tail_text(ref, what="git update-ref HEAD"))
    return config


def entry_change(top, tip, path):
    """How `path` differs between the tip and HEAD, read from `git diff --raw`: both modes when they differ, else
    both blobs ("" when git reports no difference)."""
    f = zlist(git(top, "diff", "--raw", "-z", "--no-renames", "--abbrev=40", tip, "HEAD", "--", path, check=False))
    m = re.match(r"^:(\d+) (\d+) ([0-9a-f]+) ([0-9a-f]+) ", f[0]) if f else None
    if not m:
        return ""
    if m.group(1) != m.group(2):
        return " (mode %s in the commit, %s in the branch)" % (m.group(2), m.group(1))
    return " (blob %s in the commit, %s in the branch)" % (m.group(4)[:7], m.group(3)[:7])


def inside(path, root):
    """Whether `path` is `root` or lies under it."""
    a, b = norm(Path(path).resolve()), norm(Path(root).resolve())
    return a == b or a.startswith(b.rstrip(os.sep) + os.sep)


# Who holds a worktree git cannot delete: measured, the calling agent's own shell after a `cd` into it (measured
# 2026-10-27), and a background pytest or a Windows indexer that let go minutes later (2026-10-28).
HOLDERS = ("likely holder: a process whose current directory is inside it, often the calling agent's own shell "
           "after a `cd` into the worktree (cd to the main checkout), a background test run or other job started "
           "there, an editor, or a Windows indexer or antivirus scan (they let go within minutes)")


def remove_worktree(p):
    """Remove the build worktree (unlocked first when locked). (leftover line or "", still registered, folder left)."""
    top, wt = p["top"], p["wt"]
    failed = ""
    if p["rec"]["locked"]:
        r = git(top, "worktree", "unlock", wt, check=False)
        if r.returncode:
            failed = "could not unlock %s: %s" % (wt, tail_text(r))
    if not failed:
        rm = git(top, "worktree", "remove", wt, check=False)
        if not rm.returncode:
            return "", False, False
        failed = "could not remove %s: %s" % (wt, tail_text(rm))
    now = next((r for r in worktrees(top) if same_path(r["path"], wt)), None)
    registered = now is not None
    unreadable = ""
    try:
        left = len(os.listdir(wt))
    except FileNotFoundError:
        left = None
    except OSError as e:
        # A folder that cannot be read is not a folder that is gone (Codex 2026-11-02): read as gone, a PermissionError
        # printed no LEFTOVER and, inside the main checkout, let the verify run over what is left.
        left, unreadable = -1, "%s: %s" % (type(e).__name__, e.strerror or e)
    if not registered and left is None:
        return "", False, False   # git reported a failure, but nothing is left of it
    if registered:
        # Unlocked first only while git lists it as locked NOW: after an unlock that worked, a second `unlock` fails
        # and `&&` stops the removal (Codex 2026-11-02).
        cmd = 'git -C "%s" worktree %sremove "%s"' % (top, "unlock \"%s\" && git -C \"%s\" worktree " % (wt, top)
                                                       if now["locked"] else "", wt)
        state = "git still lists it as a worktree"
    elif unreadable:
        cmd = 'rm -rf "%s"' % wt
        state = "git unregistered it; what is left in it is unknown"
    elif left == 0:
        cmd = 'rmdir "%s"' % wt
        state = "git unregistered it and deleted its files; the empty folder is left"
    else:
        cmd = 'rm -rf "%s"' % wt
        state = ("git unregistered it; %d entr%s it could not delete are left (the landing holds every tracked byte "
                 "and the worktree had no untracked file)" % (left, "y" if left == 1 else "ies"))
    if unreadable:
        state += "; its folder could not be read (%s)" % unreadable
    return ("the worktree %s is left (%s); %s; once the holder is gone: %s -- %s" % (wt, state, HOLDERS, cmd, failed),
            registered, True)


def remove_branch(p, wt_registered):
    """Delete the build branch, only while it still points at the landed tip; the leftover line, or ""."""
    top, branch, tip = p["top"], p["branch"], p["tip"]
    if wt_registered:
        return ("the branch %s is kept: the worktree above still has it checked out; once that is removed: git -C "
                "\"%s\" branch -D %s" % (branch, top, branch))
    now = out(git(top, "rev-parse", "--verify", "-q", "refs/heads/" + branch, check=False))
    if now != tip:
        return ("the branch %s moved to %s after %s was landed, so it is kept (it holds commits this landing did not "
                "bring): inspect them with git -C \"%s\" log %s..%s, then git -C \"%s\" branch -D %s"
                % (branch, now[:7] or "?", tip[:7], top, tip[:7], branch, top, branch))
    br = git(top, "branch", "-D", p["branch"], check=False)
    if br.returncode:
        return ("the branch %s is kept (delete it by hand: git -C \"%s\" branch -D %s) -- could not delete %s: %s"
                % (branch, top, branch, branch, tail_text(br)))
    return ""


def remove_build(p, a):
    """Remove the worktree and the branch; print what could not be removed as LEFTOVER lines and return the line to
    repeat after the verify ("" when nothing is left). Raises Kept only for a worktree folder left INSIDE the main
    checkout, which the verify would read as a second copy of the tree; anything else left (a folder outside it, a
    branch) changes nothing the verify reads, so the verify still runs (three landings,
    2026-10-27 to 2026-11-02, each skipped the gating verify over an empty folder outside the checkout)."""
    top, wt = p["top"], p["wt"]
    wt_left, registered, folder = remove_worktree(p)
    br_left = remove_branch(p, registered)
    leftovers = [x for x in (wt_left, br_left) if x]
    if not leftovers:
        print("removed: worktree %s, branch %s" % (wt, p["branch"]))
        return ""
    if not wt_left:
        print("removed: worktree %s" % wt)
    if folder and inside(wt, top):
        raise Kept("the worktree %s is INSIDE the main checkout %s, where the verify would read what is left of it as "
                   "a second copy of the tree, so the verify was NOT run: %s; then run the verify yourself%s -- the "
                   "landing is committed and byte-checked" % (wt, top, "; ".join(leftovers),
                                                               ": " + a.verify if a.verify else ""))
    for ln in leftovers:
        print("LEFTOVER: " + ln)
    why = ("the worktree's folder is outside the main checkout %s, so the verify never reads it" % top if folder else
           "a kept branch changes no file the verify reads")
    print("the landing is committed and byte-checked, and the verify still runs: %s" % why)
    return "LEFTOVER (repeated): %s -- clean it up as above; it does not change the exit code" % "; ".join(
        ln.split(" -- ")[0] for ln in leftovers)


def repeat_leftover(p):
    if p.get("leftover_note"):
        print(p["leftover_note"])


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
            if p["queue_new"] is not None:
                (top / p["queue_rel"]).write_bytes(p["queue_new"])
                git(top, "add", "--", p["queue_rel"])
            env = landing_index(p, tmp / "index")
            config = commit_landing(p, env, msgfile)
        except Refused as e:
            undo(p)
            raise Refused("the landing commit failed and nothing landed; the main checkout was restored: %s" % e)
        # Main has moved, so past the undo: git commit ignores the post-commit hook's exit code, and so does this.
        git(top, *config, "hook", "run", "--ignore-missing", "post-commit", check=False, env=dict(env, GIT_EDITOR=":"))
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
    # Blob AND mode: `git diff` compares both, and entry_change names which one differs.
    for path in p["landed"]:
        if git(top, "diff", "--quiet", tip, "HEAD", "--", path, check=False).returncode != 0:
            problems.append("%s in the commit differs from %s at %s%s" % (path, p["branch"], tip[:7],
                                                                          entry_change(top, tip, path)))
    for path in p["deleted"] + p["partial_paths"]:
        if git(top, "cat-file", "-e", "HEAD:" + path, check=False).returncode == 0:
            problems.append("%s is still in the commit" % path)
    # The queue is written with the checkout's own line endings and committed through git's eol conversion, so it
    # is compared in the form git STORES, not as working-tree bytes: under core.autocrlf=true and no eol attribute
    # the working file is CRLF and the blob LF, and a byte compare refused every correct landing (exit 71, no
    # verify; measured in two projects, 2026-10-13 and 2026-10-15). Still exact: a blob git would not store from these bytes fails.
    if p["queue_new"] is not None:
        qblob = out(git(top, "rev-parse", "-q", "--verify", "HEAD:" + p["queue_rel"], check=False))
        if not qblob or qblob not in blob_ids(top, p["queue_rel"], p["queue_new"]):
            problems.append("the committed %s is not the edited queue byte for byte (as git stores it)" % p["queue_rel"])
    if problems:
        raise Mismatch("commit %s does not match %s (%s): %s -- the worktree %s and branch %s are kept; inspect "
                       "with git diff %s HEAD" % (commit[:7], p["branch"], tip[:7], "; ".join(problems), p["wt"],
                                                  p["branch"], tip[:7]))
    p["byte_checked"] = True  # the commit holds exactly the tip the review was handed
    counts = {k: sum(1 for kk, _ in p["changes"] if kk[:1] == k) for k in "AMD"}
    queue_note = ("no queue entry (--no-item: %s)" % a.no_item.strip() if a.no_item else
                  "queue entry %r removed%s" % (a.item, "; partial files removed: %s" % ", ".join(p["partial_paths"])
                                                if p["partial_paths"] else ""))
    print("LANDED %s as %s on %s: %d path(s), %d added, %d modified, %d deleted; %s" % (
        p["branch"], commit[:7], p["main_branch"], len(p["changes"]), counts["A"], counts["M"], counts["D"],
        queue_note))
    print("byte check: %d landed path(s) equal %s (%s) in the COMMITTED tree, blob and mode; %d deleted path(s) "
          "absent from HEAD" % (len(p["landed"]), p["branch"], tip[:7], len(p["deleted"]) + len(p["partial_paths"])))

    # Removal only once the commit provably holds the branch's bytes, and only the tip that was landed.
    p["leftover_note"] = remove_build(p, a)

    if not a.verify:
        print("NO VERIFY RAN (--no-verify): the landing is committed (%s) but unverified -- run the project's "
              "verify loop yourself" % commit[:7])
        repeat_parent(p)
        repeat_leftover(p)
        return 0
    print("VERIFY: %s" % a.verify)
    say_tier("the verify")
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
    repeat_leftover(p)
    return verify_rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == [REVIEW_CHILD] and len(argv) == 2:
        return review_child(argv[1])
    ap = argparse.ArgumentParser(description="Land a build helper's branch on the main checkout in one command.")
    ap.add_argument("worktree", help="the build helper's linked worktree")
    it = ap.add_mutually_exclusive_group(required=True)
    it.add_argument("--item", help="the queue entry: its exact title (after '## YYYY-MM-DD · '), or that whole "
                                   "heading as written, 'YYYY-MM-DD · <title>'")
    it.add_argument("--no-item", metavar="WHY",
                    help="land a branch with no queue entry (a fix-forward of a landed build, a design build): no "
                         "queue edit and no Upgrade: trailer, every other check kept; WHY is one line, printed")
    ap.add_argument("--subject", required=True, help="the commit subject")
    ap.add_argument("--upgrade", help="the Upgrade: trailer's one plain sentence (required with --item; refused with "
                                      "--no-item, which writes no Upgrade: trailer)")
    ap.add_argument("--body-file", help="a file holding the commit body (UTF-8)")
    ap.add_argument("--trailer", action="append", default=[], help="an extra 'Key: value' trailer line, repeatable")
    v = ap.add_mutually_exclusive_group(required=True)
    v.add_argument("--verify", metavar="COMMAND",
                   help="the project's verify loop, run from the main checkout through the platform's default "
                        "shell: cmd.exe on Windows, so a bash-form VAR=x cmd goes inside bash -c '...'")
    v.add_argument("--no-verify", action="store_true", help="run no verify (says so loudly)")
    ap.add_argument("--pre-verify", metavar="COMMAND",
                    help="the project's lint command, run IN THE BUILD WORKTREE (the committed branch) before "
                         "anything on main changes, through the same shell as --verify; a non-zero exit refuses "
                         "the landing (exit %d). Without it one line says no lint roster was run" % EXIT_PRE_VERIFY)
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
    if a.no_item is not None:
        if not a.no_item.strip() or "\n" in a.no_item.strip():
            ap.error("--no-item must be one non-empty line: why this landing has no queue entry")
        if a.upgrade is not None:
            ap.error("--upgrade with --no-item: a landing with no queue entry writes no Upgrade: trailer (the ledger "
                     "reads that trailer as a delivered queued upgrade)")
    elif a.upgrade is None or not a.upgrade.strip() or "\n" in a.upgrade.strip():
        ap.error("--upgrade must be one non-empty line: the sentence the Upgrade: trailer records")
    if not a.subject.strip() or "\n" in a.subject.strip():
        ap.error("--subject must be one non-empty line")
    if a.verify is not None and not a.verify.strip():
        ap.error("--verify is empty: name the project's verify loop, or pass --no-verify")
    if a.pre_verify is not None and not a.pre_verify.strip():
        ap.error("--pre-verify is empty: name the project's lint command, or leave the flag out")
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
        # Before anything starts a tier, on a dry run too: under the machine's memory floor nothing changes (exit 75).
        check_memory(a)
        if a.dry_run:
            return show(p, a)
        # In the worktree, before the review and before anything on main: a refusal here changes nothing.
        run_pre_verify(p, a)
        if a.pre_verify:
            # The pre-verify took minutes: plan again, so main is checked right before the landing writes it.
            p = replan(p, a)
        # Before the commit, and never waited on here: the review never gates the landing.
        p["codex"] = codex_start(p, a)
        rc = land(p, a)
    except PreVerifyFailed as e:
        print("PRE-VERIFY FAILED: %s" % e)
        rc = EXIT_PRE_VERIFY
    except HeadroomLow as e:
        print("REFUSED: %s" % e)
        rc = EXIT_HEADROOM
    except Refused as e:
        print("REFUSED: %s" % e)
        rc = EXIT_REFUSED
    except Mismatch as e:
        print("MISMATCH: %s" % e)
        rc = EXIT_MISMATCH
    except Kept as e:
        print("KEPT: %s" % e)
        rc = EXIT_KEPT
    except UndoFailed as e:
        print("UNDO FAILED: %s" % e)
        rc = EXIT_UNDO_FAILED
    codex_finish(p, a)
    return rc


if __name__ == "__main__":
    sys.exit(main())
