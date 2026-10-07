#!/usr/bin/env python
"""workflow-lanes.py -- session-evidence.sh's WORKFLOWS section: the finished lanes of runs that never completed.

The Workflow tool notifies only when a WHOLE run completes. When its remaining lanes die (a machine
switch, a usage limit), the lanes that already FINISHED stay unread in the run's journal, and a wrap
that reads only the notification records every lane as "killed, re-run". Measured in another
project: two lanes had returned FAIL before the cut, and their verdicts sat unread for six days.

For each in-scope run whose status is not `completed`, this prints every lane that has a result
(label + verdict) and, on ONE line, only the lanes with no result. A run that is not terminal yet
(`running`, or a status this script does not know) lists its finished lanes but never names a lane
as needing a re-run. Prints NOTHING when no in-scope run is incomplete.

Scope -- never wider than the slug dirs it is handed:
  * journals are globbed ONLY under --projects-dir/<slug>/*/workflows/ for each --slug. It never
    calls task-output.py's find_journals(), which falls back to EVERY project when cwd's project
    has none (G#97).
  * a journal is in the window when its mtime is at or after the EARLIER of --handoff-epoch (the
    last commit touching HANDOFF.md: the window this wrap covers) and --days days back. The day
    floor keeps a dead run visible when a HANDOFF commit made on the OTHER machine is newer than it.

Parsing is task-output.py's (orchestrate/scripts, imported by path): load_json, agent_entries,
agents_dir_for, agent_transcript_output. A missing or broken task-output.py is reported, never
silent.

usage: workflow-lanes.py --projects-dir DIR --slug SLUG [--slug SLUG ...] [--days 7] [--handoff-epoch N]
Exit 0 always, unless the arguments are wrong (2).
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
TASK_OUTPUT = HERE.parent.parent / "orchestrate" / "scripts" / "task-output.py"
HEADER = ("== WORKFLOWS (runs in this project's scope that did not complete: report each FINISHED lane's "
          "verdict; only the NO RESULT lanes need a re-run) ==")

COMPLETED = {"completed"}
# Terminal and not completed: every lane without a result will never get one.
DEAD = {"killed", "failed", "cancelled", "canceled", "aborted", "error", "errored", "stopped",
        "timeout", "timed_out", "timedout"}
# A lane's own top-level fields that carry its verdict, in the order they are shown.
VERDICT_KEYS = ("verdict", "disposition", "decision", "outcome", "status", "result",
                "passed", "pass", "ok", "agree")
PREVIEW_VERDICT_RE = re.compile(
    r'"(%s)"\s*:\s*("(?:[^"\\]|\\.)*"|true|false|null|-?\d+(?:\.\d+)?)' % "|".join(VERDICT_KEYS))
MAX_LISTED = 40     # finished lanes listed per run; the rest are counted, never dropped silently


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def scalar(v):
    return v is None or isinstance(v, (str, int, float, bool))


def show(v):
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v


def verdict_of_output(out):
    """'verdict=FAIL, disposition=NEW' from a structured output's own top-level fields, else None."""
    if not isinstance(out, dict):
        return None
    parts = ["%s=%s" % (k, clip(show(out[k]), 80)) for k in VERDICT_KEYS if k in out and scalar(out[k])]
    return ", ".join(parts[:3]) or None


def verdict_of_preview(preview):
    """The same fields read off a (usually truncated) resultPreview, else None."""
    seen, parts = set(), []
    for m in PREVIEW_VERDICT_RE.finditer(preview or ""):
        k = m.group(1)
        if k in seen:
            continue
        seen.add(k)
        try:
            v = json.loads(m.group(2))
        except ValueError:
            v = m.group(2)
        parts.append((VERDICT_KEYS.index(k), "%s=%s" % (k, clip(show(v), 80))))
    return ", ".join(p for _, p in sorted(parts)[:3]) or None


def lane_summary(to, journal_path, entry):
    """The one-line result of a lane that HAS one, or None when it has none.

    A lane has a result when the journal marks it `done` or recorded a resultPreview. Its verdict is
    read from its own transcript's StructuredOutput first (the preview is cut at ~400 chars and is
    usually all sources_opened), then from the preview, then the preview text itself."""
    preview = entry.get("resultPreview")
    if entry.get("state") != "done" and not preview:
        return None
    out = None
    aid = entry.get("agentId")
    if aid:
        tp = to.agents_dir_for(str(journal_path)) / ("agent-%s.jsonl" % aid)
        if tp.is_file():
            try:
                out = to.agent_transcript_output(str(tp))
            except (OSError, ValueError):
                out = None
    v = verdict_of_output(out) or verdict_of_preview(preview)
    if v:
        return v
    if preview:
        return "preview: " + clip(preview, 160)
    if isinstance(out, dict) and out.get("final_text"):
        return "text: " + clip(out["final_text"], 160)
    return "(done; no result text recorded)"


def age(seconds):
    h = seconds / 3600.0
    return "%dm" % (seconds // 60) if h < 1 else ("%dh" % h if h < 48 else "%dd" % (h / 24))


def first_line(s):
    for ln in str(s or "").splitlines():
        if ln.strip():
            return clip(ln, 140)
    return ""


def load_task_output():
    spec = importlib.util.spec_from_file_location("task_output_for_lanes", str(TASK_OUTPUT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for name in ("load_json", "agent_entries", "agents_dir_for", "agent_transcript_output"):
        if not callable(getattr(mod, name, None)):
            raise AttributeError("task-output.py has no %s()" % name)
    return mod


def report_run(to, path, journal, now):
    status = str(journal.get("status") or "?")
    lanes = to.agent_entries(journal)
    finished, unrun = [], []
    names = [e.get("label") or e.get("agentId") or "?" for e in lanes]
    for e, label in zip(lanes, names):
        if names.count(label) > 1 and e.get("agentId"):   # a fleet reusing one label: say WHICH lane
            label = "%s (%s)" % (label, str(e.get("agentId"))[:9])
        s = lane_summary(to, path, e)
        if s is None:
            unrun.append("%s [%s]" % (label, e.get("state") or "no state"))
        else:
            finished.append((label, s))
    head = 'RUN %s "%s" status=%s' % (journal.get("runId") or os.path.basename(str(path))[:-5],
                                      journal.get("workflowName") or "?", status)
    dead = status.lower() in DEAD
    if dead and not lanes:
        head += " -- no lane was recorded (the run stopped before any lane started)"
    elif dead:
        head += " -- %d of %d recorded lane(s) finished, %d with no result" % (len(finished), len(lanes), len(unrun))
    else:
        head += (" -- not terminal (still running, or its session ended without recording an outcome; "
                 "journal last written %s ago): %d of %d recorded lane(s) have results so far"
                 % (age(now - os.path.getmtime(str(path))), len(finished), len(lanes)))
    err = first_line(journal.get("error"))
    if err:
        head += "; run error: " + err
    print(head)
    for label, s in finished[:MAX_LISTED]:
        print("  FINISHED %s -- %s" % (label, s))
    if len(finished) > MAX_LISTED:
        print("  ... %d of %d finished lane(s) listed above; the other %d: task-output.py --agents"
              % (MAX_LISTED, len(finished), len(finished) - MAX_LISTED))
    if dead and unrun:
        print("  NO RESULT (only these need a re-run): " + ", ".join(unrun))
    print('  detail: python "%s" "%s" --agents   (--agent <label> for one lane\'s full output)' % (TASK_OUTPUT, path))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--projects-dir", required=True)
    ap.add_argument("--slug", action="append", required=True)
    ap.add_argument("--days", type=float, default=7.0)
    ap.add_argument("--handoff-epoch", default="")
    a = ap.parse_args()

    now = time.time()
    since = now - a.days * 86400
    handoff = None
    if a.handoff_epoch.strip().isdigit():
        handoff = int(a.handoff_epoch.strip())
        since = min(since, handoff)

    root = Path(a.projects_dir)
    slugs = []
    for s in a.slug:
        if s and s not in slugs:
            slugs.append(s)
    journals = []
    for s in slugs:
        journals += glob.glob(os.path.join(glob.escape(str(root)), glob.escape(s), "*", "workflows", "wf_*.json"))
    journals = sorted(set(journals), key=os.path.getmtime, reverse=True)
    in_window = [j for j in journals if os.path.getmtime(j) >= since]
    older = len(journals) - len(in_window)
    if not in_window:
        return 0

    try:
        to = load_task_output()
    except Exception as e:  # any import failure is reported, never silent
        print()
        print(HEADER)
        print("WORKFLOWS: could not check -- %d journal(s) in scope, but %s could not be loaded (%s)"
              % (len(in_window), TASK_OUTPUT, clip(e, 160)))
        return 0

    incomplete, completed, unreadable = [], 0, []
    for j in in_window:
        try:
            jr = to.load_json(j)
        except (OSError, ValueError) as e:
            unreadable.append((j, clip(e, 120)))
            continue
        if not isinstance(jr, dict):
            unreadable.append((j, "not a JSON object"))
        elif str(jr.get("status") or "").lower() in COMPLETED:
            completed += 1
        else:
            incomplete.append((j, jr))
    if not incomplete and not unreadable:
        return 0

    print()
    print(HEADER)
    win = time.strftime("%Y-%m-%d %H:%M", time.localtime(since))
    basis = ("the earlier of the last HANDOFF.md commit (%s) and %g days back"
             % (time.strftime("%Y-%m-%d", time.localtime(handoff)), a.days)) if handoff is not None \
        else "%g days back; no commit touches HANDOFF.md" % a.days
    print("scope: %d journal(s) under %s/{%s} modified since %s (%s); %d completed (not listed), "
          "%d incomplete (below), %d unreadable; %d older journal(s) not scanned"
          % (len(in_window), root, ",".join(slugs), win, basis, completed, len(incomplete),
             len(unreadable), older))
    for j, why in unreadable:
        print("UNREADABLE journal %s: %s" % (j, why))
    for j, jr in incomplete:
        report_run(to, j, jr, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
