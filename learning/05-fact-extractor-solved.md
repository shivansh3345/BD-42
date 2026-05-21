# BD-42 — Walkthrough 05: How the Fact Extractor Was Fixed

The solution companion to `04-fact-extractor-exercise.md`. That doc posed five
problems in `services/fact_extractor.py`. This doc records how they were
actually solved — the bugs hit along the way, the keystone design decision,
and the result.

---

## The starting point

The original extractor was a **hybrid**: a list of regex patterns
(`_extract_with_patterns`) tried first, an LLM call (`_extract_with_llm`) as
fallback. It returned `dict | None` — one fact, or nothing.

Exercise 04 named five problems: (1) the return type can't hold multiple
facts, (2) regex extracts only one match per message, (3) a regex hit
silently blocks the LLM, (4) missing interest-patterns + no quality gate,
(5) category and importance are mechanical/constant.

---

## The keystone decision: go LLM-only

Rather than patch the regex path, the decision was to **delete it entirely**
and make the LLM the sole extractor. `extract_fact` became LLM-only.

This one move collapsed four of the five problems at once:

- **Problem 2 (multi-match)** — gone. The LLM reads the whole message and
  returns a JSON *array* of facts natively.
- **Problem 4a (missing patterns)** — gone. The LLM understands meaning;
  "physics is so fascinating" needs no pattern.
- **Problem 5 (category & importance)** — gone. The LLM judges category from
  a real taxonomy and grades importance 0–1, because it actually models
  meaning. A regex never could.
- **Problem 4b (quality gate)** — mostly gone. The LLM prompt asks for a
  "concise restatement, third person," so it doesn't emit `"it"`-tier junk.

That left Problem 1 (return type) as explicit work, and Problem 3 (the
cascade) transformed — see below.

**Lesson:** sometimes the best fix for a flawed component is to delete it,
not repair it. The regex was the wrong tool for *extraction*. Recognizing
that — instead of trying to make it robust — was the unlock.

---

## The bugs in the Problem 1 attempt

Changing the return type to a list and rewiring the callers introduced five
bugs. A code review caught them; all were fixed.

**Bug 1 — `list(response.output_text)`.** `output_text` is a JSON *string*.
`list()` on a string explodes it into individual characters. The loop then
tried to `json.loads` each character, failed on `'['`, and returned `None`.
The extractor was returning nothing on essentially every call.
*Fix:* `json.loads(response.output_text)` once — `output_text` is one JSON
string representing the whole array; parse it a single time.

**Bug 2 — `i.get["content"]`.** Square brackets subscript the `.get`
*method object* → `TypeError`. *Fix:* `i.get("content")` — call it.

**Bug 3 — `"fact_captured": fact` in `main.py`.** The variable had been
renamed to `facts`; `fact` no longer existed → `NameError`, every `/chat`
returning 500. *Fix:* `facts`.

**Bug 4 — `save_fact` stored the whole list as one Redis element.**
`json.dumps(facts)` serialized the entire list into one string; `rpush`
pushed it as a single element. `get_facts` then returned a list *of lists*.
*Fix:* loop the list, `rpush` each fact as its own element.

**Bug 5 — `max_output_tokens=120`.** Fine for one fact; far too low for a
JSON array of several facts plus reasoning tokens → truncated JSON → parse
failure. *Fix:* raised (now 1000).

Two more improvements were added beyond the bug list: an
`isinstance(raw, list)` guard (so a malformed LLM response that parses as a
dict can't crash the loop), and a `timestamp` stamped onto each fact in
`save_fact` (so `FactsPanel`'s "Xm ago" keeps working).

**Lesson:** the recurring misconception was treating `output_text` as a
collection to iterate. It's a single string. Parse once, then iterate the
*result*.

---

## Problem 3, properly resolved: the gate

LLM-only created a real cost problem: **every message now fires an LLM
extraction call** — "hello", "ok", "what is a nebula?", everything. Two LLM
calls per turn instead of one.

The instinct was to make the regex robust enough to share the load — but
that's the wall the exercise already established: regex can't extract well.

**The reframe that unblocked it:** the regex doesn't need to *extract*. It
needs to *detect*. Detection — "could there plausibly be a self-fact here,
yes/no?" — is a vastly easier job than extraction, and the cost structure is
asymmetric in your favor:

- False positive (gate says yes, no fact) → one wasted LLM call. Tiny cost.
- False negative (gate says no, fact missed) → a lost fact. Real cost.

So the gate is tuned for **recall** — generous, "when unsure, let it
through." A generous yes/no detector is trivial to write.

**The implementation:** a single signal — first-person reference. A fact
*about the user* requires the user to refer to themselves. No `i` / `my` /
`me` in the message → almost certainly no self-fact → skip the LLM.

```python
_FIRST_PERSON = re.compile(r"\b(i|my|me|mine|myself)\b", re.I)

def _might_contain_fact(message: str) -> bool:
    return bool(_FIRST_PERSON.search(message))

def extract_fact(message, openai_client) -> list:
    if not _might_contain_fact(message):
        return []                                  # skip the LLM entirely
    return _extract_with_llm(message, openai_client) or []
```

`extract_fact` now always returns a **list** (Problem 1, resolved cleanly —
no more `None` vs `[]` ambiguity; `or []` normalizes).

First-person-only is a *deliberate v1*. Question-detection and
length-detection were considered and rejected for now — each is risky alone
("why do I love trekking?" is a question *with* a fact). Start with the one
safe signal, **measure** the real skip rate, add more only if needed.

**Lesson:** when a cheap component can't do the expensive job, ask whether it
can do a *cheaper* job that still helps. Extractor → detector was the move.

---

## The frontend ripple

`fact_captured` went from one object to a list. `ChatPanel.jsx` rendered it
as a single object (`m.fact.content`) — which silently broke once it became a
list. Fixed by renaming the local field to `facts` and `.map`-ing over it,
guarded with `m.facts.length > 0` (an empty array is *truthy* in JavaScript,
so `m.facts &&` alone is not enough).

**Lesson:** a return-type change ripples to every consumer — including the
ones in another language. "Trace the data all the way" was the exercise's
own warning, and this is where it landed.

---

## The result — proof it worked

From a real session (`d14f4196`), facts captured after the redesign:

```
identity    User's name is Shiv                                   0.80
preference  Loves mountains and trekking                          0.90
interest    Interested in singularities and black holes           0.70
interest    Completed a solo trek to Lamadugh near Manali         0.60
goal        Goal to finish at least 2 proper treks by May 2027    0.95
goal        Goal to complete at least 10 treks before turning 30  0.95
identity    Currently 26 years old                                0.60
interest    Enjoys imagining falling into black holes ...         0.70
preference  Loves physics                                         0.90
goal        Wishes they could have become an astrophysicist       0.80
```

Compare to the old extractor's output: verbatim regex fragments like
`"trying to visualize how it would feel like to fall into a black hole"`,
every one tagged `preference`, every one at importance `0.7`.

After the redesign:
- **Multi-fact** — timestamps show one message produced 6 facts in a single
  call, another produced 3. The old `dict | None` could never do this.
- **Clean phrasing** — third-person restatements, not raw fragments.
- **Real categories** — identity / preference / interest / goal, judged from
  meaning.
- **Graded importance** — 0.60 to 0.95, reflecting actual significance.

And the message that *failed* in the exercise's triggering example —
"Physics is so fascinating, I love it!" — now correctly yields **"Loves
physics"** as its own fact.

---

## What was deliberately left

- **The gate is first-person-only.** Question/length signals can be added
  later — but only after measuring the real skip rate (a `[gate] SKIP/CALL`
  print is in place for exactly this).
- **Secondary cost optimizations not done:** a cheaper model/config for the
  extraction call, batching K turns into one call, async fire-and-forget.
  All discussed, none needed yet — revisit only if cost is still a problem
  after the gate.
- **Dead code:** `_PATTERNS` and the commented-out `_extract_with_patterns`
  remain in the file. Harmless, but worth deleting (the project committed to
  LLM-only) so the repo reads as finished.
