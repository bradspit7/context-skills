#!/usr/bin/env python3
"""Committed regression tests for session-evidence.sh `_rotation_hold` / `_active_hold_dates`.

Two failed rework rounds + an adversarial fleet produced this case list. The design axis is
FAIL-SAFE: a MISSED real marker (-> a held doc gets rotated = data loss) is the dangerous
direction, so the match is permissive and only high-confidence quotes are rejected. These cases
pin BOTH directions:
  * false-POSITIVE (must NOT hold on a quoted example): single/double-backtick inline, ``` /
    ~~~ fenced, info-string inner fence, blockquote, 4-space + tab indented code blocks,
    expired markers, and a stale head date whose reason free-text names a future 'until' date.
  * false-NEGATIVE (must NOT miss a real active marker -> data loss): a reason containing '>'
    or an '-> arrow', a code-formatted date inside the comment, a marker trailing a real
    info-string-bearing close fence, multiple markers, and an active head whose reason names an
    expired date.
Reintroducing any earlier logic (single-backtick-only strip, `[^>]*-->`, head-1, naive fence
parity) fails one of these.

Run by validate.sh (tests/*.py); exits non-zero on any failure. Needs bash on PATH.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SE = os.path.normpath(os.path.join(
    HERE, "..", "skills", "update-context", "scripts", "session-evidence.sh"))

F = "2099"   # far-future year: unexpired regardless of run date
P = "2020"   # definitely expired
BT = "```"


def rotation_hold(md_text):
    with tempfile.TemporaryDirectory() as d:
        fx = os.path.join(d, "doc.md")
        with open(fx, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(md_text)
        fns = os.path.join(d, "_fns.sh")
        script = (
            "set -u\n"
            # Every function in the call chain must be extracted, INCLUDING helpers the
            # named ones delegate to. `_active_hold_dates` became a thin wrapper over
            # `_active_marker_values`; omitting the callee made the sourced shim call an
            # undefined function, which returns EMPTY rather than erroring -- so every
            # expects-a-date case failed while every expects-'' case kept passing, and the
            # suite reported a partial pass instead of an obvious break.
            "sed -n '/^_active_marker_values() {/,/^}/p; /^_active_hold_dates() {/,/^}/p;"
            " /^_rotation_hold() {/,/^}/p' \"$SE\" > \"$FNS\"\n"
            "source \"$FNS\"\n"
            # Fail LOUD if the chain is incomplete again: an undefined callee returns EMPTY,
            # which is a legitimate expected value for half these cases -- so a silent break
            # reads as a partial pass. Emit on STDOUT, not stderr: this harness compares
            # stdout and DISCARDS stderr, so a stderr message is invisible to the operator
            # (measured -- the first cut of this guard wrote to stderr and changed nothing).
            # On stdout every case fails, including the expects-'' ones, and each names why.
            "for f in _active_marker_values _active_hold_dates _rotation_hold; do\n"
            "  command -v \"$f\" >/dev/null || { echo \"EXTRACTION-INCOMPLETE:$f\"; exit 3; }\n"
            "done\n"
            "_rotation_hold \"$FX\"\n"
        )
        env = dict(os.environ, SE=SE, FNS=fns, FX=fx)
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, env=env).stdout.strip()


CASES = [
    # --- real active markers: MUST hold ---
    ("A_real_active", "<!-- rotation-hold: until %s-12-31 real -->\n" % F, "%s-12-31" % F),
    ("H_gt_in_reason",
     "<!-- rotation-hold: until %s-01-01 wait for >5 rows -->\n" % F, "%s-01-01" % F),
    ("I_arrow_in_reason",
     "<!-- rotation-hold: until %s-02-02 estate-sync -> receive lands -->\n" % F, "%s-02-02" % F),
    ("J_backticked_date",
     "<!-- rotation-hold: `until %s-03-03` code-formatted date -->\n" % F, "%s-03-03" % F),
    ("L_marker_after_infostring_close",
     "%stext\nexample\n%spython\nmore\n%s\n<!-- rotation-hold: until %s-04-04 real -->\n"
     % (BT, BT, BT, F), "%s-04-04" % F),
    ("P_active_head_expired_reason_date",
     "<!-- rotation-hold: until %s-05-05 keep frozen until %s-01-01 per plan -->\n" % (F, P),
     "%s-05-05" % F),
    ("multiple_active_first_wins",
     "<!-- rotation-hold: until %s-08-08 a -->\n<!-- rotation-hold: until %s-09-09 b -->\n"
     % (F, F), "%s-08-08" % F),
    ("expired_then_active",
     "<!-- rotation-hold: until %s-01-01 old -->\n\n<!-- rotation-hold: until %s-07-07 new -->\n"
     % (P, F), "%s-07-07" % F),
    ("Q_unclosed_fence_above_marker_holds",
     "## Commands\n%sbash\nbash bin/refresh-mirror.sh\n\n## Docket\n"
     "<!-- rotation-hold: until %s-06-06 keep -->\n" % (BT, F), "%s-06-06" % F),
    ("R_backtick_infostring_is_not_a_fence",
     # CommonMark: a backtick fence's info string may not contain a backtick, so ```lang`bad is
     # NOT a valid opener -> the marker below it is LIVE, not fenced. Must hold (data-loss dir).
     "%slang`bad\n<!-- rotation-hold: until %s-10-10 real -->\n%s\n" % (BT, F, BT), "%s-10-10" % F),
    # --- quoted / expired: must NOT hold ---
    ("B_inline_single_quoted",
     "see `<!-- rotation-hold: until %s-01-01 x -->` in prose\n" % F, ""),
    ("E_inline_double_quoted",
     "see ``<!-- rotation-hold: until %s-02-02 x -->`` in prose\n" % F, ""),
    ("fenced_backtick", "%s\n<!-- rotation-hold: until %s-03-03 x -->\n%s\n" % (BT, F, BT), ""),
    ("fenced_tilde", "~~~\n<!-- rotation-hold: until %s-04-04 x -->\n~~~\n" % F, ""),
    ("S_valid_backtick_infostring_still_fences",
     # a backtick fence WITH a backtick-free info string is a real fence -> still suppress
     # (accepts-good boundary: the fix must reject ONLY a backtick-bearing info string)
     "%spython\n<!-- rotation-hold: until %s-11-11 x -->\n%s\n" % (BT, F, BT), ""),
    ("T_tilde_infostring_with_tilde_still_fences",
     # CommonMark permits tildes/backticks in a TILDE info string, so ~~~lang~bad IS a valid
     # fence -> suppress (the fix is scoped to backtick fences only, per the reviewer)
     "~~~lang~bad\n<!-- rotation-hold: until %s-12-12 x -->\n~~~\n" % F, ""),
    ("K_infostring_inner_fence",
     "%s\ninner example:\n%sbash\n<!-- rotation-hold: until %s-05-05 x -->\n%s\n"
     % (BT, BT, F, BT), ""),
    ("blockquote", "> <!-- rotation-hold: until %s-06-06 x -->\n" % F, ""),
    ("M_four_space_indent",
     "Example:\n\n    <!-- rotation-hold: until %s-07-07 demo -->\n\nend.\n" % F, ""),
    ("N_tab_indent",
     "Example:\n\n\t<!-- rotation-hold: until %s-08-08 demo -->\n\nend.\n" % F, ""),
    ("malformed_unclosed", "<!-- rotation-hold: until %s-09-09 no closing arrow\n" % F, ""),
    ("expired_only", "<!-- rotation-hold: until %s-01-01 old -->\n" % P, ""),
    ("O_expired_head_future_reason_date",
     "<!-- rotation-hold: until %s-03-01 keep archive frozen; hold until %s-01-15 -->\n" % (P, F),
     ""),
]


def main():
    fails = 0
    for label, md, expected in CASES:
        got = rotation_hold(md)
        if got == expected:
            print("PASS %s (=%r)" % (label, got))
        else:
            print("FAIL %s: expected %r got %r" % (label, expected, got))
            fails += 1
    print("=== %d/%d passed ===" % (len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
