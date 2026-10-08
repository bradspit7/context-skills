#!/usr/bin/env python
"""park-worktree.py -- save a build helper's partial work as a committed patch, then (optionally) drop its worktree.

A background build helper (reflect-upgrades Step 5) works in its own linked worktree. Stopped before it
reports -- a departure, a restart, a closed session -- its partial diff stays there: untracked,
machine-local and named by no step. Measured once: a resumed session saved such a diff by hand (9 files)
as a committed patch, and the next session landed the build from it. This does that by command.

PARK (default):  python park-worktree.py <worktree> [--repo <checkout>] [--out DIR] [--item TITLE]
                 [--queue FILE] [--snapshot]
  - exports `git diff --binary <base>` of everything the worktree holds that its base does not: its
    branch commits, staged and unstaged edits, and untracked files (not ignored ones). The export goes
    through a TEMPORARY index, so neither the worktree's own index nor the checkout's is touched;
    <base> is the merge-base of the worktree's HEAD and the checkout's HEAD;
  - checks the patch applies at that base (`git apply --cached --check` on an index of the base), and
    that applying it there reproduces the worktree's tree exactly, byte for byte;
  - refuses: a worktree not registered to the checkout, the main checkout or the current one, a
    prunable one, one holding the mutation-harness strand sentinel (a battery, not build work), one
    with nothing to park, and one whose every change is a deletion (an emptied worktree: prune it);
  - writes <out>/<date>-<name>.patch (a '#' header git apply skips, then the diff) and <stem>.base
    (the base sha, one line), and COMMITS both -- even when the patch does not apply at HEAD, which it
    reports -- with `git commit -- <paths>`, so nothing else staged in the checkout goes with them;
  - with --item, adds (or replaces) `- **Partial:** <patch> at <base7>` in the UPGRADE-QUEUE.md entry
    whose `## ` heading contains TITLE, in the same commit when the queue file had no other edits;
  - removes the worktree only once the commit provably holds the patch (the committed blobs equal the
    written bytes). --snapshot keeps it: a plain wrap does not stop or wait for a running helper, so it
    commits the snapshot and leaves the helper working.
  Park only a worktree THIS session's helper used; another session's worktree is its own business.

UNPARK:  python park-worktree.py --unpark <patch> --into <new worktree dir> --branch <name> [--repo <checkout>]
  creates the worktree at the patch's recorded base and applies the patch there with --index, reading
  the patch from its COMMITTED blob (a checkout that converts line endings to CRLF makes the working
  copy unappliable). Any evidence recorded with a partial (a FAILED count, a passing test) is a LEAD,
  not a result: re-run it.

Exit: 0 done; 1 refused (nothing written or committed); 2 usage; 3 committed, but the worktree was kept
because a post-commit check or the removal failed (the message says which).
"""
import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# = SENTINEL_NAME in tests/mutations/mutation_harness.py; tests/test-park-worktree.py asserts they agree.
SENTINEL = ".mutation-in-flight.json"
DEFAULT_OUT = "upgrade-partials"
PARTIAL_LEAD = "- **Partial:** "


class Refused(Exception):
    """Nothing was written or committed; the message says why."""


class Kept(Exception):
    """The patch is committed, but the worktree was kept; the message says why."""


def git(cwd, *args, env=None, data=None, check=True):
    """Run git; bytes out. check=True raises Refused with git's own message on a non-zero exit."""
    r = subprocess.run(["git", "-C", str(cwd)] + [str(a) for a in args], input=data, capture_output=True,
                       env=env)
    if check and r.returncode:
        raise Refused("git %s failed (rc %d): %s" % (" ".join(str(a) for a in args[:3]), r.returncode,
                                                    r.stderr.decode("utf-8", "replace").strip()[:400]))
    return r


def out(r):
    return r.stdout.decode("utf-8", "replace").strip()


def norm(p):
    return os.path.normcase(os.path.normpath(str(p).replace("\\", "/")))


def worktrees(top):
    """[{path, head, branch, locked, prunable}] from `git worktree list --porcelain`; the main checkout first."""
    recs, cur = [], None
    for ln in out(git(top, "worktree", "list", "--porcelain")).replace("\r", "").splitlines():
        if ln.startswith("worktree "):
            cur = {"path": ln[len("worktree "):], "head": "", "branch": "", "locked": False, "prunable": ""}
            recs.append(cur)
        elif cur is None:
            continue
        elif ln.startswith("HEAD "):
            cur["head"] = ln[len("HEAD "):]
        elif ln.startswith("branch "):
            cur["branch"] = ln[len("branch "):].replace("refs/heads/", "", 1)
        elif ln.startswith("locked"):
            cur["locked"] = True
        elif ln.startswith("prunable"):
            cur["prunable"] = ln[len("prunable"):].strip() or "prunable"
    return recs


def index_env(path):
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = str(path)
    return env


def find_worktree(top, target):
    recs = worktrees(top)
    want = norm(Path(target).resolve()) if Path(target).exists() else norm(target)
    for i, rec in enumerate(recs):
        if norm(rec["path"]) == want or (Path(rec["path"]).exists() and norm(Path(rec["path"]).resolve()) == want):
            if i == 0:
                raise Refused("%s is the MAIN checkout, not a helper's worktree" % rec["path"])
            if norm(rec["path"]) == norm(top):
                raise Refused("%s is the checkout this runs in: run it from the project checkout instead" % rec["path"])
            return rec
    raise Refused("%s is not a worktree registered to %s (git worktree list does not name it)" % (target, top))


def edit_queue(queue, item, line):
    """Return the queue file's new bytes with `line` as the Partial bullet of the one entry whose heading holds `item`."""
    raw = queue.read_bytes()
    text = raw.decode("utf-8")
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    heads = [i for i, ln in enumerate(lines) if ln.startswith("## ") and item.lower() in ln.lower()]
    if len(heads) != 1:
        raise Refused("--item %r matches %d '## ' headings in %s (it must match exactly one)" % (item, len(heads), queue))
    h = heads[0]
    end = next((i for i in range(h + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for i in range(h + 1, end):
        if lines[i].startswith(PARTIAL_LEAD):
            lines[i] = line + eol
            break
    else:
        last = h
        for i in range(h + 1, end):
            if lines[i].strip():
                last = i
        if not lines[last].endswith(("\n", "\r")):
            lines[last] += eol
        lines.insert(last + 1, line + eol)
    return "".join(lines).encode("utf-8")


def park(a):
    top = Path(out(git(a.repo or os.getcwd(), "rev-parse", "--show-toplevel")))
    rec = find_worktree(top, a.worktree)
    wt = Path(rec["path"])
    if rec["prunable"]:
        raise Refused("%s is prunable (%s): nothing left to park -- git worktree prune" % (wt, rec["prunable"]))
    if not wt.is_dir():
        raise Refused("%s is gone (a lock keeps its registration): nothing left to park" % wt)
    wtop = git(wt, "rev-parse", "--show-toplevel", check=False)
    if wtop.returncode or norm(out(wtop)) != norm(wt):
        raise Refused("%s has no working .git link of its own: nothing git can read there" % wt)
    if (wt / SENTINEL).exists():
        raise Refused("%s holds %s: a mutation battery in flight or stranded, not build work -- inspect it with "
                      "git -C \"%s\" diff and restore it first; never park it" % (wt, SENTINEL, wt))
    head = out(git(top, "rev-parse", "--verify", "HEAD"))
    whead = out(git(wt, "rev-parse", "--verify", "HEAD"))
    mb = git(top, "merge-base", head, whead, check=False)
    if mb.returncode or not out(mb):
        raise Refused("%s shares no history with HEAD %s: no base to park against" % (wt, head[:7]))
    base = out(mb)

    tmp = Path(tempfile.mkdtemp(prefix="park-worktree-"))
    try:
        # The worktree's whole state, through a temporary index: start from its HEAD, add everything.
        wenv = index_env(tmp / "wt.index")
        git(wt, "read-tree", "HEAD", env=wenv)
        git(wt, "add", "-A", env=wenv)
        wt_tree = out(git(wt, "write-tree", env=wenv))
        diff_opts = ["--no-renames", "--no-color", "--no-ext-diff", "--no-textconv", "--src-prefix=a/",
                     "--dst-prefix=b/"]
        status = out(git(wt, "diff", "--cached", "--name-status", *diff_opts, base, env=wenv)).splitlines()
        if not status:
            raise Refused("%s holds nothing its base %s does not: nothing to park" % (wt, base[:7]))
        kinds = [s.split("\t", 1)[0][:1] for s in status]
        if all(k == "D" for k in kinds):
            raise Refused("every change in %s is a deletion (%d path(s)): an emptied worktree, not build work -- "
                          "git worktree remove --force \"%s\"" % (wt, len(kinds), wt))
        body = git(wt, "diff", "--cached", "--binary", "--full-index", *diff_opts, base, env=wenv).stdout
        ahead = int(out(git(top, "rev-list", "--count", "%s..%s" % (head, whead))) or 0)

        # Applies at its base, and reproduces the worktree's tree there exactly.
        probe = tmp / "probe.patch"
        probe.write_bytes(body)
        benv = index_env(tmp / "base.index")
        git(top, "read-tree", base, env=benv)
        chk = git(top, "apply", "--cached", "--check", "--whitespace=nowarn", probe, env=benv, check=False)
        if chk.returncode:
            raise Refused("the exported patch does not apply at its own base %s: %s" % (
                base[:7], chk.stderr.decode("utf-8", "replace").strip()[:300]))
        git(top, "apply", "--cached", "--whitespace=nowarn", probe, env=benv)
        if out(git(top, "write-tree", env=benv)) != wt_tree:
            raise Refused("applying the patch at %s does not reproduce %s's tree: not committed" % (base[:7], wt))
        henv = index_env(tmp / "head.index")
        git(top, "read-tree", head, env=henv)
        at_head = git(top, "apply", "--cached", "--check", "--whitespace=nowarn", probe, env=henv,
                      check=False).returncode == 0

        counts = {k: kinds.count(k) for k in "AMD"}
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", wt.name).strip("-") or "worktree"
        if a.out and (Path(a.out).is_absolute() or ".." in Path(a.out).parts):
            raise Refused("--out must be a directory inside the checkout, given relative to it: %s" % a.out)
        outdir = top / (a.out or DEFAULT_OUT)
        stem = "%s-%s" % (datetime.date.today().isoformat(), name)
        n = 1
        while (outdir / (stem + ".patch")).exists() or (outdir / (stem + ".base")).exists():
            n += 1
            stem = "%s-%s-%d" % (datetime.date.today().isoformat(), name, n)
        patch_rel = (Path(a.out or DEFAULT_OUT) / (stem + ".patch")).as_posix()
        base_rel = (Path(a.out or DEFAULT_OUT) / (stem + ".base")).as_posix()
        header = "".join("# %s\n" % s for s in [
            "park-worktree.py: a partial build, parked %s" % datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "worktree: %s (%s)" % (wt, "branch " + rec["branch"] if rec["branch"] else "detached"),
            "base: %s -- apply it there: park-worktree.py --unpark %s --into <dir> --branch <name>" % (base, patch_rel),
            "worktree HEAD: %s (%d branch commit(s) not in HEAD %s)" % (whead, ahead, head[:7]),
            "changes: %d path(s): %d added, %d modified, %d deleted" % (len(kinds), counts["A"], counts["M"],
                                                                       counts["D"]),
            "applies at HEAD %s too: %s" % (head[:7], "yes" if at_head else "no"),
            "Evidence recorded with this partial is a LEAD, not a result: re-run it.",
        ]).encode("utf-8")
        patch_bytes = header + body
        base_bytes = (base + "\n").encode("ascii")

        # The repo's line-ending rules must not rewrite the patch on commit (a rewritten patch stops applying).
        for rel, data in ((patch_rel, patch_bytes), (base_rel, base_bytes)):
            f = tmp / "filtered.bin"
            f.write_bytes(data)
            filt = out(git(top, "hash-object", "--path=" + rel, f))
            raw = out(git(top, "hash-object", "--no-filters", f))
            if filt != raw:
                raise Refused("this repo's line-ending rules would rewrite %s on commit (it carries CR bytes): "
                              "nothing committed" % rel)

        queue_new = queue_rel = None
        queue_in_commit = False
        if a.item:
            queue = top / (a.queue or "UPGRADE-QUEUE.md")
            if not queue.is_file():
                raise Refused("--item given, but %s does not exist" % queue)
            queue_rel = queue.relative_to(top).as_posix()
            queue_new = edit_queue(queue, a.item, "%s%s at %s" % (PARTIAL_LEAD, patch_rel, base[:7]))
            st = git(top, "status", "--porcelain", "--", queue_rel, check=False)
            queue_in_commit = st.returncode == 0 and not out(st)

        queue_old = (top / queue_rel).read_bytes() if queue_new is not None else None
        made_dir = not outdir.exists()
        outdir.mkdir(parents=True, exist_ok=True)
        (top / patch_rel).write_bytes(patch_bytes)
        (top / base_rel).write_bytes(base_bytes)
        paths = [patch_rel, base_rel]
        if queue_new is not None:
            (top / queue_rel).write_bytes(queue_new)
            if queue_in_commit:
                paths.append(queue_rel)
        msg = "park: partial build from %s at %s (%d path(s); applies at HEAD: %s)" % (
            wt.name, base[:7], len(kinds), "yes" if at_head else "no")
        try:
            git(top, "add", "--", *paths)
            git(top, "commit", "-q", "-m", msg, "--", *paths)
        except Refused:
            # Undo every write, so "refused" keeps meaning "nothing written": unstage, delete, restore.
            git(top, "reset", "-q", "--", *paths, check=False)
            for rel in (patch_rel, base_rel):
                (top / rel).unlink(missing_ok=True)
            if made_dir:
                shutil.rmtree(outdir, ignore_errors=True)
            if queue_old is not None:
                (top / queue_rel).write_bytes(queue_old)
            raise
        commit = out(git(top, "rev-parse", "--short", "HEAD"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("PARKED %s at %s in commit %s: %d path(s) (%d added, %d modified, %d deleted), %d branch commit(s); "
          "applies at HEAD %s: %s" % (patch_rel, base[:7], commit, len(kinds), counts["A"], counts["M"], counts["D"],
                                     ahead, head[:7], "yes" if at_head else "no"))
    if queue_new is not None:
        if queue_in_commit:
            print("queue: %s names it (%s%s at %s), in the same commit" % (queue_rel, PARTIAL_LEAD, patch_rel, base[:7]))
        else:
            print("queue: %s names it, but the file had other uncommitted edits, so that line is NOT committed: "
                  "commit it with them" % queue_rel)

    # Only once the commit provably holds the patch is the worktree dropped.
    for rel, data in ((patch_rel, patch_bytes), (base_rel, base_bytes)):
        held = git(top, "cat-file", "blob", "HEAD:" + rel, check=False)
        if held.returncode or held.stdout != data:
            raise Kept("the commit does not hold %s byte for byte: %s kept" % (rel, wt))
    if a.snapshot:
        print("worktree kept (--snapshot): %s -- a running helper keeps working there" % wt)
        return 0
    rm = git(top, "worktree", "remove", "--force", "--force", wt, check=False)
    if rm.returncode:
        raise Kept("could not remove %s: %s" % (wt, rm.stderr.decode("utf-8", "replace").strip()[:300]))
    tail = " (branch %s kept: git branch -D %s drops it)" % (rec["branch"], rec["branch"]) if rec["branch"] else ""
    print("worktree removed: %s%s" % (wt, tail))
    return 0


def unpark(a):
    top = Path(out(git(a.repo or os.getcwd(), "rev-parse", "--show-toplevel")))
    patch = Path(a.unpark)
    if not patch.is_absolute():
        patch = (Path(os.getcwd()) / patch)
    patch = patch.resolve()
    try:
        rel = patch.relative_to(top.resolve()).as_posix()
    except ValueError:
        raise Refused("%s is not inside %s" % (patch, top))
    base_file = patch.with_suffix(".base")
    if not base_file.is_file():
        raise Refused("%s has no %s beside it: the base is unknown" % (patch.name, base_file.name))
    base = base_file.read_text(encoding="utf-8", errors="replace").split()[0] if base_file.read_bytes().strip() else ""
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise Refused("%s does not hold a full sha" % base_file)
    git(top, "cat-file", "-e", base + "^{commit}")
    held = git(top, "cat-file", "blob", "HEAD:" + rel, check=False)
    if held.returncode:
        raise Refused("%s is not committed at HEAD: park it (and commit) first" % rel)
    into = Path(a.into) if Path(a.into).is_absolute() else Path(os.getcwd()) / a.into
    if into.exists():
        raise Refused("%s already exists" % into)
    git(top, "worktree", "add", "-b", a.branch, into, base)
    r = git(into, "apply", "--index", "--whitespace=nowarn", "-", data=held.stdout, check=False)
    if r.returncode:
        raise Refused("the patch does not apply at %s in %s (the worktree is left there to inspect): %s" % (
            base[:7], into, r.stderr.decode("utf-8", "replace").strip()[:300]))
    n = len(out(git(into, "diff", "--cached", "--name-only")).splitlines())
    print("UNPARKED %s into %s (branch %s at %s): %d path(s) staged. Commit it as the starting point, merge the "
          "current HEAD, then build; its recorded evidence is a lead, not a result." % (rel, into, a.branch, base[:7], n))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Park a build helper's linked worktree as a committed patch, or unpark one.")
    ap.add_argument("worktree", nargs="?", help="the linked worktree to park")
    ap.add_argument("--repo", help="the project checkout the patch is committed in (default: the current directory)")
    ap.add_argument("--out", help="directory for the patch, relative to the checkout (default: %s)" % DEFAULT_OUT)
    ap.add_argument("--item", help="a substring of the UPGRADE-QUEUE.md heading whose entry gets the Partial bullet")
    ap.add_argument("--queue", help="the queue file, relative to the checkout (default: UPGRADE-QUEUE.md)")
    ap.add_argument("--snapshot", "--keep", dest="snapshot", action="store_true",
                    help="commit the patch but keep the worktree (a plain wrap: the helper keeps running)")
    ap.add_argument("--unpark", metavar="PATCH", help="apply a parked patch at its base in a new worktree")
    ap.add_argument("--into", help="with --unpark: the new worktree's directory")
    ap.add_argument("--branch", help="with --unpark: the new worktree's branch")
    a = ap.parse_args(argv)
    if a.unpark:
        if a.worktree or not a.into or not a.branch:
            ap.error("--unpark takes --into and --branch, and no worktree argument")
    elif not a.worktree:
        ap.error("name the worktree to park (or --unpark PATCH)")
    try:
        return unpark(a) if a.unpark else park(a)
    except Refused as e:
        print("REFUSED: %s" % e)
        return 1
    except Kept as e:
        print("KEPT: %s" % e)
        return 3


if __name__ == "__main__":
    sys.exit(main())
