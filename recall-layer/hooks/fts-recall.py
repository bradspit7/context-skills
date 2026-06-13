#!/usr/bin/env python3
"""UserPromptSubmit hook: always-on KEYWORD auto-recall (FTS, no Ollama).

The keyword counterpart to `semantic-recall.sh`. On each substantive prompt it
surfaces a few memory/catalog notes that share the prompt's *distinctive*
terminology, injected as additionalContext so relevant past notes appear without
running `/recall`. Pure stdlib Python; reads the FTS `search.db` only. Use this
when you run the FTS half but not Ollama (the semantic hook needs both).

WHY a custom relevance model (not just "FTS top hit"): firing on every prompt,
naive keyword match is noisy - generic words ("function", "context") and rare-
but-incidental English words ("stricter") drag in unrelated notes. Three gates
keep it quiet unless the prompt is genuinely specific:
  1. STOPLIST - drop function/conversational/generic-tech words.
  2. DISTINCTIVE + PROXIMITY - a term counts only if it appears in <= DF_MAX docs,
     and >=2 such terms must CO-OCCUR within PROXIMITY_CHARS in the note (not just
     both exist somewhere in it).
  3. RARE ANCHOR - at least one co-occurring term must be genuinely rare
     (<= RARE_ANCHOR docs). This separates topical matches (which have a specific
     anchor) from all-generic co-occurrences. This gate is what kills the
     "rare English word" false positives.

Fails silent on any error or weak match (never blocks/errors a prompt).

Install: wire into ~/.claude/settings.json under UserPromptSubmit, e.g.
  {"hooks": {"UserPromptSubmit": [ { "hooks": [ {
     "type": "command",
     "command": "python ~/.claude/hooks/fts-recall.py",
     "shell": "bash" } ] } ] }}
(use a real python interpreter path on Windows, not the MS Store `python3` stub).

Env tunables (all optional):
  FTS_RECALL_DB           override the index path (default ~/.claude/memory-sync/search.db)
  FTS_RECALL_DF_MAX       distinctive-term ceiling (default 90)
  FTS_RECALL_RARE_ANCHOR  rare-anchor ceiling (default 20)
  FTS_RECALL_MAX_RESULTS  max notes injected (default 3)
  FTS_RECALL_LOG=1        append an audit line per fire to ~/.claude/.fts-recall.log
                          (off by default; logs the prompt snippet locally when on)
"""
import datetime
import json
import os
import re
import sqlite3
import sys
from pathlib import Path


def _int_env(name, default):
    try:
        return int(os.environ[name])
    except (KeyError, ValueError):
        return default


DB = Path(os.environ.get(
    "FTS_RECALL_DB", str(Path.home() / ".claude" / "memory-sync" / "search.db")))
DF_MAX = _int_env("FTS_RECALL_DF_MAX", 90)
RARE_ANCHOR = _int_env("FTS_RECALL_RARE_ANCHOR", 20)
MAX_INJECT = _int_env("FTS_RECALL_MAX_RESULTS", 3)
LOG_ENABLED = os.environ.get("FTS_RECALL_LOG", "0") == "1"
LOG_FILE = Path.home() / ".claude" / ".fts-recall.log"
MAX_LOG_BYTES = 262144

MIN_PROMPT_CHARS = 25
MAX_TERMS = 14
MIN_DISTINCTIVE = 2
PROXIMITY_CHARS = 160
TOP_CANDIDATES = 15
EXCERPT_CHARS = 170

# Function words + broad generic English/tech (adjectives, adverbs, comparatives,
# filler). These are often RARE in a technical corpus yet carry no topical signal,
# so rarity alone wrongly flags them - the stoplist is the real precision lever.
STOP = set("""
a about above after again against all am an and any are arent as at be because been
before being below between both but by can cant could couldnt did didnt do does doesnt
doing dont down during each few for from further had hadnt has hasnt have havent having
he her here hers herself him himself his how i if in into is isnt it its itself just
like me more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should shouldnt so some such than that thats the their
theirs them themselves then there these they this those through to too under until up
very was wasnt we were werent what when where which while who whom why will with wont
would wouldnt you your yours yourself yourselves get got make made need want lets let
know think feel really actually thing things way ways one two see look go going done
also able add added adding new now using use used via per etc onto
thanks thank sense please sorry hello hey yeah yep nope okay sure awesome cool hmm wow
oops maybe perhaps probably definitely basically literally honestly anyway anyways
something anything everything nothing someone anyone everyone somewhere anywhere
everywhere gonna wanna gotta nah yes else well much many lot lots bit kind sort stuff
better best around along ahead back move moves moving makes making help quick simple
easy hard fast slow good bad nice great okay still even right next last first
stricter strict strictly looser loose tighter tight tightly point points pointing
context contexts pulling pull pulled pulls pushing push pushed eating eat eats ate
usage usages manual manually start starts starting started stop stops stopping stopped
lol def imo tbh fyi kinda sorta bigger smaller larger little big small large
higher lower deeper wider longer shorter older newer harder easier heavier lighter
cleaner messier faster slower stronger weaker fuller fewer fewest least
actual whole full empty real true false certain unsure clear unclear simple complex
heavy light soft solid part parts piece pieces item items case cases type types
example examples reason reasons idea ideas problem problems issue issues question
questions answer answers result results option options change changes changed changing
mean means meant matter matters fine pretty rather quite somewhat fairly mostly
mainly currently merely only always never often sometimes usually rarely already yet
soon later before recently lately again though although however therefore thus hence
instead otherwise possibly likely unlikely wanted wanting recommend recommendation
recommendations recommended suggest suggested suggestion suggestions function functions
string strings variable variables value values method methods array arrays loop loops
""".split())


def salient_terms(prompt):
    out, seen = [], set()
    for w in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{3,}", prompt.lower()):
        if w in STOP or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= MAX_TERMS:
            break
    return out


def excerpt(body, terms):
    low = body.lower()
    pos = -1
    for t in terms:
        i = low.find(t)
        if i != -1 and (pos == -1 or i < pos):
            pos = i
    if pos < 0:
        pos = 0
    start = max(0, pos - 30)
    return " ".join(body[start:start + EXCERPT_CHARS].split())


def best_topical_window(text_low, terms, df_of):
    """Largest set of distinct distinctive terms co-occurring within one
    PROXIMITY_CHARS window AND including a rare anchor (df <= RARE_ANCHOR)."""
    hits = []
    for t in terms:
        start, cnt = 0, 0
        while cnt < 8:
            i = text_low.find(t, start)
            if i < 0:
                break
            hits.append((i, t))
            start = i + len(t)
            cnt += 1
    if len(hits) < 2:
        return 0
    hits.sort()
    best, lo = 0, 0
    for hi in range(len(hits)):
        while hits[hi][0] - hits[lo][0] > PROXIMITY_CHARS:
            lo += 1
        window = set(h[1] for h in hits[lo:hi + 1])
        if len(window) >= 2 and any(df_of[t] <= RARE_ANCHOR for t in window):
            best = max(best, len(window))
    return best


def log_fire(prompt, distinctive, df_of, picks):
    if not LOG_ENABLED:
        return
    try:
        anchors = ",".join("%s(%d)" % (t, df_of[t]) for t in distinctive
                           if df_of[t] <= RARE_ANCHOR) or "-"
        terms = ",".join("%s(%d)" % (t, df_of[t]) for t in distinctive)
        names = "; ".join(os.path.basename(p) for _, p, _ in picks)
        snip = " ".join(prompt.split())[:120]
        line = '%s | anchor=%s | terms=%s | "%s" | %s\n' % (
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), anchors, terms, snip, names)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_LOG_BYTES:
            old = LOG_FILE.read_text(encoding="utf-8", errors="replace")
            LOG_FILE.write_text(old[-MAX_LOG_BYTES // 2:], encoding="utf-8")
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass


def main():
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except Exception:
        return
    prompt = (data.get("prompt") or "").strip()
    if len(prompt) < MIN_PROMPT_CHARS or prompt.startswith("/") or not DB.exists():
        return
    terms = salient_terms(prompt)
    if not terms:
        return
    try:
        conn = sqlite3.connect(str(DB))
        distinctive, df_of = [], {}
        for t in terms:
            d = conn.execute("SELECT count(*) FROM docs WHERE docs MATCH ?",
                             ('"%s"' % t,)).fetchone()[0]
            if 1 <= d <= DF_MAX:
                distinctive.append(t)
                df_of[t] = d
        if len(distinctive) < MIN_DISTINCTIVE or not any(
                df_of[t] <= RARE_ANCHOR for t in distinctive):
            conn.close()
            return
        match = " OR ".join('"%s"' % t for t in distinctive)
        rows = conn.execute(
            "SELECT path, body FROM docs WHERE docs MATCH ? ORDER BY bm25(docs) LIMIT ?",
            (match, TOP_CANDIDATES),
        ).fetchall()
        conn.close()
    except Exception:
        return
    scored = []
    for path, body in rows:
        prox = best_topical_window(body.lower(), distinctive, df_of)
        if prox >= 2:
            scored.append((prox, path, body))
    if not scored:
        return
    scored.sort(key=lambda r: -r[0])
    picks = scored[:MAX_INJECT]
    log_fire(prompt, distinctive, df_of, picks)
    lines = ["- %s\n    %s" % (path, excerpt(body, distinctive))
             for _, path, body in picks]
    ctx = (
        "[memory auto-recall | keyword] Possibly-relevant past notes (they share "
        "distinctive terms with your prompt). POINTERS, not facts - Read the file "
        "before relying on it; the index can be stale:\n%s" % "\n".join(lines)
    )
    try:
        sys.stdout.write(json.dumps(
            {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                    "additionalContext": ctx}}))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
