#!/usr/bin/env python
"""plan-blocks.py -- place the fenced code blocks of a written plan into files, byte for byte.

A plan that holds the complete code of every step is built by PLACING its blocks, never by
retyping them: retyping costs output and lets the built files drift from the plan. A block is
named by the LINE NUMBER OF ITS OPENING FENCE in the plan (index lists them).

  index   <plan>
      list every fence: its line, language tag, number of lines and the block's first line
  create  <plan> <fence> <target>
      the block becomes a new file holding the plan's own bytes; refuses a target that exists
  append  <plan> <fence> <target> [--blank N]
      the block goes on the end of the target (after N blank lines, default 0)
  replace <plan> <old fence> <new fence> <target>
      the old block must be in the target exactly once; the new block takes its place
  delete  <plan> <fence> <target>
      the block must be in the target exactly once; it is removed
  above   <plan> <fence> <target> "<exact line>" [--blank N]
      the block goes above the one line of the target that equals <exact line> (followed by
      N blank lines, default 0); that line must be there exactly once
  check   <plan> <built file or folder>... [--lang <tag>[,<tag>...]]
      after the build: each block is found verbatim in a built file, or listed for a person to
      explain; prints the counts (blocks, found, unfound). A file that holds a block as the
      whole body of a fence of its own is a copy of the plan and is never credited with it.
      --lang checks only the blocks whose fence carries one of those language tags (python,
      not the shell commands and expected output), and the counts then say how many blocks
      were skipped by tag; a list that matches no block is refused, never a clean result.

A block ends at a fence of the same character, at least as long, standing at most three spaces
deeper than its opening fence: a fence four spaces deeper, or behind a tab, is text of the block.
A target that exists keeps its line endings: the block is converted to them. A block is matched
as whole lines. Every file is read and written as bytes. A refusal prints one line and changes
nothing.

exit status: 0 done (check: every block found); 1 refused, or check found a block in no built
file; 2 a command line that cannot be read, or a check that could not run
"""
import os
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

NAME = "plan-blocks"
LF = b"\n"
CRLF = b"\r\n"
OPEN_RE = re.compile(rb"^([ \t]*)(`{3,}|~{3,})(.*)$")
SKIP_DIRS = (".git", "node_modules", "__pycache__", ".venv")
MAX_BUILT_BYTES = 8 * 1024 * 1024


class UsageError(Exception):
    """The command line cannot be read: exit 2, with the usage."""


class Refusal(Exception):
    """Something is wrong with the plan or the target: one line, and nothing is changed."""

    def __init__(self, message, code=1):
        Exception.__init__(self, message)
        self.code = code


# --------------------------------------------------------------------------- bytes in, bytes out

def read_file(path, what):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError as exc:
        raise Refusal("cannot read %s %s (%s)" % (what, path, exc.strerror or exc))


def write_file(path, data):
    with open(path, "wb") as handle:
        handle.write(data)


def show(raw):
    return raw.decode("utf-8", "replace")


def split_lines(data):
    """[(text, ending)] for every line; ending is CRLF, LF, or b"" for a last line that has none."""
    out, pos = [], 0
    while pos < len(data):
        cut = data.find(LF, pos)
        if cut < 0:
            out.append((data[pos:], b""))
            break
        if cut > pos and data[cut - 1:cut] == b"\r":
            out.append((data[pos:cut - 1], CRLF))
        else:
            out.append((data[pos:cut], LF))
        pos = cut + 1
    return out


# --------------------------------------------------------------------------- the plan's blocks

def strip_indent(text, indent):
    """A fence indented under a list item: its lines lose that indentation, as markdown reads them."""
    n = 0
    while n < len(indent) and text[n:n + 1] == indent[n:n + 1]:
        n += 1
    return text[n:]


def closes(text, indent, fence):
    """Whether the line `text` closes the block that `fence` opened behind `indent`: at most three
    spaces deeper than the opening fence, then the same character at least as many times, then
    nothing but spaces and tabs. A fence four spaces deeper, or behind a tab, is text of the block
    (a fence quoted in a string of the code), and taking it for the end would cut the block short."""
    rest = strip_indent(text, indent)
    run = rest.lstrip(b" ")
    if len(rest) - len(run) > 3:
        return False
    run = run.rstrip(b" \t")
    return len(run) >= len(fence) and run == fence[:1] * len(run)


def parse_blocks(data):
    """Every fenced block: {"line": the opening fence's line (1-based), "info": its language tag,
    "body": [(text, ending)], "closed": whether a closing fence was found}. A fence closes on a line
    of the same character, at least as long, so a longer fence can hold shorter ones as text."""
    rows = split_lines(data)
    blocks, i = [], 0
    while i < len(rows):
        m = OPEN_RE.match(rows[i][0])
        if not m or (m.group(2)[:1] == b"`" and b"`" in m.group(3)):
            i += 1
            continue
        indent, fence = m.group(1), m.group(2)
        body, j, closed = [], i + 1, False
        while j < len(rows):
            if closes(rows[j][0], indent, fence):
                closed = True
                break
            body.append((strip_indent(rows[j][0], indent), rows[j][1]))
            j += 1
        blocks.append({"line": i + 1, "info": m.group(3).strip(b" \t"), "body": body, "closed": closed})
        i = j + 1
    return blocks


def load(plan):
    return parse_blocks(read_file(plan, "the plan"))


def block_at(blocks, plan, number):
    for block in blocks:
        if block["line"] == number:
            if not block["closed"]:
                raise Refusal("the fence at line %d of %s is never closed" % (number, plan))
            if not block["body"]:
                raise Refusal("the block at line %d of %s is empty" % (number, plan))
            return block
    lines = [b["line"] for b in blocks]
    near = [str(n) for n in (max([x for x in lines if x < number], default=None),
                             min([x for x in lines if x > number], default=None)) if n]
    raise Refusal("no fence opens at line %d of %s (%s)" % (
        number, plan, "the nearest open at line " + " and ".join(near) if near else "it has no fence"))


def own_bytes(block):
    return b"".join(text + ending for text, ending in block["body"])


def as_lines(block, eol):
    return b"".join(text + eol for text, _ in block["body"])


def eol_of(data, block):
    """The target's line ending; a target with no line ending at all takes the block's own."""
    crlf = data.count(CRLF)
    lf = data.count(LF) - crlf
    if crlf or lf:
        return CRLF if crlf > lf else LF
    return block["body"][0][1] or LF


def find_block(data, needle, eol):
    """[(offset, length)] of every place `needle` stands in `data` as WHOLE LINES. The last one may
    lack its line ending when it is the very end of a file that has no final line ending."""
    hits, start = [], 0
    while True:
        at = data.find(needle, start)
        if at < 0:
            break
        if at == 0 or data[at - 1:at] == LF:
            hits.append((at, len(needle)))
        start = at + 1
    bare = needle[:-len(eol)]
    if bare and data.endswith(bare) and not data.endswith(needle):
        at = len(data) - len(bare)
        if at == 0 or data[at - 1:at] == LF:
            hits.append((at, len(bare)))
    return hits


def in_built(data, block, eol):
    """Whether `block` stands in a built file's bytes as whole lines: as the plan's own bytes first
    (create writes them as they are, so a block whose lines end differently is found), and only
    then with every line in the file's line ending `eol`."""
    last = block["body"][-1][1]
    if last and find_block(data, own_bytes(block), last):
        return True
    return bool(find_block(data, as_lines(block, eol), eol))


def tag_of(block):
    """The fence's language tag: the first word after the fence characters, "" when it has none."""
    return (show(block["info"]).split() or [""])[0]


def put_once(target, data, block, eol, new):
    """Write `target` with the ONE place `block` stands in `data` replaced by `new`."""
    hits = find_block(data, as_lines(block, eol), eol)
    if not hits:
        raise Refusal("the block at plan line %d is not in %s: it must be there exactly once, as whole lines"
                      % (block["line"], target))
    if len(hits) > 1:
        raise Refusal("the block at plan line %d is in %s %d times: it must be there exactly once"
                      % (block["line"], target, len(hits)))
    at, size = hits[0]
    write_file(target, data[:at] + new + data[at + size:])


# --------------------------------------------------------------------------- the command line

def positional(args, count, form):
    if len(args) != count:
        raise UsageError("expected: %s" % form)
    return args


def with_blank(args, count, form):
    """(positionals, N) for a command that takes `count` positionals and then an optional --blank N."""
    if len(args) == count + 2 and args[count] == "--blank" and args[count + 1].isascii() \
            and args[count + 1].isdigit():
        return args[:count], int(args[count + 1])
    return positional(args, count, form), 0


def fence_number(word):
    if not (word.isascii() and word.isdigit()):
        raise UsageError("a block is named by the line number of its opening fence, got %r" % word)
    return int(word)


def cmd_index(args):
    (plan,) = positional(args, 1, "index <plan>")
    blocks = load(plan)
    for block in blocks:
        first = show(block["body"][0][0]) if block["body"] else ""
        print("%5d  %-12s %4d lines  %s%s" % (block["line"], show(block["info"]) or "-", len(block["body"]),
                                              first[:90], "" if block["closed"] else "  [NEVER CLOSED]"))
    print("%d fences in %s" % (len(blocks), plan))
    return 0


def cmd_create(args):
    plan, fence, target = positional(args, 3, "create <plan> <fence> <target>")
    block = block_at(load(plan), plan, fence_number(fence))
    try:
        os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
        with open(target, "xb") as handle:
            handle.write(own_bytes(block))
    except FileExistsError:
        raise Refusal("%s exists, and create never writes over a file (use replace or append)" % target)
    print("create %s <- plan line %d (%d lines)" % (target, block["line"], len(block["body"])))
    return 0


def cmd_append(args):
    (plan, fence, target), blank = with_blank(args, 3, "append <plan> <fence> <target> [--blank N]")
    block = block_at(load(plan), plan, fence_number(fence))
    data = read_file(target, "the target")
    if data and not data.endswith(LF):
        raise Refusal("%s has no line ending after its last line, so the block would join that line" % target)
    eol = eol_of(data, block)
    write_file(target, data + eol * blank + as_lines(block, eol))
    print("append %s <- plan line %d (%d lines)" % (target, block["line"], len(block["body"])))
    return 0


def cmd_replace(args):
    plan, old_fence, new_fence, target = positional(args, 4, "replace <plan> <old fence> <new fence> <target>")
    blocks = load(plan)
    old = block_at(blocks, plan, fence_number(old_fence))
    new = block_at(blocks, plan, fence_number(new_fence))
    data = read_file(target, "the target")
    eol = eol_of(data, old)
    put_once(target, data, old, eol, as_lines(new, eol))
    print("replace in %s: plan line %d -> plan line %d" % (target, old["line"], new["line"]))
    return 0


def cmd_delete(args):
    plan, fence, target = positional(args, 3, "delete <plan> <fence> <target>")
    block = block_at(load(plan), plan, fence_number(fence))
    data = read_file(target, "the target")
    put_once(target, data, block, eol_of(data, block), b"")
    print("delete in %s: plan line %d (%d lines)" % (target, block["line"], len(block["body"])))
    return 0


def cmd_above(args):
    (plan, fence, target, line), blank = with_blank(
        args, 4, 'above <plan> <fence> <target> "<exact line>" [--blank N]')
    block = block_at(load(plan), plan, fence_number(fence))
    data = read_file(target, "the target")
    want, hits, pos = line.encode("utf-8"), [], 0
    for text, ending in split_lines(data):
        if text == want:
            hits.append(pos)
        pos += len(text) + len(ending)
    if len(hits) != 1:
        raise Refusal("the line to put the block above is in %s %d times: it must be there exactly once"
                      % (target, len(hits)))
    eol = eol_of(data, block)
    write_file(target, data[:hits[0]] + as_lines(block, eol) + eol * blank + data[hits[0]:])
    print("above in %s <- plan line %d (%d lines)" % (target, block["line"], len(block["body"])))
    return 0


def built_files(paths):
    out = []
    for path in paths:
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                out.extend(os.path.join(root, name) for name in sorted(files))
        elif os.path.isfile(path):
            out.append(path)
        else:
            raise Refusal("%s is not a file or a folder, so the check did not run" % path, 2)
    return out


def lang_option(args):
    """(the other arguments, the tags of --lang or None). `--lang <tag>[,<tag>...]` stands anywhere, once."""
    if "--lang" not in args:
        return args, None
    at = args.index("--lang")
    tags = [tag for tag in "".join(args[at + 1:at + 2]).split(",") if tag]
    rest = args[:at] + args[at + 2:]
    if not tags or "--lang" in rest:
        raise UsageError("--lang takes one list of language tags, as in --lang python,bash")
    return rest, tags


def cmd_check(args):
    args, tags = lang_option(args)
    if len(args) < 2:
        raise UsageError("expected: check <plan> <built file or folder>... [--lang <tag>[,<tag>...]]")
    plan = args[0]
    every = load(plan)
    blocks = [b for b in every if b["body"]]
    if not blocks:
        raise Refusal("%s has no fenced block with text in it, so there is nothing to check" % plan, 2)
    empty, skipped = len(every) - len(blocks), 0
    if tags is not None:
        kept = [b for b in blocks if tag_of(b) in tags]
        if not kept:
            raise Refusal("no block of %s has the language tag %s, so nothing was checked (its fences are tagged: %s)"
                          % (plan, " or ".join(tags), ", ".join(sorted({tag_of(b) or "-" for b in blocks}))), 2)
        skipped, blocks = len(blocks) - len(kept), kept
    found, quoted, read, unread = {}, {}, 0, []
    for path in built_files(args[1:]):
        try:
            if os.path.getsize(path) > MAX_BUILT_BYTES:
                unread.append(path)
                continue
            data = read_file(path, "the built file")
        except (OSError, Refusal):
            unread.append(path)
            continue
        read += 1
        fenced = set()
        if b"```" in data or b"~~~" in data:
            fenced = {as_lines(b, LF) for b in parse_blocks(data)}
        eol = CRLF if data.count(CRLF) > data.count(LF) - data.count(CRLF) else LF
        for block in blocks:
            if block["line"] in found:
                continue
            if as_lines(block, LF) in fenced:
                quoted.setdefault(block["line"], path)
            elif in_built(data, block, eol):
                found[block["line"]] = path
    if not read:
        raise Refusal("no built file could be read, so the check did not run", 2)
    for block in blocks:
        head = "line %5d  %-12s %4d lines" % (block["line"], show(block["info"]) or "-", len(block["body"]))
        if block["line"] in found:
            print("found    %s  in %s" % (head, found[block["line"]]))
            continue
        print("UNFOUND  %s  | %s" % (head, show(block["body"][0][0])[:70]))
        if block["line"] in quoted:
            print("         only inside a fence of %s, which reads as a copy of the plan" % quoted[block["line"]])
    if empty:
        print("%d empty block(s) not counted" % empty)
    if unread:
        print("%d file(s) not read (unreadable, or over %d bytes): %s"
              % (len(unread), MAX_BUILT_BYTES, ", ".join(unread[:5])))
    unfound = len(blocks) - len(found)
    by_tag = "" if tags is None else ", skipped by tag %d" % skipped
    print("blocks %d, found %d, unfound %d%s (%d built file(s) read)"
          % (len(blocks), len(found), unfound, by_tag, read))
    return 1 if unfound else 0


COMMANDS = {"index": cmd_index, "create": cmd_create, "append": cmd_append, "replace": cmd_replace,
            "delete": cmd_delete, "above": cmd_above, "check": cmd_check}


def main(argv):
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    try:
        if not argv:
            raise UsageError("no command given")
        handler = COMMANDS.get(argv[0])
        if handler is None:
            raise UsageError("unknown command %r" % argv[0])
        return handler(argv[1:])
    except UsageError as exc:
        sys.stderr.write("%s: %s\n\n%s\n" % (NAME, exc, __doc__.strip()))
        return 2
    except Refusal as exc:
        sys.stderr.write("%s: refused: %s\n" % (NAME, exc))
        return exc.code
    except OSError as exc:
        sys.stderr.write("%s: failed: %s\n" % (NAME, exc))
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
