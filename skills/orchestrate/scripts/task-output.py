#!/usr/bin/env python
"""task-output.py -- extract Workflow run results + per-agent outputs from Claude Code transcripts.

Kills the post-run probe-fail-reparse loop (mined 4x independently, 2026-07-04 skill audit):
after a Workflow run, get the return value, per-agent structured outputs, and logs WITHOUT
hand-rolled JSON probes that fumble on encoding, entity-escapes, and result wrappers.

Data layout (probed live 2026-07-05 -- do not trust from memory, re-probe if this errors):
  ~/.claude/projects/<slug>/<session>/workflows/wf_<id>.json          run journal (result, logs, progress)
  ~/.claude/projects/<slug>/<session>/subagents/workflows/<runId>/agent-<agentId>.jsonl
                                                                      per-agent transcript; structured
                                                                      output = last ACCEPTED StructuredOutput
                                                                      tool_use (no is_error tool_result)
Usage:
  task-output.py                          newest run for this project: summary + result shape
  task-output.py --list                   recent runs (this project; --all-projects to widen)
  task-output.py wf_c502254a              summary of that run (runId prefix ok)
  task-output.py wf_c502254a --full       dump the full result JSON
  task-output.py wf_c502254a --key primary.0.title    dump one keypath of the result
  task-output.py wf_c502254a --logs       the run's log() lines
  task-output.py wf_c502254a --agents     per-agent table (label, model, state, tokens), plus one
                                          `<agentId> cause: ...` line under each agent with NO result
                                          (schema rejections by field, API error, tool errors, or
                                          an explicit `unknown` / `no transcript`)
  task-output.py wf_c502254a --agent a07e    one agent's structured output (id prefix or label); an agent
                                          whose every StructuredOutput call was rejected prints a
                                          `NOT ACCEPTED:` line and exits 1, never the rejected payload
  task-output.py wf_c502254a --extract out.json   all agents' outputs -> JSON (fleet-resume step 1); such
                                          an agent's record has output null, not_accepted true, and
                                          the blob's top-level not_accepted lists every one
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

# How a dead agent's transcript records its errors -- probed live 2026-10-14 over 4,232 agent transcripts
# (297 StructuredOutput rejections, 1,737 other tool errors, 50 API errors); re-probe if causes read `unknown`.
#   * an error tool result: a `tool_result` block with `is_error: true` and a STRING `content`, matched to its
#     `tool_use` (which carries the tool name) by `tool_use_id`.
#   * a StructuredOutput schema rejection's content: SCHEMA_PREFIX + ajv clauses joined by ", ", each clause
#     `<JSON pointer or root>: <ajv message>`, e.g. "/reason: must NOT have more than 1500 characters".
#   * a StructuredOutput call that is not JSON: "<tool_use_error>InputValidationError: StructuredOutput was
#     called with input that could not be parsed as JSON. ..."
#   * an API error: an assistant record with `isApiErrorMessage: true`, `error` (rate_limit, server_error),
#     `apiErrorStatus` (429, or absent) and the message text in a `<synthetic>` text block.
SCHEMA_PREFIX = "Output does not match required schema:"
UNPARSEABLE_MARK = "could not be parsed as JSON"
CLAUSE_SPLIT_RE = re.compile(r", (?=(?:root|/[^\s:]*): )")
CLAUSE_RE = re.compile(r"^(root|/[^\s:]*): (.+)$", re.S)
# ajv message -> (schema keyword, whether group 1 is shown beside it). maxLength, additionalProperties,
# required, enum and type were seen in real rejections; minLength, maxItems, minItems and pattern are ajv's
# default messages for the same family, not yet seen here. An unmatched message is shown verbatim
# (clipped), never dropped.
AJV_KEYWORDS = [
    (re.compile(r"^must NOT have more than (\d+) characters$"), "maxLength", True),
    (re.compile(r"^must NOT have fewer than (\d+) characters$"), "minLength", True),
    (re.compile(r"^must NOT have more than (\d+) items$"), "maxItems", True),
    (re.compile(r"^must NOT have fewer than (\d+) items$"), "minItems", True),
    (re.compile(r"^must NOT have additional properties$"), "additionalProperties", False),
    (re.compile(r"^must have required property '([^']*)'$"), "required", False),
    (re.compile(r"^must be equal to one of the allowed values"), "enum", False),
    (re.compile(r'^must match pattern "'), "pattern", False),
    (re.compile(r"^must be ([a-z]+(?:,[a-z]+)*)$"), "type", True),
]


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


def transcript_events(path):
    """Walk one agent transcript in order, yielding (kind, record, item) -- the ONE place a tool_result
    with `is_error` is matched to the tool_use it answers (agent_death_cause() and agent_transcript_outcome()
    both read this, so the two can never disagree about which call was rejected):
      ("api_error", rec, message)                   an assistant record with isApiErrorMessage
      ("tool_use", rec, block)                      any tool call; its id is remembered for the match
      ("tool_error", rec, (tool, text, tool_use_id))  an error result, tool named via its call's id
                                                    (a schema-rejection text with no matching call still
                                                    reads as StructuredOutput)
      ("text", rec, block)                          a text block"""
    names = {}
    with open(str(path), encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(rec, dict):
                continue
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            if rec.get("isApiErrorMessage"):
                yield "api_error", rec, msg
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for c in content:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_use":
                    names[c.get("id")] = c.get("name")
                    yield "tool_use", rec, c
                elif c.get("type") == "tool_result" and c.get("is_error"):
                    text = _block_text(c.get("content")).strip()
                    tool = names.get(c.get("tool_use_id")) or (
                        "StructuredOutput" if text.startswith(SCHEMA_PREFIX) else "<unmatched tool_use_id>")
                    yield "tool_error", rec, (tool, text, c.get("tool_use_id"))
                elif c.get("type") == "text":
                    yield "text", rec, c


def agent_transcript_outcome(path):
    """(output, rejected_calls) for one agent transcript.

    output is the input of the LAST StructuredOutput call that did NOT get an error tool_result (unwrapped).
    A rejected call's payload is never an output: when every StructuredOutput call was rejected, output is
    None and rejected_calls says how many -- the agent is NOT ACCEPTED. Only an agent that made no
    StructuredOutput call at all falls back to {"final_text": <its last assistant text>} (agents without a
    schema return prose), else None. (Probed live 2026-10-17: 6,181 StructuredOutput calls in 6,778 agent
    transcripts, every one with a tool_result -- 5,772 accepted, 409 rejected, none unanswered.)"""
    calls, rejected_ids, text = [], set(), None
    for kind, rec, item in transcript_events(path):
        if kind == "tool_use" and item.get("name") == "StructuredOutput":
            calls.append((item.get("id"), item.get("input")))
        elif kind == "tool_error" and item[0] == "StructuredOutput":
            rejected_ids.add(item[2])
        elif kind == "text" and rec.get("type") == "assistant":
            text = item.get("text")
    rejected = sum(1 for tid, _ in calls if tid in rejected_ids)
    accepted = [inp for tid, inp in calls if tid not in rejected_ids and inp is not None]
    if accepted:
        return unwrap(accepted[-1]), rejected
    if rejected:
        return None, rejected
    return ({"final_text": text} if text else None), 0


def agent_transcript_output(path):
    """The agent's output: its last ACCEPTED StructuredOutput input, else (no StructuredOutput call at all) its
    last assistant text as {"final_text": ...}, else None. None too when every StructuredOutput call was
    rejected -- agent_transcript_outcome() says how many."""
    return agent_transcript_outcome(path)[0]


def not_accepted_line(who, rejected):
    """The line --agent and the direct transcript path print for an agent whose every StructuredOutput call
    the schema rejected, in place of the rejected payload."""
    calls = ("1 StructuredOutput call and the schema rejected it" if rejected == 1
             else "%d StructuredOutput calls and the schema rejected all %d" % (rejected, rejected))
    return ("NOT ACCEPTED: %s made %s -- it has no accepted output, and a rejected payload is not shown "
            "as one (--agents prints why it was rejected)" % (who, calls))


def has_result(entry):
    """True when the run journal recorded a result for this agent. state 'done' coincides exactly with a
    `result` record in the run's journal.jsonl (3,608 of 3,608 agents, 0 disagreeing, probed 2026-10-14);
    resultPreview is the second leg workflow-lanes.py's lane_summary() also accepts. Never decided from the
    transcript: a dead agent's last StructuredOutput call is a REJECTED payload, not a result."""
    return entry.get("state") == "done" or bool(entry.get("resultPreview"))


def _block_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(c.get("text") or "" for c in content if isinstance(c, dict))
    return "" if content is None else str(content)


def _clip(s, n):
    s = re.sub(r"\s+", " ", str(s)).strip()
    return s if len(s) <= n else s[: n - 3] + "..."


def _rejection_items(text):
    """The distinct '<field path> (<keyword>)' items one rejected StructuredOutput call names. Array indices
    collapse to * so a cap on a list item counts once per call, not once per element."""
    if UNPARSEABLE_MARK in text:
        return ["unparseable JSON"]
    if not text.startswith(SCHEMA_PREFIX):
        return ['unrecognized error "%s"' % _clip(text, 60)]
    items = []
    for clause in CLAUSE_SPLIT_RE.split(text[len(SCHEMA_PREFIX):].strip()):
        m = CLAUSE_RE.match(clause.strip())
        if not m:
            items.append('unrecognized clause "%s"' % _clip(clause, 60))
            continue
        ptr, msg = m.group(1), m.group(2).strip()
        segs = [] if ptr == "root" else ptr.split("/")[1:]
        label = '"%s"' % _clip(msg, 60)
        for rx, keyword, show_arg in AJV_KEYWORDS:
            km = rx.match(msg)
            if km:
                label = "%s %s" % (keyword, km.group(1)) if show_arg else keyword
                if keyword == "required":
                    segs.append(km.group(1))       # name the missing field, not its parent
                break
        segs = ["*" if s.isdigit() else s.replace("~1", "/").replace("~0", "~") for s in segs]
        item = "%s (%s)" % ("/".join(segs) or "(root)", label)
        if item not in items:
            items.append(item)
    return items


def _counted(counter, order):
    return ", ".join("%s x%d" % (k, counter[k])
                     for k in sorted(counter, key=lambda k: (-counter[k], order.index(k))))


def agent_death_cause(path):
    """One line saying why an agent that has NO result died, read from its transcript: StructuredOutput
    rejections by field path + schema keyword + count, API errors, other tools' errors by name + count, or
    an explicit 'unknown'. Every signal present is named, most specific first; it is never an empty string."""
    if not path or not os.path.isfile(str(path)):
        return "no transcript"
    rejected, items, order = 0, {}, []
    tool_errs, tool_order, api = {}, [], []
    for kind, rec, item in transcript_events(path):
        if kind == "api_error":
            api.append(" ".join(str(x) for x in (rec.get("error"), rec.get("apiErrorStatus")) if x)
                       + ": " + _clip(_block_text(item.get("content")), 100))
        elif kind == "tool_error":
            tool, text = item[0], item[1]
            if tool == "StructuredOutput":
                rejected += 1
                for it in _rejection_items(text):
                    if it not in items:
                        order.append(it)
                    items[it] = items.get(it, 0) + 1
            else:
                if tool not in tool_errs:
                    tool_order.append(tool)
                tool_errs[tool] = tool_errs.get(tool, 0) + 1
    parts = []
    if rejected:
        parts.append("StructuredOutput rejected %dx -- %s" % (rejected, _counted(items, order)))
    if api:
        parts.append("API error x%d -- %s" % (len(api), api[-1]))
    if tool_errs:
        parts.append("tool errors -- %s" % _counted(tool_errs, tool_order))
    return "; ".join(parts) or "unknown -- no error tool result and no API error in the transcript"


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
        out, rejected = agent_transcript_outcome(path)
        if out is None and rejected:
            print(not_accepted_line(path, rejected))
            sys.exit(1)
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
        adir = agents_dir_for(path)
        for e in agent_entries(journal):
            print("%-19s %-18s %-9s %-26s %-12s tok=%s" % (
                e.get("agentId", "?"), (e.get("label") or "?")[:18], e.get("state", "?"),
                (e.get("model") or "?")[:26], (e.get("phaseTitle") or "")[:12], e.get("tokens", "?")))
            if not has_result(e):
                # printed for EVERY agent without a result, live or dead: a run whose session ended without
                # recording an outcome still reads 'running', and skipping it would be silence for a dead lane
                aid = e.get("agentId")
                cause = agent_death_cause(adir / ("agent-%s.jsonl" % aid) if aid else None)
                if e.get("state") != "error":
                    # no terminal state: in a killed run the lane was cut off, so its transcript's errors are
                    # incidental -- say what was RECORDED rather than let them read as the reason
                    cause = "[no terminal state recorded: agent state=%s, run status=%s] %s" % (
                        e.get("state") or "none", journal.get("status") or "?", cause)
                print("%-19s cause: %s" % (aid or "?", cause))
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
            out, rejected = agent_transcript_outcome(hits[0])
            if out is None and rejected:
                aid = os.path.basename(hits[0])[len("agent-"):-len(".jsonl")]
                label = meta.get(aid, {}).get("label")
                print(not_accepted_line("agent %s%s" % (aid, " (%s)" % label if label else ""), rejected))
                sys.exit(1)
            dump(out if out is not None else {"error": "no output found", "file": hits[0]})
            return
        # --extract: every agent -> one JSON blob (fleet-resume recipe, step 1). An agent whose every
        # StructuredOutput call was rejected gets output null and not_accepted true, never the rejected payload.
        agents, not_accepted = [], []
        for f in files:
            aid = os.path.basename(f)[len("agent-"):-len(".jsonl")]
            m = meta.get(aid, {})
            out, rejected = agent_transcript_outcome(f)
            refused = out is None and rejected > 0
            if refused:
                not_accepted.append(aid)
            agents.append({"agentId": aid, "label": m.get("label"), "phase": m.get("phaseTitle"),
                           "model": m.get("model"), "state": m.get("state"),
                           "output": out, "not_accepted": refused, "rejected_calls": rejected})
        blob = {"runId": journal.get("runId"), "status": journal.get("status"), "not_accepted": not_accepted,
                "agents": agents}
        if args.extract == "-":
            dump(blob)
        else:
            with io.open(args.extract, "w", encoding="utf-8", newline="") as f:
                json.dump(blob, f, indent=2, ensure_ascii=False)
            print("wrote %d agent records -> %s%s" % (
                len(agents), args.extract,
                "; %d NOT ACCEPTED (every StructuredOutput call rejected; output null): %s"
                % (len(not_accepted), ", ".join(not_accepted)) if not_accepted else ""))
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
    entries = agent_entries(journal)
    no_result = [e for e in entries if not has_result(e)]
    if no_result:
        print("agents without a result: %d of %d (--agents prints each one's cause)" % (len(no_result), len(entries)))
    if result is None:
        print("result: MISSING (run %s) -- per-agent outputs may still be recoverable: --agents / --extract"
              % journal.get("status", "?"))
    else:
        print("result shape (--full to dump, --key <path> for one node):")
        for line in shape_lines(result):
            print(line)


if __name__ == "__main__":
    main()
