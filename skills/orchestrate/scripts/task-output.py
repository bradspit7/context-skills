#!/usr/bin/env python
"""task-output.py -- extract Workflow run results + per-agent outputs from Claude Code transcripts.

Kills the post-run probe-fail-reparse loop (mined 4x independently, 2026-07-04 skill audit):
after a Workflow run, get the return value, per-agent structured outputs, and logs WITHOUT
hand-rolled JSON probes that fumble on encoding, entity-escapes, and result wrappers.

Data layout (probed live 2026-07-05 -- do not trust from memory, re-probe if this errors):
  ~/.claude/projects/<slug>/<session>/workflows/wf_<id>.json          run journal (result, logs, progress)
  ~/.claude/projects/<slug>/<session>/subagents/workflows/<runId>/agent-<agentId>.jsonl
                                                                      per-agent transcript; structured
                                                                      output = last StructuredOutput tool_use
Usage:
  task-output.py                          newest run for this project: summary + result shape
  task-output.py --list                   recent runs (this project; --all-projects to widen)
  task-output.py wf_c502254a              summary of that run (runId prefix ok)
  task-output.py wf_c502254a --full       dump the full result JSON
  task-output.py wf_c502254a --key primary.0.title    dump one keypath of the result
  task-output.py wf_c502254a --logs       the run's log() lines
  task-output.py wf_c502254a --agents     per-agent table (label, model, state, tokens)
  task-output.py wf_c502254a --agent a07e    one agent's structured output (id prefix or label)
  task-output.py wf_c502254a --extract out.json   all agents' outputs -> JSON (fleet-resume step 1)
  task-output.py <path .json|.jsonl>      parse a journal / agent transcript file directly
"""
import argparse
import glob
import html
import io
import json
import os
import re
import sys
from pathlib import Path

# Windows console default is cp1252 -- force UTF-8 so dumps never die on a smart quote.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECTS = Path.home() / ".claude" / "projects"
ENTITY_RE = re.compile(r"&(?:quot|amp|lt|gt|#x?[0-9a-fA-F]+);")


def cwd_slug():
    return re.sub(r"[^A-Za-z0-9]", "-", str(Path.cwd()))


def unwrap(obj, max_layers=6):
    """Peel {"result": X} wrappers and JSON-encoded-in-a-string layers (entity-decoding when
    a parse only succeeds after html.unescape). Never unescapes content that already parses."""
    for _ in range(max_layers):
        if isinstance(obj, dict) and set(obj.keys()) == {"result"}:
            obj = obj["result"]
            continue
        if isinstance(obj, str):
            s = obj.strip()
            if s[:1] in "{[":
                try:
                    obj = json.loads(s)
                    continue
                except (json.JSONDecodeError, ValueError):
                    if ENTITY_RE.search(s):
                        try:
                            obj = json.loads(html.unescape(s))
                            continue
                        except (json.JSONDecodeError, ValueError):
                            pass
            break
        break
    return obj


def load_json(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return json.load(f)


def find_journals(all_projects=False):
    """Run journals, newest first. Default scope: the project for cwd; fall back to all."""
    scopes = []
    if not all_projects:
        p = PROJECTS / cwd_slug()
        if p.is_dir():
            scopes = [p]
    if not scopes:
        scopes = [d for d in PROJECTS.iterdir() if d.is_dir()] if PROJECTS.is_dir() else []
    journals = []
    for proj in scopes:
        journals += glob.glob(str(proj / "*" / "workflows" / "wf_*.json"))
    return sorted(journals, key=os.path.getmtime, reverse=True)


def resolve_target(target, all_projects=False):
    """target = None (newest), runId prefix, or a direct file path. Returns (kind, path):
    kind 'journal' or 'agent-jsonl'."""
    if target and os.path.isfile(target):
        return ("agent-jsonl" if target.endswith(".jsonl") else "journal", target)
    journals = find_journals(all_projects)
    if not journals:
        sys.exit("no workflow run journals found under %s (try --all-projects)" % PROJECTS)
    if not target:
        return ("journal", journals[0])
    want = target if target.startswith("wf_") else "wf_" + target
    hits = [j for j in journals if os.path.basename(j).startswith(want)]
    if not hits:
        sys.exit("no run matching %r; use --list to see recent runs" % target)
    return ("journal", hits[0])


def agents_dir_for(journal_path):
    run_id = os.path.basename(journal_path)[: -len(".json")]
    return Path(journal_path).parent.parent / "subagents" / "workflows" / run_id


def agent_entries(journal):
    return [e for e in journal.get("workflowProgress") or [] if e.get("type") == "workflow_agent"]


def agent_transcript_output(path):
    """Last StructuredOutput tool_use input in the transcript; falls back to the last
    assistant text block (agents without a schema return prose)."""
    structured, text = None, None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            content = (rec.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use" and c.get("name") == "StructuredOutput":
                    structured = c.get("input")
                elif c.get("type") == "text" and rec.get("type") == "assistant":
                    text = c.get("text")
    if structured is not None:
        return unwrap(structured)
    return {"final_text": text} if text else None


def keypath_get(obj, keypath):
    node = obj
    for part in keypath.split("."):
        if isinstance(node, list):
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                sys.exit("keypath %r: %r is not a valid index into a list of %d" % (keypath, part, len(node)))
        elif isinstance(node, dict):
            if part not in node:
                sys.exit("keypath %r: no key %r; available: %s" % (keypath, part, ", ".join(sorted(node)[:20])))
            node = node[part]
        else:
            sys.exit("keypath %r: hit a %s at %r, cannot descend" % (keypath, type(node).__name__, part))
    return node


def shape_lines(obj, indent="  "):
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if isinstance(v, list):
                out.append("%s%s: list[%d]" % (indent, k, len(v)))
            elif isinstance(v, dict):
                out.append("%s%s: dict{%d keys}" % (indent, k, len(v)))
            elif isinstance(v, str) and len(v) > 100:
                out.append("%s%s: str[%d chars]" % (indent, k, len(v)))
            else:
                out.append("%s%s: %s" % (indent, k, json.dumps(v, ensure_ascii=False)))
        return out
    if isinstance(obj, list):
        return ["%slist[%d]" % (indent, len(obj))]
    return [indent + json.dumps(obj, ensure_ascii=False)[:200]]


def dump(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def fmt_duration(ms):
    if not ms:
        return "?"
    s = int(ms / 1000)
    return "%dm%02ds" % (s // 60, s % 60) if s >= 60 else "%ds" % s


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="runId (prefix ok) or a journal/.jsonl file path; default = newest run")
    ap.add_argument("--list", action="store_true", help="list recent runs")
    ap.add_argument("--all-projects", action="store_true", help="search every project, not just cwd's")
    ap.add_argument("--full", action="store_true", help="dump the full result JSON")
    ap.add_argument("--key", help="dump one keypath of the result, e.g. primary.0.title")
    ap.add_argument("--logs", action="store_true", help="print the run's log() lines")
    ap.add_argument("--agents", action="store_true", help="per-agent table")
    ap.add_argument("--agent", help="one agent's output, by agentId prefix or exact label")
    ap.add_argument("--extract", nargs="?", const="-", metavar="FILE",
                    help="all agents' structured outputs as JSON (to FILE, or stdout)")
    args = ap.parse_args()

    if args.list:
        for j in find_journals(args.all_projects)[:20]:
            try:
                jr = load_json(j)
            except (json.JSONDecodeError, OSError) as e:
                print("%-20s UNREADABLE (%s)" % (os.path.basename(j), e))
                continue
            print("%-20s %-24s %-10s agents=%-4s tokens=%-9s %s" % (
                jr.get("runId", os.path.basename(j)), (jr.get("workflowName") or "?")[:24],
                jr.get("status", "?"), jr.get("agentCount", "?"), jr.get("totalTokens", "?"),
                jr.get("timestamp", "")[:19]))
        return

    kind, path = resolve_target(args.target, args.all_projects)

    if kind == "agent-jsonl":
        out = agent_transcript_output(path)
        if out is None:
            sys.exit("no StructuredOutput call and no assistant text in %s" % path)
        dump(out)
        return

    journal = load_json(path)
    result = unwrap(journal.get("result"))

    if args.key is not None:
        dump(keypath_get(result, args.key))
        return
    if args.full:
        dump(result)
        return
    if args.logs:
        for line in journal.get("logs") or []:
            print(line if isinstance(line, str) else json.dumps(line, ensure_ascii=False))
        return
    if args.agents:
        for e in agent_entries(journal):
            print("%-19s %-18s %-9s %-26s %-12s tok=%s" % (
                e.get("agentId", "?"), (e.get("label") or "?")[:18], e.get("state", "?"),
                (e.get("model") or "?")[:26], (e.get("phaseTitle") or "")[:12], e.get("tokens", "?")))
        return
    if args.agent or args.extract:
        adir = agents_dir_for(path)
        files = sorted(glob.glob(str(adir / "agent-*.jsonl")))
        if not files:
            sys.exit("no agent transcripts under %s (crashed before any agent, or pruned)" % adir)
        meta = {e.get("agentId"): e for e in agent_entries(journal)}
        if args.agent:
            hits = [f for f in files if os.path.basename(f)[len("agent-"):].startswith(args.agent)]
            if not hits:
                hits = [f for f in files
                        if (meta.get(os.path.basename(f)[len("agent-"):-len(".jsonl")], {}).get("label")) == args.agent]
            if not hits:
                sys.exit("no agent with id prefix or label %r; use --agents to list" % args.agent)
            if len(hits) > 1:
                print("%d agents match; dumping the first. All matches:" % len(hits), file=sys.stderr)
                for h in hits:
                    print("  " + os.path.basename(h), file=sys.stderr)
            out = agent_transcript_output(hits[0])
            dump(out if out is not None else {"error": "no output found", "file": hits[0]})
            return
        # --extract: every agent -> one JSON blob (fleet-resume recipe, step 1)
        agents = []
        for f in files:
            aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
            m = meta.get(aid, {})
            agents.append({"agentId": aid, "label": m.get("label"), "phase": m.get("phaseTitle"),
                           "model": m.get("model"), "state": m.get("state"),
                           "output": agent_transcript_output(f)})
        blob = {"runId": journal.get("runId"), "status": journal.get("status"), "agents": agents}
        if args.extract == "-":
            dump(blob)
        else:
            with io.open(args.extract, "w", encoding="utf-8") as f:
                json.dump(blob, f, indent=2, ensure_ascii=False)
            print("wrote %d agent outputs -> %s" % (len(agents), args.extract))
        return

    # default: summary + result shape
    print("run %s  %s  status=%s  agents=%s  tokens=%s  duration=%s" % (
        journal.get("runId", "?"), journal.get("workflowName", "?"), journal.get("status", "?"),
        journal.get("agentCount", "?"), journal.get("totalTokens", "?"), fmt_duration(journal.get("durationMs"))))
    print("journal: %s" % path)
    phases = [p.get("title") for p in journal.get("phases") or [] if isinstance(p, dict)]
    if phases:
        print("phases: " + ", ".join(str(p) for p in phases))
    logs = journal.get("logs") or []
    print("logs: %d (--logs to print)" % len(logs))
    if result is None:
        print("result: MISSING (run %s) -- per-agent outputs may still be recoverable: --agents / --extract"
              % journal.get("status", "?"))
    else:
        print("result shape (--full to dump, --key <path> for one node):")
        for line in shape_lines(result):
            print(line)


if __name__ == "__main__":
    main()
