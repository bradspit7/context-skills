#!/usr/bin/env python3
"""UserPromptSubmit hook: once per session, after substantial work, inject a
non-blocking nudge to run the reflect-upgrades skill.

Deterministic proxy for "substantial work": counts Edit/Write/MultiEdit/
NotebookEdit tool uses in the session transcript, plus flags a memory-file
write or a `git commit`. Fires at most once per session (marker file). The
judgment ("did we actually learn something tool-worthy") is left to the
reflect-upgrades skill the nudge points to - a hook cannot make that call.

ASCII-only (project hook rule). Fails open: any error -> exit 0, no output.

Env tunables:
  UPGRADE_NUDGE_EDIT_THRESHOLD   edits needed to fire (default 3)
  UPGRADE_NUDGE_DISABLE=1        silence the hook entirely

Side effect: appends one tab-separated line per fire (ISO time, project, signal,
session) to ~/.claude/run/upgrade-nudge/fires.log for later Layer-2 tuning.
"""
import json
import os
import sys

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def _threshold():
    try:
        return int(os.environ.get("UPGRADE_NUDGE_EDIT_THRESHOLD", "3"))
    except ValueError:
        return 3


def _tool_uses(ev):
    if not isinstance(ev, dict):
        return
    msg = ev.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                yield block


def main():
    if os.environ.get("UPGRADE_NUDGE_DISABLE") == "1":
        return
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        return
    session_id = str(data.get("session_id") or "").strip()
    transcript = str(data.get("transcript_path") or "").strip()
    if not session_id or not transcript or not os.path.isfile(transcript):
        return

    state_dir = os.path.join(os.path.expanduser("~"), ".claude", "run", "upgrade-nudge")
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    marker = os.path.join(state_dir, safe_id)
    if os.path.exists(marker):
        return  # already nudged this session

    edits = 0
    memory_write = False
    commit = False
    try:
        with open(transcript, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                for tu in _tool_uses(ev):
                    name = tu.get("name", "")
                    inp = tu.get("input") or {}
                    if name in EDIT_TOOLS:
                        edits += 1
                        fp = str(inp.get("file_path", "")).replace("\\", "/")
                        if "/memory/" in fp and fp.endswith(".md"):
                            memory_write = True
                    elif name in ("Bash", "PowerShell"):
                        # both tools carry the command string under the same "command" key;
                        # PowerShell is the primary shell on Windows machines, so matching
                        # Bash alone made commits invisible there (fleet finding, 2026-07-02)
                        if "git commit" in str(inp.get("command", "")):
                            commit = True
    except OSError:
        return

    if not (edits >= _threshold() or memory_write or commit):
        return

    parts = []
    if edits:
        parts.append("%d file edit%s" % (edits, "" if edits == 1 else "s"))
    if commit:
        parts.append("a commit")
    if memory_write:
        parts.append("a memory write")
    signal = ", ".join(parts) if parts else "substantial work"

    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write("nudged\n")
    except OSError:
        pass  # if we cannot write the marker, still nudge this once

    # Log each fire (fail-open) so Layer-2 tuning can be data-driven later:
    # project + signal + session. Markers alone record only THAT a session fired.
    try:
        from datetime import datetime
        proj = str(data.get("cwd") or os.path.dirname(transcript) or "?")
        with open(os.path.join(state_dir, "fires.log"), "a", encoding="utf-8") as lf:
            lf.write("%s\t%s\t%s\t%s\n" % (
                datetime.now().isoformat(timespec="seconds"), proj, signal, session_id))
    except Exception:
        pass

    msg = (
        "[upgrade-reflection] Substantial work this session (%s). Before moving on, "
        "consider the reflect-upgrades skill - scan whether anything here warrants a "
        "new or upgraded tool, hook, subagent, slash command, or rule, and file the "
        "real candidates. Routing: a generalizable kernel - anything touching a lifecycle "
        "or process skill, global CLAUDE.md, the catalog, or a global hook - goes to the "
        "central upgrades repo even from inside this project (split it from any project-local "
        "instance; do not let the local surface trap it); project-specific ones to this "
        "project's docket. Nothing tool-worthy is a fine answer - and record whichever "
        "way it lands (the session id below makes the fires<->responses join exact; "
        "a considered zero is invisible otherwise): "
        "python ~/.claude/upgrade-ledger.py record --layer nudge "
        "--status <filed-central|filed-project|zero|...> "
        "--candidate <ref or -> --reason \"...\" --session %s" % (signal, session_id)
    )
    try:
        sys.stdout.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": msg,
            }
        }))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
