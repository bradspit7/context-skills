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
Every git call is bounded by GIT_TIMEOUT seconds; a call past it exits 2.
"""
import argparse
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys

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
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
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
