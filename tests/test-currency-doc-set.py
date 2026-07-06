#!/usr/bin/env python
"""Supported-doc-set fixtures for currency-check.sh's primary-doc detection.

The currency gate must recognize a handoff doc in ANY supported location -- root
HANDOFF.md, context/HANDOFF.md, root CONTEXT.md, or continuation/context.md -- and run
its currency checks against that doc. A doc present only under context/ once fell through
to "NO PRIMARY DOC ON DISK" (silent zero-coverage); this suite locks that shut. It is the
behavioral net validate.sh's structural checks (bash -n / frontmatter / CRLF) cannot give.

Run:  python tests/test-currency-doc-set.py   (needs bash on PATH -- git-bash on Windows)
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "skills" / "analyze-context" / "scripts" / "currency-check.sh"
HOST = socket.gethostname()

passed = failed = 0


def check(cond, name, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print("  PASS %s" % name)
    else:
        failed += 1
        print("  FAIL %s %s" % (name, extra))


def make_repo(docs):
    """docs: {relpath: text}. Seeds a scratch git repo committing each doc."""
    d = Path(tempfile.mkdtemp(prefix="doc-set-"))
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

    def git(*args):
        subprocess.run(["git", "-C", str(d)] + list(args), check=True,
                       capture_output=True, env=env)

    git("init", "-q")
    for rel, text in docs.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    return d


def run_gate(repo):
    r = subprocess.run(["bash", str(SCRIPT)], cwd=str(repo),
                       capture_output=True, text=True, timeout=120)
    return r.stdout + r.stderr


BODY = "# Handoff\n\n**Machine:** %s\n\nbody\n" % HOST

try:
    print("supported doc locations are recognized as the primary doc:")
    for rel in ("HANDOFF.md", "context/HANDOFF.md", "CONTEXT.md", "continuation/context.md"):
        out = run_gate(make_repo({rel: BODY}))
        check(("%s last commit" % rel) in out and "NO PRIMARY DOC ON DISK" not in out,
              "%s recognized as primary doc" % rel, out[-300:])

    print("root HANDOFF.md wins when several are present (first-found precedence):")
    out = run_gate(make_repo({"HANDOFF.md": BODY, "context/HANDOFF.md": BODY, "CONTEXT.md": BODY}))
    check("HANDOFF.md last commit" in out and "context/HANDOFF.md last commit" not in out,
          "root HANDOFF.md preferred over context/ and CONTEXT.md", out[-300:])

    print("no supported doc -> NO PRIMARY DOC ON DISK (and never a false primary):")
    out = run_gate(make_repo({"README.md": "nothing here\n"}))
    check("NO PRIMARY DOC ON DISK" in out, "bare repo (no handoff) -> NO PRIMARY DOC ON DISK", out[-300:])

    print("\n%d passed, %d failed" % (passed, failed))
    sys.exit(1 if failed else 0)
finally:
    for p in Path(tempfile.gettempdir()).glob("doc-set-*"):
        shutil.rmtree(p, ignore_errors=True)
