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
"""
import argparse
import json
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


class Usage(Exception):
    pass


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-c", "core.quotePath=false", "-C", repo] + list(args),
                       capture_output=True, encoding="utf-8", errors="replace")
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


def score(repo, wrap):
    """None when no earlier wrap bounds the span; else the scored wrap."""
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
    scored = score(repo, wrap)
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
        scored = score(repo, sha)
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


def main(argv=None):
    ap = argparse.ArgumentParser(description="How much of a session's work did its wrap write down?")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--wrap", metavar="REV")
    ap.add_argument("--since", metavar="DATE")
    ap.add_argument("--until", metavar="DATE")
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args(argv)
    try:
        if bool(a.wrap) == bool(a.since):
            raise Usage("give exactly one of --wrap or --since")
        if a.wrap:
            return one_wrap(a.repo, a.wrap)
        return run_cohort(a.repo, a.since, a.until, a.json)
    except Usage as e:
        print("wrap-completeness: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
