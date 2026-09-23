#!/usr/bin/env python3
"""deploy-parity -- does production serve the bytes git says it should?

WHAT IT IS FOR
    When deploys are manual (a drag-and-drop, an FTP upload, a dashboard click), the
    repo never records WHEN production last moved, so every "production is current"
    sentence in a handoff is a claim about the moment it was measured. This tool
    re-derives the claim from bytes: every file the committed tree publishes is fetched
    from production (cache-busted), normalised per the project's config, and compared
    with its blob at --ref (default HEAD). A file that differs is traced back through
    history to the newest commit production DOES serve, and the report names the one
    TREE production matches -- so "what was last deployed?" has an answer, and the
    pending-deploy list derives from that tree, never from a handoff sentence.

WHY A FULL SWEEP IS THE DEFAULT
    A single-page probe (a hash of the homepage) is evidence only over the set that
    could have moved. A page the last deploy did not change matches either way, so such
    a probe reports clean while production is many commits behind.

OPT-IN: a `deploy-parity.json` at the repo root. Its presence is what makes the
analyze-context currency gate and the update-context evidence script print the one
production line automatically. Keys:
    site              production origin, e.g. "https://example.com" (required unless
                      url_module supplies BASE; if both are given they must agree)
    publish_dir       repo directory served as the site root, e.g. "public" (required)
    url_style         "literal" (the file path is the URL path) or "extensionless"
                      (x.html -> /x, dir/index.html -> /dir/). Default "literal".
    url_module        repo-relative path of a module exposing BASE and page_url(rel);
                      when set it owns the page mapping, so URLs keep one source
    literal_pages     pages always probed at their literal path (a force-404 target)
    include_ext       compare only these extensions; the rest are NOT EXAMINED
    exclude           publish_dir-relative path prefixes never compared
    not_served        basenames the host never serves (its config files, dotfile placeholders)
    normalise         any of: crlf, netlify-rum, ws-before-body-close,
                      collapse-blank-lines, strip-trailing-ws (applied in that order)
    report_normalised "each" (a line per normalised file) or "summary" (a count)
    controls, workers, timeout, history_limit, user_agent -- tuning, with defaults

PER-FILE CLASSES
    MATCH       served bytes == the blob at --ref
    NORMALISED  equal only after the configured normalisers (warned; fatal under --strict)
    BEHIND      production serves an OLDER committed version (the report names it)
    MISSING     404/410 on production for a file --ref publishes
    DIFFERS     matches no committed version in reach: an uncommitted tree was
                deployed, or the host rewrites the file
    FETCH-ERROR network failure or any other status: NOT a verdict about the deploy

INSTRUMENT CONTROLS -- a "production is behind" verdict is only worth what its
controls prove.
    --since REF   also fetches a few files UNCHANGED since REF. A control that matches
                  no committed version means the instrument is broken (a new injection,
                  a CDN rewrite, a normaliser gap): INSTRUMENT SUSPECT, exit 2. A control
                  that serves an OLDER version means production predates REF: the window
                  is too narrow, so the verdict is "behind" and a full sweep is advised.
    full sweep    if every fetched file matches no committed version at all, the tool is
                  measuring nothing rather than finding a total outage: INSTRUMENT
                  SUSPECT, exit 2.

WHAT IT CANNOT SEE
    Files production serves that the tree does not track (zombies) are UNKNOWN, not
    zero. Excluded classes are counted and named NOT EXAMINED. Uncommitted changes under
    publish_dir are reported as NOT INCLUDED, so a dirty tree cannot be certified.

EXIT STATUS
    0  every checked file is at --ref (normalised matches warned, not fatal)
    1  deploy owed / drift: any BEHIND, MISSING or DIFFERS (or NORMALISED under --strict)
    2  could not check: usage or config error, a failed fetch, INSTRUMENT SUSPECT, an
       exhausted --budget, or a tree that publishes nothing. Never 0 on a failed fetch.

USAGE (run from anywhere inside the project repo)
    python deploy-parity.py                    # full sweep: production vs HEAD
    python deploy-parity.py --brief            # the one line the briefing prints
    python deploy-parity.py --since <ref>      # only files changed since <ref>, plus controls
    python deploy-parity.py --ref <sha>        # production vs a named tree
    python deploy-parity.py --paths a.html css/site.css
    python deploy-parity.py --site http://127.0.0.1:8000   # probe a local copy instead
    python deploy-parity.py --selftest         # offline, both directions, real git + HTTP
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import importlib.util
import json
import random
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

CONFIG_NAME = "deploy-parity.json"

MATCH, NORMALISED, BEHIND, MISSING, DIFFERS, FETCH_ERROR = (
    "MATCH", "NORMALISED", "BEHIND", "MISSING", "DIFFERS", "FETCH-ERROR")
DIFF = "DIFF"  # the raw comparison outcome before history tracing splits it

DEFAULTS = {
    "url_style": "literal",
    "url_module": None,
    "literal_pages": [],
    "include_ext": None,
    "exclude": [],
    "not_served": [],
    "normalise": [],
    "report_normalised": "summary",
    "controls": 3,
    "workers": 8,
    "timeout": 20,
    "history_limit": 300,
    "user_agent": "deploy-parity/1",
}
KNOWN_KEYS = set(DEFAULTS) | {"site", "publish_dir", "comment"}

# --------------------------------------------------------------------------- #
# Normalisers. Each was a measured false difference on a real site; each is a
# lossy step, so a project opts into exactly the ones its host needs.
# --------------------------------------------------------------------------- #
_RUM = re.compile(rb'<script async id="netlify-rum-container"[^>]*>\s*</script>')


def _n_crlf(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def _n_netlify_rum(b: bytes) -> bytes:
    # Netlify injects its RUM tag before </body> when analytics is on.
    return _RUM.sub(b"", b)


def _n_ws_before_body_close(b: bytes) -> bytes:
    # The injection lands with a newline of its own; where the source keeps </body> on
    # the content line, that newline is the only difference left.
    return re.sub(rb"\s+(</body>)", rb"\1", b)


def _n_collapse_blank_lines(b: bytes) -> bytes:
    # The injection also brings a blank line; a strip that leaves it reports the page
    # as matching neither version.
    return re.sub(rb"\n[ \t]*\n(?:[ \t]*\n)*", b"\n", b)


def _n_strip_trailing_ws(b: bytes) -> bytes:
    return b.rstrip()


NORMALISERS: list[tuple[str, Callable[[bytes], bytes]]] = [
    ("crlf", _n_crlf),
    ("netlify-rum", _n_netlify_rum),
    ("ws-before-body-close", _n_ws_before_body_close),
    ("collapse-blank-lines", _n_collapse_blank_lines),
    ("strip-trailing-ws", _n_strip_trailing_ws),
]
NORMALISER_NAMES = [n for n, _ in NORMALISERS]


def make_normaliser(names: list[str]) -> Callable[[bytes], bytes]:
    unknown = [n for n in names if n not in NORMALISER_NAMES]
    if unknown:
        raise ConfigError("unknown normaliser(s) %s; known: %s" % (unknown, NORMALISER_NAMES))
    steps = [fn for n, fn in NORMALISERS if n in names]  # canonical order, not config order

    def norm(b: bytes) -> bytes:
        for fn in steps:
            b = fn(b)
        return b
    return norm


def git_blob_id(data: bytes) -> str:
    """The SHA-1 object id git would give these bytes (fast exact-match path)."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def classify(live: bytes, want: bytes, norm: Callable[[bytes], bytes]) -> str:
    """Exact equality first; then equality after normalisation; anything else is DIFF."""
    if live == want:
        return MATCH
    if norm(live) == norm(want):
        return NORMALISED
    return DIFF


class ConfigError(Exception):
    pass


class CouldNotCheck(Exception):
    pass


# --------------------------------------------------------------------------- #
# Git access. Paths come from `-z` listings (no quoting of non-ASCII names), blob
# ids come from one `cat-file --batch-check` call per batch, and blob bytes are
# cached by id -- a file unchanged across 300 commits is read once, not 300 times.
# --------------------------------------------------------------------------- #
class Repo:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._blobs: dict[str, bytes] = {}

    def run(self, *args: str, stdin: Optional[bytes] = None) -> bytes:
        r = subprocess.run(["git", "-C", str(self.root), *args], input=stdin,
                           capture_output=True)
        if r.returncode != 0:
            raise CouldNotCheck("git %s failed: %s" % (" ".join(args[:3]),
                                r.stderr.decode("utf-8", "replace").strip()[:160]))
        return r.stdout

    def lines(self, *args: str) -> list[str]:
        return [ln for ln in self.run(*args).decode("utf-8", "replace").splitlines() if ln.strip()]

    def zlist(self, *args: str) -> list[str]:
        return [p for p in self.run(*args).decode("utf-8", "replace").split("\0") if p]

    def batch_ids(self, specs: list[str]) -> dict[str, Optional[str]]:
        """{'<rev>:<path>': blob id, or None when absent / not a blob}."""
        if not specs:
            return {}
        out = self.run("cat-file", "--batch-check",
                       stdin=("\n".join(specs) + "\n").encode("utf-8"))
        res: dict[str, Optional[str]] = {}
        for spec, line in zip(specs, out.decode("utf-8", "replace").splitlines()):
            parts = line.split()
            res[spec] = parts[0] if len(parts) == 3 and parts[1] == "blob" else None
        return res

    def blob(self, blob_id: str) -> bytes:
        if blob_id not in self._blobs:
            self._blobs[blob_id] = self.run("cat-file", "blob", blob_id)
        return self._blobs[blob_id]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def load_config(path: Path, repo_root: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConfigError("%s is not readable JSON: %s" % (path.name, e))
    if not isinstance(raw, dict):
        raise ConfigError("%s must hold a JSON object" % path.name)
    unknown = sorted(set(raw) - KNOWN_KEYS)
    if unknown:  # a typo'd key must never silently fall back to a default
        raise ConfigError("unknown key(s) in %s: %s" % (path.name, unknown))
    cfg = dict(DEFAULTS)
    cfg.update(raw)
    if not cfg.get("publish_dir"):
        raise ConfigError("publish_dir is required")
    cfg["publish_dir"] = str(cfg["publish_dir"]).strip("/")
    if cfg["url_style"] not in ("literal", "extensionless"):
        raise ConfigError("url_style must be 'literal' or 'extensionless'")
    if cfg["report_normalised"] not in ("each", "summary"):
        raise ConfigError("report_normalised must be 'each' or 'summary'")
    cfg["_norm"] = make_normaliser(list(cfg["normalise"]))
    cfg["_mod"] = None
    if cfg["url_module"]:
        mpath = repo_root / cfg["url_module"]
        if not mpath.is_file():
            raise ConfigError("url_module %s does not exist" % cfg["url_module"])
        spec = importlib.util.spec_from_file_location("deploy_parity_url_module", mpath)
        mod = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(mpath.parent))
        try:
            spec.loader.exec_module(mod)
        except Exception as e:  # a broken project module is a config problem, not a verdict
            raise ConfigError("url_module %s failed to import: %s" % (cfg["url_module"], e))
        finally:
            sys.path.pop(0)
        if not hasattr(mod, "BASE") or not callable(getattr(mod, "page_url", None)):
            raise ConfigError("url_module must expose BASE and page_url(rel)")
        base = str(mod.BASE).rstrip("/")
        if cfg.get("site") and cfg["site"].rstrip("/") != base:
            raise ConfigError("site %r disagrees with %s BASE %r -- one fact, one owner"
                              % (cfg["site"], cfg["url_module"], base))
        cfg["site"] = base
        cfg["_mod"] = mod
    if not cfg.get("site"):
        raise ConfigError("site is required (or a url_module exposing BASE)")
    cfg["site"] = cfg["site"].rstrip("/")
    for k in ("controls", "workers", "timeout", "history_limit"):
        if not isinstance(cfg[k], int) or cfg[k] < (0 if k == "controls" else 1):
            raise ConfigError("%s must be a positive integer" % k)
    return cfg


def url_path(rel: str, cfg: dict) -> str:
    """The URL path (leading slash, no origin) a publish_dir-relative file answers at."""
    is_page = rel.endswith(".html") and rel not in cfg["literal_pages"]
    mod = cfg["_mod"]
    if mod is not None:
        base = str(mod.BASE).rstrip("/")
        full = mod.page_url(rel) if is_page else base + "/" + rel
        if not full.startswith(base):
            raise ConfigError("url_module page_url(%r) returned %r, outside BASE" % (rel, full))
        path = full[len(base):] or "/"
    elif cfg["url_style"] == "extensionless" and is_page:
        if rel == "index.html":
            path = "/"
        elif rel.endswith("/index.html"):
            path = "/" + rel[: -len("index.html")]
        else:
            path = "/" + rel[: -len(".html")]
    else:
        path = "/" + rel
    return urllib.parse.quote(path, safe="/%:@!$&'()*+,;=-._~")


# --------------------------------------------------------------------------- #
# The served set and its complement
# --------------------------------------------------------------------------- #
def served_files(repo: Repo, ref: str, cfg: dict) -> tuple[list[str], dict]:
    """(sorted publish_dir-relative paths --ref publishes, counts of what was excluded).

    Enumerated from the COMMITTED tree, never the working directory: a certification is
    only ever about bytes git can name.
    """
    pd = cfg["publish_dir"]
    skipped = {"not_served": 0, "excluded": 0, "ext": 0}
    keep = []
    inc = [e.lower() for e in cfg["include_ext"]] if cfg["include_ext"] else None
    for full in repo.zlist("ls-tree", "-r", "--name-only", "-z", ref, "--", pd + "/"):
        rel = full[len(pd) + 1:]
        if rel.rsplit("/", 1)[-1] in cfg["not_served"]:
            skipped["not_served"] += 1
        elif any(rel.startswith(p.lstrip("/")) for p in cfg["exclude"]):
            skipped["excluded"] += 1
        elif inc is not None and Path(rel).suffix.lower() not in inc:
            skipped["ext"] += 1
        else:
            keep.append(rel)
    return sorted(keep), skipped


def not_examined_line(cfg: dict, skipped: dict) -> str:
    parts = []
    if skipped["not_served"]:
        parts.append("%d host-config file(s) (%s)" % (skipped["not_served"], ", ".join(cfg["not_served"])))
    if skipped["excluded"]:
        parts.append("%d excluded path(s) (%s)" % (skipped["excluded"], ", ".join(cfg["exclude"])))
    if skipped["ext"]:
        parts.append("%d file(s) outside include_ext" % skipped["ext"])
    parts.append("anything production serves that this tree does not track (UNKNOWN, not zero)")
    return "NOT EXAMINED: " + "; ".join(parts)


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch(url: str, cfg: dict) -> tuple[Optional[int], bytes, str]:
    """(final status after redirects or None on network failure, body, error text)."""
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request("%s%scb=%d" % (url, sep, random.randint(1, 10**9)),
                                 headers={"User-Agent": cfg["user_agent"],
                                          "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
            return r.status, r.read(), ""
    except urllib.error.HTTPError as e:
        return e.code, b"", ""
    except Exception as e:  # DNS, TLS, refused, timeout: not a verdict about the deploy
        return None, b"", str(e)[:120]


def fetch_all(rels: list[str], site: str, cfg: dict, deadline: Optional[float]) -> dict:
    """{rel: (status, body, err)}. Unfinished at the deadline -> FETCH-ERROR 'budget'."""
    out: dict = {}
    ex = cf.ThreadPoolExecutor(max_workers=cfg["workers"])
    futs = {ex.submit(fetch, site + url_path(r, cfg), cfg): r for r in rels}
    try:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        done, pending = cf.wait(futs, timeout=remaining)
        for f in done:
            out[futs[f]] = f.result()
        for f in pending:
            out[futs[f]] = (None, b"", "--budget exhausted before this fetch finished")
    finally:
        ex.shutdown(wait=False, cancel_futures=True)
    return out


# --------------------------------------------------------------------------- #
# History: which committed version / tree does production serve?
# --------------------------------------------------------------------------- #
def compare_to_blob(repo: Repo, live: bytes, live_id: str, blob_id: Optional[str],
                    norm: Callable[[bytes], bytes]) -> str:
    if blob_id is None:
        return DIFF
    if blob_id == live_id:
        return MATCH
    return classify(live, repo.blob(blob_id), norm)


def newest_matching_commit(repo: Repo, ref: str, path: str, live: bytes, cfg: dict
                           ) -> Optional[tuple[str, str]]:
    """(short sha, date) of the newest commit at or before --ref whose blob for `path`
    equals `live` exactly or after normalisation. None when nothing in reach matches --
    DIFFERS is reported as such, never rounded to the nearest commit."""
    rows = repo.lines("log", "-n%d" % cfg["history_limit"], "--format=%H %h %ad",
                      "--date=short", ref, "--", path)
    ids = repo.batch_ids(["%s:%s" % (r.split()[0], path) for r in rows])
    live_id = git_blob_id(live)
    for r in rows:
        full, short, date = r.split()[:3]
        if compare_to_blob(repo, live, live_id, ids["%s:%s" % (full, path)], cfg["_norm"]) != DIFF:
            return short, date
    return None


def production_tree(repo: Repo, ref: str, live_by_rel: dict, cfg: dict) -> Optional[str]:
    """Newest commit (at or before --ref, touching publish_dir) whose blob for EVERY
    fetched file equals production. Per-file tracing names the last commit that touched
    each file; this names the one TREE a deploy uploaded, which is what a handoff
    sentence and a pending-deploy list need. None: no single committed tree matches
    (an uncommitted tree was deployed, or files arrived over several deploys)."""
    pd = cfg["publish_dir"]
    commits = repo.lines("log", "-n%d" % cfg["history_limit"], "--format=%H", ref, "--", pd + "/")
    live_ids = {rel: git_blob_id(b) for rel, b in live_by_rel.items()}
    memo: dict[tuple[str, Optional[str]], bool] = {}
    for i in range(0, len(commits), 25):
        chunk = commits[i:i + 25]
        ids = repo.batch_ids(["%s:%s/%s" % (c, pd, rel) for c in chunk for rel in live_by_rel])
        for c in chunk:
            for rel, live in live_by_rel.items():
                bid = ids["%s:%s/%s" % (c, pd, rel)]
                key = (rel, bid)
                if key not in memo:
                    memo[key] = compare_to_blob(repo, live, live_ids[rel], bid, cfg["_norm"]) != DIFF
                if not memo[key]:
                    break
            else:
                return c
    return None


# --------------------------------------------------------------------------- #
# The run
# --------------------------------------------------------------------------- #
def verdict(counts: dict, strict: bool) -> int:
    if counts.get(BEHIND) or counts.get(MISSING) or counts.get(DIFFERS):
        return 1
    if counts.get(NORMALISED) and strict:
        return 1
    return 0


def run(repo: Repo, cfg: dict, ref: str = "HEAD", since: Optional[str] = None,
        paths: Optional[list[str]] = None, strict: bool = False, verbose: bool = False,
        brief: bool = False, site: Optional[str] = None, budget: Optional[float] = None,
        emit: Callable[[str], None] = print) -> int:
    say = (lambda s: None) if brief else emit
    site = (site or cfg["site"]).rstrip("/")
    try:
        full = repo.lines("rev-parse", "--verify", ref + "^{commit}")[0]
        sha = full[:7]
        pd = cfg["publish_dir"]
        files, skipped = served_files(repo, ref, cfg)
        if not files:
            raise CouldNotCheck("the tree at %s publishes nothing under %s/" % (ref, pd))
        dirty = repo.lines("status", "--porcelain", "--", pd + "/")
        controls: list[str] = []
        if paths:
            targets = [p.split(pd + "/", 1)[-1].lstrip("/") for p in paths]
            unknown = [t for t in targets if t not in files]
            if unknown:
                raise CouldNotCheck("not in the served set at %s: %s" % (ref, ", ".join(unknown[:5])))
            scope = "%d named path(s)" % len(targets)
        elif since:
            repo.lines("rev-parse", "--verify", since + "^{commit}")
            changed = set(p[len(pd) + 1:] for p in repo.zlist(
                "diff", "--name-only", "-z", since, ref, "--", pd + "/"))
            targets = [f for f in files if f in changed]  # removed/unserved files are not "owed"
            unchanged = sorted(set(files) - set(targets))
            controls = random.Random(since).sample(unchanged, min(cfg["controls"], len(unchanged)))
            scope = "%d file(s) changed since %s + %d control(s)" % (len(targets), since, len(controls))
            if not targets:
                emit("production: nothing to compare -- no served file changed between %s and %s" % (since, ref))
                return 0
        else:
            targets = list(files)
            scope = "full sweep of %d served file(s)" % len(targets)

        say("evaluating %s (%s) against %s -- %s; %d uncommitted %s/ change(s) NOT included"
            % (ref, sha, site, scope, len(dirty), pd))
        deadline = None if not budget else time.monotonic() + budget

        # Preflight one fetch alone: a dead network fails in one timeout, not N/workers.
        first = targets[0]
        pre = fetch(site + url_path(first, cfg), cfg)
        if pre[0] is None:
            raise CouldNotCheck("%s unreachable (%s)" % (site, pre[2] or "network error"))
        fetched = {first: pre}
        fetched.update(fetch_all([t for t in targets[1:] + controls if t != first], site, cfg, deadline))

        want_ids = repo.batch_ids(["%s:%s/%s" % (full, pd, r) for r in targets + controls])
        results: dict[str, tuple[str, str]] = {}
        live_by_rel: dict[str, bytes] = {}
        for rel in targets + controls:
            status, body, err = fetched[rel]
            if status is None:
                results[rel] = (FETCH_ERROR, err or "network error")
                continue
            if status in (404, 410):
                results[rel] = (MISSING, "HTTP %d on production; present at %s" % (status, ref))
                continue
            if status != 200:
                results[rel] = (FETCH_ERROR, "HTTP %d" % status)
                continue
            live_by_rel[rel] = body
            kind = compare_to_blob(repo, body, git_blob_id(body),
                                   want_ids["%s:%s/%s" % (full, pd, rel)], cfg["_norm"])
            if kind != DIFF:
                results[rel] = (kind, "")
                continue
            m = newest_matching_commit(repo, ref, "%s/%s" % (pd, rel), body, cfg)
            results[rel] = (BEHIND, "production = %s %s" % m) if m else (
                DIFFERS, "matches no committed version in the last %d" % cfg["history_limit"])

        # Controls: a broken instrument must never be read as a deploy verdict.
        bad = [c for c in controls if results[c][0] in (DIFFERS, FETCH_ERROR, MISSING)]
        if bad:
            for c in bad:
                say("  ! control %-50s %s %s" % (c, *results[c]))
            raise CouldNotCheck("INSTRUMENT SUSPECT -- %d unchanged control file(s) match no committed "
                                "version (a new injection, a CDN rewrite or a normaliser gap), so a "
                                "difference proves nothing about the deploy" % len(bad))
        stale_controls = [c for c in controls if results[c][0] == BEHIND]

        counts: dict[str, int] = {}
        for rel in targets:
            counts[results[rel][0]] = counts.get(results[rel][0], 0) + 1
        ok_fetched = [r for r in targets if results[r][0] not in (FETCH_ERROR, MISSING)]
        if len(ok_fetched) >= 3 and all(results[r][0] == DIFFERS for r in ok_fetched):
            raise CouldNotCheck("INSTRUMENT SUSPECT -- all %d fetched file(s) match no committed version; "
                                "that is a tool measuring nothing, not a total outage" % len(ok_fetched))

        for rel in targets:
            kind, why = results[rel]
            if kind == MATCH and not verbose:
                continue
            if kind == NORMALISED and not (verbose or cfg["report_normalised"] == "each"):
                continue
            say("  %-10s %s  %s" % (kind, rel, why))
        for c in controls:
            say("  control    %s  %s %s" % (c, *results[c]))

        say("")
        say("checked %d: " % len(targets) + " · ".join(
            "%s %d" % (k.lower(), counts.get(k, 0))
            for k in (MATCH, NORMALISED, BEHIND, MISSING, DIFFERS, FETCH_ERROR)))
        if counts.get(NORMALISED):
            say("normalised matches use: %s" % (", ".join(cfg["normalise"]) or "(none)"))
        say(not_examined_line(cfg, skipped))

        if counts.get(FETCH_ERROR):
            raise CouldNotCheck("%d of %d fetch(es) failed (first: %s)" % (
                counts[FETCH_ERROR], len(targets),
                next(results[r][1] for r in targets if results[r][0] == FETCH_ERROR)))

        rc = verdict(counts, strict)
        if stale_controls:
            rc = 1
        owed = [r for r in targets if results[r][0] in (BEHIND, MISSING, DIFFERS)]
        tree_note = ""
        if owed or stale_controls:
            tree = production_tree(repo, ref, live_by_rel, cfg)
            label = "PRODUCTION TREE" if not (since or paths) else "NEWEST TREE CONSISTENT WITH THE CHECKED FILES"
            if tree:
                desc = repo.lines("log", "-1", "--format=%h %ad %s", "--date=short", tree)[0]
                pending = repo.zlist("diff", "--name-only", "-z", tree, ref, "--", pd + "/")
                say("%s: %s" % (label, desc[:100]))
                say("pending deploy: git diff --name-only %s %s -- %s/  (%d file(s))"
                    % (desc.split()[0], sha, pd, len(pending)))
                tree_note = "; production tree = %s (%s); %d file(s) pending deploy" % (
                    desc.split()[0], desc.split()[1], len(pending))
            else:
                say("%s: none -- no single committed tree matches every fetched file "
                    "(an uncommitted tree was deployed, or files arrived over several deploys)" % label)
                tree_note = "; no single committed tree matches production"
        if stale_controls:
            say("production predates --since %s (control %s serves an older version) -- run a full sweep"
                % (since, stale_controls[0]))

        if rc == 0:
            say("PARITY -- production serves %s for every checked file" % ref)
            norm_note = (" (%d only after normalisation)" % counts[NORMALISED]) if counts.get(NORMALISED) else ""
            emit_brief = "production MATCHES %s (%s): %s%s" % (ref, sha, scope, norm_note)
        else:
            say("NOT AT PARITY -- deploy owed")
            parts = ["%s %d" % (k.lower(), counts[k]) for k in (BEHIND, MISSING, DIFFERS) if counts.get(k)]
            if strict and counts.get(NORMALISED) and not parts:
                parts.append("normalised %d (--strict)" % counts[NORMALISED])
            emit_brief = "production is NOT at %s (%s): %d of %d checked file(s) differ (%s)%s" % (
                ref, sha, len(owed), len(targets), ", ".join(parts) or "controls older than --since", tree_note)
        if brief:
            emit(emit_brief)
        return rc
    except CouldNotCheck as e:
        emit("production: could not check -- %s" % e)
        return 2


# --------------------------------------------------------------------------- #
# Selftest: offline, both directions, through REAL git and a REAL local HTTP server
# --------------------------------------------------------------------------- #
def selftest() -> int:
    import contextlib
    import functools
    import http.server
    import io
    import shutil
    import tempfile
    import threading

    fails: list[str] = []
    passes = [0]

    def ok(cond: bool, label: str) -> None:
        print(("  PASS " if cond else "  FAIL ") + label)
        if cond:
            passes[0] += 1
        else:
            fails.append(label)

    ident = make_normaliser([])
    print("-- classification: both directions --")
    ok(classify(b"a\n", b"a\n", ident) == MATCH, "identical bytes -> MATCH")
    crlf = make_normaliser(["crlf"])
    ok(classify(b"a\r\nb\r\n", b"a\nb\n", crlf) == NORMALISED, "CRLF live vs LF ref -> NORMALISED, never MATCH")
    ok(classify(b"a\r\nb\r\n", b"a\nb\n", ident) == DIFF, "without the crlf normaliser the same pair is a DIFF")
    ok(classify(b"a\n", b"b\n", crlf) == DIFF, "different content -> DIFF")
    ok(classify(b"a\n", b"a", crlf) == DIFF, "a missing trailing newline is real unless strip-trailing-ws is on")
    ok(git_blob_id(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a",
       "git_blob_id agrees with `git hash-object` (the exact-match fast path)")

    print("-- normalisers: the measured Netlify injection, both directions --")
    rr = make_normaliser(["crlf", "netlify-rum", "ws-before-body-close", "collapse-blank-lines",
                          "strip-trailing-ws"])
    head = b"<body>\n<p>x</p>\n  <script src=\"s.js?v=37\"></script>\n</body>\n"
    served = (b"<body>\r\n<p>x</p>\r\n  <script src=\"s.js?v=37\"></script>\r\n\n"
              b"<script async id=\"netlify-rum-container\" src=\"/.netlify/scripts/rum\" "
              b"data-netlify-deploy-context=\"production\"></script>\r\n</body>\r\n")
    inline_head = b"<section>x</section></body></html>\n"
    inline_served = (b"<section>x</section>\r\n<script async id=\"netlify-rum-container\" "
                     b"src=\"/.netlify/scripts/rum\"></script>\r\n</body></html>\r\n")
    ok(rr(served) == rr(head), "accepts-good: CRLF + RUM tag + its blank line == the LF blob")
    ok(rr(inline_served) == rr(inline_head), "accepts-good: </body> kept on the content line")
    ok(rr(served.replace(b"<p>x</p>", b"<p>y</p>")) != rr(head), "rejects-bad: a one-word content change still differs")
    ok(rr(served.replace(b"v=37", b"v=38")) != rr(head), "rejects-bad: an asset version bump still differs")
    ok(rr(served.replace(b'id="netlify-rum-container"', b'id="other"')) != rr(head),
       "rejects-bad: only the netlify-rum tag is stripped, not other async scripts")
    ok(crlf(served) != crlf(head), "the rum normaliser is opt-in: crlf alone does not hide the injection")
    try:
        make_normaliser(["crlf", "typo"])
        ok(False, "an unknown normaliser name is a config error")
    except ConfigError:
        ok(True, "an unknown normaliser name is a config error")

    print("-- URL mapping --")
    base_cfg = dict(DEFAULTS, site="https://ex.test", publish_dir="site", _norm=ident, _mod=None)
    ext = dict(base_cfg, url_style="extensionless", literal_pages=["404.html"])
    ok(url_path("index.html", ext) == "/", "extensionless: index.html -> /")
    ok(url_path("research/index.html", ext) == "/research/", "extensionless: a directory index keeps its slash")
    ok(url_path("book.html", ext) == "/book", "extensionless: a page -> its extensionless path")
    ok(url_path("404.html", ext) == "/404.html", "a literal_pages entry is probed at its literal path")
    ok(url_path("css/site.css", ext) == "/css/site.css", "an asset -> its literal path")
    ok(url_path("about.html", base_cfg) == "/about.html", "literal style: the file path is the URL path")
    ok(url_path("a b/é.html", base_cfg) == "/a%20b/%C3%A9.html", "non-ASCII and spaces are percent-encoded")

    class FakeMod:
        BASE = "https://ex.test"

        @staticmethod
        def page_url(rel):
            return FakeMod.BASE + "/p/" + rel[:-5]
    modcfg = dict(base_cfg, _mod=FakeMod)
    ok(url_path("x.html", modcfg) == "/p/x", "url_module owns the page mapping when set")
    ok(url_path("img/a.png", modcfg) == "/img/a.png", "url_module: assets are BASE + literal path")

    print("-- config validation --")
    tmpd = Path(tempfile.mkdtemp(prefix="deploy-parity-cfg-"))
    try:
        def cfg_err(obj) -> bool:
            p = tmpd / CONFIG_NAME
            p.write_text(json.dumps(obj), encoding="utf-8")
            try:
                load_config(p, tmpd)
                return False
            except ConfigError:
                return True
        ok(cfg_err({"site": "https://x", "publish_dir": "site", "normalize": ["crlf"]}),
           "a typo'd key (normalize) is rejected, never silently defaulted")
        ok(cfg_err({"site": "https://x"}), "publish_dir is required")
        ok(cfg_err({"publish_dir": "site"}), "site is required without a url_module")
        (tmpd / "m.py").write_text("BASE='https://a.test'\ndef page_url(r): return BASE+'/'+r\n", encoding="utf-8")
        ok(cfg_err({"site": "https://b.test", "publish_dir": "s", "url_module": "m.py"}),
           "site disagreeing with url_module BASE is rejected (one fact, one owner)")
        ok(not cfg_err({"publish_dir": "s", "url_module": "m.py"}), "url_module alone supplies the site")
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)

    print("-- end to end: real git history, real HTTP --")
    tmp = Path(tempfile.mkdtemp(prefix="deploy-parity-e2e-"))
    httpd = None
    try:
        repo_dir, serve = tmp / "repo", tmp / "serve"
        repo_dir.mkdir()
        serve.mkdir()
        G = ["git", "-C", str(repo_dir), "-c", "core.autocrlf=false", "-c", "commit.gpgsign=false",
             "-c", "core.hooksPath=" + str(tmp / "nohooks"), "-c", "user.name=t", "-c", "user.email=t@t"]

        def git(*a):
            return subprocess.run(G + list(a), capture_output=True, check=True).stdout

        def write(rel, data):
            p = repo_dir / "site" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)

        def commit(msg):
            git("add", "-A")
            git("commit", "-q", "-m", msg)
            return git("rev-parse", "--short=7", "HEAD").decode().strip()

        git("init", "-q")
        write("index.html", b"<p>home</p>\n")
        write("a.html", b"<p>a v1</p>\n")
        write("css/s.css", b"body{}\n")
        write("_headers", b"/*\n  X: y\n")
        write("sandbox/x.html", b"draft\n")
        c1 = commit("c1")
        write("a.html", b"<p>a v2</p>\n")
        write("b.html", b"<p>b new</p>\n")
        c2 = commit("c2")
        (repo_dir / "notes.txt").write_bytes(b"x\n")
        c3 = commit("c3 touches nothing published")

        def deploy(ref, crlf_rel=None):
            shutil.rmtree(serve)
            serve.mkdir()
            for rel in Repo(repo_dir).zlist("ls-tree", "-r", "--name-only", "-z", ref, "--", "site/"):
                data = Repo(repo_dir).run("show", "%s:%s" % (ref, rel))
                if crlf_rel and rel == "site/" + crlf_rel:
                    data = data.replace(b"\n", b"\r\n")
                out = serve / rel[len("site/"):]
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Quiet, directory=str(serve)))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        site = "http://127.0.0.1:%d" % httpd.server_address[1]
        (repo_dir / CONFIG_NAME).write_text(json.dumps({
            "site": site, "publish_dir": "site", "not_served": ["_headers"],
            "exclude": ["sandbox/"], "normalise": ["crlf"], "workers": 4, "timeout": 5}), encoding="utf-8")
        cfg = load_config(repo_dir / CONFIG_NAME, repo_dir)
        R = Repo(repo_dir)

        def go(**kw):
            buf = io.StringIO()
            rc = run(R, cfg, emit=lambda s: buf.write(s + "\n"), **kw)
            return rc, buf.getvalue()

        deploy(c1)
        rc, out = go()
        ok(rc == 1, "production at c1, HEAD at c3 -> exit 1 (deploy owed)")
        ok(re.search(r"BEHIND\s+a\.html\s+production = %s" % c1, out) is not None,
           "a.html is BEHIND and names c1 as the version production serves")
        ok(re.search(r"MISSING\s+b\.html", out) is not None, "b.html (added after c1) is MISSING")
        ok(("PRODUCTION TREE: %s" % c1) in out, "the one production TREE is named: c1")
        ok("(2 file(s))" in out, "the pending-deploy list is derived from that tree: 2 files")
        ok("1 host-config file(s) (_headers)" in out and "1 excluded path(s) (sandbox/)" in out,
           "excluded classes are COUNTED and named NOT EXAMINED, never silently dropped")
        ok("UNKNOWN, not zero" in out, "untracked served files are declared UNKNOWN")
        rc, out = go(brief=True)
        ok(rc == 1 and out.count("\n") == 1 and out.startswith("production is NOT at HEAD"),
           "--brief prints exactly ONE line and it says NOT at HEAD")
        ok(("production tree = %s" % c1) in out and "2 file(s) pending deploy" in out,
           "the brief line carries the production tree and the pending count")

        deploy(c3)
        rc, out = go(brief=True)
        ok(rc == 0 and out.startswith("production MATCHES HEAD") and out.count("\n") == 1,
           "after deploying HEAD: exit 0 and one MATCHES line")
        (repo_dir / "site" / "a.html").write_bytes(b"<p>dirty</p>\n")
        rc, out = go()
        ok("1 uncommitted site/ change(s) NOT included" in out,
           "a dirty tree is reported as NOT INCLUDED, never certified")
        git("checkout", "--", "site/a.html")

        deploy(c3, crlf_rel="index.html")
        rc, out = go(brief=True)
        ok(rc == 0 and "1 only after normalisation" in out, "a CRLF-only file is a warned NORMALISED match (exit 0)")
        rc, out = go(strict=True)
        ok(rc == 1, "--strict makes a NORMALISED match fatal")
        cfg_no_crlf = dict(cfg, _norm=ident, normalise=[])
        buf = io.StringIO()
        rc = run(R, cfg_no_crlf, emit=lambda s: buf.write(s + "\n"))
        ok(rc == 1 and re.search(r"DIFFERS\s+index\.html", buf.getvalue()) is not None,
           "without the crlf normaliser the CRLF copy DIFFERS (the normaliser is load-bearing)")

        deploy(c1)
        rc, out = go(since=c1)
        ok(rc == 1 and "changed since" in out and "control" in out,
           "--since c1: only the changed files are targets, plus controls; deploy owed")
        rc, out = go(since=c2)
        ok(rc == 0 and "nothing to compare" in out, "--since c2 with no served change since -> nothing to compare, exit 0")
        deploy(c1)
        (serve / "index.html").write_bytes(b"<p>rewritten by a CDN</p>\n")
        (serve / "css" / "s.css").write_bytes(b"/* injected */\n")
        rc, out = go(since=c1)
        ok(rc == 2 and "INSTRUMENT SUSPECT" in out,
           "--since: a control matching no committed version -> INSTRUMENT SUSPECT, exit 2")
        for rel in ("index.html", "a.html", "css/s.css"):
            (serve / rel).write_bytes(b"garbage from a broken proxy\n")
        rc, out = go()
        ok(rc == 2 and "INSTRUMENT SUSPECT" in out and "measuring nothing" in out,
           "full sweep: every fetched file matching nothing -> INSTRUMENT SUSPECT, exit 2 (not an outage)")

        deploy(c1)
        rc, out = go(paths=["a.html"])
        ok(rc == 1 and "NEWEST TREE CONSISTENT WITH THE CHECKED FILES" in out,
           "--paths: a subset never claims to name THE production tree")
        rc, out = go(paths=["nope.html"])
        ok(rc == 2 and "not in the served set" in out, "--paths naming an unserved file -> exit 2")

        full_norm = ["crlf", "netlify-rum", "ws-before-body-close", "collapse-blank-lines", "strip-trailing-ws"]
        ext_cfg = dict(cfg, url_style="extensionless", normalise=full_norm, _norm=make_normaliser(full_norm))
        h2, origin2, tmp2 = start_replay(R, c1, ext_cfg, ["crlf", "netlify-rum"])
        try:
            buf = io.StringIO()
            rc = run(R, ext_cfg, site=origin2, emit=lambda s: buf.write(s + "\n"))
            ok(rc == 1 and ("PRODUCTION TREE: %s" % c1) in buf.getvalue(),
               "--replay c1 (pretty URLs + CRLF + injected RUM tag) names c1 as the production tree")
            buf = io.StringIO()
            rc = run(R, ext_cfg, ref=c1, site=origin2, emit=lambda s: buf.write(s + "\n"))
            ok(rc == 0, "--replay c1 checked against --ref c1 is PARITY (the host effects all normalise away)")
        finally:
            h2.shutdown()
            h2.server_close()
            shutil.rmtree(tmp2, ignore_errors=True)
        try:
            start_replay(R, c1, cfg, ["gzip"])
            ok(False, "an unknown replay transform is refused")
        except CouldNotCheck:
            ok(True, "an unknown replay transform is refused")

        buf = io.StringIO()
        rc = run(R, cfg, site="http://127.0.0.1:9", emit=lambda s: buf.write(s + "\n"))
        ok(rc == 2 and "could not check" in buf.getvalue() and "unreachable" in buf.getvalue(),
           "an unreachable site -> 'could not check', exit 2, never a verdict")
        rc, out = go(ref="no-such-ref")
        ok(rc == 2 and out.startswith("production: could not check"), "a bad --ref -> could not check, exit 2")
        rc, out = go(budget=0.000001)
        ok(rc in (0, 2), "a tiny --budget never crashes (it either finished or reports could-not-check)")
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nselftest: %d passed, %d failed" % (passes[0], len(fails)))
    return 1 if fails else 0


REPLAY_TRANSFORMS = ("crlf", "netlify-rum")


def start_replay(repo: Repo, ref: str, cfg: dict, transforms: list[str]):
    """Serve the tree at `ref` locally, as the host would, and return (httpd, origin, tmpdir).

    This is how an instrument is acceptance-tested against a REAL past incident: "if
    production had been at <ref>, what would this tool have said?" The server resolves
    paths like a static host with pretty URLs (exact file, then +.html, then /index.html,
    else 404) and ignores query strings. Transforms simulate what the host did to the
    bytes: 'crlf' (uploaded from a Windows working tree) and 'netlify-rum' (the injected
    analytics tag and its blank line before </body>).
    """
    import functools
    import http.server
    import io
    import tarfile
    import tempfile
    import threading

    bad = [t for t in transforms if t not in REPLAY_TRANSFORMS]
    if bad:
        raise CouldNotCheck("unknown --replay-transform %s; known: %s" % (bad, list(REPLAY_TRANSFORMS)))
    pd = cfg["publish_dir"]
    tmp = Path(tempfile.mkdtemp(prefix="deploy-parity-replay-"))
    root = tmp / "root"
    data = repo.run("archive", "--format=tar", ref, pd + "/")
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        tf.extractall(tmp)  # noqa: S202 -- our own repo's tree, extracted into a fresh temp dir
    (tmp / pd).rename(root)
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        b = p.read_bytes()
        if "netlify-rum" in transforms and p.suffix == ".html" and b"</body>" in b:
            b = b.replace(b"</body>", b'\n<script async id="netlify-rum-container" '
                          b'src="/.netlify/scripts/rum"></script>\n</body>', 1)
        if "crlf" in transforms and b"\0" not in b:
            b = b.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        p.write_bytes(b)

    class Host(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def translate_path(self, path):
            base = super().translate_path(path)
            clean = urllib.parse.urlsplit(path).path
            for cand in (base, base + ".html", str(Path(base) / "index.html")):
                if Path(cand).is_file():
                    return cand
            return base if not clean.endswith("/") else str(Path(base) / "index.html")

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Host, directory=str(root)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1], tmp


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="HEAD", help="tree to compare production against (default HEAD)")
    ap.add_argument("--since", help="only files changed since this ref, plus unchanged controls")
    ap.add_argument("--paths", nargs="+", help="only these publish_dir-relative files")
    ap.add_argument("--strict", action="store_true", help="NORMALISED matches are fatal")
    ap.add_argument("--verbose", action="store_true", help="print MATCH lines too")
    ap.add_argument("--brief", action="store_true", help="print exactly one line (the briefing form)")
    ap.add_argument("--site", help="probe this origin instead of the configured one (e.g. a local copy)")
    ap.add_argument("--budget", type=float, help="seconds allowed for all fetches")
    ap.add_argument("--config", help="path to deploy-parity.json (default: <repo root>/%s)" % CONFIG_NAME)
    ap.add_argument("--repo", help="a path inside the project repo (default: the current directory)")
    ap.add_argument("--replay", metavar="OLD_REF",
                    help="serve the tree at OLD_REF locally as 'production' and check against it "
                         "(acceptance-test the tool on a real past incident)")
    ap.add_argument("--replay-transform", default="",
                    help="comma list of host effects to simulate in --replay: %s" % ",".join(REPLAY_TRANSFORMS))
    ap.add_argument("--selftest", action="store_true", help="offline checks, both directions")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    here = Path(a.repo or ".").resolve()
    r = subprocess.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"], capture_output=True)
    if r.returncode != 0:
        print("production: could not check -- %s is not inside a git repo" % here)
        return 2
    root = Path(r.stdout.decode("utf-8", "replace").strip())
    cfg_path = Path(a.config) if a.config else root / CONFIG_NAME
    if not cfg_path.is_file():
        print("production: could not check -- no %s at %s (this project declares no deploy target)"
              % (CONFIG_NAME, root))
        return 2
    try:
        cfg = load_config(cfg_path, root)
    except ConfigError as e:
        print("production: could not check -- config: %s" % e)
        return 2
    if a.since and a.paths:
        print("production: could not check -- --since and --paths are mutually exclusive")
        return 2
    repo = Repo(root)
    if not a.replay:
        return run(repo, cfg, ref=a.ref, since=a.since, paths=a.paths, strict=a.strict,
                   verbose=a.verbose, brief=a.brief, site=a.site, budget=a.budget)
    import shutil
    transforms = [t for t in a.replay_transform.split(",") if t]
    try:
        httpd, origin, tmp = start_replay(repo, a.replay, cfg, transforms)
    except CouldNotCheck as e:
        print("production: could not check -- %s" % e)
        return 2
    try:
        print("REPLAY: 'production' is the tree at %s served locally%s" % (
            a.replay, (" with host effects: " + ", ".join(transforms)) if transforms else ""))
        return run(repo, cfg, ref=a.ref, since=a.since, paths=a.paths, strict=a.strict,
                   verbose=a.verbose, brief=a.brief, site=origin, budget=a.budget)
    finally:
        httpd.shutdown()
        httpd.server_close()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
