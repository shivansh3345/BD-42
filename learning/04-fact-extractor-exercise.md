# BD-42 — Exercise 04: Redesign the Fact Extractor

This is a **debugging / redesign exercise**, not a walkthrough. It hands you
five scoped problem statements in `services/fact_extractor.py` and asks you
to fix them yourself. Solutions are deliberately withheld — one problem
(Problem 3) has no single right answer; it's a real design decision.

Work it, then have it reviewed.

---

## What triggered this

During a conversation about black holes, the user sent BD-42 this message:

> "oh damn now I understand, I love trying to visualize how it would feel like
> to fall into a black hole, both in a non-spinning one and a spinning one.
> Physics is so fascinating, I love it!"

That sentence contains **two** facts about the user:

1. enjoys visualizing what falling into a black hole feels like
2. is fascinated by physics

BD-42 stored **one**, and stored it badly — as the verbatim fragment
`"trying to visualize how it would feel like to fall into a black hole"`,
tagged `preference`, importance `70%`. The bigger, cleaner fact ("fascinated
by physics") was lost entirely.

That one example exposes five separate problems. The exercise is to fix them.

---

## Background — how the extractor works today

`extract_fact` is called once per chat turn, on the user's message, after the
reply is generated. Its job: detect persistent facts about the user and hand
them to `save_fact` for storage.

The current shape:

```python
def extract_fact(message, openai_client) -> dict | None:
    return _extract_with_patterns(message) or _extract_with_llm(message, openai_client)
```

- `_extract_with_patterns` — a list of compiled regex patterns, each paired
  with a hardcoded category. Tries them, returns the first match as a dict
  `{content, category, importance}`.
- `_extract_with_llm` — a fallback: sends the message to gpt-5-mini with a
  prompt asking for JSON `{content, category, importance}` or `null`.

The caller (`main.py`) does roughly:

```python
fact = extract_fact(req.message, openai_client)
if fact:
    save_fact(req.session_id, fact["content"], fact["category"], fact["importance"])
return {"reply": reply, "fact_captured": fact}
```

Before you start, re-read `services/fact_extractor.py`, the `/chat` handler in
`main.py`, and `save_fact` in `memory.py`.

---

## Problem 1 — The return type can't represent reality

**Symptom.** The triggering message contains two facts. The extractor stored
one. It will *always* store at most one, regardless of how good the
extraction logic gets.

**Root cause.** The contract:

```python
def extract_fact(message, openai_client) -> dict | None:
```

`dict | None` means "one fact, or nothing." There is no slot for a second
fact. This isn't a logic bug you can patch — it's the *shape* of the
function. Every other problem below is partly blocked on this one.

**Constraints a fix must respect.**
- The return value flows further than `fact_extractor.py`. Trace it: who
  calls `extract_fact`? What does that caller do with the result? What does
  the caller send back to the frontend, and what does the frontend *render*?
  Follow the data all the way. If you change the shape here, every consumer
  downstream changes with it — and one of those consumers is not Python.
- Decide what "no facts found" looks like in the new shape, and make sure
  every caller handles it cleanly.

**Do this first.** Everything else assumes the new shape exists.

---

## Problem 2 — The regex extracts at most one match per message

**Symptom.** Even with Problem 1 fixed — even if the return type *could* hold
many — the regex layer would still surface only one.

**Root cause.** In `_extract_with_patterns`, two compounding limits:
1. It loops the patterns and **returns on the first pattern that matches** —
   the remaining patterns are never tried.
2. Within a pattern it uses `re.search`, which finds only the **first
   occurrence**. "I love X ... I love Y" → only X.

**Constraints a fix must respect.**
- A message can contain multiple facts matching the *same* pattern (two
  "I love"s) **and** facts matching *different* patterns ("my name is X" +
  "I love Y"). Both cases must work.
- Don't store the same fact twice if two patterns overlap on the same span.

**Think about.** What's the right `re` method when you want *all* matches,
not the first? Once you have every match across every pattern — is there a
deduplication question?

---

## Problem 3 — A regex hit silently blocks the smarter extractor

**Symptom.** The triggering message produced the clumsy fragment
`"trying to visualize how it would feel like to fall into a black hole"`. The
LLM extractor — which is *built* to read the whole sentence and produce a
clean restatement — never ran.

**Root cause.**

```python
return _extract_with_patterns(message) or _extract_with_llm(message, openai_client)
```

`or` short-circuits. The instant the regex returns anything truthy, the LLM
is skipped. The code assumes **"a regex hit is always good enough."** It
isn't: a regex hit on a simple sentence ("I love mountains and trekking") is
fine; a regex hit on a rich, clause-heavy sentence is fragment-garbage *and*
it suppresses the path that would have done it well.

**This is the hard one — a genuine design decision, not a bug with one right
answer.** Questions to reason through:

- What is the regex layer actually *for*? Is it an *extractor* (produces the
  final fact) or a *detector* (cheaply answers "is there probably a fact
  here at all")? Those are very different roles with very different designs.
- Is it ever correct to run *both* paths? What does each contribute?
- "Cheap path first" exists for **cost** — not firing an LLM call on every
  "hello" / "ok". Whatever you design, does it preserve that? Count the LLM
  calls per message in your design and compare against today's.
- If the LLM does more of the work, what happens to latency? The chat reply
  is the primary path; extraction is secondary and must not slow it down or
  break it.

There is no answer key. Design it, justify it, defend it.

---

## Problem 4 — Missing interest-patterns, and no quality gate

Two related sub-problems.

**4a — Symptom.** "Physics is so fascinating" matched nothing. The pattern
set covers `my favorite X`, `I love/like X`, `I'm into X`, `I'm a/an X`,
`my name is X`. The most natural way a person states an intellectual
interest — "X is fascinating", "I'm fascinated by X", "X fascinates me" —
has **no pattern at all**.

**4b — Symptom.** If you fix Problem 2 and capture the second "I love" in the
triggering message — "I love **it**!" — the regex grabs the pronoun `"it"`.
A stored fact whose content is `"it"` is worse than no fact.

**Root cause.** 4a is a gap in the pattern set. 4b is the absence of any
check that a capture is *substantive enough to be worth keeping*.

**Constraints a fix must respect.**
- For 4b: what makes `"it"` a bad capture but `"dogs"` a good one? Both are
  short — so length alone is not the discriminator. Think harder about what
  is actually wrong with `"it"`. And whatever rule you write, make sure it
  doesn't reject legitimate short facts.
- Be careful adding patterns (4a): every new pattern is a new false-positive
  risk. "That movie was fascinating" is not a fact about the *user*.

**Think about.** Is the quality gate a regex-layer concern, an everywhere
concern, or does it tie back into your Problem 3 design?

---

## Problem 5 — Category and importance are fake

**Symptom.** Every captured fact shows `PREFERENCE` and `70%`. A multi-year
life goal (Himalayan trekking) and a passing delight score identically, and
both are mis-categorized.

**Root cause.**
- **Category** is hardcoded *per regex pattern* — the `I love X` pattern
  always stamps `"preference"`. It reflects *which regex matched*, not what
  the fact *means*.
- **Importance** is a constant — `0.7` for any regex hit. It differentiates
  nothing. This bites in Phase B, where hybrid retrieval scoring weights 20%
  on importance.

**Think about.** Be honest about a hard question: *can a regex realistically
produce a good category and a graded importance at all?* A regex matches
surface text; it has no model of meaning. If the answer is "no, not really,"
then this problem is not solved in isolation — it becomes an argument that
feeds back into your Problem 3 design. Which path is actually *capable* of
judging category and importance?

---

## How to work it

**Recommended order:** Problem 1 first — everything depends on it. Then
Problem 3 is the keystone: once the cascade architecture is decided,
Problems 2, 4, and 5 largely become implementation details that follow from
it. So: **1 → think hard about 3 → then 2, 4, 5 fall into place.**

**Getting it reviewed:** either paste the edited `fact_extractor.py` (plus
any other files changed) once something works, or — for Problem 3 especially
— describe the design in prose *first* and have it pressure-tested before
writing code. For a design decision this size, talking it through before
coding is usually the smart move.

**Definition of done:** re-send the triggering message to BD-42 and confirm
both facts are captured, cleanly phrased, sensibly categorized, with
non-identical importance — and that "hello" / "ok" style messages still cost
zero LLM extraction calls.
