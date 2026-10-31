#!/usr/bin/env python
"""compare-choices.py -- ONE comparison page for every option run: "Keep as is" first, every
option, then Codex's when a Codex call ran.

Every option run shows the user one page, built the way a project's options picker was
(a serve.py plus a compare/index.html):
per decision a "why", Choice / Page / Screen button rows, one frame per choice flipped by
visibility, a description box, "This one", "Open this in its own tab", and a fixed bottom bar with
"Your picks" and "Copy picks". Each frame is the REAL page with that choice applied. This script
generalizes that picker and fixes its one known defect: that picker served "Keep as is" from the
live site/ tree, so once the winner was applied it showed the NEW look under the keep label. Here
the base is FROZEN: a `git archive` of the pinned commit (or a recorded snapshot dir), so Keep as
is stays the pinned bytes however the live tree moves.

  python compare-choices.py serve MANIFEST [--port N]
  python compare-choices.py check MANIFEST [--live]
  python compare-choices.py --selftest

serve     Validate, freeze the base, probe the port and REFUSE if anything already answers there
          (a second Windows bind can share a port and serve the wrong site), then serve:
            COMPARISON PAGE: http://127.0.0.1:<port>/
          `/` is the comparison page. `/v/<decision>/<choice>/<page>` is the real page from the
          frozen base (a folder choice: from its folder first) with the choice applied: its CSS in
          a <style> before </head>, its fragment swapped in, its JS and the helper script before
          </body>. Every other path is served from the frozen base the way a static host serves it
          (/x -> x.html, /d/ -> d/index.html), so root-absolute assets and links work. A path that
          names a directory without its trailing slash (/v/d/1/docs, /docs, /v/d/1) answers 301
          to the same path plus "/", choice prefix and query kept, so the directory page's
          RELATIVE references resolve inside it; the comparison page's frames already use the
          slash form. A root-absolute request outside /v/ whose Referer is a FOLDER choice's page
          (/v/<decision>/<choice>/...) answers 307 to the same path inside that choice (folder
          first, then base, as a prefixed request), so the folder's JavaScript (import "/js/x.js",
          import(), new Worker("/w.js")) loads the folder's files and not the base's, at any
          import depth: the redirected module's own URL is inside the choice, so its imports are
          routed too. No JavaScript is parsed. A page that sets referrerpolicy="no-referrer"
          ("origin" and "strict-origin" too, as an attribute or a <meta name="referrer">) sends no
          path in its Referer and DEFEATS this; `check` warns when a folder choice's page carries
          one. A url choice's frame points straight at its own server (Choice kinds). The helper
          waits for fonts, then scrolls `at=<selector>` to the middle with window.scrollTo (never
          scrollIntoView, which also scrolls the comparison page around the frame). Ctrl-C (or
          Ctrl-Break / SIGTERM) stops it and removes the frozen copy. Serve it from a process that
          outlives the turn (a Terminal-panel tab), since the user clicks after the turn ends.
check     Validate the manifest against the frozen base and exit. --live also starts the server
          in-process on a free port, GETs the comparison page and every choice x page frame URL
          (a url choice's on its own server), following redirects, and prints one row each
          (status, bytes, what was applied, URL); every row must answer 200. A url choice whose
          response forbids framing (X-Frame-Options, CSP frame-ancestors) is a WARNING: the frame
          would be blank though the row says 200.

THE MANIFEST (JSON). Relative paths resolve against the manifest's own folder.

  {
    "title": "Header and forms: two choices",        page heading and the "Copy picks" prefix
    "lede": "...",                                     optional; default: a standard lede
    "id": "lx-106",                                    localStorage key for the picks
    "base": {"repo": "C:/path/to/repo",              the BASE: a pinned commit ...
             "pin": "151d641bc5fe",                    a commit sha (never HEAD or a branch)
             "site_root": "site"},                     the served dir inside the repo
            (or {"snapshot_dir": "path/to/base-snapshot"}: design-variants' dirty-base case;
             omit "base" only when every choice is served by a url)
    "port": 8790,                                      optional; --port wins; default 8790
    "decisions": [
      {"id": "fields", "title": "Form box outlines",
       "why": "The empty boxes' outlines are too faint to see.",
       "pages": [{"name": "Request a consultation", "path": "/book", "q": "at=%23firstName"},
                 {"name": "Homepage", "path": "/"}],
       "widths": [{"name": "Phone", "w": 392}, {"name": "Desktop", "w": 1440, "h": 900}],
                                     optional; default Phone 392, Small phone 362, Desktop 1440
                                     (a frame wider than the column is scaled to fit); h defaults
                                     to 660 up to 600 px wide, 900 above
       "choices": [
         {"c": "1", "kind": "keep", "name": "Keep as is", "text": "No change."},
         {"c": "2", "kind": "css", "name": "Gold outline", "text": "One plain line.",
          "css": "html body .field input{border-color:#C9A96E}", "recommended": true},
         {"c": "3", "kind": "fragment", "name": "New form", "text": "...",
          "fragment_file": "form.html", "replace_id": "booking-form"},
         {"c": "4", "kind": "url", "name": "Dev build", "text": "...",
          "url": "http://127.0.0.1:5174/"},
         {"c": "5", "kind": "folder", "name": "Codex's take", "text": "...",
          "folder": "C:/Users/me/.claude/run/codex/pages/<key>/site",
          "map": {"/book": "book.html"}, "codex_call": "20261030-120000-abc123"}]}]
  }

Choice kinds. `keep`: nothing is applied (only the helper script); it is always the first choice,
there is exactly one, and its name is "Keep as is" (the default when omitted; text defaults to
"No change."). `css`: `css` (a string) or `css_file`, injected in a <style> before </head>.
`fragment`: `fragment_file` plus exactly one of `replace_id` (the element with that id, start tag
through its matching end tag, found with html.parser tracking same-name depth) or `replace_text`
(an exact substring); it must match EXACTLY once on every page of its decision. `folder`: the
choice's pages resolve inside `folder` first (`map` sends a page path to a file in the folder),
everything else falls back to the base; the root-absolute src/href/srcset/url() references of
what it serves are rewritten to stay inside the choice, so a stylesheet the folder changed is the
one the page loads. A plain folder copy of a page another model built is a folder choice.
`url`: the frame points straight at a running server. `url` is an http://127.0.0.1:<port>/ or
http://localhost:<port>/ origin (anything else, a non-loopback host above all, is refused) and each
page path of the decision is appended to it; nothing is proxied or injected (no helper either, so
`at=` does not scroll it). It is how a dev-server project shows its sandboxes: a build step, or a
/src/main.tsx module entry that this static server would hand back as raw TSX, needs the
project's own dev server, one per sandbox. The keep choice of such a project carries a `url` too:
the baseline dev server, run from a frozen `git worktree add "$BASELINE_DIR" "$PINNED_COMMIT"`,
never the live tree. The tool cannot verify that server's bytes against the pin, so `check` prints
a WARNING saying so. A decision may mix kinds.
Any kind but keep and url may add `js` / `js_file` (injected before </body>). `recommended: true` marks
at most one choice per decision. `codex_call` names the Codex call that produced the choice; a
Codex choice comes last, and the page tags it "Codex". `text` is ONE plain line for the user
(at most 60 words): reviewer and verify counts go in the run's report, never on the page.

Refusals (exit 2, one `COMPARE-CHOICES REFUSED <what>` line each; never a page missing a
choice). First the SHAPE: a container of the wrong shape (the top level, base, decisions, a
decision, pages, a page, choices, a choice, widths, a width, map) or a field of the wrong type
(every supplied field is type-checked before anything else reads it, the refusal naming the field:
a replace_id of 123 would otherwise pass check and answer 409, a js object 500). Every schema
refusal is reported, then the run STOPS, before the base is frozen or any file is read. Then:
no decisions; a decision whose first choice is not kind keep; more than one keep; a
keep not named "Keep as is"; a codex_call on a choice with no page source (a keep, a missing
folder, a missing fragment file, no css); a Codex choice that is not last; a missing file (a
css/js/fragment file, a folder, a map target, the snapshot dir, a page the base lacks); a
replace_id / replace_text matching zero or more than one time; a pin that is not a commit sha or
does not resolve; a site_root the pin lacks; duplicate decision or choice ids; a choice text
over 60 words; more than one recommended choice; an unknown key (a typo would otherwise apply
nothing and look like Keep as is); a url that is not an http loopback origin with a port; a url on
a kind other than url / keep; js on a url choice; a missing base while a choice serves from it. A
codex_call whose ~/.claude/run/codex/calls/<id> dir is absent is a WARNING only (it may live on
another machine), as are a keep choice's url and a folder choice's path-stripping referrer policy.

Exit: 0 done, 2 refused / a live row not 200 / the port is taken, 64 usage error. ASCII-only.
Guard: tests/test-compare-choices.py; mutation battery tests/mutations/compare_choices.py.
"""
import argparse
import html
import html.parser
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import socketserver
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import http.server
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

EXIT_OK, EXIT_INVALID, EXIT_USAGE = 0, 2, 64
DEFAULT_PORT = 8790
MAX_WORDS = 60
KEEP_NAME = "Keep as is"
KINDS = ("keep", "css", "fragment", "folder", "url")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
# A directory path without its slash: the answer never depends on who asks, so 301 is right.
REDIRECT_SLASH = 301
# A root-absolute request routed into a folder choice by its Referer: the same path answers
# differently per Referer, so it must never be cached as permanent (307, and no-store).
REDIRECT_CHOICE = 307
REFERER_CHOICE = re.compile(r"^/v/([^/]+)/([^/]+)/")
# Referrer policies that send no PATH for a same-origin request, which the Referer routing needs.
PATH_STRIPPING = ("no-referrer", "origin", "strict-origin")
DEFAULT_WIDTHS = [{"name": "Phone", "w": 392}, {"name": "Small phone", "w": 362},
                  {"name": "Desktop", "w": 1440}]
DEFAULT_LEDE = ("Each frame is the real page with that choice applied. Choice 1 always keeps things "
                "as they are. Click a choice to flip between them, scroll inside the frame to look "
                "around, then press This one. Your picks collect in the bar at the bottom. Please "
                "don't send the forms in these frames.")
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")
CALL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
TOP_KEYS = {"title", "lede", "id", "base", "port", "decisions"}
BASE_KEYS = ({"repo", "pin", "site_root"}, {"snapshot_dir"})
DECISION_KEYS = {"id", "title", "why", "pages", "widths", "choices"}
PAGE_KEYS = {"name", "path", "q"}
WIDTH_KEYS = {"name", "w", "h"}
CHOICE_KEYS = {"c", "name", "text", "kind", "recommended", "codex_call", "css", "css_file", "js",
               "js_file", "fragment_file", "replace_id", "replace_text", "folder", "map", "url"}
APPLY_KEYS = ("css", "css_file", "js", "js_file", "fragment_file", "replace_id", "replace_text",
              "folder", "map")

# Every field's JSON type, checked before anything else reads the field. A wrong type used to pass
# `check` and fail only when the user opened the choice (replace_id 123 -> 409, js {} -> 500).
TYPE_OK = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "str|int": lambda v: isinstance(v, str) or (isinstance(v, int) and not isinstance(v, bool)),
}
TYPE_WORD = {"str": "a string", "int": "an integer", "bool": "true or false",
             "str|int": "a string (or an integer)"}
BASE_TYPES = {"repo": "str", "pin": "str", "site_root": "str", "snapshot_dir": "str"}
PAGE_TYPES = {"name": "str", "path": "str", "q": "str"}
WIDTH_TYPES = {"name": "str", "w": "int", "h": "int"}
CHOICE_TYPES = {"c": "str|int", "name": "str", "text": "str", "recommended": "bool", "codex_call": "str",
                "css": "str", "css_file": "str", "js": "str", "js_file": "str", "fragment_file": "str",
                "replace_id": "str", "replace_text": "str", "folder": "str", "url": "str"}


def type_name(v):
    """What a JSON value is, in the words a refusal uses."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true/false"
    if isinstance(v, int):
        return "an integer"
    if isinstance(v, float):
        return "a number"
    if isinstance(v, str):
        return "a string"
    if isinstance(v, list):
        return "a list"
    if isinstance(v, dict):
        return "an object"
    return type(v).__name__


def url_served(c):
    """A choice whose frame points at its own server: kind url, or a dev-server project's keep."""
    return c.get("kind") == "url" or (c.get("kind") == "keep" and "url" in c)


def url_problem(u):
    """None when `u` is an http loopback origin with a port (http://127.0.0.1:5173/); else why not."""
    try:
        s = urllib.parse.urlsplit(u)
        port = s.port
    except ValueError as e:
        return "is not a URL (%s)" % e
    if not s.netloc:
        return "is not an http://127.0.0.1:<port>/ origin"
    host = (s.hostname or "").lower()
    if host not in LOOPBACK_HOSTS:
        return ("is not a loopback origin: a url choice's frame points at a local server "
                "(http://127.0.0.1:<port>/ or http://localhost:<port>/), never %r" % (s.hostname or s.netloc))
    if s.scheme != "http":
        return "must start with http:// (a local dev server; %s:// is refused)" % s.scheme
    if port is None:
        return "names no port (http://%s:<port>/)" % host
    if s.username is not None or s.password is not None or s.path not in ("", "/") or s.query or s.fragment:
        return ("must be an origin only (http://%s:%d/): each page path of the decision is appended to it"
                % (host, port))
    return None


REFERRER_ATTR = re.compile(r"""(?<![\w-])referrerpolicy\s*=\s*(["']?)([^"'\s>]*)\1""", re.I)
REFERRER_META = re.compile(r"""<meta\b[^>]*\bname\s*=\s*["']?referrer(?=["'\s/>])[^>]*>""", re.I)
META_CONTENT = re.compile(r"""\bcontent\s*=\s*(["'])(.*?)\1|\bcontent\s*=\s*([^"'\s>]+)""", re.I | re.S)


def referrer_strippers(text):
    """The referrer policies in an HTML page that send no path for a same-origin request (they
    defeat the Referer routing that keeps a folder choice's root-absolute JavaScript inside it)."""
    out = []
    for m in REFERRER_ATTR.finditer(text):
        v = m.group(2).strip().lower()
        if v in PATH_STRIPPING:
            out.append('referrerpolicy="%s"' % v)
    for m in REFERRER_META.finditer(text):
        cm = META_CONTENT.search(m.group(0))
        if cm:
            toks = [t.strip().lower() for t in (cm.group(2) if cm.group(1) else cm.group(3)).split(",") if t.strip()]
            if toks and toks[-1] in PATH_STRIPPING:   # the last policy the browser understands wins
                out.append('<meta name="referrer" content="%s">' % toks[-1])
    return out

CSS_OPEN = '<style id="compare-choices-css">'
HELPER_START = "<!-- compare-choices helper -->"
HELPER_END = "<!-- /compare-choices helper -->"
HELPER_JS = """(function () {
  var q = new URLSearchParams(location.search);
  function go() {
    var at = q.get('at'), e = null;
    try { e = at && document.querySelector(at); } catch (x) { e = null; }
    /* window.scrollTo, never scrollIntoView: inside a same-origin frame that also scrolls the comparison page */
    if (e) { document.documentElement.style.scrollBehavior = 'auto';
      var r = e.getBoundingClientRect(); window.scrollTo(0, r.top + scrollY - (innerHeight - r.height) / 2); }
  }
  (document.fonts ? document.fonts.ready : Promise.resolve()).then(function () { setTimeout(go, 60); });
})();"""

for _ext, _type in ((".css", "text/css"), (".js", "text/javascript"), (".mjs", "text/javascript"),
                    (".svg", "image/svg+xml"), (".woff2", "font/woff2"), (".woff", "font/woff"),
                    (".webp", "image/webp"), (".avif", "image/avif"), (".json", "application/json")):
    mimetypes.add_type(_type, _ext)


def emit(kind, msg):
    print("COMPARE-CHOICES %s %s" % (kind, msg), flush=True)


# --------------------------------------------------------------------------- paths and git

def resolve_ex(root, url_path):
    """(file, slashless): URL path -> file under root, the way a static host resolves it: /x ->
    x.html when that page exists (the page wins over a folder of the same name), /d/ ->
    d/index.html, / -> index.html; file is None when absent or outside root. `slashless` is True
    when the path names a directory WITHOUT its trailing slash (/d): a static host answers that
    with a redirect to /d/, because served at /d the index's relative references resolve one
    level up."""
    rel = urllib.parse.unquote(url_path).lstrip("/")
    root = Path(root).resolve()
    p = (root / rel).resolve()
    if p != root and root not in p.parents:
        return None, False
    if rel and not rel.endswith("/") and not rel.lower().endswith((".html", ".htm")):
        page = (root / (rel + ".html")).resolve()
        if root in page.parents and page.is_file():
            return page, False
    if p.is_dir():
        index = p / "index.html"
        if not index.is_file():
            return None, False
        return index, bool(rel) and not rel.endswith("/")
    return (p if p.is_file() else None), False


def resolve(root, url_path):
    """The file resolve_ex() names (None when absent or outside root)."""
    return resolve_ex(root, url_path)[0]


def inside(root, rel):
    """root/rel when it stays inside root, else None."""
    root = Path(root).resolve()
    p = (root / rel).resolve()
    return p if (p == root or root in p.parents) else None


def norm_page(path):
    """'/research/' and '/research' are one page; '/' stays '/'."""
    s = "/" + urllib.parse.unquote(path).strip("/")
    return s


def git(repo, *args):
    try:
        return subprocess.run(["git", "-C", str(repo)] + list(args), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return subprocess.CompletedProcess(args, 127, "", str(e))


def inside_git_repo(path):
    p = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(p, ".git")):
            return p
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent


def codex_calls_dir():
    """Where codex-ask keeps one dir per call; its own run_dir() when importable (it honours the
    test knob), else the default."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import codex_budget  # noqa: E402
        return os.path.join(codex_budget.run_dir(), "calls")
    except Exception:  # noqa: BLE001
        return os.path.join(os.path.expanduser("~"), ".claude", "run", "codex", "calls")


# --------------------------------------------------------------------------- fragments

class _IdFinder(html.parser.HTMLParser):
    """Every element whose id equals `target`: (start offset, end offset or None)."""
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
            "source", "track", "wbr"}

    def __init__(self, text, target):
        super().__init__(convert_charrefs=True)
        self.text, self.target = text, target
        self.lines = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.lines.append(i + 1)
        self.found = []          # [start, end] per element with the id
        self.open = None         # (tag, depth, index into found) of the element being closed

    def _off(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self._off()
        if dict(attrs).get("id") == self.target:
            stt = self.get_starttag_text() or ""
            if tag in self.VOID:
                self.found.append([start, start + len(stt)])
            else:
                self.found.append([start, None])
                if self.open is None:
                    self.open = (tag, 1, len(self.found) - 1)
                return
        if self.open and tag == self.open[0] and tag not in self.VOID:
            self.open = (self.open[0], self.open[1] + 1, self.open[2])

    def handle_startendtag(self, tag, attrs):
        start = self._off()
        if dict(attrs).get("id") == self.target:
            self.found.append([start, start + len(self.get_starttag_text() or "")])

    def handle_endtag(self, tag):
        if self.open and tag == self.open[0]:
            depth = self.open[1] - 1
            if depth == 0:
                pos = self._off()
                end = self.text.find(">", pos)
                self.found[self.open[2]][1] = (end + 1) if end >= 0 else None
                self.open = None
            else:
                self.open = (self.open[0], depth, self.open[2])


def fragment_span(text, replace_id=None, replace_text=None):
    """(start, end, count): the one span the fragment replaces, and how many matched."""
    if replace_id is None and replace_text is None:
        return None, None, 0
    if replace_text is not None:
        hits = [m.start() for m in re.finditer(re.escape(replace_text), text)]
        if len(hits) != 1:
            return None, None, len(hits)
        return hits[0], hits[0] + len(replace_text), 1
    p = _IdFinder(text, replace_id)
    try:
        p.feed(text)
        p.close()
    except Exception:  # noqa: BLE001
        pass
    found = p.found
    if len(found) != 1:
        return None, None, len(found)
    start, end = found[0]
    if end is None:
        return None, None, -1          # an element with no matching end tag
    return start, end, 1


# --------------------------------------------------------------------------- injection

def _escape_close(code, tag):
    return re.sub(r"</(%s)" % tag, r"<\\/\1", code, flags=re.I)


def inject(text, css=None, js=None):
    """The page with `css` in a <style> before the first </head> and the helper (plus `js`) before
    the last </body>. Keep pages get the helper only."""
    if css:
        block = CSS_OPEN + _escape_close(css, "style") + "</style>"
        m = re.search(r"</head\s*>", text, re.I) or re.search(r"<body[\s>]", text, re.I)
        i = m.start() if m else 0
        text = text[:i] + block + text[i:]
    script = ""
    if js:
        script += '<script data-compare-choices="choice">' + _escape_close(js, "script") + "</script>"
    script += "<script>" + HELPER_JS + "</script>"
    block = HELPER_START + script + HELPER_END
    ends = list(re.finditer(r"</body\s*>", text, re.I))
    i = ends[-1].start() if ends else len(text)
    return text[:i] + block + text[i:]


ATTR_URL = re.compile(r"""(\s(?:src|href|poster)\s*=\s*)(["']?)/(?![/\\])""", re.I)
SRCSET = re.compile(r"""(\ssrcset\s*=\s*)(["'])(.*?)\2""", re.I | re.S)
CSS_URL = re.compile(r"""(url\(\s*["']?)/(?![/\\])""", re.I)
CSS_IMPORT = re.compile(r"""(@import\s+["'])/(?![/\\])""", re.I)


def rewrite_html(text, prefix):
    """Root-absolute references kept inside a folder choice: /css/a.css -> <prefix>css/a.css."""
    text = ATTR_URL.sub(lambda m: m.group(1) + m.group(2) + prefix, text)

    def srcset(m):
        parts = []
        for cand in m.group(3).split(","):
            s = cand.lstrip()
            lead = cand[:len(cand) - len(s)]
            if s.startswith("/") and not s.startswith("//"):
                s = prefix + s[1:]
            parts.append(lead + s)
        return m.group(1) + m.group(2) + ",".join(parts) + m.group(2)
    text = SRCSET.sub(srcset, text)
    return rewrite_css(text, prefix)


def rewrite_css(text, prefix):
    text = CSS_URL.sub(lambda m: m.group(1) + prefix, text)
    return CSS_IMPORT.sub(lambda m: m.group(1) + prefix, text)


def read_text(path):
    return Path(path).read_bytes().decode("utf-8", "surrogateescape")


def to_bytes(text):
    return text.encode("utf-8", "surrogateescape")


# --------------------------------------------------------------------------- the manifest

class Plan(object):
    """A validated manifest: decisions with resolved paths, plus the frozen base."""

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.dir = self.path.parent
        self.problems, self.warnings = [], []
        self.m = None
        self.base = None          # the served root (the frozen copy or the snapshot dir)
        self.tmp = None           # the temp dir to remove on exit (pin bases only)
        self.base_label = ""
        self.halt = False         # a wrong shape or type: stop after the schema pass

    def refuse(self, msg):
        self.problems.append(msg)

    def shape(self, msg):
        """A container of the wrong shape, or a field of the wrong type: refused, and validate()
        stops once the schema pass has reported everything, before the base is frozen or any file
        is read (what follows would traverse it: `"decisions": 12` used to raise TypeError there,
        with no refusal printed)."""
        self.halt = True
        self.refuse(msg)

    def abs(self, p):
        p = Path(os.path.expanduser(str(p)))
        return p if p.is_absolute() else (self.dir / p)

    # -- load ---------------------------------------------------------------- #

    def load(self):
        try:
            self.m = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except OSError as e:
            self.refuse("missing file: the manifest %s cannot be read (%s)" % (self.path, e.strerror))
            return False
        except ValueError as e:
            self.refuse("the manifest %s is not valid JSON: %s" % (self.path, e))
            return False
        if not isinstance(self.m, dict):
            self.refuse("the manifest is not a JSON object")
            return False
        self._schema()
        return True

    def _keys(self, obj, allowed, where):
        if not isinstance(obj, dict):
            self.shape("%s is not a JSON object (it is %s)" % (where, type_name(obj)))
            return False
        for k in sorted(set(obj) - set(allowed)):
            self.refuse("unknown key %r in %s (allowed: %s)" % (k, where, ", ".join(sorted(allowed))))
        return True

    def _typed(self, obj, types, where):
        """Refuse (and halt on) every supplied field whose JSON type is wrong, naming it. Returns
        the set of wrong fields so the checks after it do not refuse the same field twice."""
        bad = set()
        for k in sorted(types):
            if k in obj and not TYPE_OK[types[k]](obj[k]):
                self.shape("%s: %r must be %s, not %s" % (where, k, TYPE_WORD[types[k]], type_name(obj[k])))
                bad.add(k)
        return bad

    def _schema(self):
        m = self.m
        self._keys(m, TOP_KEYS, "the manifest")
        if not isinstance(m.get("title"), str) or not m.get("title", "").strip():
            self.refuse("the manifest needs a non-empty 'title'")
        if not isinstance(m.get("id"), str) or not ID_RE.match(m.get("id", "")):
            self.refuse("the manifest needs an 'id' of letters, digits, '-' or '_' (the picks' storage key)")
        if "lede" in m and not isinstance(m["lede"], str):
            self.refuse("'lede' must be a string")
        if "port" in m and (not isinstance(m["port"], int) or not 0 <= m["port"] <= 65535):
            self.refuse("'port' must be an integer 0-65535")
        base = m.get("base")
        if "base" in m:
            if not isinstance(base, dict):
                self.shape("'base' must be a JSON object ({\"repo\", \"pin\", \"site_root\"} or "
                           "{\"snapshot_dir\"}), not %s" % type_name(base))
            elif not self._typed(base, BASE_TYPES, "'base'") and not (
                    set(base) <= BASE_KEYS[0] and {"repo", "pin"} <= set(base) or set(base) == BASE_KEYS[1]):
                self.refuse("'base' must be {\"repo\", \"pin\", \"site_root\"} or {\"snapshot_dir\"}")
        decisions = m.get("decisions")
        if decisions is None or decisions == []:
            self.refuse("no decisions: the manifest needs at least one decision")
            return
        if not isinstance(decisions, list):
            self.shape("'decisions' must be a list of decisions, not %s" % type_name(decisions))
            return
        seen = set()
        for i, d in enumerate(decisions):
            where = "decision %d" % (i + 1)
            if not self._keys(d, DECISION_KEYS, where):
                continue
            did = d.get("id")
            if not isinstance(did, str) or not ID_RE.match(did):
                self.refuse("%s needs an 'id' of letters, digits, '-' or '_'" % where)
            elif did in seen:
                self.refuse("duplicate decision id %r" % did)
            else:
                seen.add(did)
                where = "decision %r" % did
            for k in ("title", "why"):
                if not isinstance(d.get(k), str) or not d.get(k, "").strip():
                    self.refuse("%s needs a non-empty %r" % (where, k))
            self._pages(d, where)
            self._widths(d, where)
            self._choices(d, where)
        if "base" not in m:
            # A url choice brings its own server; every other choice is served from the base.
            users = ["%s/%s" % (d.get("id"), c.get("c")) for d in decisions if isinstance(d, dict)
                     for c in d.get("choices", []) if c.get("kind") in KINDS and not url_served(c)]
            if users:
                self.refuse("'base' is missing, and choice %s serve%s from the frozen base: give "
                            "{\"repo\", \"pin\", \"site_root\"} or {\"snapshot_dir\"}"
                            % (", ".join(users[:6]), "s" if len(users) == 1 else ""))

    def _pages(self, d, where):
        pages = d.get("pages")
        if pages is not None and not isinstance(pages, list):
            self.shape("%s: 'pages' must be a list of pages, not %s" % (where, type_name(pages)))
            d["pages"] = []
            return
        if not pages:
            self.refuse("%s needs at least one page" % where)
            d["pages"] = []
            return
        good = []
        for j, p in enumerate(pages):
            pw = "%s page %d" % (where, j + 1)
            if not self._keys(p, PAGE_KEYS, pw):
                continue
            bad = self._typed(p, PAGE_TYPES, pw)
            if "name" not in bad and not p.get("name", "").strip():
                self.refuse("%s needs a 'name'" % pw)
            if "path" not in bad and not p.get("path", "").startswith("/"):
                self.refuse("%s needs a 'path' starting with '/'" % pw)
            if "q" not in bad:
                p["q"] = p.get("q", "").lstrip("?")
            good.append(p)
        d["pages"] = good

    def _widths(self, d, where):
        widths = d.get("widths", DEFAULT_WIDTHS)
        if not isinstance(widths, list):
            self.shape("%s: 'widths' must be a list, not %s" % (where, type_name(widths)))
            widths = []
        elif not widths:
            self.refuse("%s: 'widths' must be a non-empty list" % where)
        out = []
        for j, w in enumerate(widths):
            ww = "%s width %d" % (where, j + 1)
            if not self._keys(w, WIDTH_KEYS, ww) or self._typed(w, WIDTH_TYPES, ww):
                continue
            h = w.get("h", 660 if isinstance(w.get("w"), int) and w["w"] <= 600 else 900)
            if not isinstance(w.get("name"), str) or not isinstance(w.get("w"), int) \
                    or not 200 <= w["w"] <= 3840 or not 200 <= h <= 4000:
                self.refuse("%s needs a 'name' and integer 'w' 200-3840 (optional 'h' 200-4000)" % ww)
                continue
            out.append({"name": w["name"], "w": w["w"], "h": h})
        d["widths"] = out or [dict(x, h=660 if x["w"] <= 600 else 900) for x in DEFAULT_WIDTHS]

    def _choice_fields(self, c, cw):
        """The choice's field types and its map's shape, before anything else reads them."""
        bad = self._typed(c, CHOICE_TYPES, cw)
        if "map" in c:
            if not isinstance(c["map"], dict):
                self.shape("%s: 'map' must be a JSON object {\"<page path>\": \"<file in the folder>\"}, not %s"
                           % (cw, type_name(c["map"])))
                bad.add("map")
            else:
                # JSON object keys are always strings; a value need not be.
                for k, v in sorted(c["map"].items(), key=lambda kv: str(kv[0])):
                    if not isinstance(k, str) or not isinstance(v, str):
                        self.shape("%s: 'map' entry %r -> %r must map a page path (a string) to a file in "
                                   "the folder (a string), not %s" % (cw, k, v, type_name(v)))
                        bad.add("map")
        return bad

    def _choices(self, d, where):
        chs = d.get("choices")
        if chs is not None and not isinstance(chs, list):
            self.shape("%s: 'choices' must be a list of choices, not %s" % (where, type_name(chs)))
            d["choices"] = []
            return
        if not chs:
            self.refuse("%s has no choices" % where)
            d["choices"] = []
            return
        good = []                       # (choice, the set of its fields of the wrong type)
        for j, c in enumerate(chs):
            cw = "%s choice %d" % (where, j + 1)
            if not self._keys(c, CHOICE_KEYS, cw):
                continue
            bad = self._choice_fields(c, cw)
            if "c" not in bad and isinstance(c.get("c"), int):
                c["c"] = str(c["c"])
            good.append((c, bad))
        d["choices"] = chs = [c for c, _bad in good]
        if not chs:
            return
        # Choice 1 always keeps things as they are, and there is only one of it.
        if chs[0].get("kind") != "keep":
            self.refuse("%s: the first choice must be kind keep (\"Keep as is\"), not %r"
                        % (where, chs[0].get("kind")))
        keeps = [c for c in chs if c.get("kind") == "keep"]
        if len(keeps) > 1:
            self.refuse("%s has more than one keep choice (%d)" % (where, len(keeps)))
        recs = [c for c in chs if c.get("recommended") is True]
        if len(recs) > 1:
            self.refuse("%s has more than one recommended choice (%s)"
                        % (where, ", ".join(str(c.get("c")) for c in recs)))
        seen_codex = False
        ids = set()
        for c, bad in good:
            cid = c.get("c")
            cw = "%s choice %r" % (where, cid)
            if "c" in bad:
                pass                    # refused, by name, in _typed
            elif not isinstance(cid, str) or not ID_RE.match(cid):
                self.refuse("%s choice %r needs a 'c' of letters, digits, '-' or '_'" % (where, cid))
            elif cid in ids:
                self.refuse("%s: duplicate choice id %r" % (where, cid))
            else:
                ids.add(cid)
            kind = c.get("kind")
            if kind not in KINDS:
                self.refuse("%s: kind must be one of %s, not %r" % (cw, ", ".join(KINDS), kind))
                continue
            if kind == "keep":
                c.setdefault("name", KEEP_NAME)
                c.setdefault("text", "No change.")
                if "name" not in bad and c.get("name") != KEEP_NAME:
                    self.refuse("%s: the keep choice is always named \"%s\", not %r"
                                % (cw, KEEP_NAME, c.get("name")))
                extra = [k for k in APPLY_KEYS if k in c]
                if extra:
                    self.refuse("%s: a keep choice applies nothing; remove %s" % (cw, ", ".join(extra)))
            for k in ("name", "text"):
                if k not in bad and not c.get(k, "").strip():
                    self.refuse("%s needs a non-empty %r" % (cw, k))
            text = c.get("text", "") if "text" not in bad else ""
            if len(text.split()) > MAX_WORDS:
                self.refuse("%s: its text is %d words, over %d words (one plain line per choice; "
                            "reviewer and verify counts go in the run's report, never on the page)"
                            % (cw, len(text.split()), MAX_WORDS))
            if kind != "css" and ("css" in c or "css_file" in c):
                self.refuse("%s: css / css_file belong to kind css" % cw)
            if kind == "fragment" and ("replace_id" in c) == ("replace_text" in c):
                self.refuse("%s: a fragment needs exactly one of replace_id / replace_text" % cw)
            if kind != "fragment" and any(k in c for k in ("fragment_file", "replace_id", "replace_text")):
                self.refuse("%s: fragment_file / replace_id / replace_text belong to kind fragment" % cw)
            if kind != "folder" and ("folder" in c or "map" in c):
                self.refuse("%s: folder / map belong to kind folder" % cw)
            if "url" in c and kind not in ("url", "keep"):
                self.refuse("%s: 'url' belongs to kind url (or the keep choice of a dev-server project)" % cw)
            if kind == "url":
                if "url" not in c:
                    self.refuse("%s: a url choice needs a 'url' (http://127.0.0.1:<port>/)" % cw)
                for k in ("js", "js_file"):
                    if k in c:
                        self.refuse("%s: a url choice is its server's page as served, nothing is injected; "
                                    "remove %s" % (cw, k))
            if "url" in c and "url" not in bad and kind in ("url", "keep"):
                why = url_problem(c["url"])
                if why:
                    self.refuse("%s: url %r %s" % (cw, c["url"], why))
            # A Codex choice comes last; nothing that is not Codex's follows it.
            if "codex_call" in c:
                seen_codex = True
            elif seen_codex:
                self.refuse("%s: the Codex choice (codex_call) must be the last choice; %r follows it"
                            % (where, cid))

    # -- the base and the files ---------------------------------------------- #

    def freeze(self):
        """The frozen base: a git archive of the pin into a temp dir outside every repo, or the
        snapshot dir as is. Never the live working tree."""
        base = self.m.get("base") if isinstance(self.m, dict) else None
        if not isinstance(base, dict):
            return False
        if "snapshot_dir" in base:
            p = self.abs(base["snapshot_dir"])
            if not p.is_dir():
                self.refuse("missing file: base.snapshot_dir %s is not a directory" % p)
                return False
            self.base, self.base_label = p.resolve(), "snapshot %s" % p
            return True
        repo, pin = self.abs(base.get("repo", "")), str(base.get("pin", ""))
        site_root = str(base.get("site_root", "") or "").strip("/\\")
        if not SHA_RE.match(pin):
            self.refuse("base.pin %r is not a commit sha: a moving ref (HEAD, a branch) shows the winner "
                        "under Keep as is once the winner is committed" % pin)
            return False
        r = git(repo, "rev-parse", "--verify", "--quiet", pin + "^{commit}")
        if r.returncode != 0 or not r.stdout.strip():
            self.refuse("base.pin %s does not resolve to a commit in %s" % (pin, repo))
            return False
        sha = r.stdout.strip()
        tmp = Path(tempfile.mkdtemp(prefix="compare-choices-"))
        holder = inside_git_repo(str(tmp))
        if holder:
            shutil.rmtree(tmp, ignore_errors=True)
            self.refuse("the frozen base must be outside every git repo; %s is inside %s" % (tmp, holder))
            return False
        self.tmp = tmp
        tar = tmp / "base.tar"
        a = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "-o", str(tar), sha, "--",
                            site_root or "."], capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
        if a.returncode != 0 or not tar.is_file():
            self.refuse("base.site_root %r does not exist at %s in %s: %s"
                        % (site_root, sha[:12], repo, (a.stderr or "").strip()[:200]))
            return False
        with tarfile.open(tar) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(tmp / "tree", filter="data")
            else:
                tf.extractall(tmp / "tree")
        tar.unlink()
        root = (tmp / "tree" / site_root) if site_root else (tmp / "tree")
        if not root.is_dir():
            self.refuse("base.site_root %r is not a directory at %s" % (site_root, sha[:12]))
            return False
        self.base = root.resolve()
        self.base_label = "pin %s (%s) of %s" % (sha[:12], site_root or ".", repo)
        return True

    def cleanup(self):
        if self.tmp is not None:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _file(self, c, key, where):
        p = self.abs(c[key])
        if not p.is_file():
            self.refuse("missing file: %s %s %s" % (where, key, p))
            return None
        return p

    def check_files(self):
        """Every file a choice names exists, every page exists in the base, every fragment matches
        exactly once on every page of its decision, every Codex choice has a page source. Runs only
        after a schema pass with no wrong shape or type (validate() stops before it otherwise)."""
        calls = codex_calls_dir()
        for d in self.m.get("decisions") or []:
            where = "decision %r" % d.get("id")
            base_pages = {}
            # A decision whose every choice is served by its own url needs no page in the base
            # (a dev-server project may have no committed HTML entry at all).
            from_base = any(not url_served(c) for c in d.get("choices", []))
            for p in d.get("pages", []):
                if not from_base or not isinstance(p.get("path"), str) or self.base is None:
                    continue
                f = resolve(self.base, p["path"])
                if f is None or f.suffix.lower() not in (".html", ".htm"):
                    self.refuse("missing file: %s page %s does not exist in the base (%s)"
                                % (where, p["path"], self.base_label))
                else:
                    base_pages[p["path"]] = f
            for c in d.get("choices", []):
                self._check_choice(d, c, where, base_pages, calls)

    def _check_choice(self, d, c, where, base_pages, calls):
        kind = c.get("kind")
        cw = "%s choice %r" % (where, c.get("c"))
        source = False                  # does the choice have a page source of its own?
        for key in ("css_file", "js_file"):
            if key in c and isinstance(c[key], str):
                f = self._file(c, key, cw)
                source = source or (key == "css_file" and f is not None)
        if kind == "url":
            source = True               # its own server (url_problem() already vetted the origin)
        elif kind == "keep" and "url" in c:
            self.warnings.append(
                "%s: Keep as is is served by %s, a server this tool cannot verify: run it from a frozen "
                "`git worktree add \"$BASELINE_DIR\" \"$PINNED_COMMIT\"`, never the live tree; its bytes "
                "are not checked against the pin" % (cw, c["url"]))
        elif kind == "css":
            if isinstance(c.get("css"), str) and c["css"].strip():
                source = True
            if not source:
                self.refuse("%s: a css choice needs a non-empty 'css' or an existing 'css_file'" % cw)
        elif kind == "fragment" and isinstance(c.get("fragment_file"), str):
            f = self._file(c, "fragment_file", cw)
            source = f is not None
            rid, rtext = c.get("replace_id"), c.get("replace_text")
            if source and (isinstance(rid, str) or isinstance(rtext, str)):
                for path, page in base_pages.items():
                    _s, _e, n = fragment_span(read_text(page), rid if isinstance(rid, str) else None,
                                              rtext if isinstance(rtext, str) else None)
                    what = ("replace_id %r" % rid) if isinstance(rid, str) else ("replace_text %r" % rtext)
                    if n == -1:
                        self.refuse("%s: %s has no matching end tag on %s" % (cw, what, path))
                    elif n != 1:
                        self.refuse("%s: %s matches %d times on %s (it must match exactly once)"
                                    % (cw, what, n, path))
        elif kind == "fragment":
            self.refuse("%s: a fragment needs a 'fragment_file'" % cw)
        elif kind == "folder":
            folder = self.abs(c["folder"]) if isinstance(c.get("folder"), str) else None
            if folder is None or not folder.is_dir():
                self.refuse("missing file: %s folder %s is not a directory" % (cw, folder))
            else:
                source = True
                mp = c.get("map") if isinstance(c.get("map"), dict) else {}
                for page, target in sorted(mp.items()):
                    t = inside(folder, target)
                    if t is None or not t.is_file():
                        self.refuse("missing file: %s map %s -> %s is not a file in the folder"
                                    % (cw, page, target))
                mapped = {norm_page(k) for k in mp}
                for path in base_pages:
                    if norm_page(path) not in mapped and resolve(folder, path) is None:
                        self.warnings.append("%s serves page %s from the base (it is not in its folder)"
                                             % (cw, path))
                # The Referer routing that keeps its root-absolute JavaScript inside the choice needs
                # the page's path in the Referer; a path-stripping policy sends none.
                for path in base_pages:
                    f, _origin, _slashless = self.locate(c, path)
                    if f is not None and f.suffix.lower() in (".html", ".htm"):
                        for found in referrer_strippers(read_text(f)):
                            self.warnings.append(
                                "%s: page %s carries %s, so its root-absolute JavaScript requests (import "
                                "\"/x.js\", import(), workers) send no path in their Referer and load the "
                                "BASE's files, not this choice's" % (cw, path, found))
        call = c.get("codex_call")
        if call is not None:
            if not isinstance(call, str) or not CALL_RE.match(call):
                self.refuse("%s: codex_call %r is not a call id" % (cw, call))
            elif not source:
                self.refuse("%s: codex_call %s names a choice with no page source (no folder, no fragment "
                            "file, no css): there is nothing of Codex's to show" % (cw, call))
            elif not os.path.isdir(os.path.join(calls, call)):
                self.warnings.append("%s: codex_call %s not found under %s (it may live on another machine)"
                                     % (cw, call, calls))

    def validate(self):
        """Load, then stop if the schema pass found a wrong shape or type; else freeze and check.
        True when nothing was refused."""
        if not self.load():
            return False
        if self.halt:
            return False            # every schema refusal is recorded; nothing below may traverse it
        self.freeze()
        self.check_files()          # with no base (a bad pin), the page checks are skipped
        return not self.problems

    def report(self):
        if self.base is not None:
            emit("base", "%s frozen=%s" % (self.base_label, self.base))
        for w in self.warnings:
            emit("WARNING", w)
        for p in self.problems:
            emit("REFUSED", p)

    # -- the served pages ---------------------------------------------------- #

    def decision(self, did):
        for d in self.m["decisions"]:
            if d.get("id") == did:
                return d
        return None

    def choice(self, did, cid):
        d = self.decision(did)
        return next((x for x in (d or {}).get("choices", []) if x.get("c") == cid), None)

    def locate(self, c, url_path):
        """(file, origin, slashless) for a base-served choice's url_path: a folder choice's map,
        then its folder, then the frozen base. `slashless`: the path names a directory without its
        trailing slash (answered with a redirect, never the index served in place)."""
        f, origin, slashless = None, "base", False
        if c.get("kind") == "folder":
            folder = self.abs(c["folder"])
            mp = {norm_page(k): v for k, v in (c.get("map") or {}).items()}
            if norm_page(url_path) in mp:
                f = inside(folder, mp[norm_page(url_path)])
                f = f if (f is not None and f.is_file()) else None
            if f is None:
                f, slashless = resolve_ex(folder, url_path)
            if f is not None:
                origin = "folder"
        if f is None and self.base is not None:
            f, slashless = resolve_ex(self.base, url_path)
        return f, origin, slashless

    def frame_url(self, d, c, p):
        """The URL the comparison page's frame loads for choice c on page p: a url choice's own
        server with the page path appended, else /v/<decision>/<choice><path>, a directory path in
        its trailing-slash form so the user never sees the redirect."""
        q = ("?" + p["q"]) if p.get("q") else ""
        if url_served(c):
            return "http://%s%s%s" % (urllib.parse.urlsplit(c["url"]).netloc, p["path"], q)
        path = p["path"]
        _f, _origin, dir_page = self.locate(c, path)
        if dir_page:
            path += "/"
        return "/v/%s/%s%s%s" % (d["id"], c["c"], path, q)

    def urls(self):
        out = []
        for d in self.m["decisions"]:
            for c in d["choices"]:
                for p in d["pages"]:
                    out.append((d, c, p, self.frame_url(d, c, p)))
        return out

    def serve_choice(self, did, cid, url_path):
        """(status, body bytes, content type, what) for /v/<did>/<cid><url_path>. A 301 carries
        its target path (no query) in `what`."""
        c = self.choice(did, cid)
        if c is None:
            return 404, b"no such decision or choice", "text/plain; charset=utf-8", ""
        if url_served(c):
            return (404, ("this choice is served by %s itself; its frame points there, nothing is proxied"
                          % c["url"]).encode("utf-8"), "text/plain; charset=utf-8", "")
        kind = c["kind"]
        prefix = "/v/%s/%s/" % (did, cid)
        f, origin, slashless = self.locate(c, url_path)
        if slashless:
            # /v/d/1/docs -> /v/d/1/docs/: served in place, docs/index.html's relative theme.css
            # would resolve to /v/d/1/theme.css.
            return REDIRECT_SLASH, b"", "text/plain; charset=utf-8", prefix + url_path.lstrip("/") + "/"
        if f is None:
            return 404, b"not found", "text/plain; charset=utf-8", ""
        if f.suffix.lower() not in (".html", ".htm"):
            body = f.read_bytes()
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if kind == "folder" and ctype == "text/css":
                body = to_bytes(rewrite_css(body.decode("utf-8", "surrogateescape"), prefix))
            return 200, body, _ctype(ctype), "%s asset" % origin
        text = read_text(f)
        if kind == "fragment":
            rid, rtext = c.get("replace_id"), c.get("replace_text")
            s, e, n = fragment_span(text, rid, rtext)
            if n != 1:
                return (409, ("this choice's fragment matches %d times on %s; it applies only where it "
                              "matches exactly once" % (n, url_path)).encode("utf-8"),
                        "text/plain; charset=utf-8", "")
            text = text[:s] + read_text(self.abs(c["fragment_file"])) + text[e:]
        if kind == "folder":
            text = rewrite_html(text, prefix)
        css = None
        if kind == "css":
            css = c.get("css") or ""
            if c.get("css_file"):
                css = (css + "\n" if css else "") + read_text(self.abs(c["css_file"]))
        js = c.get("js") or ""
        if c.get("js_file"):
            js = (js + "\n" if js else "") + read_text(self.abs(c["js_file"]))
        return 200, to_bytes(inject(text, css, js or None)), "text/html; charset=utf-8", "%s/%s" % (kind, origin)

    def page(self):
        return build_page(self.m, self.frame_url).encode("utf-8")


def _ctype(t):
    if t.startswith("text/") or t in ("application/javascript", "application/json", "image/svg+xml"):
        return t + "; charset=utf-8"
    return t


# --------------------------------------------------------------------------- the comparison page

PAGE_CSS = """
  :root { --bg:#121212; --panel:#181818; --ink:#F5F3EE; --muted:#B9B4A8; --lbl:#8F8A80; --accent:#C9A96E;
          --accent-light:#E8D5B0; --dark:#0D0D0D; --line:rgba(201,169,110,.28); }
  * { box-sizing:border-box; margin:0; padding:0; }
  body { background:var(--bg); color:var(--ink); padding-bottom:96px;
         font:15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
  header.top { padding:28px 20px 8px; max-width:1180px; margin:0 auto; }
  h1 { font-weight:400; font-size:28px; color:var(--ink); }
  .lede { color:var(--muted); margin-top:8px; max-width:760px; }
  section.dec { max-width:1180px; margin:28px auto 0; padding:22px 20px 26px; border-top:1px solid var(--line);
                display:grid; grid-template-columns:minmax(0,1fr) auto; gap:28px; align-items:start; }
  section.dec.wide { grid-template-columns:minmax(0,1fr); }
  h2 { font-weight:500; font-size:21px; color:var(--accent-light); }
  h2 span.n { color:var(--accent); margin-right:10px; }
  .why { color:var(--muted); margin-top:6px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; margin-top:14px; align-items:center; }
  .lbl { color:var(--lbl); font-size:11px; letter-spacing:.14em; text-transform:uppercase; width:70px; }
  button { font:inherit; font-size:14px; cursor:pointer; background:transparent; color:var(--ink);
           border:1px solid var(--line); border-radius:3px; padding:8px 13px; }
  button:hover { border-color:var(--accent); }
  button[aria-pressed="true"] { background:var(--accent); color:var(--dark); border-color:var(--accent); font-weight:600; }
  button:focus-visible { outline:2px solid var(--accent-light); outline-offset:2px; }
  .tag { display:inline-block; margin-left:6px; padding:0 6px; border-radius:9px; font-size:11px; font-weight:600;
         letter-spacing:.06em; text-transform:uppercase; border:1px solid currentColor; }
  .desc { margin-top:16px; padding:14px 16px; background:var(--panel); border-left:2px solid var(--accent); }
  .desc b { color:#fff; font-weight:600; }
  .pick { margin-top:12px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
  .pick button { border-color:var(--accent); color:var(--accent-light); }
  .picked { color:var(--accent); font-weight:600; }
  .stage { position:relative; border:1px solid var(--line); border-radius:18px; overflow:hidden; background:#000;
           justify-self:center; }
  section.dec.wide .stage { justify-self:start; border-radius:6px; }
  .stage iframe { position:absolute; top:0; left:0; border:0; background:#fff; visibility:hidden; transform-origin:0 0; }
  .stage iframe.on { visibility:visible; }
  a.open { display:inline-block; margin-top:10px; font-size:13px; color:var(--accent); }
  footer.bar { position:fixed; left:0; right:0; bottom:0; background:var(--dark); border-top:1px solid var(--accent);
               padding:12px 20px; display:flex; gap:14px; align-items:center; flex-wrap:wrap; z-index:5; }
  footer.bar b { color:var(--accent-light); font-weight:600; }
  #picks { font-variant-numeric:tabular-nums; }
  #copied { user-select:all; }
  @media (max-width:900px) { section.dec { grid-template-columns:minmax(0,1fr); } }
"""

PAGE_JS = r"""
(function () {
  var M = JSON.parse(document.getElementById("cc-data").textContent);
  var D = M.decisions, KEY = "compare-choices:" + M.id;
  var picks = {};
  try { picks = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { picks = {}; }
  D.forEach(function (d) {      /* a pick saved by an older manifest under the same id */
    if (picks[d.id] && !d.choices.some(function (c) { return c.c === picks[d.id]; })) delete picks[d.id];
  });
  function save() { try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (e) {} }
  function el(tag, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (text) e.textContent = text;
    return e;
  }
  /* the server computes each frame URL: a directory page in its slash form, a url choice on its own server */
  function src(ch, i) { return ch.src[i]; }
  function tags(parent, ch) {
    if (ch.codex) parent.appendChild(el("span", { "class": "tag" }, "Codex"));
    if (ch.recommended) parent.appendChild(el("span", { "class": "tag" }, "Recommended"));
  }
  function renderBar() {
    document.getElementById("picks").textContent = D.map(function (d) {
      return d.n + ": " + (picks[d.id] ? "Choice " + picks[d.id] : "\u2013"); }).join("   \u00b7   ");
  }
  var fits = [];

  D.forEach(function (d) {
    var st = { c: d.choices[0].c, p: 0, w: 0 };
    var sec = el("section", { "class": "dec", id: "d-" + d.id });
    var left = el("div", {});
    var h = el("h2", {}); h.appendChild(el("span", { "class": "n" }, String(d.n))); h.appendChild(document.createTextNode(d.title));
    left.appendChild(h);
    left.appendChild(el("p", { "class": "why" }, d.why));
    var rowC = el("div", { "class": "row" }); rowC.appendChild(el("span", { "class": "lbl" }, "Choice"));
    var rowP = el("div", { "class": "row" }); rowP.appendChild(el("span", { "class": "lbl" }, "Page"));
    var rowW = el("div", { "class": "row" }); rowW.appendChild(el("span", { "class": "lbl" }, "Screen"));
    var desc = el("div", { "class": "desc" });
    var pick = el("div", { "class": "pick" });
    var pickBtn = el("button", { type: "button" }, "This one");
    var pickTxt = el("span", { "class": "picked" });
    pick.appendChild(pickBtn); pick.appendChild(pickTxt);
    var open = el("a", { "class": "open", target: "_blank", rel: "noopener" }, "Open this in its own tab");
    left.appendChild(rowC);
    if (d.pages.length > 1) left.appendChild(rowP);
    if (d.widths.length > 1) left.appendChild(rowW);
    left.appendChild(desc); left.appendChild(pick); left.appendChild(open);
    var stage = el("div", { "class": "stage" });
    sec.appendChild(left); sec.appendChild(stage);
    document.getElementById("decisions").appendChild(sec);
    var frames = {};

    function fit() {
      var w = d.widths[st.w], wide = w.w > 600;
      sec.classList.toggle("wide", wide);
      var room = sec.clientWidth - 40;
      var s = Math.min(1, Math.max(0.1, (wide ? room : Math.min(w.w, room)) / w.w));
      stage.style.width = Math.round(w.w * s) + "px";
      stage.style.height = Math.round(w.h * s) + "px";
      Object.keys(frames).forEach(function (k) {
        var f = frames[k];
        f.style.width = w.w + "px"; f.style.height = w.h + "px";
        f.style.transform = s < 1 ? "scale(" + s + ")" : "";
      });
    }
    fits.push(fit);
    function load() {
      stage.innerHTML = ""; frames = {};
      d.choices.forEach(function (ch) {
        var f = el("iframe", { title: "Choice " + ch.c + ": " + ch.name, loading: "lazy", src: src(ch, st.p) });
        frames[ch.c] = f; stage.appendChild(f);
      });
      fit(); paint();
    }
    function paint() {
      [[rowC, "c"], [rowP, "p"], [rowW, "w"]].forEach(function (r) {
        r[0].querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.v === String(st[r[1]]))); });
      });
      var ch = d.choices.filter(function (x) { return x.c === st.c; })[0];
      desc.innerHTML = "";
      desc.appendChild(el("b", {}, "Choice " + ch.c + ": " + ch.name + ". "));
      desc.appendChild(document.createTextNode(ch.text));
      tags(desc, ch);
      Object.keys(frames).forEach(function (k) { frames[k].classList.toggle("on", k === st.c); });
      pickTxt.textContent = picks[d.id] ? "You picked Choice " + picks[d.id] + "." : "";
      open.href = src(ch, st.p);
    }
    d.choices.forEach(function (ch) {
      var b = el("button", { type: "button" }, ch.c + " \u00b7 " + ch.name); b.dataset.v = ch.c;
      tags(b, ch);
      b.addEventListener("click", function () { st.c = ch.c; paint(); }); rowC.appendChild(b);
    });
    d.pages.forEach(function (p, i) {
      var b = el("button", { type: "button" }, p.name); b.dataset.v = String(i);
      b.addEventListener("click", function () { if (st.p !== i) { st.p = i; load(); } }); rowP.appendChild(b);
    });
    d.widths.forEach(function (w, i) {
      var b = el("button", { type: "button" }, w.name); b.dataset.v = String(i);
      b.addEventListener("click", function () { st.w = i; fit(); paint(); }); rowW.appendChild(b);
    });
    pickBtn.addEventListener("click", function () { picks[d.id] = st.c; save(); renderBar(); paint(); });
    load();
  });
  window.addEventListener("resize", function () { fits.forEach(function (f) { f(); }); });

  document.getElementById("copy").addEventListener("click", function () {
    var t = M.title + " picks: " + D.map(function (d) { return d.n + "-" + (picks[d.id] || "?"); }).join(", ");
    var out = document.getElementById("copied");
    function shown() { out.textContent = t;
      try { var r = document.createRange(); r.selectNodeContents(out); var s = getSelection(); s.removeAllRanges(); s.addRange(r); } catch (e) {} }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(t).then(function () { out.textContent = "Copied: " + t; }, shown);
    } else { shown(); }
  });
  renderBar();
})();
"""


def page_data(m, src):
    """What the page script needs: no file paths, no CSS, no file names; what the user reads, and
    each choice's frame URL per page (`src(d, c, p)`, Plan.frame_url)."""
    out = {"title": m["title"], "id": m["id"], "decisions": []}
    for n, d in enumerate(m["decisions"], 1):
        out["decisions"].append({
            "id": d["id"], "n": n, "title": d["title"], "why": d["why"],
            "pages": [{"name": p["name"], "path": p["path"], "q": p.get("q", "")} for p in d["pages"]],
            "widths": d["widths"],
            "choices": [{"c": c["c"], "name": c["name"], "text": c["text"],
                         "recommended": c.get("recommended") is True, "codex": "codex_call" in c,
                         "src": [src(d, c, p) for p in d["pages"]]}
                        for c in d["choices"]],
        })
    return out


def build_page(m, src):
    data = json.dumps(page_data(m, src), ensure_ascii=True).replace("</", "<\\/")
    title = html.escape(m["title"])
    lede = html.escape(m.get("lede") or DEFAULT_LEDE)
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n"
            "<header class=\"top\">\n  <h1>%s</h1>\n  <p class=\"lede\">%s</p>\n</header>\n"
            "<div id=\"decisions\"></div>\n"
            "<footer class=\"bar\">\n  <b>Your picks:</b> <span id=\"picks\"></span>\n"
            "  <button type=\"button\" id=\"copy\">Copy picks</button> <span id=\"copied\" class=\"picked\"></span>\n"
            "</footer>\n<script type=\"application/json\" id=\"cc-data\">%s</script>\n"
            "<script>%s</script>\n</body>\n</html>\n" % (title, PAGE_CSS, title, lede, data, PAGE_JS))


# --------------------------------------------------------------------------- the server

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype, what=""):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if what:
            self.send_header("X-Compare-Choices", what)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, code, path, query=""):
        self.send_response(code)
        self.send_header("Location", path + (("?" + query) if query else ""))
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def referer_choice(self, plan):
        """(decision, choice) when this request's Referer is a page of a FOLDER choice on this same
        server (/v/<decision>/<choice>/...); else None."""
        ref = self.headers.get("Referer")
        if not ref:
            return None
        r = urllib.parse.urlsplit(ref)
        if r.netloc.lower() != (self.headers.get("Host") or "").lower():
            return None
        m = REFERER_CHOICE.match(r.path)
        if not m:
            return None
        did, cid = urllib.parse.unquote(m.group(1)), urllib.parse.unquote(m.group(2))
        c = plan.choice(did, cid)
        return (did, cid) if c is not None and c.get("kind") == "folder" else None

    def do_GET(self):
        plan = self.server.plan
        u = urllib.parse.urlsplit(self.path)
        try:
            if not u.path.startswith("/v/"):
                # A folder choice's JavaScript asks for a root-absolute path (import "/js/theme.js",
                # import(), new Worker): HTML and CSS were rewritten, JavaScript is not, so send it
                # into the choice. A redirect, not the bytes in place: the module's own URL is then
                # inside the choice, so ITS root-absolute and relative imports are routed too.
                routed = self.referer_choice(plan)
                if routed is not None:
                    return self.redirect(REDIRECT_CHOICE, "/v/%s/%s%s" % (routed[0], routed[1], u.path), u.query)
            # A frame that navigates to / (a logo link) gets the site's home page, not the picker.
            if u.path in ("/", "/index.html") and self.headers.get("Sec-Fetch-Dest", "").lower() != "iframe":
                return self.send(200, self.server.page, "text/html; charset=utf-8", "comparison page")
            parts = u.path.split("/", 4)
            if len(parts) >= 4 and parts[1] == "v" and parts[2] and parts[3]:
                if len(parts) == 4:                     # /v/<decision>/<choice> without its slash
                    return self.redirect(REDIRECT_SLASH, u.path + "/", u.query)
                code, body, ctype, what = plan.serve_choice(parts[2], parts[3], "/" + parts[4])
                if code == REDIRECT_SLASH:
                    return self.redirect(code, what, u.query)
                return self.send(code, body, ctype, what)
            f, base_slashless = resolve_ex(plan.base, u.path) if plan.base is not None else (None, False)
            if base_slashless:
                return self.redirect(REDIRECT_SLASH, u.path + "/", u.query)
            if f is None:
                return self.send(404, b"not found", "text/plain; charset=utf-8")
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            return self.send(200, f.read_bytes(), _ctype(ctype), "base")
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return None
        except Exception as e:  # noqa: BLE001
            return self.send(500, ("compare-choices: %s" % e).encode("utf-8"), "text/plain; charset=utf-8")


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = False

    def server_bind(self):
        # Windows lets a second SO_REUSEADDR bind share a port; claim it exclusively.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)


def port_answers(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def make_server(plan, port):
    srv = Server(("127.0.0.1", port), Handler)
    srv.plan, srv.page = plan, plan.page()
    return srv


# --------------------------------------------------------------------------- commands

def cmd_check(args):
    plan = Plan(args.manifest)
    try:
        ok = plan.validate()
        plan.report()
        if not ok:
            return EXIT_INVALID
        urls = plan.urls()
        emit("CHECK OK", "decisions=%d choices=%d pages=%d urls=%d" % (
            len(plan.m["decisions"]), sum(len(d["choices"]) for d in plan.m["decisions"]),
            sum(len(d["pages"]) for d in plan.m["decisions"]), len(urls)))
        if not args.live:
            return EXIT_OK
        return live(plan, urls)
    finally:
        plan.cleanup()


def framing_refused(headers):
    """Why a response may not be shown in the comparison page's frame (another origin), or ''."""
    xfo = (headers.get("X-Frame-Options") or "").strip().lower()
    if xfo in ("deny", "sameorigin"):
        return "X-Frame-Options: %s" % xfo.upper()
    csp = headers.get("Content-Security-Policy") or ""
    if "frame-ancestors" in csp.lower():
        return "a Content-Security-Policy frame-ancestors rule"
    return ""


def live(plan, urls):
    srv = make_server(plan, 0)
    port = srv.server_address[1]
    origin = "http://127.0.0.1:%d" % port
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    t.start()
    rows = [("comparison page", "/")] + [("%s/%s %s" % (d["id"], c["c"], c["kind"]), u) for d, c, p, u in urls]
    good, warnings = 0, []
    try:
        emit("LIVE", "GET each URL on %s, following redirects; a url choice's on its own server "
                     "(status, bytes, applied, url)" % origin)
        for label, u in rows:
            full = u if u.startswith("http://") else origin + u
            final, blocked = full, ""
            try:
                with urllib.request.urlopen(full, timeout=30) as r:
                    status, body, what, final = r.status, r.read(), r.headers.get("X-Compare-Choices", ""), r.geturl()
                    if u.startswith("http://"):
                        blocked = framing_refused(r.headers)
            except urllib.error.HTTPError as e:
                status, body, what = e.code, e.read(), ""
            except OSError as e:
                status, body, what = 0, b"", str(e)
            good += status == 200
            if blocked:
                warnings.append("%s answers 200 but carries %s: its frame on the comparison page would be "
                                "blank" % (u, blocked))
            shown = u if final == full else "%s -> %s" % (u, final[len(origin):] if final.startswith(origin) else final)
            print("  %3d  %8d  %-22s %s" % (status, len(body), what or label, shown), flush=True)
    finally:
        srv.shutdown()
        srv.server_close()
    for w in warnings:
        emit("WARNING", w)
    if good == len(rows):
        emit("LIVE OK", "%d/%d answered 200" % (good, len(rows)))
        return EXIT_OK
    emit("LIVE FAILED", "%d/%d answered 200" % (good, len(rows)))
    return EXIT_INVALID


def _interrupt(signum, frame):
    raise KeyboardInterrupt


def cmd_serve(args):
    plan = Plan(args.manifest)
    try:
        ok = plan.validate()
        plan.report()
        if not ok:
            return EXIT_INVALID
        port = args.port if args.port is not None else plan.m.get("port", DEFAULT_PORT)
        if port and port_answers(port):
            print("COMPARE-CHOICES REFUSED: something already answers on port %d; stop it first or pass "
                  "--port." % port, flush=True)
            return EXIT_INVALID
        try:
            srv = make_server(plan, port)
        except OSError as e:
            emit("INVALID", "cannot listen on 127.0.0.1:%d: %s" % (port, e))
            return EXIT_INVALID
        for name in ("SIGTERM", "SIGBREAK"):
            if hasattr(signal, name):
                try:
                    signal.signal(getattr(signal, name), _interrupt)
                except (ValueError, OSError):
                    pass
        with srv:
            print("COMPARISON PAGE: http://127.0.0.1:%d/   (Ctrl-C stops it)" % srv.server_address[1], flush=True)
            try:
                srv.serve_forever(poll_interval=0.3)
            except KeyboardInterrupt:
                pass
        return EXIT_OK
    finally:
        plan.cleanup()
        if plan.tmp is not None:
            emit("stopped", "removed %s" % plan.tmp)


# --------------------------------------------------------------------------- selftest

def selftest():
    """In-process: a snapshot base, a keep / css / fragment manifest, the refusals that need no
    git, and the served bytes."""
    results = []

    def ok(cond, label):
        results.append((bool(cond), label))

    tmp = Path(tempfile.mkdtemp(prefix="compare-choices-selftest-"))
    try:
        site = tmp / "site"
        site.mkdir()
        page = ('<!doctype html><html><head><title>t</title></head><body>'
                '<div id="a"><div>in</div></div><p>KEEP-ME</p></body></html>')
        (site / "index.html").write_text(page, encoding="utf-8", newline="")
        (tmp / "f.html").write_text("<div id=\"a\">NEW</div>", encoding="utf-8")
        man = {"title": "Selftest", "id": "selftest", "base": {"snapshot_dir": "site"},
               "decisions": [{"id": "d", "title": "D", "why": "W", "pages": [{"name": "Home", "path": "/"}],
                              "choices": [{"c": "1", "kind": "keep"},
                                          {"c": "2", "kind": "css", "name": "C", "text": "t", "css": "p{x:1}"},
                                          {"c": "3", "kind": "fragment", "name": "F", "text": "t",
                                           "fragment_file": "f.html", "replace_id": "a"}]}]}

        def plan_for(m):
            p = tmp / "m.json"
            p.write_text(json.dumps(m), encoding="utf-8")
            pl = Plan(p)
            pl.validate()
            return pl
        pl = plan_for(man)
        ok(not pl.problems, "the selftest manifest validates")
        s, e, n = fragment_span(page, "a")
        ok(n == 1 and page[s:e] == '<div id="a"><div>in</div></div>', "fragment_span tracks nested depth")
        code, body, _t, _w = pl.serve_choice("d", "1", "/")
        t = body.decode("utf-8")
        i, j = t.find(HELPER_START), t.find(HELPER_END)
        ok(code == 200 and t[:i] + t[j + len(HELPER_END):] == page, "keep = the base bytes plus the helper")
        code, body, _t, _w = pl.serve_choice("d", "2", "/")
        ok(b"p{x:1}" in body and CSS_OPEN.encode() in body, "css choice carries its style")
        code, body, _t, _w = pl.serve_choice("d", "3", "/")
        ok(b"NEW" in body and b"<div>in</div>" not in body and b"KEEP-ME" in body, "fragment swapped")
        bad = json.loads(json.dumps(man))
        bad["decisions"][0]["choices"].reverse()
        ok(any("first choice must be kind keep" in p for p in plan_for(bad).problems), "keep-first refusal")
        bad = json.loads(json.dumps(man))
        bad["decisions"][0]["choices"][1]["text"] = " ".join(["w"] * (MAX_WORDS + 1))
        ok(any("over 60 words" in p for p in plan_for(bad).problems), "61-word refusal")
        good = json.loads(json.dumps(man))
        good["decisions"][0]["choices"][1]["text"] = " ".join(["w"] * MAX_WORDS)
        ok(not plan_for(good).problems, "60 words pass")
        page_html = pl.page().decode("utf-8")
        ok("Copy picks" in page_html and "http://" not in page_html and "https://" not in page_html,
           "the page carries Copy picks and no external URL")
        (site / "docs").mkdir()
        (site / "docs" / "index.html").write_text(page, encoding="utf-8", newline="")
        ok(resolve_ex(site, "/docs") == ((site / "docs" / "index.html").resolve(), True)
           and resolve_ex(site, "/docs/")[1] is False and resolve_ex(site, "/")[1] is False,
           "a directory path without its slash is flagged for the redirect, with it is not")
        code, _b, _t, where = pl.serve_choice("d", "1", "/docs")
        ok(code == REDIRECT_SLASH and where == "/v/d/1/docs/", "/v/d/1/docs answers 301 to /v/d/1/docs/")
        ok(url_problem("http://127.0.0.1:5173/") is None and url_problem("http://localhost:3000") is None
           and "loopback" in (url_problem("http://example.com:3000/") or "")
           and url_problem("http://127.0.0.1/") and url_problem("http://127.0.0.1:5173/app"),
           "url: a loopback origin with a port passes; another host, no port, a path are refused")
        ok(referrer_strippers('<meta name="referrer" content="no-referrer">') and
           referrer_strippers('<script referrerpolicy=strict-origin src=x>') and not
           referrer_strippers('<meta name="referrer" content="no-referrer-when-downgrade">'),
           "a path-stripping referrer policy is found; no-referrer-when-downgrade is not one")
        bad = json.loads(json.dumps(man))
        bad["decisions"] = 12
        pb = plan_for(bad)
        ok(pb.halt and pb.base is None and any("'decisions'" in p for p in pb.problems),
           "a container of the wrong shape halts before the base is frozen")
        bad = json.loads(json.dumps(man))
        bad["decisions"][0]["choices"][2]["replace_id"] = 123
        pb = plan_for(bad)
        ok(pb.halt and any("'replace_id' must be a string" in p for p in pb.problems),
           "a field of the wrong type is refused by name, and halts")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    for good_, label in results:
        print("  %s %s" % ("ok  " if good_ else "FAIL", label))
    passed = sum(1 for g, _ in results if g)
    print("SELFTEST %s %d/%d" % ("PASS" if passed == len(results) else "FAIL", passed, len(results)))
    return 0 if passed == len(results) else 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--selftest"]:
        return selftest()
    ap = argparse.ArgumentParser(prog="compare-choices.py", description="One comparison page for an option run.")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="serve the comparison page")
    s.add_argument("manifest")
    s.add_argument("--port", type=int, default=None)
    c = sub.add_parser("check", help="validate the manifest (--live: and GET every URL)")
    c.add_argument("manifest")
    c.add_argument("--live", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return EXIT_USAGE if e.code else EXIT_OK
    if args.cmd == "serve":
        return cmd_serve(args)
    if args.cmd == "check":
        return cmd_check(args)
    ap.print_usage()
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
