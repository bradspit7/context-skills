#!/usr/bin/env python
"""wrap-completeness.py -- how much of a session's work did its wrap write down?

The lean-wrap gate instrument (U5). update-context persists each session's state to the context
layer and commits it as `Session update: ...` (its Step 7). When the wrap's writing moves from the
main thread to a fresh writer agent that never saw the conversation, the silent failure is a
writer that leaves work out. This scores a wrap by the commits it covers.

A WRAP is a commit whose subject starts with "Session update". Its SPAN is the work since the
previous wrap: the non-merge commits in `<previous wrap>..<wrap>^`, minus commits that change only
HANDOFF*.md files (device-handoff's post-push records). A span commit is COVERED when the wrap's
persisted text names it: a lowercase hex token of 7+ characters that is a prefix of its full sha
(sha-cited), or a `G#N` id that its subject carries (id-cited). The persisted text is every file
the wrap commit changed, plus every HANDOFF*.md, CONTEXT.md and continuation/context.md in the
tree, all read at the wrap commit.

Coverage below 1 is normal -- another session's filing lands in the same span, a wrap names three
small commits by one line -- so the number is a RELATIVE gate: compare a cohort before and after
a change, matched by repo and span size, never against 1.

Usage:
  python wrap-completeness.py --wrap <rev> [--repo DIR]
      One wrap: every span commit marked CITED (sha or id) or UNCITED with its subject, then the
      coverage line. Exit 0; 2 when <rev> is not a wrap or no earlier wrap bounds its span.
  python wrap-completeness.py --since <date> [--until <date>] [--repo DIR] [--json PATH]
      A cohort: one row per wrap (no commit text is printed or written, so it is safe on a repo
      whose subjects must not leave it), the denominators, and the median coverage overall and
      per span bucket (1-3, 4-8, 9+ commits). Exit 0; 2 (INVALID) when no wrap in the range had a
      non-empty span to score -- a zero denominator is not a clean result.
Read-only.

That is scorer 1, the default (`--scorer 1`), unchanged since the U5 cohorts were scored with it.
SCORER 2 (`--scorer 2`, opt-in; docs/superpowers/specs/2026-10-28-commit-responsibility-record-
design.md, component 4) scores RESPONSIBILITY by session instead of a span. Each commit's
`Claude-Session` trailer (read only through git's trailer parser) names the session that made it:
exactly one distinct valid value (`<uuid>` or `<uuid> local_<uuid>`) is that session, none is
UNKNOWN, two or more or an invalid one is CONFLICT. W is the wrap's own value. Same session means
the same app id when both carry one, otherwise the same CLI id. The wrap declares
`Wrap-Workflow:` and its `Adopts-Session:` lines (one CLI or app id each, or exactly `none`).
  - Each session s (W, and each adopted id) is bounded by its own previous wrap P_s, or, with
    none, by L_s: the newest wrap that is an ancestor of every commit reachable from the wrap that
    carries s among its valid values (conflicting ones included). s's interval is everything
    reachable from the wrap and not from that bound. I is W's.
  - R is every ELIGIBLE work commit (non-merge, not a wrap, not a fold, not HANDOFF-only) in s's
    interval whose single valid value is s, over every s.
  - A CONFLICT commit in I or an adopted interval makes the wrap ineligible when one of its valid
    values is W or adopted (relevant) or it has no valid value (unattributable).
  - A commit is a fold of SOME wrap when its `Wrap-Fold` values are exactly `yes`, it carries one
    valid stamp s, is non-merge and not a wrap, and has an ancestor wrap by s. Any other
    `Wrap-Fold` commit is ordinary work, reported as a malformed or orphan marker. The folds OF a
    wrap are its session's folds that descend from it, are ancestors of the tip (`--tip`, default
    HEAD), and whose newest ancestor wrap by W is the wrap.
  - Citations: the .md files the wrap (and each fold) changed, outside upgrade-loop/ledger/, plus
    every HANDOFF*.md, CONTEXT.md and continuation/context.md, read at that commit; a file whose
    first line starts `<!-- generated` is skipped and lines starting `- **Partial:**` dropped.
    Commit messages are never read as a citation. An added-lines-only figure is printed beside.
  python wrap-completeness.py --wrap <rev> --scorer 2 [--tip REF] [--repo DIR]
      One wrap: W, the adoption declaration, the bounds, the folds, every R commit CITED or
      UNCITED (subjects printed), coverage_R pre- and post-fold, the classes over I and over the
      v1 span, the OTHER sessions over I (by id), the UNKNOWN and CONFLICT commits, eligibility.
      Exit 0; 2 when <rev> is not a wrap.
  python wrap-completeness.py --since <date> [--until <date>] --scorer 2 [--tip REF] [--json PATH]
      A cohort (text-free: no subjects, no session ids). `--until` bounds which wraps are scored,
      never which folds count. Primary: the mix-adjusted mean of post-fold coverage_R over the
      eligible wraps (bucket means by |R| weighted with U5 gate.md section 3's PRE weights), with
      the per-bucket medians beside it and the same statistic pre-fold; sensitivities (UNKNOWN in
      I counted as responsibility, added-lines sources, span-wide v1-style coverage under v1 and
      v2 sources in every row); the session-wide gap. The window is selected with git's
      --since-as-filter (git 2.37+; an older git exits 2). Exit 0; 2 (INVALID) when no wrap is
      eligible.
  python wrap-completeness.py --candidates [--session VALUE] [--tip REF] [--repo DIR]
      The window a wrap made now would be scored on (update-context's Step 1). A pending wrap by
      this session is placed on the tip (default HEAD) and bounded with scorer 2's own bound(),
      so the window is the one `--wrap --scorer 2` will compute for a wrap committed there: since
      this session's previous wrap; before its first one, since the last wrap before its first
      commit; with no commit of its own at all, since the newest wrap below the tip. It lists the
      OWN commits, the OTHER sessions (each by the id an Adopts-Session line takes) with their
      counts and how many of those the checked-out branch's upstream already holds, and the
      UNKNOWN and CONFLICT commits (subjects printed). The session is --session, else
      CLAUDE_CODE_SESSION_ID plus " " + CLAUDE_CODE_HOST_SESSION_ID when that is set, built and
      refused exactly as the session-trailer card builds its stamp: with no usable id it exits 2
      and names what is missing, never guessing one. It always reads with scorer 2's rules;
      --scorer does not change what it prints. Exit 0 (nothing to bound the window is printed,
      not an error); 2 with no usable session id, or on a git failure.
  python wrap-completeness.py --sessions TOKEN [TOKEN ...] [--folder TOKEN=PATH ...] [--repo DIR]
      Where the work of the sessions this session started sits (update-context's Steps 1 and 7,
      device-handoff's Step 1; docs/superpowers/specs/2026-10-30-closing-mode-design.md, C4). A
      TOKEN is one id exactly as an `Adopts-Session:` line takes it, a CLI uuid or local_<uuid>; a
      `<cli> <app>` pair is a usage error. A commit counts for a token exactly when scorer 2 counts
      it ADOPTED under `Adopts-Session: TOKEN` -- in_adopted(), the function score_v2 classifies
      ADOPTED with, never same_session() -- so what it reports and what that line covers cannot
      differ. It reads HEAD, every local branch and every other worktree's HEAD. Per token: the
      matching commits HEAD reaches (short sha, subject); those HEAD does not reach, grouped by
      branch or by detached worktree HEAD, with counts; for a local_ token, each CLI id seen paired
      with it in stamps whose commits stamped with that CLI id alone the line does not cover,
      listed with the extra `Adopts-Session: <cli>` line that would (a CLI id seen with two app ids
      is reported ambiguous and never resolved); for each --folder of the token, its uncommitted-
      change count (git status --porcelain, untracked files included), whether it is a linked
      worktree, and its branch; and, with no match, "no matching stamped commits found" -- never
      "no commits": unstamped writers (a PowerShell commit, for one) are outside the record. Then
      one line per linked worktree with uncommitted changes that no --folder and not the checkout
      it runs in claims: `unassigned worktree: PATH (BRANCH), N uncommitted`; stamps attribute
      commits, never uncommitted work. One repository per run; it always reads with scorer 2's
      identity rules, and --scorer does not change what it prints. Integration is "reachable from
      HEAD": a squash or a cherry-pick shows as not on HEAD. Exit 0 with the report, unintegrated
      work included; 2 on a usage error, or when a ref or worktree could not be read: it names
      each as `inspection incomplete: WHAT` and never reports as absent what it could not read.
  python wrap-completeness.py --started TOKEN [TOKEN ...] [--folder TOKEN=PATH ...]
                              [--merge TOKEN[=BRANCH] ...] [--is-running TOKEN ...]
                              [--name-only TOKEN=REASON ...] [--repo DIR]
      update-context's Step 1: merge what the sessions this session started finished, before the
      wrap commits (the owner's word, 2026-11-04). The only mode that writes, and only for a token
      given --merge: nothing merges by default, so a disposition left out cannot merge a running
      session's branch. --merge says the session finished and this session started it; BRANCH is
      its branch as the app records it, else its --folder's branch. --is-running and --name-only
      merge nothing and are named: a running session is asked about, and --name-only's REASON says
      why it is left alone (started by another session, work in an open PR).
      Each merge is device-sync's (merge, never rebase; merge-check), built as an object so the
      checkout holds no merge state at any point: git merge-tree, git commit-tree, merge-check
      --commit, then git merge --ff-only. So a conflict or a finding leaves HEAD, the index and the
      tree untouched with nothing to abort; a sibling session's staged file neither blocks the merge
      nor rides along; and HEAD moving meanwhile fails the fast-forward instead of reverting that
      commit. It never pushes, and never commits, deletes or moves anything of the session's. Then
      the --sessions report, then the verdict: `clear:`, or `open:` with one line per item that
      withholds the wrap's closing line (a branch not merged and why; a running session; commits
      HEAD does not reach, stamped or not; a session's uncommitted files, by name; a session it
      cannot see). `no matching stamped commits found` with no branch or folder to look at is
      unknown, never clean. Exit 0 clear, 1 open, 2 usage or inspection incomplete (merges nothing).
      With nothing to merge it runs no merge-check and costs what --sessions costs.
      A conflict only in docket files (the ones analyze-context's docket_corpus.py finds: roadmap.md,
      docket.md and their archives) is settled row by row before it is reported NOT MERGED. In each
      conflict block (git merge-file --diff3), a line that is one row on all three sides comes from
      the side that changed it; whole lines a side added after the shared ones are kept (ours, then
      theirs); a row both sides changed is settled only when one side only inserted text: ours
      first, theirs' addition after it. Anything else stays NOT MERGED and says why: a conflict
      outside a docket file, a changed line that is not one row on all three sides, a block a side
      shortened, a row both sides rewrote. Bytes are kept exactly, line endings included, and the
      MERGED line says how many rows were settled. merge-check runs on the result as on any merge,
      and a merge that combined a row both sides changed is never landed here, whatever merge-check
      says: it reads NOT MERGED with each combined row named, and the by-hand path names the settled
      commit to check and land.
Every git call is bounded by GIT_TIMEOUT seconds; a call past it exits 2.
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WRAP_SUBJECT = "Session update"
MIN_SHA = 7
HEX = re.compile(r"\b[0-9a-f]{%d,40}\b" % MIN_SHA)
GID = re.compile(r"\bG#\d+\b")
HANDOFF_NAME = re.compile(r"(^|/)HANDOFF[^/]*\.md$")
ALWAYS_READ = ("CONTEXT.md", "continuation/context.md")
MAX_FILE_BYTES = 2000000
BUCKETS = ((1, 3, "1-3"), (4, 8, "4-8"), (9, 10 ** 9, "9+"))
GIT_TIMEOUT = 120  # seconds; every git call the scorer makes is bounded (design nee-32)


class Usage(Exception):
    pass


def git(repo, *args, check=True):
    try:
        r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", repo] + list(args),
                           capture_output=True, encoding="utf-8", errors="replace", timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise Usage("git %s timed out after %ss" % (" ".join(args), GIT_TIMEOUT))
    if check and r.returncode != 0:
        raise Usage("git %s failed: %s" % (" ".join(args), r.stderr.strip()))
    return r


def subject(repo, rev):
    return git(repo, "log", "-1", "--format=%s", rev).stdout.strip()


def previous_wrap(repo, rev):
    """The newest wrap among rev's ancestors (rev itself excluded), or None."""
    r = git(repo, "rev-list", "--no-merges", "--grep=^" + WRAP_SUBJECT, rev + "^", check=False)
    for sha in r.stdout.split():
        if subject(repo, sha).startswith(WRAP_SUBJECT):
            return sha
    return None


def span(repo, prev, wrap):
    """[(sha, subject)] of the work commits between the previous wrap and this one."""
    out = git(repo, "log", "--no-merges", "--format=%x00%H%x09%s", "--name-only",
              "%s..%s^" % (prev, wrap)).stdout
    work = []
    for rec in out.split("\x00")[1:]:
        head, _, rest = rec.partition("\n")
        sha, _, subj = head.partition("\t")
        paths = [p for p in rest.splitlines() if p.strip()]
        if paths and all(HANDOFF_NAME.search(p) for p in paths):
            continue
        work.append((sha, subj))
    return work


def persisted_text(repo, wrap):
    paths = set(p for p in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root",
                               wrap).stdout.splitlines() if p)
    for p in git(repo, "ls-tree", "-r", "--name-only", wrap).stdout.splitlines():
        if HANDOFF_NAME.search(p) or p in ALWAYS_READ:
            paths.add(p)
    chunks = []
    for p in sorted(paths):
        size = git(repo, "cat-file", "-s", "%s:%s" % (wrap, p), check=False)
        if size.returncode != 0:  # the wrap deleted it
            continue
        if int(size.stdout.strip() or "0") > MAX_FILE_BYTES:
            continue
        chunks.append(git(repo, "show", "%s:%s" % (wrap, p), check=False).stdout)
    return "\n".join(chunks)


def score(repo, wrap, scorer=1, tip=None):
    """None when no earlier wrap bounds the span; else the scored wrap. scorer=2 returns scorer
    v2's structure for the wrap instead (score_v2); the default is scorer 1, unchanged."""
    if scorer == 2:
        return score_v2(repo, wrap, tip)
    if scorer != 1:
        raise Usage("unknown scorer %r" % (scorer,))
    if tip is not None:
        raise Usage("--tip applies to --scorer 2 only")
    prev = previous_wrap(repo, wrap)
    if prev is None:
        return None
    text = persisted_text(repo, wrap)
    tokens = set(HEX.findall(text))
    ids = set(GID.findall(text))
    rows = []
    for sha, subj in span(repo, prev, wrap):
        sha_hit = any(sha.startswith(t) for t in tokens)
        id_hit = (not sha_hit) and any(i in ids for i in GID.findall(subj))
        rows.append({"sha": sha, "subject": subj,
                     "cited": "sha" if sha_hit else ("id" if id_hit else None)})
    return {"wrap": wrap, "prev": prev, "rows": rows}


def counts(scored):
    rows = scored["rows"]
    s = sum(1 for r in rows if r["cited"] == "sha")
    i = sum(1 for r in rows if r["cited"] == "id")
    return len(rows), s + i, s, i


def one_wrap(repo, rev):
    wrap = git(repo, "rev-parse", "--verify", rev + "^{commit}").stdout.strip()
    subj = subject(repo, wrap)
    if not subj.startswith(WRAP_SUBJECT):
        raise Usage("%s is not a wrap: its subject does not start with %r" % (wrap[:9], WRAP_SUBJECT))
    scored = score(repo, wrap, scorer=1)
    if scored is None:
        raise Usage("%s has no earlier wrap, so its span has no lower bound" % wrap[:9])
    n, k, s, i = counts(scored)
    print('wrap %s "%s"; span %s..%s^ (%d commit(s))' % (wrap[:9], subj, scored["prev"][:9], wrap[:9], n))
    for r in scored["rows"]:
        mark = "CITED sha" if r["cited"] == "sha" else ("CITED id " if r["cited"] == "id" else "UNCITED  ")
        print("  %s  %s  %s" % (mark, r["sha"][:9], r["subject"]))
    print("coverage: %d/%d covered (%d by sha, %d by id)" % (k, n, s, i))
    return 0


def bucket(n):
    for lo, hi, name in BUCKETS:
        if lo <= n <= hi:
            return name
    return None


def run_cohort(repo, since, until, json_path):
    args = ["log", "--no-merges", "--format=%H%x09%cs%x09%s", "--since=" + since]
    if until:
        args.append("--until=" + until)
    wraps = []
    for ln in git(repo, *args).stdout.splitlines():
        parts = ln.split("\t", 2)
        if len(parts) == 3 and parts[2].startswith(WRAP_SUBJECT):
            wraps.append((parts[0], parts[1]))
    print("wrap-completeness  %s  since %s until %s" % (repo, since, until or "now"))
    rows, unscored, empty = [], 0, 0
    for sha, day in reversed(wraps):
        scored = score(repo, sha, scorer=1)
        if scored is None:
            unscored += 1
            print("  %s  %s  unscored (no earlier wrap)" % (sha[:9], day))
            continue
        n, k, s, i = counts(scored)
        if n == 0:
            empty += 1
            print("  %s  %s  span 0  (empty)" % (sha[:9], day))
            continue
        frac = k / n
        rows.append({"wrap": sha[:9], "date": day, "span": n, "covered": k, "sha_cited": s,
                     "id_cited": i, "fraction": round(frac, 4)})
        print("  %s  %s  span %d  covered %d  (sha %d, id %d)  %.2f" % (sha[:9], day, n, k, s, i, frac))
    print("DENOMINATOR  wraps found %d · scored %d · unscored (no earlier wrap) %d · empty span %d"
          % (len(wraps), len(rows), unscored, empty))
    summary = {"wraps_found": len(wraps), "scored": len(rows), "unscored": unscored, "empty": empty}
    if not rows:
        print("INVALID: no wrap in the range had a non-empty span to score")
        code = 2
    else:
        med = statistics.median(r["fraction"] for r in rows)
        summary["median"] = round(med, 4)
        print("median coverage %.2f over %d wrap(s)" % (med, len(rows)))
        for _lo, _hi, name in BUCKETS:
            fr = [r["fraction"] for r in rows if bucket(r["span"]) == name]
            summary["median_" + name] = round(statistics.median(fr), 4) if fr else None
            summary["n_" + name] = len(fr)
            print("  span %-4s median %s  n %d" % (name, "%.2f" % statistics.median(fr) if fr else "--", len(fr)))
        code = 0
    if json_path:
        with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"repo": repo, "since": since, "until": until, "wraps": rows,
                       "summary": summary}, fh, indent=1, sort_keys=True)
            fh.write("\n")
    return code


# ==============================================================================================
# Scorer v2: responsibility by session (docs/superpowers/specs/2026-10-28-commit-responsibility-
# record-design.md, component 4). Opt-in with --scorer 2; nothing above this line changes for v1.
# ==============================================================================================

SESSION_KEY = "Claude-Session"
FOLD_KEY = "Wrap-Fold"
ADOPTS_KEY = "Adopts-Session"
WORKFLOW_KEY = "Wrap-Workflow"
WORKFLOWS = ("main-thread-check", "writer")  # anything else reads as `other`, absence as `absent`
# The protocol's value grammar (claude-infra/scripts/guard_cards.py is its single source; the
# suite asserts these agree with it): `<uuid>` or `<uuid> local_<uuid>`.
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
CLI_ID_RE = re.compile(_UUID)
APP_ID_RE = re.compile("local_" + _UUID)
SESSION_VALUE_RE = re.compile("(%s)(?: (local_%s))?" % (_UUID, _UUID))
GENERATED_LEAD = "<!-- generated"
PARTIAL_LEAD = "- **Partial:**"  # park-worktree.py's base-sha line
LEDGER_DIR = "upgrade-loop/ledger/"
# U5 gate.md section 3's PRE weights (the share of each |R| bucket before U5), frozen.
WEIGHTS = (("1-3", 0.3694), ("4-8", 0.3885), ("9+", 0.242))
OWN, ADOPTED, OTHER, UNKNOWN, CONFLICT = "OWN", "ADOPTED", "OTHER", "UNKNOWN", "CONFLICT"
CLASSES = (OWN, ADOPTED, OTHER, UNKNOWN, CONFLICT)
ONE = "ONE"
_LOG_KEYS = (SESSION_KEY, FOLD_KEY, ADOPTS_KEY, WORKFLOW_KEY)
# Every field ends in NUL, which no commit message can hold, so the split is exact.
_LOG_FORMAT = ("%H%x00%P%x00%cs%x00"
               + "".join("%(trailers:key=" + k + ",valueonly,unfold)%x00" for k in _LOG_KEYS)
               + "%s%x00")
_LOG_FIELDS = 3 + len(_LOG_KEYS) + 1
_SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def trailer_values(field):
    """git prints each value of a key on its own line (an empty value as a bare newline), and
    nothing when the key is absent, so an empty value still counts as one (invalid) value."""
    if not field:
        return []
    if field.endswith("\n"):
        field = field[:-1]
    return field.split("\n")


def parse_session(value):
    """(cli id, app id or None), lowercased, for a valid value; None for an invalid one."""
    m = SESSION_VALUE_RE.fullmatch(value)
    if not m:
        return None
    return m.group(1).lower(), (m.group(2).lower() if m.group(2) else None)


def identity(values):
    """The authority rule: (ONE, (cli, app)) for exactly one distinct valid value (repeats count
    once); (UNKNOWN, None) for none; (CONFLICT, [its valid values]) for two or more distinct
    values or an invalid one -- never resolved by position."""
    if not values:
        return UNKNOWN, None
    distinct = sorted(set(v.strip() for v in values))
    valid = [p for p in (parse_session(v) for v in distinct) if p is not None]
    if len(distinct) == 1 and valid:
        return ONE, valid[0]
    return CONFLICT, valid


def same_session(a, b):
    """The same app id when both carry one, otherwise the same CLI id."""
    if a is None or b is None:
        return False
    if a[1] and b[1]:
        return a[1] == b[1]
    return a[0] == b[0]


def in_adopted(ident, ids):
    """A value is adopted when its CLI id or its app id is one of the declared ids."""
    return ident is not None and (ident[0] in ids or (ident[1] is not None and ident[1] in ids))


def session_groups(idents):
    """A key function grouping single valid values the way same_session() reads them, over the
    values of one window: a value's app id when it carries one; a CLI-only value joins the app id
    its CLI id carries elsewhere in the window when there is exactly one such app id; a CLI id
    seen with two or more app ids keeps its CLI-only values as their own group, never merged."""
    apps = {}
    for cli, app in idents:
        if app:
            apps.setdefault(cli, set()).add(app)

    def key(ident):
        cli, app = ident
        if app:
            return app
        seen = apps.get(cli, ())
        return next(iter(seen)) if len(seen) == 1 else cli
    return key


def show_value(ident):
    return ident[0] + (" " + ident[1] if ident[1] else "")


def adoption(values):
    """(status, ids) for the wrap's `Adopts-Session:` lines. Valid: exactly one line `none`
    (status `none`), or one or more lines each holding one CLI id or one app id (status `ids`).
    Otherwise `missing`, `none-beside-id` or `malformed`, each ineligible (cx3-6). `ids` is the
    valid ids among the lines, whatever the status."""
    vals = [v.strip() for v in values]
    is_id = [bool(CLI_ID_RE.fullmatch(v) or APP_ID_RE.fullmatch(v)) for v in vals]
    ids = sorted(set(v.lower() for v, ok in zip(vals, is_id) if ok))
    if not vals:
        return "missing", ids
    if vals == ["none"]:
        return "none", []
    if "none" in vals:
        rest_ok = all(ok for v, ok in zip(vals, is_id) if v != "none")
        return ("none-beside-id" if ids and rest_ok and vals.count("none") == 1 else "malformed"), ids
    return ("ids" if all(is_id) else "malformed"), ids


def workflow_of(values):
    vals = set(v.strip() for v in values)
    if not vals:
        return "absent"
    if len(vals) == 1 and next(iter(vals)) in WORKFLOWS:
        return next(iter(vals))
    return "other"


class Graph(object):
    """Every commit reachable from `revs`, read once: parents, committer date, subject and the
    four trailer keys (through git's parser only), topological order, and which non-merge commits
    change only HANDOFF*.md (v1's exclusion)."""

    def __init__(self, repo, revs):
        out = git(repo, "log", "--no-show-signature", "--no-color", "--topo-order",
                  "--format=" + _LOG_FORMAT, *revs, "--").stdout
        parts = out.split("\x00")
        tail = parts.pop()
        if tail.strip() or len(parts) % _LOG_FIELDS:
            raise Usage("could not parse git log's output for %s" % " ".join(revs))
        self.order, self.parents, self.date, self.subject = [], {}, {}, {}
        self.values, self.fold_values, self.adopts, self.workflow = {}, {}, {}, {}
        for i in range(0, len(parts), _LOG_FIELDS):
            f = parts[i:i + _LOG_FIELDS]
            sha = f[0].lstrip("\n")
            if not _SHA_RE.fullmatch(sha):
                raise Usage("could not parse git log's output for %s" % " ".join(revs))
            self.order.append(sha)
            self.parents[sha] = f[1].split()
            self.date[sha] = f[2]
            self.values[sha] = trailer_values(f[3])
            self.fold_values[sha] = trailer_values(f[4])
            self.adopts[sha] = trailer_values(f[5])
            self.workflow[sha] = trailer_values(f[6])
            self.subject[sha] = f[7]
        self.handoff_only = set()
        out = git(repo, "log", "--no-show-signature", "--no-color", "--no-merges", "--format=%x00%H",
                  "--name-only", *revs, "--").stdout
        for rec in out.split("\x00")[1:]:
            head, _, rest = rec.partition("\n")
            paths = [p for p in rest.splitlines() if p.strip()]
            if paths and all(HANDOFF_NAME.search(p) for p in paths):
                self.handoff_only.add(head.strip())
        self.wraps = [c for c in self.order if self.is_wrap(c)]  # newest first
        self._anc, self._ident, self._marker, self.sources = {}, {}, {}, {}

    def is_merge(self, c):
        return len(self.parents.get(c, ())) > 1

    def is_wrap(self, c):
        return not self.is_merge(c) and self.subject[c].startswith(WRAP_SUBJECT)

    def fold_marker(self, c):
        """None without a `Wrap-Fold` marker. Otherwise `fold` for a fold of SOME wrap: exactly
        one distinct marker value, exactly `yes`; a single valid stamp s; non-merge, not a wrap;
        and at least one ancestor wrap by s. `malformed` when the marker is anything but exactly
        `yes`; `orphan` for any other marker commit. Malformed and orphan markers are ordinary
        work: they stay in I, in R and in the conflict check, and are reported."""
        got = self._marker.get(c, 0)
        if got == 0:
            vals = self.fold_values[c]
            if not vals:
                got = None
            elif set(vals) != {"yes"}:
                got = "malformed"
            else:
                kind, s = self.ident(c)
                got = "fold" if (kind == ONE and not self.is_merge(c) and not self.is_wrap(c)
                                 and newest_wrap_by(self, c, lambda i: same_session(i, s)) is not None) else "orphan"
            self._marker[c] = got
        return got

    def is_fold(self, c):
        return self.fold_marker(c) == "fold"

    def is_work(self, c):
        """An eligible work commit: non-merge, not a wrap, not a fold, not HANDOFF-only."""
        return not (self.is_merge(c) or self.is_wrap(c) or self.is_fold(c) or c in self.handoff_only)

    def ident(self, c):
        got = self._ident.get(c)
        if got is None:
            got = self._ident[c] = identity(self.values[c])
        return got

    def ancestors(self, c):
        """c and every commit reachable from it."""
        got = self._anc.get(c)
        if got is None:
            seen, stack = set(), [c]
            while stack:
                x = stack.pop()
                if x not in seen:
                    seen.add(x)
                    stack.extend(self.parents.get(x, ()))
            got = self._anc[c] = frozenset(seen)
        return got


def newest_wrap_by(g, c, match):
    """The newest wrap among c's ancestors (c excluded) whose single valid value `match` accepts."""
    anc = g.ancestors(c)
    for w in g.wraps:
        if w != c and w in anc:
            kind, ident = g.ident(w)
            if kind == ONE and match(ident):
                return w
    return None


def last_wrap_before(g, x, commits):
    """L: the newest wrap of any session (x excluded) that is an ancestor of every one of
    `commits` -- the last wrap before that session's first work. Bounded by construction: it is
    found among the commits' common ancestors."""
    common = None
    for c in commits:
        a = g.ancestors(c)
        common = set(a) if common is None else (common & a)
        if not common:
            return None
    for w in g.wraps:
        if w != x and w in common:
            return w
    return None


def carries(g, c, match):
    """Whether one of c's VALID values is the session: its single value, or any of a CONFLICT's."""
    kind, ident = g.ident(c)
    if kind == ONE:
        return match(ident)
    if kind == CONFLICT:
        return any(match(v) for v in ident)
    return False


def bound(g, x, match):
    """(bound, how) for one session: its previous wrap P_s ('previous'), else L_s
    ('last-before-first'), found from EVERY commit reachable from x that carries the session among
    its valid values -- conflicting ones too, so a conflicting record is never bounded out of the
    interval that must judge it. (None, None) when no commit carries the session at all (an empty
    interval); (None, 'none') when no wrap bounds it (the wrap is then ineligible)."""
    p = newest_wrap_by(g, x, match)
    if p is not None:
        return p, "previous"
    anc = g.ancestors(x)
    mine = [c for c in g.order if c in anc and carries(g, c, match)]
    if not mine:
        return None, None
    lw = last_wrap_before(g, x, mine)
    return (lw, "last-before-first") if lw is not None else (None, "none")


def find_folds(g, x, w_ident, tip):
    """The folds of wrap x, oldest first: folds (Graph.fold_marker) stamped W that descend from x,
    are ancestors of the tip, and whose newest ancestor wrap by W is x."""
    tip_anc = g.ancestors(tip)
    found = []
    for c in g.order:
        if c == x or c not in tip_anc or not g.is_fold(c) or g.is_merge(c) or g.is_wrap(c):
            continue
        kind, ident = g.ident(c)
        if kind != ONE or not same_session(ident, w_ident):
            continue
        if x not in g.ancestors(c):
            continue
        if newest_wrap_by(g, c, lambda i: same_session(i, w_ident)) != x:
            continue
        found.append(c)
    found.reverse()
    return found


def strip_partial(text):
    return "\n".join(ln for ln in text.split("\n") if not ln.startswith(PARTIAL_LEAD))


def source_text(repo, commit, path):
    """The file at `commit`, `- **Partial:**` lines dropped; None when it is absent, too large or
    generated (its first line starts `<!-- generated`)."""
    size = git(repo, "cat-file", "-s", "%s:%s" % (commit, path), check=False)
    if size.returncode != 0:
        return None
    if int(size.stdout.strip() or "0") > MAX_FILE_BYTES:
        return None
    text = git(repo, "show", "%s:%s" % (commit, path), check=False).stdout
    if text.lstrip("\ufeff").startswith(GENERATED_LEAD):
        return None
    return strip_partial(text)


def added_lines(repo, commit, path):
    """The lines `commit` added to `path` (against its first parent, or created at the root)."""
    out = git(repo, "diff-tree", "-p", "-U0", "--no-color", "--no-ext-diff", "--no-textconv",
              "--no-renames", "-r", "--root", commit, "--", ":(literal)" + path).stdout
    added, in_hunk = [], False
    for ln in out.split("\n"):
        if ln.startswith("diff --git "):
            in_hunk = False
        elif ln.startswith("@@"):
            in_hunk = True
        elif in_hunk and ln.startswith("+") and not ln[1:].startswith(PARTIAL_LEAD):
            added.append(ln[1:])
    return added


def sources(repo, g, commit):
    """(whole-file text, added-lines text) of one wrap's or fold's citation sources: the .md files
    it changed outside upgrade-loop/ledger/, plus every HANDOFF*.md, CONTEXT.md and
    continuation/context.md, all read at that commit."""
    got = g.sources.get(commit)
    if got is not None:
        return got
    changed = [p for p in git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root",
                              commit).stdout.splitlines() if p]
    md = set(p for p in changed if p.lower().endswith(".md") and not p.startswith(LEDGER_DIR))
    paths = set(md)
    for p in git(repo, "ls-tree", "-r", "--name-only", commit).stdout.splitlines():
        if (HANDOFF_NAME.search(p) or p in ALWAYS_READ) and not p.startswith(LEDGER_DIR):
            paths.add(p)
    whole, added = [], []
    for p in sorted(paths):
        text = source_text(repo, commit, p)
        if text is None:
            continue
        whole.append(text)
        if p in md:
            added.extend(added_lines(repo, commit, p))
    got = g.sources[commit] = ("\n".join(whole), "\n".join(added))
    return got


class Cites(object):
    """v1's citation rule over a set of texts: a 7+ character hex prefix of the sha, else a G#N id
    the subject carries."""

    def __init__(self, texts):
        self.tokens, self.ids = set(), set()
        for t in texts:
            self.tokens.update(HEX.findall(t))
            self.ids.update(GID.findall(t))

    def __call__(self, sha, subj):
        if any(sha[:n] in self.tokens for n in range(MIN_SHA, len(sha) + 1)):
            return "sha"
        if any(i in self.ids for i in GID.findall(subj)):
            return "id"
        return None


def score_v2(repo, wrap, tip=None, graph=None):
    """Scorer v2's structure for one wrap (it holds subjects and session ids; the cohort keeps
    only counts)."""
    tip_sha = git(repo, "rev-parse", "--verify", (tip or "HEAD") + "^{commit}").stdout.strip()
    x = git(repo, "rev-parse", "--verify", wrap + "^{commit}").stdout.strip()
    g = graph
    if g is None or x not in g.parents or tip_sha not in g.parents:
        g = Graph(repo, [tip_sha, x])
    if not g.is_wrap(x):
        raise Usage("%s is not a wrap: it is a merge, or its subject does not start with %r"
                    % (x[:9], WRAP_SUBJECT))
    kind, ident = g.ident(x)
    W = ident if kind == ONE else None
    distinct = set(v.strip() for v in g.values[x])
    w_status = "valid" if W else ("missing" if not distinct else ("conflict" if len(distinct) > 1 else "invalid"))
    a_status, a_ids = adoption(g.adopts[x])
    adopted_set = set(a_ids)
    reasons = []
    if W is None:
        reasons.append("ownership-unavailable")
    if a_status not in ("none", "ids"):
        reasons.append("adoption-" + a_status)

    def classify(c):
        k, i = g.ident(c)
        if k != ONE:
            return k
        if same_session(i, W):
            return OWN
        return ADOPTED if in_adopted(i, adopted_set) else OTHER

    sessions = []
    if W is not None:
        sessions.append(("W", lambda i: same_session(i, W)))
        for a in a_ids:
            sessions.append((a, lambda i, a=a: in_adopted(i, {a})))
    bounds, intervals = {}, {}
    x_anc = g.ancestors(x)
    for label, match in sessions:
        b, how = bound(g, x, match)
        bounds[label] = [b, how]
        if b is not None:
            intervals[label] = x_anc - g.ancestors(b)
        elif how is None:
            intervals[label] = frozenset()
        else:
            intervals[label] = None
    if any(iv is None for iv in intervals.values()):
        reasons.append("no-bound")
    I = intervals.get("W")

    R = {}
    matched = {a: False for a in a_ids}
    for label, match in sessions:
        for c in intervals[label] or ():
            if not g.is_work(c):
                continue
            k, i = g.ident(c)
            if k == ONE and match(i):
                R.setdefault(c, OWN if same_session(i, W) else ADOPTED)
                if label != "W":
                    matched[label] = True

    scope = set()
    for iv in intervals.values():
        scope |= iv or set()
    relevant, unattributable = [], []
    for c in g.order:
        if c in scope and g.is_work(c):
            k, valid = g.ident(c)
            if k != CONFLICT:
                continue
            if not valid:
                unattributable.append(c)
            elif any(same_session(v, W) or in_adopted(v, adopted_set) for v in valid):
                relevant.append(c)
    if relevant:
        reasons.append("conflict-relevant")
    if unattributable:
        reasons.append("conflict-unattributable")

    folds = find_folds(g, x, W, tip_sha) if W is not None else []
    whole_x, added_x = sources(repo, g, x)
    fold_src = [sources(repo, g, f) for f in folds]
    cite_pre = Cites([whole_x])
    cite_post = Cites([whole_x] + [s[0] for s in fold_src])
    cite_added = Cites([added_x] + [s[1] for s in fold_src])

    r_list = []
    for c in g.order:
        if c in R:
            subj = g.subject[c]
            r_list.append({"sha": c, "subject": subj, "class": R[c], "pre": cite_pre(c, subj),
                           "post": cite_post(c, subj), "added": cite_added(c, subj)})
    i_list = None
    if I is not None:
        i_list = [{"sha": c, "subject": g.subject[c], "class": classify(c), "post": cite_post(c, g.subject[c])}
                  for c in g.order if c in I and g.is_work(c)]
    if W is not None and I is not None and not r_list:
        reasons.append("R-empty")

    other_sessions, unknown = {}, []
    group = session_groups([g.ident(e["sha"])[1] for e in i_list or () if g.ident(e["sha"])[0] == ONE])
    for e in i_list or ():
        if e["class"] == OTHER:
            key = group(g.ident(e["sha"])[1])
            other_sessions[key] = other_sessions.get(key, 0) + 1
        elif e["class"] == UNKNOWN:
            unknown.append(e["sha"])
    fold_markers = [{"sha": c, "subject": g.subject[c], "why": g.fold_marker(c)}
                    for c in g.order if c in scope and g.fold_marker(c) in ("malformed", "orphan")]

    prev = previous_wrap(repo, x)
    span_list = None
    if prev is not None:
        v1cite = Cites([persisted_text(repo, x)])
        span_list = [{"sha": sha, "subject": subj, "class": classify(sha) if sha in g.parents else UNKNOWN,
                      "post": cite_post(sha, subj), "v1": v1cite(sha, subj)}
                     for sha, subj in span(repo, prev, x)]

    def coverage(key):
        if W is None or I is None or not r_list:
            return None
        return sum(1 for e in r_list if e[key]) / len(r_list)

    return {"scorer": 2, "wrap": x, "subject": g.subject[x], "date": g.date[x], "tip": tip_sha,
            "W": show_value(W) if W else None, "W_status": w_status,
            "workflow": workflow_of(g.workflow[x]), "adoption": {"status": a_status, "ids": a_ids},
            "bounds": bounds, "folds": folds, "R": r_list, "I": i_list,
            "span_prev": prev, "span": span_list, "other_sessions": other_sessions, "unknown": unknown,
            "conflicts_relevant": relevant, "conflicts_unattributable": unattributable,
            "fold_markers": fold_markers,
            "adopted_without_commits": sorted(a for a, hit in matched.items() if not hit),
            "coverage_pre": coverage("pre"), "coverage_post": coverage("post"),
            "coverage_added": coverage("added"), "reasons": reasons, "eligible": not reasons}


def _frac(k, n):
    return "%d/%d (%.2f)" % (k, n, k / n) if n else "%d/%d (unavailable)" % (k, n)


def _class_counts(entries, key="post"):
    out = {c: [0, 0] for c in CLASSES}
    for e in entries:
        out[e["class"]][0] += 1
        out[e["class"]][1] += 1 if e[key] else 0
    return out


def _class_line(counts):
    return " · ".join("%s %d (cited %d)" % (c, counts[c][0], counts[c][1]) for c in CLASSES)


def one_wrap_v2(repo, rev, tip):
    s = score_v2(repo, rev, tip)
    x = s["wrap"]
    print('wrap %s "%s"; scorer 2; tip %s' % (x[:9], s["subject"], s["tip"][:9]))
    print("  W: %s" % (s["W"] if s["W"] else "unavailable (%s)" % s["W_status"]))
    print("  workflow: %s" % s["workflow"])
    a = s["adoption"]
    if a["status"] == "none":
        print("  adoption: none (declared)")
    elif a["status"] == "ids":
        print("  adoption: %d id(s): %s" % (len(a["ids"]), ", ".join(a["ids"])))
    else:
        print("  adoption: INVALID (%s)%s" % (a["status"], (" ids " + ", ".join(a["ids"])) if a["ids"] else ""))
    for label, (b, how) in sorted(s["bounds"].items(), key=lambda kv: kv[0] != "W"):
        what = {"previous": "its previous wrap", "last-before-first": "the last wrap before its first commit",
                None: "no commit reachable", "none": "NOTHING bounds it"}[how]
        print("  bound %s: %s (%s)" % (label, b[:9] if b else "-", what))
    print("  folds: %s" % (" ".join(f[:9] for f in s["folds"]) or "none"))
    R = s["R"]
    if s["I"] is None:
        print("  R: unavailable (ownership unavailable or unbounded)")
    else:
        own = sum(1 for e in R if e["class"] == OWN)
        print("  R: %d commit(s): OWN %d, ADOPTED %d" % (len(R), own, len(R) - own))
        for e in R:
            mark = {"sha": "CITED sha", "id": "CITED id "}.get(e["post"], "UNCITED  ")
            late = "  (by a fold)" if e["post"] and not e["pre"] else ""
            print("    %s  %s  %-7s  %s%s" % (mark, e["sha"][:9], e["class"], e["subject"], late))
        print("  coverage_R: pre-fold %s · post-fold %s · added-lines post-fold %s" % (
            _frac(sum(1 for e in R if e["pre"]), len(R)), _frac(sum(1 for e in R if e["post"]), len(R)),
            _frac(sum(1 for e in R if e["added"]), len(R))))
        print("  classes over I (%d): %s" % (len(s["I"]), _class_line(_class_counts(s["I"]))))
    if s["span"] is None:
        print("  v1 span: none (no earlier wrap)")
    else:
        sp = s["span"]
        print("  classes over the v1 span %s..%s^ (%d): %s" % (s["span_prev"][:9], x[:9], len(sp),
                                                             _class_line(_class_counts(sp))))
        print("  v1 span coverage: v1 sources %s · v2 sources %s" % (
            _frac(sum(1 for e in sp if e["v1"]), len(sp)), _frac(sum(1 for e in sp if e["post"]), len(sp))))
    if s["I"] is not None:
        print("  OTHER sessions over I: %s" % ("; ".join(
            "%s %d" % kv for kv in sorted(s["other_sessions"].items(), key=lambda kv: (-kv[1], kv[0]))) or "none"))
        unknown = [e for e in s["I"] if e["class"] == UNKNOWN]
        print("  UNKNOWN over I: %d" % len(unknown))
        for e in unknown:
            print("    UNKNOWN    %s  %s" % (e["sha"][:9], e["subject"]))
    subjects = {}
    for e in (s["I"] or []) + (s["R"] or []):
        subjects[e["sha"]] = e["subject"]
    for name, key in (("relevant", "conflicts_relevant"), ("unattributable", "conflicts_unattributable")):
        print("  CONFLICT %s: %d" % (name, len(s[key])))
        for c in s[key]:
            print("    CONFLICT   %s  %s" % (c[:9], subjects.get(c, "(outside I, in an adopted interval)")))
    print("  Wrap-Fold markers that are not folds (counted as work): %d" % len(s["fold_markers"]))
    for m in s["fold_markers"]:
        print("    MARKER     %s  %-9s  %s" % (m["sha"][:9], m["why"], m["subject"]))
    print("  adopted ids with no commit in R: %s" % (", ".join(s["adopted_without_commits"]) or "none"))
    print("  eligible: %s" % ("yes" if s["eligible"] else "no (%s)" % ", ".join(s["reasons"])))
    return 0


def mix_adjusted(pairs):
    """gate.md section 3's statistic: bucket means by size weighted with the PRE weights,
    renormalised over the buckets present; None with no pair."""
    num = den = 0.0
    for name, w in WEIGHTS:
        v = [f for n, f in pairs if bucket(n) == name]
        if v:
            num += w * statistics.mean(v)
            den += w
    return num / den if den else None


def _r4(v):
    return None if v is None else round(v, 4)


def _buckets(pairs):
    out = {}
    for name, _w in WEIGHTS:
        v = [f for n, f in pairs if bucket(n) == name]
        out[name] = {"n": len(v), "mean": _r4(statistics.mean(v)) if v else None,
                     "median": _r4(statistics.median(v)) if v else None}
    return out


def cohort_row(s, day):
    """One text-free row: counts, shas and fixed codes only."""
    R, I, sp = s["R"], s["I"], s["span"]
    row = {"wrap": s["wrap"][:9], "date": day, "eligible": s["eligible"],
           "reason": s["reasons"][0] if s["reasons"] else "eligible", "reasons": s["reasons"],
           "workflow": s["workflow"], "adoption": s["adoption"]["status"], "W": s["W_status"],
           "folds": [f[:9] for f in s["folds"]], "R": None if I is None else len(R),
           "bucket": bucket(len(R)) if I is not None and R else None}
    for cls in (OWN, ADOPTED):
        mine = [e for e in R if e["class"] == cls]
        key = cls.lower()
        row[key] = len(mine)
        row[key + "_cited_pre"] = sum(1 for e in mine if e["pre"])
        row[key + "_cited_post"] = sum(1 for e in mine if e["post"])
    row["cited_pre"] = sum(1 for e in R if e["pre"])
    row["cited_post"] = sum(1 for e in R if e["post"])
    row["cited_added"] = sum(1 for e in R if e["added"])
    for k in ("coverage_pre", "coverage_post", "coverage_added"):
        row[k] = _r4(s[k])
    row["I"] = None if I is None else len(I)
    row["classes_I"] = None if I is None else _class_counts(I)
    unknown = [e for e in I or () if e["class"] == UNKNOWN]
    row["unknown_I"] = len(unknown)
    row["unknown_cited_I"] = sum(1 for e in unknown if e["post"])
    row["other_sessions_I"] = len(s["other_sessions"])
    row["span"] = None if sp is None else len(sp)
    row["classes_span"] = None if sp is None else _class_counts(sp)
    row["span_cited_v1src"] = None if sp is None else sum(1 for e in sp if e["v1"])
    row["span_cited_v2src"] = None if sp is None else sum(1 for e in sp if e["post"])
    row["conflicts_relevant"] = len(s["conflicts_relevant"])
    row["conflicts_unattributable"] = len(s["conflicts_unattributable"])
    row["markers_malformed"] = sum(1 for m in s["fold_markers"] if m["why"] == "malformed")
    row["markers_orphan"] = sum(1 for m in s["fold_markers"] if m["why"] == "orphan")
    row["adopted_ids"] = len(s["adoption"]["ids"])
    row["adopted_without_commits"] = len(s["adopted_without_commits"])
    return row


def script_blob():
    """The git blob hash of this script's bytes, so a result names the code that produced it."""
    try:
        with open(__file__, "rb") as fh:
            data = fh.read()
    except (NameError, OSError):
        return None
    return hashlib.sha1(b"blob %d\x00" % len(data) + data).hexdigest()


def session_wide(repo, g, since, until, tip, scored):
    """Per session: its eligible stamped work commits in the window that no wrap's R holds.
    Wraps, folds and HANDOFF-only records are counted apart, as structure (cx3-5). Sessions are
    grouped by session_groups() over the window's values."""
    args = ["log", "--no-merges", "--no-show-signature", "--format=%H", "--since-as-filter=" + since]
    if until:
        args.append("--until=" + until)
    window = [c for c in git(repo, *(args + [tip, "--"])).stdout.split() if c in g.parents]
    covered = set()
    for s in scored:
        covered.update(e["sha"] for e in s["R"])
    group = session_groups([g.ident(c)[1] for c in window if g.ident(c)[0] == ONE])
    per = {}
    structural = {"wraps": 0, "folds": 0, "handoff_only": 0}
    stamped = 0
    for c in window:
        kind, ident = g.ident(c)
        if kind != ONE:
            continue
        key = group(ident)
        per.setdefault(key, 0)
        if g.is_wrap(c):
            structural["wraps"] += 1
        elif g.is_fold(c):
            structural["folds"] += 1
        elif c in g.handoff_only:
            structural["handoff_only"] += 1
        else:
            stamped += 1
            if c not in covered:
                per[key] += 1
    return {"sessions": len(per), "stamped_work": stamped, "gap": sum(per.values()),
            "per_session": sorted(per.values(), reverse=True), "structural": structural}


def run_cohort_v2(repo, since, until, tip, json_path):
    tip_sha = git(repo, "rev-parse", "--verify", (tip or "HEAD") + "^{commit}").stdout.strip()
    # --since-as-filter (git 2.37+): plain --since stops walking at the first commit dated before
    # the bound, hiding newer-dated ancestors behind it. An older git refuses the option, and that
    # refusal exits 2 (Usage); there is no fallback to --since.
    args = ["log", "--no-merges", "--no-show-signature", "--format=%H%x09%cs%x09%s", "--since-as-filter=" + since]
    if until:
        args.append("--until=" + until)
    wraps = []
    for ln in git(repo, *(args + [tip_sha, "--"])).stdout.splitlines():
        parts = ln.split("\t", 2)
        if len(parts) == 3 and parts[2].startswith(WRAP_SUBJECT):
            wraps.append((parts[0], parts[1]))
    g = Graph(repo, [tip_sha])
    blob = script_blob()
    print("wrap-completeness  %s  since %s until %s  scorer 2  tip %s  blob %s"
          % (repo, since, until or "now", tip_sha, blob))
    rows, scored = [], []
    for sha, day in reversed(wraps):
        s = score_v2(repo, sha, tip_sha, graph=g)
        scored.append(s)
        row = cohort_row(s, day)
        rows.append(row)
        if row["R"] is None:
            body = "R unavailable"
        else:
            body = "R %d (own %d, adopted %d)  pre %s  post %s  added %s" % (
                row["R"], row["own"], row["adopted"], _frac(row["cited_pre"], row["R"]),
                _frac(row["cited_post"], row["R"]), _frac(row["cited_added"], row["R"]))
        spantxt = "span -" if row["span"] is None else "span %d (v1src %d, v2src %d)" % (
            row["span"], row["span_cited_v1src"], row["span_cited_v2src"])
        marks = ""
        if row["markers_malformed"] or row["markers_orphan"]:
            marks = "  markers malformed %d orphan %d" % (row["markers_malformed"], row["markers_orphan"])
        print("  %s  %s  %s  %s  folds %s%s  wf %s  %s" % (
            row["wrap"], day, body, spantxt, ",".join(row["folds"]) or "none", marks, row["workflow"],
            "eligible" if row["eligible"] else "INELIGIBLE " + ",".join(row["reasons"])))
    elig = [r for r in rows if r["eligible"]]
    reasons = {}
    for r in rows:
        if not r["eligible"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    print("DENOMINATOR  wraps found %d · eligible %d · ineligible %d%s" % (
        len(rows), len(elig), len(rows) - len(elig),
        ("  (" + ", ".join("%s %d" % kv for kv in sorted(reasons.items())) + ")") if reasons else ""))
    # Eligibility already requires |R| > 0; the filter keeps a broken eligibility rule visible as a
    # wrong denominator above rather than a crash here.
    scorable = [r for r in elig if r["R"]]
    post = [(r["R"], r["cited_post"] / r["R"]) for r in scorable]
    pre = [(r["R"], r["cited_pre"] / r["R"]) for r in scorable]
    added = [(r["R"], r["cited_added"] / r["R"]) for r in scorable]
    unk = [(r["R"] + r["unknown_I"], (r["cited_post"] + r["unknown_cited_I"]) / (r["R"] + r["unknown_I"]))
           for r in scorable]
    spans = [r for r in rows if r["span"]]
    span_v1 = [(r["span"], r["span_cited_v1src"] / r["span"]) for r in spans]
    span_v2 = [(r["span"], r["span_cited_v2src"] / r["span"]) for r in spans]
    summary = {"wraps_found": len(rows), "eligible": len(elig), "ineligible": len(rows) - len(elig),
               "ineligible_reasons": reasons,
               "primary_post": _r4(mix_adjusted(post)), "primary_pre": _r4(mix_adjusted(pre)),
               "buckets_post": _buckets(post), "buckets_pre": _buckets(pre),
               "median_post": _r4(statistics.median(f for _n, f in post)) if post else None,
               "median_pre": _r4(statistics.median(f for _n, f in pre)) if pre else None,
               "unknown_as_R": _r4(mix_adjusted(unk)), "added_lines": _r4(mix_adjusted(added)),
               "span_rows": len(spans), "span_v1src": _r4(mix_adjusted(span_v1)),
               "span_v2src": _r4(mix_adjusted(span_v2))}
    sw = session_wide(repo, g, since, until, tip_sha, scored)

    def num(v):
        return "--" if v is None else "%.4f" % v
    print("primary: mix-adjusted mean of post-fold coverage_R (gate.md section 3 PRE weights) %s over %d "
          "eligible wrap(s); pre-fold %s" % (num(summary["primary_post"]), len(elig), num(summary["primary_pre"])))
    for name, _w in WEIGHTS:
        b = summary["buckets_post"][name]
        print("  |R| %-4s post-fold mean %s  median %s  n %d" % (name, num(b["mean"]), num(b["median"]), b["n"]))
    print("secondary: pooled median post-fold %s, pre-fold %s" % (num(summary["median_post"]), num(summary["median_pre"])))
    print("sensitivity: UNKNOWN in I counted as responsibility %s" % num(summary["unknown_as_R"]))
    print("sensitivity: added-lines sources %s" % num(summary["added_lines"]))
    print("sensitivity: span-wide v1-style coverage over %d row(s) with a span: v1 sources %s, v2 sources %s"
          % (len(spans), num(summary["span_v1src"]), num(summary["span_v2src"])))
    print("session-wide: %d session(s) stamped in the window; %d eligible stamped work commit(s), %d in no "
          "wrap's R; per session %s; structural (not counted) wraps %d, folds %d, HANDOFF-only %d" % (
              sw["sessions"], sw["stamped_work"], sw["gap"], sw["per_session"], sw["structural"]["wraps"],
              sw["structural"]["folds"], sw["structural"]["handoff_only"]))
    if not elig:
        print("INVALID: no wrap in the range is eligible")
        code = 2
    else:
        code = 0
    if json_path:
        with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"scorer": 2, "blob": blob, "repo": repo, "since": since, "until": until, "tip": tip_sha,
                       "wraps": rows, "summary": summary, "session_wide": sw}, fh, indent=1, sort_keys=True)
            fh.write("\n")
    return code


# ==============================================================================================
# --candidates: the window a wrap made now would be scored on, for update-context's Step 1
# (design component 3: "the evidence step shows the OTHER sessions with commits in the candidate
# interval, by id and count"). Read-only; always scorer 2's rules. Nothing above changes for it.
# ==============================================================================================

PENDING = "pending-wrap"  # the pending wrap's key in the graph; no git object name can equal it
NO_SESSION = {
    "no-session-id": "CLAUDE_CODE_SESSION_ID unset; pass --session",
    "bad-session-id": "CLAUDE_CODE_SESSION_ID is not a session id (a UUID); pass --session",
    "bad-host-id": ("CLAUDE_CODE_HOST_SESSION_ID is malformed, so the hook stamps nothing (bad-host-id); "
                    "pass --session"),
}


def session_from_env(env=None):
    """(value, None) for this session's Claude-Session value, or (None, reason): built from
    CLAUDE_CODE_SESSION_ID and CLAUDE_CODE_HOST_SESSION_ID exactly as guard_cards.py's
    session_value() builds the stamp the hook writes (the suite compares the two, G#415). The CLI
    id must be a UUID; an app id, when set, must be local_<UUID>, and a malformed one is refused
    (bad-host-id) the way the card then stamps nothing -- never the CLI id alone."""
    env = os.environ if env is None else env
    cli, app = env.get("CLAUDE_CODE_SESSION_ID"), env.get("CLAUDE_CODE_HOST_SESSION_ID")
    if not cli:
        return None, "no-session-id"
    if not CLI_ID_RE.fullmatch(cli):
        return None, "bad-session-id"
    if not app:
        return cli, None
    if not APP_ID_RE.fullmatch(app):
        return None, "bad-host-id"
    return cli + " " + app, None


def add_pending_wrap(g, tip, value):
    """Place on g the wrap this session would commit at `tip` now: parent `tip`, Claude-Session
    `value`, a `Session update` subject, no fold, adoption or workflow values, not a merge and not
    HANDOFF-only. It goes first in g.order and g.wraps (it is the newest commit), so bound()
    computes for it what score_v2() will compute for the real wrap, whose own stamp counts in
    bound() the same way. Returns its key."""
    p = PENDING
    g.order.insert(0, p)
    g.wraps.insert(0, p)
    g.parents[p] = [tip]
    g.date[p] = ""
    g.subject[p] = WRAP_SUBJECT + ": (pending)"
    g.values[p] = [value]
    g.fold_values[p], g.adopts[p], g.workflow[p] = [], [], []
    return p


def candidates(repo, w_value, tip=None):
    """The window a wrap by session `w_value` committed at `tip` (default HEAD) would be scored on,
    classified the way score_v2() classifies I with no adoption. A dict: tip, W, bound, how
    (bound()'s), carried (whether a commit below the tip carries the session), upstream (the
    checked-out branch's, or None), window (its work commits, newest first; None when nothing
    bounds it), classes and subjects by sha, own, other ([{id, shas, commits, on_upstream}], most
    commits first; on_upstream None with no upstream), unknown, conflict ([{sha, ids, carries}]).
    print_candidates() formats it. Raises Usage for an invalid value or a git failure."""
    w = parse_session(w_value.strip())
    if w is None:
        raise Usage("%r is not a Claude-Session value (<uuid> or <uuid> local_<uuid>)" % (w_value,))
    tip_sha = git(repo, "rev-parse", "--verify", (tip or "HEAD") + "^{commit}").stdout.strip()
    up = git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}", check=False)
    upstream = up.stdout.strip() if up.returncode == 0 else ""
    up_sha = git(repo, "rev-parse", "--verify", upstream + "^{commit}").stdout.strip() if upstream else None
    # Read from the tip alone, as score_v2() reads it for the wrap: with another start (the
    # upstream) git's --topo-order can order unrelated lines differently (measured on git 2.53),
    # and bound() takes the first wrap in that order as the newest, so a wider read moves L.
    g = Graph(repo, [tip_sha])
    p = add_pending_wrap(g, tip_sha, show_value(w))

    def match(i):
        return same_session(i, w)
    b, how = bound(g, p, match)
    out = {"scorer": 2, "tip": tip_sha, "W": show_value(w), "bound": b, "how": how,
           "carried": any(c != p and carries(g, c, match) for c in g.order),
           "upstream": upstream or None, "window": None, "classes": {}, "subjects": {}, "own": [],
           "other": [], "unknown": [], "conflict": []}
    if b is None and how == "none":
        return out
    win = (g.ancestors(p) - g.ancestors(b) - {p}) if b is not None else frozenset()
    work = [c for c in g.order if c in win and g.is_work(c)]
    on_up = set()
    if up_sha and work:
        on_up = set(git(repo, "rev-list", up_sha, "^" + b, "--").stdout.split())
    group = session_groups([g.ident(c)[1] for c in work if g.ident(c)[0] == ONE])
    others = {}
    for c in work:
        kind, ident = g.ident(c)
        cls = (OWN if same_session(ident, w) else OTHER) if kind == ONE else kind
        out["classes"][c] = cls
        out["subjects"][c] = g.subject[c]
        if cls == OWN:
            out["own"].append(c)
        elif cls == OTHER:
            others.setdefault(group(ident), []).append(c)
        elif cls == UNKNOWN:
            out["unknown"].append(c)
        else:
            out["conflict"].append({"sha": c, "ids": sorted(set(v[1] or v[0] for v in ident)),
                                    "carries": any(same_session(v, w) for v in ident)})
    out["window"] = work
    out["other"] = [{"id": k, "shas": v, "commits": len(v),
                     "on_upstream": sum(1 for c in v if c in on_up) if up_sha else None}
                    for k, v in sorted(others.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    return out


def print_candidates(c):
    print("candidates for a wrap at %s; session %s; scorer 2" % (c["tip"][:9], c["W"]))
    if c["window"] is None:
        print("  bound: NOTHING (no earlier wrap; the wrap will read ineligible no-bound)")
        return 0
    if c["bound"] is None:
        print("  bound: - (no commit carries this session)")
    else:
        what = ("this session's previous wrap" if c["how"] == "previous" else
                "the last wrap before its first commit" if c["carried"] else "the last wrap before this point")
        print("  bound: %s (%s)" % (c["bound"][:9], what))
    n = dict((k, sum(1 for v in c["classes"].values() if v == k)) for k in (OWN, OTHER, UNKNOWN, CONFLICT))
    print("  window: %d work commit(s): OWN %d · OTHER %d · UNKNOWN %d · CONFLICT %d"
          % (len(c["window"]), n[OWN], n[OTHER], n[UNKNOWN], n[CONFLICT]))
    print("  OWN (cite each one as you write): %d" % len(c["own"]))
    for sha in c["own"]:
        print("    OWN        %s  %s" % (sha[:9], c["subjects"][sha]))
    print("  OTHER sessions (adopt only a session this session started, or whose unpublished work it merged, "
          "fast-forwarded or cherry-picked here): %d" % len(c["other"]))
    for o in c["other"]:
        where = "%d already on %s" % (o["on_upstream"], c["upstream"]) if c["upstream"] else "no upstream"
        print("    %s  %d commit(s), %s" % (o["id"], o["commits"], where))
    print("  UNKNOWN (no stamp; write one up only if this session made it): %d" % len(c["unknown"]))
    for sha in c["unknown"]:
        print("    UNKNOWN    %s  %s" % (sha[:9], c["subjects"][sha]))
    print("  CONFLICT: %d" % len(c["conflict"]))
    for e in c["conflict"]:
        print("    CONFLICT   %s  %s  (valid ids: %s; carries this session: %s)" % (
            e["sha"][:9], c["subjects"][e["sha"]], ", ".join(e["ids"]) or "none", "yes" if e["carries"] else "no"))
    return 0


def run_candidates(a):
    """--candidates from the parsed arguments: the view printed, exit 0; Usage (exit 2) otherwise."""
    if a.wrap or a.since:
        raise Usage("--candidates cannot be combined with --wrap or --since")
    if a.until or a.json:
        raise Usage("--until and --json apply to --since only")
    if a.session is not None:
        value = a.session
    else:
        value, why = session_from_env()
        if value is None:
            raise Usage(NO_SESSION[why])
    return print_candidates(candidates(a.repo, value, a.tip))


# ==============================================================================================
# --sessions: where the work of the sessions this session started sits, for update-context's
# Steps 1 and 7 and device-handoff's Step 1 (docs/superpowers/specs/2026-10-30-closing-mode-
# design.md, component C4). Read-only. A commit counts for a token exactly when scorer 2 counts it
# ADOPTED for that Adopts-Session line. Nothing above changes for it.
# ==============================================================================================

INCOMPLETE = "inspection incomplete"


def session_token(raw):
    """One id exactly as an `Adopts-Session:` line takes it (adoption()'s grammar: a CLI uuid or
    local_<uuid>), lowercased as adoption() lowercases it. A `<cli> <app>` Claude-Session pair, or
    anything else, is a Usage error."""
    tok = raw.strip()
    if CLI_ID_RE.fullmatch(tok) or APP_ID_RE.fullmatch(tok):
        return tok.lower()
    if parse_session(tok) is not None:
        raise Usage("%r is a <cli> <app> pair: --sessions takes one id per token, the CLI id or the app id, as an "
                    "Adopts-Session line does" % raw)
    raise Usage("%r is not a session id: a token is a CLI uuid or local_<uuid>, as an Adopts-Session line takes it"
                % raw)


def adopts(g, c, token):
    """Whether `Adopts-Session: <token>` covers commit c: scorer 2 counts it ADOPTED under that line
    exactly when c carries one valid stamp whose CLI id or app id is the token -- in_adopted(), the
    function score_v2's classify() and its adopted-session match both call. Never same_session():
    an app-id line does not cover that session's CLI id stamped alone."""
    kind, ident = g.ident(c)
    return kind == ONE and in_adopted(ident, {token})


def worktree_list(repo):
    """Every worktree of the repository (`git worktree list --porcelain -z`), the main one first:
    dicts with path, head (the sha git printed, or None), branch (refs/heads/..., or None),
    detached, prunable, bare and main."""
    out = git(repo, "worktree", "list", "--porcelain", "-z").stdout
    entries, cur = [], None
    for field in out.split("\x00"):
        if not field:
            if cur is not None:
                entries.append(cur)
            cur = None
            continue
        key, _, val = field.partition(" ")
        if key == "worktree":
            if cur is not None:
                entries.append(cur)
            cur = {"path": val, "head": None, "branch": None, "detached": False, "prunable": False, "bare": False}
        elif cur is None:
            raise Usage("%s: could not parse git worktree list's output" % INCOMPLETE)
        elif key == "HEAD":
            cur["head"] = val
        elif key == "branch":
            cur["branch"] = val
        elif key in ("detached", "prunable", "bare"):
            cur[key] = True
    if cur is not None:
        entries.append(cur)
    for i, e in enumerate(entries):
        e["main"] = i == 0
    return entries


def norm_path(p):
    return os.path.normcase(os.path.realpath(p))


def branch_label(e):
    if e["branch"]:
        return e["branch"][len("refs/heads/"):] if e["branch"].startswith("refs/heads/") else e["branch"]
    return "detached HEAD" if e["detached"] else "HEAD unreadable"


def uncommitted(path):
    """The uncommitted changes in the worktree at path: `git status --porcelain` entries, tracked
    changes and untracked files (every one, whatever status.showUntrackedFiles says); ignored files
    are not counted. Raises Usage when git cannot read it."""
    out = git(path, "status", "--porcelain", "--untracked-files=all").stdout
    return sum(1 for ln in out.split("\n") if ln.strip())


def sessions(repo, tokens, folders=()):
    """The --sessions report as a structure (print_sessions() formats it). tokens: session_token()
    ids; folders: [(token, path)]. What cannot be read is listed in `incomplete`, never read as
    absent; Usage when HEAD, the branch list or the worktree list cannot be read at all."""
    head = git(repo, "rev-parse", "--verify", "HEAD^{commit}", check=False)
    if head.returncode != 0:
        raise Usage("%s: HEAD (%s)" % (INCOMPLETE, head.stderr.strip() or "unreadable"))
    head_sha = head.stdout.strip()
    top = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    sym = git(repo, "symbolic-ref", "-q", "--short", "HEAD", check=False)
    incomplete = []
    # git for-each-ref skips a ref it cannot parse with only a warning on stderr: any stderr is a
    # ref it did not list, so the inspection is incomplete.
    refs = git(repo, "for-each-ref", "--format=%(refname)%00%(objectname)", "refs/heads/", check=False)
    if refs.returncode != 0:
        raise Usage("%s: the local branches (%s)" % (INCOMPLETE, refs.stderr.strip()))
    for ln in refs.stderr.splitlines():
        if ln.strip():
            incomplete.append("the local branches: git for-each-ref: %s" % ln.strip())
    branches = [tuple(ln.split("\x00", 1)) for ln in refs.stdout.splitlines() if "\x00" in ln]
    wts = worktree_list(repo)
    here = norm_path(top)
    others = [e for e in wts if not e["bare"] and norm_path(e["path"]) != here]
    # Every tip must name a readable commit; one that does not is named, never skipped.
    sources = []
    for name, sha in branches:
        if git(repo, "rev-parse", "--verify", "-q", sha + "^{commit}", check=False).returncode != 0:
            incomplete.append("%s: its object %s is missing or is not a commit" % (name, sha))
            continue
        sources.append(("branch " + (name[len("refs/heads/"):] if name.startswith("refs/heads/") else name), sha))
    # Every readable linked-worktree HEAD is a tip too, attached or detached: the worktrees are listed
    # after the branches, so a commit a started session makes on its branch in between is on its
    # worktree's HEAD alone (Codex 20261030-145300-aa3f76). A commit a branch already reaches is
    # reported under the branch only (labels()).
    wt_sources = []
    for e in others:
        sha = e["head"] or ""
        if not _SHA_RE.fullmatch(sha) or set(sha) == {"0"} or git(
                repo, "rev-parse", "--verify", "-q", sha + "^{commit}", check=False).returncode != 0:
            incomplete.append("worktree %s: its HEAD cannot be read" % e["path"])
            continue
        wt_sources.append(("worktree %s (%s%s)" % (e["path"], "branch " if e["branch"] else "", branch_label(e)), sha))
    try:
        g = Graph(repo, list(dict.fromkeys([head_sha] + [sha for _label, sha in sources + wt_sources])))
    except Usage as ex:
        raise Usage("%s: the history of the refs read (%s)" % (INCOMPLETE, ex))
    head_anc = g.ancestors(head_sha)
    apps_of = {}
    for c in g.order:
        kind, ident = g.ident(c)
        if kind == ONE and ident[1]:
            apps_of.setdefault(ident[0], set()).add(ident[1])

    def labels(c):
        """The tips that reach c, HEAD aside: every local branch that does, else every linked-worktree
        HEAD that does (a commit the branch listing covers is never listed twice)."""
        return ([label for label, sha in sources if c in g.ancestors(sha)]
                or [label for label, sha in wt_sources if c in g.ancestors(sha)])

    def where(c):
        if c in head_anc:
            return "on HEAD"
        return ", ".join(labels(c)) or "unknown"

    out_tokens = []
    for tok in tokens:
        matched = [c for c in g.order if adopts(g, c, tok)]
        on_head = [c for c in matched if c in head_anc]
        elsewhere = []
        for label, _sha in sources + wt_sources:
            got = [c for c in matched if c not in head_anc and label in labels(c)]
            if got:
                elsewhere.append({"label": label, "shas": got})
        pairs = []
        if tok.startswith("local_"):
            for cli in sorted(c for c, apps in apps_of.items() if tok in apps):
                alone = [c for c in g.order if g.ident(c) == (ONE, (cli, None))]
                if alone:
                    pairs.append({"cli": cli, "apps": sorted(apps_of[cli]), "alone": alone,
                                  "where": [where(c) for c in alone], "ambiguous": len(apps_of[cli]) > 1})
        out_tokens.append({"token": tok, "on_head": on_head, "elsewhere": elsewhere, "pairs": pairs, "folders": []})
    by_token = dict((t["token"], t) for t in out_tokens)
    claimed = {here}
    for tok, path in folders:
        f = {"path": path, "where": None, "uncommitted": None, "branch": None, "branch_name": None, "here": False,
             "head": None}
        try:
            ftop = git(path, "rev-parse", "--show-toplevel").stdout.strip()
        except Usage as ex:
            incomplete.append("folder %s=%s: %s" % (tok, path, ex))
            continue
        hit = [e for e in wts if norm_path(e["path"]) == norm_path(ftop)]
        if not hit:
            f["where"] = "not a worktree of this repository"
        else:
            claimed.add(norm_path(ftop))
            try:
                f["uncommitted"] = uncommitted(ftop)
            except Usage as ex:
                incomplete.append("folder %s=%s: %s" % (tok, path, ex))
                continue
            f["where"] = "the main worktree" if hit[0]["main"] else "linked worktree"
            f["branch"] = ("branch " if hit[0]["branch"] else "") + branch_label(hit[0])
            f["branch_name"] = branch_label(hit[0]) if hit[0]["branch"] else None
            f["here"] = norm_path(ftop) == here
            f["head"] = hit[0]["head"]
        by_token[tok]["folders"].append(f)
    unassigned = []
    for e in others:
        if e["main"] or norm_path(e["path"]) in claimed:
            continue
        if not os.path.isdir(e["path"]):
            if not e["prunable"]:
                incomplete.append("worktree %s: its folder is missing" % e["path"])
            continue  # git lists it prunable: no working tree, so nothing uncommitted can be there
        try:
            n = uncommitted(e["path"])
        except Usage as ex:
            incomplete.append("worktree %s: %s" % (e["path"], ex))
            continue
        if n:
            unassigned.append({"path": e["path"], "branch": branch_label(e), "uncommitted": n})
    return {"repo": top, "head": head_sha, "head_branch": sym.stdout.strip() if sym.returncode == 0 else None,
            "branches": len(branches), "worktrees": len(others), "incomplete": list(dict.fromkeys(incomplete)),
            "tokens": out_tokens, "unassigned": unassigned, "subjects": g.subject, "graph": g}


def print_sessions(s):
    """The report; exit 0, or 2 when something could not be read."""
    subj = s["subjects"]
    none_left = " in the refs read (%s)" % INCOMPLETE if s["incomplete"] else ""
    print("sessions in %s at HEAD %s (%s); read: HEAD, %d local branch(es), %d other worktree(s)" % (
        s["repo"], s["head"][:9], s["head_branch"] or "detached", s["branches"], s["worktrees"]))
    for what in s["incomplete"]:
        print("%s: %s" % (INCOMPLETE, what))
    for t in s["tokens"]:
        print("session %s:" % t["token"])
        if not t["on_head"] and not t["elsewhere"]:
            print("  no matching stamped commits found%s" % none_left)
        else:
            print("  on HEAD: %d commit(s)" % len(t["on_head"]))
            for c in t["on_head"]:
                print("    %s  %s" % (c[:9], subj[c]))
            if t["elsewhere"]:
                n = len(set(c for grp in t["elsewhere"] for c in grp["shas"]))
                print("  elsewhere: %d commit(s) HEAD does not reach" % n)
                for grp in t["elsewhere"]:
                    print("    %s: %d commit(s)" % (grp["label"], len(grp["shas"])))
                    for c in grp["shas"]:
                        print("      %s  %s" % (c[:9], subj[c]))
            else:
                print("  elsewhere: none%s" % none_left)
        for p in t["pairs"]:
            if p["ambiguous"]:
                print("  paired CLI id %s: ambiguous, seen with %d app ids (%s); its %d commit(s) stamped with it alone "
                      "are not attributed, never resolved" % (p["cli"], len(p["apps"]), ", ".join(p["apps"]),
                                                              len(p["alone"])))
                continue
            print("  paired CLI id %s: %d commit(s) stamped with it alone, which Adopts-Session: %s does not cover"
                  % (p["cli"], len(p["alone"]), t["token"]))
            for c, w in zip(p["alone"], p["where"]):
                print("    %s  %s  (%s)" % (c[:9], subj[c], w))
            print("    extra line that covers them: Adopts-Session: %s" % p["cli"])
        for f in t["folders"]:
            if f["uncommitted"] is None:
                print("  folder %s: %s" % (f["path"], f["where"]))
            else:
                print("  folder %s: %d uncommitted; %s; %s" % (f["path"], f["uncommitted"], f["where"], f["branch"]))
    for u in s["unassigned"]:
        print("unassigned worktree: %s (%s), %d uncommitted" % (u["path"], u["branch"], u["uncommitted"]))
    return 2 if s["incomplete"] else 0


def run_sessions(a):
    """--sessions from the parsed arguments: the report printed (exit 0, or 2 when something could
    not be read); Usage (exit 2) otherwise."""
    if a.wrap or a.since or a.candidates:
        raise Usage("--sessions cannot be combined with --wrap, --since or --candidates")
    if a.until or a.json or a.tip or a.session is not None:
        raise Usage("--until, --json, --tip and --session do not apply to --sessions")
    tokens = list(dict.fromkeys(session_token(t) for t in a.sessions))
    return print_sessions(sessions(a.repo, tokens, parse_folders(a.folder, tokens, "--sessions")))


def parse_folders(given, tokens, mode):
    """--folder TOKEN=PATH ...: [(token, path)], each token one of `mode`'s."""
    folders = []
    for f in given or ():
        tok, sep, path = f.partition("=")
        if not sep or not tok or not path:
            raise Usage("--folder takes TOKEN=PATH, not %r" % f)
        tok = session_token(tok)
        if tok not in tokens:
            raise Usage("--folder names %s, which is not one of the %s tokens" % (tok, mode))
        folders.append((tok, path))
    return folders


# ==============================================================================================
# --started: update-context's Step 1 merges what the sessions this session started finished, before
# the wrap commits. The owner's word, 2026-11-04, given in advance, is what the app's rule for
# started sessions asks for. A merge is built and checked as an object and lands by fast-forward, so
# the checkout holds no merge state at any point. Measured on a scratch repo: during a real
# `git merge --no-commit`, a sibling's `git commit -- path` fails outright, and a commit that moves
# the branch from a temp index (file-inbox.py's way) is silently reverted by the merge commit; and
# one staged file of a sibling's stops the merge from starting. Here none of those can happen.
# ==============================================================================================

MERGE_CHECK = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "device-sync",
                                            "scripts", "merge-check.py"))
MERGE_CHECK_TIMEOUT = 600  # seconds


# The landing. git's defaults would overwrite an ignored local file and, under merge.autoStash, stash
# a sibling's staged work and reapply it unstaged, each while reporting success.
FF_LAND = ("merge", "--ff-only", "--no-overwrite-ignore", "--no-autostash")


def merge_check(repo, sha):
    """device-sync's merge-check.py on one two-parent merge commit: (its exit status, its output),
    or (None, why) when it could not run, which is never a clean result."""
    if not os.path.isfile(MERGE_CHECK):
        return None, "%s is not there" % MERGE_CHECK
    try:
        r = subprocess.run([sys.executable, MERGE_CHECK, "--repo", repo, "--commit", sha], capture_output=True,
                           encoding="utf-8", errors="replace", timeout=MERGE_CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "it timed out after %ss" % MERGE_CHECK_TIMEOUT
    return r.returncode, r.stdout + r.stderr


def another_sessions(g, c, tok):
    """Whether commit c's one stamp is a different session's than tok. A CLI id stamped alone under
    a local_ token says nothing either way: the hook may not have seen the app id."""
    kind, ident = g.ident(c)
    if kind != ONE or in_adopted(ident, {tok}):
        return False
    return ident[1] is not None or not tok.startswith("local_")


def carried_off(repo, s, tok, tip, head, ahead, left_out):
    """Why merging tok's branch would also bring in a session this wrap leaves out, or None: that
    session's stamped commits in the range (a paired CLI id's alone included, which adoption does not
    cover), or commits on its folder's HEAD. When the other built on this branch (this tip is an
    ancestor of its HEAD) that HEAD adds nothing, and tok's own commits are tok's wherever they also
    sit."""
    g = s["graph"]
    by_token = dict((t["token"], t) for t in s["tokens"])

    def alone(t):
        return {c for p in by_token[t]["pairs"] for c in p["alone"]}

    own = {c for p in by_token[tok]["pairs"] if not p["ambiguous"] for c in p["alone"]}  # an ambiguous id proves no one's
    for other in left_out:
        got = {c for c in ahead if c in g.parents and adopts(g, c, other)}
        got.update(alone(other) & set(ahead))
        for f in by_token[other]["folders"]:
            if not f["head"] or f["here"] or git(repo, "merge-base", "--is-ancestor", tip, f["head"],
                                                 check=False).returncode == 0:
                continue
            theirs = set(git(repo, "rev-list", "%s..%s" % (head, f["head"])).stdout.split()) - own
            got.update(c for c in theirs if c in ahead and not (c in g.parents and adopts(g, c, tok)))
        if got:
            return "it would also bring in %d commit(s) of session %s, which this wrap leaves out" % (len(got), other)
    return None


def changed_since(repo, base, rev):
    return set(git(repo, "diff", "--name-only", "--no-renames", base, rev).stdout.splitlines())


# ----------------------------------------------------------------------------------------------
# A docket conflict that needs no decision, settled row by row. Measured on one project's evening of
# 2026-11-11/12: 7 of 26 wrap merges stopped on `conflict in continuation/memory/roadmap.md`. That
# docket keeps one row per physical line and git merges line hunks, so two sessions that each edit
# their OWN row conflict whenever the rows are adjacent. Each was settled by hand the same way, at
# about 8 tool calls apiece: in each conflict block, each line from the side that changed it; a row
# both sides changed, ours first and theirs' added text after it (the order merge-check's
# restated-fact finding forced on #399); whole lines a side added after the shared ones, kept. This
# does that on bytes and refuses everything else, which then stays NOT MERGED exactly as before. A
# row it combined from both sides' changes is settled but never landed: a person checks it first
# (merge-check's restated-fact cannot be relied on to stop it: it does not read every docket grammar).
# ----------------------------------------------------------------------------------------------

DOCKET_CORPUS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                                              "analyze-context", "scripts", "docket_corpus.py"))
# The conflict markers git merge-file writes here. A side holding a line that begins like one is
# refused: a markdown setext underline is a run of '=' and must never read as a block's separator.
MARKER_SIZE = 32
MARKS = (b"<", b"|", b"=", b">")
_LOADED = []


class Unsettled(Exception):
    """Why a conflict is not settled row-wise: the merge stays NOT MERGED, as before. `quiet`: no
    conflicted path is a docket file, so there was nothing to try and nothing to say."""

    def __init__(self, why, quiet=False):
        Exception.__init__(self, why)
        self.quiet = quiet


def docket_corpus():
    """analyze-context's docket_corpus.py, compiled from source once (rotate-docket.py's loader)."""
    if not _LOADED:
        if not os.path.isfile(DOCKET_CORPUS):
            raise Unsettled("%s is not there" % DOCKET_CORPUS)
        mod = types.ModuleType("_wrap_completeness_docket_corpus")
        mod.__file__ = DOCKET_CORPUS
        try:
            with open(DOCKET_CORPUS, encoding="utf-8") as fh:
                exec(compile(fh.read(), DOCKET_CORPUS, "exec"), mod.__dict__)
        except Exception as ex:  # noqa: BLE001 -- any failure to load is a reason not to settle
            raise Unsettled("%s could not be loaded: %s" % (DOCKET_CORPUS, ex))
        _LOADED.append(mod)
    return _LOADED[0]


def git_bytes(repo, *args, data=None, env=None):
    """git with bytes in and out: a blob is bytes, never decoded, never newline-translated."""
    try:
        return subprocess.run(["git", "-c", "core.quotePath=false", "-C", repo] + list(args), input=data,
                              capture_output=True, env=env, timeout=GIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise Usage("git %s timed out after %ss" % (" ".join(args), GIT_TIMEOUT)) from None


def _err(r):
    return " ".join(r.stderr.decode("utf-8", "replace").split())


def split_lines_kept(data):
    """`data` split after each LF; every line keeps its own ending (CRLF, LF), lone CRs inside it."""
    return [ln for ln in re.split(b"(?<=\n)", data) if ln]


def _body(line):
    """(a line without its ending, the ending)."""
    if line.endswith(b"\r\n"):
        return line[:-2], b"\r\n"
    if line.endswith(b"\n"):
        return line[:-1], b"\n"
    return line, b""


def _marker(line, mark):
    body = _body(line)[0]
    return body == mark * MARKER_SIZE or body.startswith(mark * MARKER_SIZE + b" ")


def docket_kinds(repo, paths):
    """{path: kind} for the conflicted paths that are docket files: the ones docket_corpus.py's own
    discovery finds in this checkout (what the session-start briefing and rotate-docket.py read)."""
    dc = docket_corpus()
    top = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    try:
        found = [f for f in dc.discover(project="root:" + top) if f["kind"] in dc.DOCKET_KINDS]
    except Exception as ex:  # noqa: BLE001 -- a discovery that failed found nothing to settle
        raise Unsettled("docket_corpus.py could not list this checkout's docket files: %s" % ex)
    kinds = dict((str(f["rel"]).replace("\\", "/").casefold(), f["kind"]) for f in found)
    return dict((p, kinds[p.casefold()]) for p in paths if p.casefold() in kinds)


def conflict_stages(repo, head, tip):
    """(the tree git merge-tree wrote, {path: {stage: (mode, oid)}} for each conflicted file)."""
    r = git_bytes(repo, "merge-tree", "--write-tree", "-z", "--no-messages", head, tip)
    fields = r.stdout.split(b"\0")
    tree = fields[0].decode("ascii", "replace")
    if r.returncode != 1 or not _SHA_RE.fullmatch(tree):
        raise Unsettled("git merge-tree did not report the conflict again: %s" % (_err(r) or "exit %d" % r.returncode))
    stages = {}
    for entry in fields[1:]:
        if not entry:
            break
        meta, tab, raw = entry.partition(b"\t")
        parts = meta.split(b" ")
        if not tab or len(parts) != 3 or parts[2] not in (b"1", b"2", b"3"):
            raise Unsettled("git merge-tree wrote a conflict entry this cannot read: %r" % entry[:80])
        try:
            path = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise Unsettled("a conflicted path is not UTF-8")
        stages.setdefault(path, {})[int(parts[2])] = (parts[0].decode("ascii"), parts[1].decode("ascii"))
    return tree, stages


def row_keys(dc, data, kind, name):
    """line -> the id of the row that line heads in this version, by docket_corpus's own parse of the
    whole file (a table row's id depends on its header), or None: not a row head, an id local to its
    line number, or a line that heads rows with different ids."""
    rows, _row_of, lines, _err_cfg = dc.parse_bytes(data, kind=kind, rel=name)
    heads = {}
    for r in rows:
        if not r["key"].startswith("@"):
            heads.setdefault(lines[r["line"] - 1], set()).add(r["id"])

    def key(line):
        ids = heads.get(_body(line)[0].decode("utf-8", "replace"))
        return next(iter(ids)) if ids and len(ids) == 1 else None
    return key


def _boundary(text, p):
    """Whether byte offset p starts a character of UTF-8 `text` (or is its end)."""
    return p == 0 or p == len(text) or not 0x80 <= text[p] <= 0xBF


def inserted(base, line, rightmost=True):
    """(p, added) when `line` is `base` with `added` inserted at byte p, a character boundary (the
    rightmost such p, or the leftmost), else None."""
    n, k = len(base), len(line) - len(base)
    if k <= 0:
        return None
    pre = 0
    while pre < n and base[pre] == line[pre]:
        pre += 1
    suf = 0
    while suf < n and base[n - 1 - suf] == line[len(line) - 1 - suf]:
        suf += 1
    spots = [p for p in range(n - suf, pre + 1) if _boundary(base, p)]
    if not spots:
        return None
    p = spots[-1] if rightmost else spots[0]
    return p, line[p:p + k]


def settle_row(b, o, t):
    """One row both sides changed, differently: the settled line, or None. Settled only when one
    side only inserted text and the other side's change lies wholly on ours' side of it: ours stays
    first, theirs' addition after it (a note of theirs ahead of ours' row head is the mis-order
    merge-check caught on #399). Line endings must agree on all three sides."""
    (bb, be), (ob, oe), (tb, te) = _body(b), _body(o), _body(t)
    if not be == oe == te:
        return None
    got = inserted(bb, tb, rightmost=True)
    if got:  # theirs only inserted: after everything ours changed before that point
        p, added = got
        if ob.endswith(bb[p:]):
            return ob[:len(ob) - (len(bb) - p)] + added + bb[p:] + be
    got = inserted(bb, ob, rightmost=False)
    if got:  # ours only inserted: theirs' change lies wholly after it
        p, added = got
        if tb.startswith(bb[:p]):
            return bb[:p] + added + tb[p:] + be
    return None


def _show(line):
    text = _body(line)[0].decode("utf-8", "replace")
    return text if len(text) <= 60 else text[:57] + "..."


def settle_block(base, ours, theirs, keys, path):
    """One diff3 conflict block settled row by row: (its lines, how many came from a side's change,
    the ids of the rows it combined from both sides' changes), or raise Unsettled. A line is taken
    positionally only when it is one row on all three sides: every line a side changed must head the
    row with the merge base line's id, which also refuses a side that inserted or deleted a line
    inside the block (its rows no longer line up)."""
    n = len(base)
    if len(ours) < n or len(theirs) < n:
        raise Unsettled("%s: a side has fewer lines than the merge base in a conflict block" % path)
    out, rows, combined = [], 0, []
    for i in range(n):
        b, o, t = base[i], ours[i], theirs[i]
        row = keys["base"](b)
        for side, x in (("ours", o), ("theirs", t)):
            if x != b and (row is None or keys[side](x) != row):
                raise Unsettled("%s: a line %s changed in a conflict block is not one row on all three sides: %s"
                                % (path, side, _show(x)))
        if o == t or t == b:
            line = o
        elif o == b:
            line = t
        else:
            line = settle_row(b, o, t)
            if line is None:
                raise Unsettled("%s: both sides changed row %s and neither only inserted text clear of the "
                                "other's change" % (path, row))
            combined.append(row)
        out.append(line)
        rows += line != b
    more_o, more_t = ours[n:], theirs[n:]
    if more_o and more_t and more_o != more_t and set(more_o) & set(more_t):
        raise Unsettled("%s: both sides added lines after the shared ones, some of them the same" % path)
    added = more_o + ([] if more_t == more_o else more_t)
    return out + added, rows + len(added), combined


def settle_file(repo, path, kind, stages):
    """A conflicted docket file's merge with each conflict block settled row by row: (its bytes,
    conflict blocks, rows from a side, ids of rows combined from both sides), or raise Unsettled."""
    if sorted(stages) != [1, 2, 3]:
        raise Unsettled("%s: not a change on both sides of one merge-base version (added, deleted or renamed)"
                        % path)
    modes = set(mode for mode, _oid in stages.values())
    if len(modes) != 1 or not modes <= {"100644", "100755"}:
        raise Unsettled("%s: not the same regular file mode on all three sides" % path)
    dc = docket_corpus()
    data = {}
    for side, stage in (("base", 1), ("ours", 2), ("theirs", 3)):
        got = git_bytes(repo, "cat-file", "blob", stages[stage][1])
        if got.returncode != 0:
            raise Unsettled("%s: git cat-file failed: %s" % (path, _err(got)))
        blob = got.stdout
        if blob and not blob.endswith(b"\n"):  # git merge-file would add the missing line ending
            raise Unsettled("%s: the last line of the %s version has no line ending" % (path, side))
        if any(_marker(ln, mark) for ln in split_lines_kept(blob) for mark in MARKS):
            raise Unsettled("%s: a line of the %s version begins like a conflict marker" % (path, side))
        data[side] = blob
    keys = dict((side, row_keys(dc, data[side], kind, posixpath.basename(path))) for side in data)
    tmp = tempfile.mkdtemp(prefix="wrap-merge-rows-")
    try:
        files = []
        for side in ("ours", "base", "theirs"):
            files.append(os.path.join(tmp, side))
            with open(files[-1], "wb") as fh:
                fh.write(data[side])
        r = git_bytes(repo, "merge-file", "-p", "--diff3", "--diff-algorithm=histogram",
                      "--marker-size=%d" % MARKER_SIZE, "-L", "ours", "-L", "base", "-L", "theirs", *files)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not 0 < r.returncode < 128:
        raise Unsettled("%s: git merge-file found no conflict to settle, or failed: %s"
                        % (path, _err(r) or "exit %d" % r.returncode))
    lines, merged, blocks, rows, combined, i = split_lines_kept(r.stdout), [], 0, 0, [], 0
    while i < len(lines):
        if _marker(lines[i], b"<"):
            part, side = {"ours": []}, "ours"
            i += 1
            while True:
                if i == len(lines):
                    raise Unsettled("%s: a conflict block git merge-file wrote never closes" % path)
                ln, nxt = lines[i], {"ours": b"|", "base": b"=", "theirs": b">"}[side]
                if _marker(ln, nxt):
                    if side == "theirs":
                        break
                    side = {"ours": "base", "base": "theirs"}[side]
                    part[side] = []
                elif any(_marker(ln, mark) for mark in MARKS):
                    raise Unsettled("%s: git merge-file wrote conflict markers out of order" % path)
                else:
                    part[side].append(ln)
                i += 1
            got, n, both = settle_block(part["base"], part["ours"], part["theirs"], keys, path)
            merged += got
            blocks += 1
            rows += n
            combined += both
        elif any(_marker(lines[i], mark) for mark in MARKS):
            raise Unsettled("%s: git merge-file wrote a conflict marker outside a block" % path)
        else:
            merged.append(lines[i])
        i += 1
    return b"".join(merged), blocks, rows, combined


def settle_docket_conflict(repo, head, tip, paths):
    """The merge of head and tip with each conflict settled row by row: (its tree, {path: (conflict
    blocks, rows, ids of rows combined from both sides)}), or raise Unsettled when a conflict is
    outside a docket file or is not one this settles. Writes only objects: the settled blobs, and a
    tree built in a throwaway index."""
    kinds = docket_kinds(repo, paths)
    if not kinds:
        raise Unsettled("no conflicted file is a docket file", quiet=True)
    others = [p for p in paths if p not in kinds]
    if others:
        raise Unsettled("%s %s not a docket file" % (", ".join(others), "is" if len(others) == 1 else "are"))
    tree, stages = conflict_stages(repo, head, tip)
    if sorted(stages) != sorted(paths):
        raise Unsettled("git merge-tree named other conflicted files on a second run: %s" % ", ".join(sorted(stages)))
    settled, entries = {}, []
    for path in sorted(stages):
        data, blocks, rows, combined = settle_file(repo, path, kinds[path], stages[path])
        made = git_bytes(repo, "hash-object", "-w", "--stdin", data=data)  # stdin: no filters, the bytes as given
        if made.returncode != 0:
            raise Unsettled("git hash-object failed: %s" % _err(made))
        entries.append("%s,%s,%s" % (stages[path][2][0], made.stdout.decode("ascii").strip(), path))
        settled[path] = (blocks, rows, combined)
    tmp = tempfile.mkdtemp(prefix="wrap-merge-rows-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        for args in [("read-tree", tree)] + [("update-index", "--cacheinfo", e) for e in entries] + [("write-tree",)]:
            r = git_bytes(repo, *args, env=env)
            if r.returncode != 0:
                raise Unsettled("git %s failed: %s" % (args[0], _err(r)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return r.stdout.decode("ascii").strip(), settled


def settled_words(settled):
    """'N docket row(s) row-wise' and the per-file detail, for the report and the merge commit."""
    rows = sum(n for _b, n, _c in settled.values())
    detail = "; ".join("%s (%d conflict block(s), %d row(s))" % (p, b, n) for p, (b, n, _c) in sorted(settled.items()))
    return "%d docket row(s) row-wise" % rows, detail


def combined_rows(settled):
    """'<path> <id>, <id>; ...' for the rows a settlement combined from both sides' changes, or ''.
    Such a merge is never landed by this tool: merge-check's restated-fact reads only some docket
    grammars (not a numbered row, not a table row with a bare number) and only some file names, so
    the hold is the settlement's own, by the row ids it combined, whatever merge-check says."""
    return "; ".join("%s %s" % (p, ", ".join(c)) for p, (_b, _n, c) in sorted(settled.items()) if c)


def merge_branch(repo, tok, branch, s, left_out):
    """One started session's branch into HEAD, or the reason it stays out. Nothing changes until the
    final fast-forward, which git refuses, changing nothing, when HEAD moved, a dirty or untracked
    file would be overwritten, or a merge is already in progress (that merge is someone else's: it
    is never aborted). Returns merged (the commit), nothing (HEAD reaches the branch), or why."""
    g, head_branch = s["graph"], s["head_branch"]
    m = {"token": tok, "branch": branch, "merged": None, "nothing": False, "why": None, "findings": [], "both": [],
         "ahead": 0, "mine": 0, "by_hand": False, "settled": None, "commit": None}
    ref = "refs/heads/" + branch  # a tag of the same name would win over the bare name
    got = git(repo, "rev-parse", "--verify", "-q", ref + "^{commit}", check=False)
    if got.returncode != 0:
        m["why"] = "no local branch %s in this repository" % branch
        return m
    tip = got.stdout.strip()
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    ahead = git(repo, "rev-list", "%s..%s" % (head, tip)).stdout.split()
    if not ahead:
        m["nothing"] = True
        return m
    m["ahead"] = len(ahead)
    if head_branch is None:
        m["why"] = "HEAD is detached, so there is no branch to merge into"
        return m
    if any(c not in g.parents for c in ahead):
        m["why"] = "it moved after it was inspected: run this check again"
        return m
    work = [c for c in ahead if c in g.parents and not g.is_merge(c)]
    m["mine"] = sum(1 for c in work if adopts(g, c, tok))
    if work and all(another_sessions(g, c, tok) for c in work):
        m["why"] = "every commit on it carries another session's stamp"
        return m
    m["why"] = carried_off(repo, s, tok, tip, head, ahead, left_out)
    if m["why"]:
        return m
    base = git(repo, "merge-base", head, tip, check=False)
    if base.returncode != 0:
        m["why"] = "it shares no history with HEAD"
        return m
    base = base.stdout.strip()
    m["both"] = sorted(changed_since(repo, base, head) & changed_since(repo, base, tip))
    built = git(repo, "merge-tree", "--write-tree", "-z", "--name-only", "--no-messages", head, tip, check=False)
    fields = built.stdout.split("\x00")
    tree = fields[0]
    if built.returncode == 1 and _SHA_RE.fullmatch(fields[0]):
        paths = [f for f in fields[1:] if f]
        try:
            tree, m["settled"] = settle_docket_conflict(repo, head, tip, paths)
        except Unsettled as ex:
            m["why"] = "conflict in %s" % ", ".join(paths) + ("" if ex.quiet else "; not settled row-wise: %s" % ex)
            m["by_hand"] = True
            return m
    elif built.returncode != 0:
        m["why"] = "git merge-tree failed (it needs git 2.38 or later): %s" % " ".join(built.stderr.split())
        return m
    msg = ["-m", "Merge started session's branch %s into %s" % (branch, head_branch),
           "-m", "Session: %s. %d commit(s). Wrap merge: merge-check clean, verify loop not run." % (tok, len(ahead))]
    if m["settled"]:
        msg += ["-m", "Docket conflict settled row by row: %s: %s." % settled_words(m["settled"])]
    value, _why = session_from_env()
    if value:
        msg += ["-m", "%s: %s" % (SESSION_KEY, value)]
    made = git(repo, "commit-tree", tree, "-p", head, "-p", tip, *msg, check=False)
    if made.returncode != 0:
        m["why"] = "git commit-tree failed: %s" % " ".join(made.stderr.split())
        return m
    commit = m["commit"] = made.stdout.strip()
    rc, out = merge_check(repo, commit)
    if rc is None:
        m["why"] = "merge-check could not run: %s" % out
        return m
    if rc != 0:
        m["why"] = "merge-check findings"
        m["findings"] = [ln for ln in out.splitlines() if ln.startswith(("FINDING", "UNUSED"))] or out.splitlines()
        m["by_hand"] = True
        return m
    both = combined_rows(m["settled"]) if m["settled"] else ""
    if both:
        m["why"] = ("rows both sides changed were combined, ours first and theirs' addition after it (%s): a person "
                    "checks each before it lands" % both)
        m["by_hand"] = True
        return m
    landed = git(repo, *FF_LAND, commit, check=False)
    if landed.returncode != 0:
        m["why"] = "git refused the fast-forward: %s" % " ".join((landed.stderr or landed.stdout).split())
        return m
    m["merged"] = commit
    return m


def print_merge(m):
    print("merge session %s, branch %s:" % (m["token"], m["branch"]))
    if m["nothing"]:
        print("  nothing to merge: HEAD reaches it")
    elif m["merged"]:
        print("  MERGED %d commit(s), %d with its stamp, as %s; %sran merge-check (clean); did not run the verify loop"
              % (m["ahead"], m["mine"], m["merged"][:9],
                 "settled %s; " % settled_words(m["settled"])[0] if m["settled"] else ""))
        if m["settled"]:
            print("  settled row by row: %s" % settled_words(m["settled"])[1])
        print("  both sides changed %s" % ("%d file(s): %s" % (len(m["both"]), ", ".join(m["both"])) if m["both"]
                                           else "no file"))
    else:
        print("  NOT MERGED: %s; nothing changed" % m["why"])
        for ln in m["findings"]:
            print("    %s" % ln)
        if m["by_hand"]:
            print("  by hand, in a worktree, so this checkout never holds a merge: git worktree add --detach <path> HEAD")
            print("    there: git merge --no-ff --no-edit refs/heads/%s; settle and check it under device-sync Step 1a"
                  % m["branch"])
            if m["settled"] and m["commit"]:
                print("    the docket conflict is already settled row by row (%s) in %s: there, git checkout %s -- %s "
                      "takes it; check a combined or restated row against live source before you land it"
                      % (settled_words(m["settled"])[1], m["commit"][:9], m["commit"], " ".join(sorted(m["settled"]))))
                if combined_rows(m["settled"]):  # whatever merge-check said: it does not read every row grammar
                    print("    rows it combined from both sides' changes, ours first, each to check: %s"
                          % combined_rows(m["settled"]))
            print("    here: git %s <its sha>; if HEAD moved it refuses: merge HEAD there and repeat" % " ".join(FF_LAND))


def uncommitted_paths(path):
    """The paths uncommitted() counts."""
    out = git(path, "status", "--porcelain", "--untracked-files=all").stdout
    return [ln[3:] for ln in out.split("\n") if ln.strip()]


def open_items(repo, s, merged, running, named):
    """One line per thing that withholds the wrap's closing line, read after the merges."""
    items = []
    head = s["head"]
    for t in s["tokens"]:
        tok = t["token"]
        m = merged.get(tok)
        if tok in running:
            items.append("session %s: still running; never stopped, never merged: ask whether to wait" % tok)
        elif tok not in named and tok not in merged:
            items.append("session %s: no --merge, --is-running or --name-only given" % tok)
        lead = "session %s: " % tok
        if tok in named:
            lead += "named only (%s): " % named[tok]
        failed = "branch %s" % m["branch"] if m and m["why"] else None
        if failed:
            items.append("branch %s (session %s): %s" % (m["branch"], tok, m["why"]))
        seen = set()
        for grp in t["elsewhere"]:
            seen.update(grp["shas"])
            if grp["label"] != failed:
                items.append("%s%d commit(s) on %s HEAD does not reach" % (lead, len(grp["shas"]), grp["label"]))
        for p in t["pairs"]:
            off = [(c, w) for c, w in zip(p["alone"], p["where"]) if c not in s["graph"].ancestors(head)]
            seen.update(c for c, _w in off)
            if off and p["ambiguous"]:
                items.append("session %s: paired CLI id %s is ambiguous (%d app ids): %d commit(s) HEAD does not "
                             "reach, not attributed" % (tok, p["cli"], len(p["apps"]), len(off)))
            elif off:
                items.append("%s%d commit(s) stamped with paired CLI id %s alone, on %s, HEAD does not reach"
                             % (lead, len(off), p["cli"], "; ".join(sorted({w for _c, w in off}))))
        looked = bool(m and m["branch"])
        for f in t["folders"]:
            if f["uncommitted"] is None:
                items.append("session %s: folder %s: %s: not checked here" % (tok, f["path"], f["where"]))
                continue
            looked = True
            if f["here"]:
                continue  # this checkout: its dirty paths and its commits are the wrap's own
            if f["uncommitted"]:
                paths = uncommitted_paths(f["path"])
                items.append("session %s: folder %s: %d uncommitted, never committed for it: %s"
                             % (tok, f["path"], len(paths), ", ".join(paths)))
            if f["head"] and not failed:
                unseen = [c for c in git(repo, "rev-list", "%s..%s" % (head, f["head"])).stdout.split()
                          if c not in seen]
                if unseen:
                    items.append("%s%d commit(s) on the folder's %s HEAD does not reach, matching no stamp"
                                 % (lead, len(unseen), f["branch"]))
        if not t["on_head"] and not t["elsewhere"] and not looked and tok not in running:
            items.append("session %s: unknown: no matching stamped commits found, and no branch or folder to look at"
                         % tok)
    return items


def print_verdict(items):
    if items:
        print('open: %d item(s), so no "Done — safe to close.":' % len(items))
        for it in items:
            print("  %s" % it)
    else:
        print("clear: every started session's committed work is on HEAD, and no folder holds uncommitted work")


def run_started(a):
    """--started from the parsed arguments: the merges, the --sessions report, the verdict."""
    if a.sessions is not None or a.wrap or a.since or a.candidates:
        raise Usage("--started cannot be combined with --sessions, --wrap, --since or --candidates")
    if a.until or a.json or a.tip or a.session is not None:
        raise Usage("--until, --json, --tip and --session do not apply to --started")
    tokens = list(dict.fromkeys(session_token(t) for t in a.started))
    folders = parse_folders(a.folder, tokens, "--started")
    merges, running, named = {}, set(), {}

    def mine(raw, flag):
        tok = session_token(raw)
        if tok not in tokens:
            raise Usage("%s names %s, which is not one of the --started tokens" % (flag, tok))
        if tok in merges or tok in running or tok in named:
            raise Usage("%s has more than one disposition: give each token one disposition" % tok)
        return tok

    for raw in a.merge or ():
        tok, _sep, branch = raw.partition("=")
        merges[mine(tok, "--merge")] = branch or None
    for raw in a.is_running or ():
        running.add(mine(raw, "--is-running"))
    for raw in a.name_only or ():
        tok, _sep, reason = raw.partition("=")
        if not reason:
            raise Usage("--name-only takes TOKEN=REASON, not %r" % raw)
        named[mine(tok, "--name-only")] = reason
    s = sessions(a.repo, tokens, folders)
    if s["incomplete"]:
        print("merged nothing: %s" % INCOMPLETE)
        code = print_sessions(s)
        print_verdict(["%s: %s" % (INCOMPLETE, what) for what in s["incomplete"]])
        return code
    try:
        return merge_and_report(a, tokens, folders, s, merges, running, named)
    except Usage as ex:  # after a merge too: what merged has been said, and the verdict still reads
        print_verdict([str(ex)])
        return 2


def merge_and_report(a, tokens, folders, s, merges, running, named):
    """--started once the first inspection reads whole: the merges, the report, the verdict."""
    by_token = dict((t["token"], t) for t in s["tokens"])
    results = {}
    left_out = [t for t in tokens if t not in merges]
    for tok in tokens:
        if tok not in merges:
            continue
        branch = merges[tok] or next((f["branch_name"] for f in by_token[tok]["folders"] if f["branch_name"]), None)
        if branch is None:
            results[tok] = {"token": tok, "branch": None, "merged": None, "nothing": False, "why": None}
            print("merge session %s: no branch on record and none from --folder" % tok)
            continue
        results[tok] = merge_branch(a.repo, tok, branch, s, left_out)
        print_merge(results[tok])
    if any(m["merged"] for m in results.values()):
        s = sessions(a.repo, tokens, folders)
    code = print_sessions(s)
    items = open_items(a.repo, s, results, running, named) + ["%s: %s" % (INCOMPLETE, w) for w in s["incomplete"]]
    print_verdict(items)
    return 2 if code == 2 else (1 if items else 0)


def build_parser():
    ap = argparse.ArgumentParser(description="How much of a session's work did its wrap write down?")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--wrap", metavar="REV")
    ap.add_argument("--since", metavar="DATE")
    # Scorer 1's parser read `--s` as --since; --scorer would make that abbreviation ambiguous, so
    # it stays an exact (hidden) option and every abbreviation scorer 1 accepted still parses.
    ap.add_argument("--s", dest="since", metavar="DATE", help=argparse.SUPPRESS)
    ap.add_argument("--until", metavar="DATE")
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--scorer", type=int, choices=(1, 2), default=1)
    ap.add_argument("--tip", metavar="REF")
    ap.add_argument("--candidates", action="store_true")
    ap.add_argument("--session", metavar="VALUE")
    ap.add_argument("--sessions", nargs="+", metavar="TOKEN")
    ap.add_argument("--folder", action="append", metavar="TOKEN=PATH")
    ap.add_argument("--started", nargs="+", metavar="TOKEN")
    ap.add_argument("--merge", action="append", metavar="TOKEN[=BRANCH]")
    ap.add_argument("--is-running", action="append", metavar="TOKEN")
    ap.add_argument("--name-only", action="append", metavar="TOKEN=REASON")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        if a.started is not None:
            return run_started(a)
        if a.merge or a.is_running or a.name_only:
            raise Usage("--merge, --is-running and --name-only apply to --started only")
        if a.sessions is not None:
            return run_sessions(a)
        if a.folder:
            raise Usage("--folder applies to --sessions and --started only")
        if a.candidates:
            return run_candidates(a)
        if a.session is not None:
            raise Usage("--session applies to --candidates only")
        if bool(a.wrap) == bool(a.since):
            raise Usage("give exactly one of --wrap or --since")
        if a.scorer == 1 and a.tip is not None:
            raise Usage("--tip applies to --scorer 2 only")
        if a.wrap:
            if a.scorer == 2:
                return one_wrap_v2(a.repo, a.wrap, a.tip)
            return one_wrap(a.repo, a.wrap)
        if a.scorer == 2:
            return run_cohort_v2(a.repo, a.since, a.until, a.tip, a.json)
        return run_cohort(a.repo, a.since, a.until, a.json)
    except Usage as e:
        print("wrap-completeness: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
