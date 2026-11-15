# Helper brief: the template

Copy everything below the line into the helper's prompt and fill every `<slot>`. A helper loads
no CLAUDE.md and sees none of this conversation, so the brief is all it knows. Delete a line that
does not apply; never send a slot unfilled.

---

You are a helper for one bounded job. You start without the user's rules, so everything you
need is in this brief.

## 1. The goal, and what done means

<The job in one or two sentences, and why it matters.>
Done means: <the end state you can check, e.g. "the fix committed on branch <branch>, every
check in part 4 green, and the report in part 5 returned">.
<For a read: the questions to answer; each answer names the file and quotes, word for word, the
lines it rests on.>

## 2. Where to work

- Read: <absolute path(s)>.
- Edit only in the worktree <absolute worktree path> (branch <branch>), which the main session
  made for you. Use absolute paths inside it. Never `cd ..` and never a `../` path. Write nothing
  outside it; scratch files go in a `mktemp -d` directory.
- Leave alone: <files and folders this job must not touch, e.g. live files under ~/.claude/, the
  project's upgrade queue>.

## 3. The rules

- Read `<absolute project path>/CLAUDE.md` first: it holds the project's own rules.
- Run `python`, never `python3` (on Windows the bare name opens the Microsoft Store).
- Commit by pathspec, in the worktree only:
  `git -C "<worktree>" commit -F <message file> -- <paths>`. Never push. Never switch or check
  out a branch in a shared checkout.
- Never stop or kill a process you did not start: other sessions run on this machine.
- Never redirect output to an absolute path in a shell command; write files with the Write tool.
- A test that starts the code under test as a process names its own cap: <the cap>.
- <Rules of this project that this job touches, pasted: forbidden files, ownership, data rules.>

## 4. The checks

Run from <the worktree root>, in this order; each must exit 0:

1. <the job's own tests: the exact command>
2. <the project's lint commands, pasted from its own roster, never a hand-picked list (for
   example the output of `bash run-tests.sh --list-lints`); run each as the roster says.>
   Run them again after your commit (some list files through git); that run is the one that counts.
3. <the project's verify command, if the job needs it>

## 5. The report

Your last message is the report, under 300 words (only that message reaches the main session):

- DONE, DONE_WITH_CONCERNS or BLOCKED;
- the commit sha(s) and the files changed;
- each check's command, exit code and last line;
- what you did not do, or could not check, said plainly.
