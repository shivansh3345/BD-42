# BD-42 — Walkthrough 01: Foundations

A guided tour of what we built in the first two refactor steps of BD-42: the
context-builder seam and the two-tier memory slice. The goal is not to remind
you of the code — the code is the code. The goal is to pull out the **concepts**
underneath, name them, and give you the language to defend the choices in an
interview or a portfolio writeup.

We make seven stops. Each stop has the same shape:

- **The question** the stop answers
- **The plain-language story**
- **Code references** (file:line) so you can follow along
- **The key insight** in a single sentence
- **What to call it** in an interview
- An optional **try this** experiment, where it helps

Skim the map below, then read in order the first time. Re-reading later, you can
jump straight to a stop.

---

## The map

| Stop | The question                                                          | The concept                       |
|-----:|-----------------------------------------------------------------------|-----------------------------------|
|    1 | What actually happens on a single `/chat` request?                    | Request lifecycle, statelessness  |
|    2 | Why refactor *before* adding the new feature?                         | Separation of concerns, SRP       |
|    3 | Why does memory live in two places?                                   | Multi-tier memory                 |
|    4 | The LLM doesn't remember anything. So how does BD-42 "remember"?      | Context engineering               |
|    5 | Why try regex first and only call the LLM as a fallback?              | Cheap-path-first / tiered work    |
|    6 | What Python idioms are doing real work in our code?                   | Python craft                      |
|    7 | What did this architecture buy us for future features?                | Seams that absorb change          |

---

## Stop 1 — A single `/chat` request, end to end

> **The question:** When you send BD-42 a message, what actually happens between
> the request landing and the reply coming back?

### The story

Forget the abstractions for a second. Trace one request:

1. Your message arrives at `POST /chat`.
2. BD-42 looks up *who is this user, and what do we know about them?* — pulls
   recent chat history and known facts from Redis.
3. It glues all of that into one big block of text — persona + facts + history
   + your new message — and hands it to the LLM.
4. The LLM hands back a reply.
5. BD-42 saves the new turn into history. Then it asks itself: *did the user
   just say something worth remembering forever?* If yes, save it to the facts
   bucket.
6. The reply goes back to you.

### Visual

```
   POST /chat
       │
       ▼
   ┌──────────────────┐
   │   main.py        │   parse request
   └────────┬─────────┘
            │
            ▼
   ┌──────────────────────────┐
   │  context_builder         │
   │   • get_history          │ ── Redis ──→  recent turns
   │   • get_facts            │ ── Redis ──→  known facts
   │   • assemble prompt      │
   └────────┬─────────────────┘
            │
            ▼
   ┌──────────────────┐
   │   LLM call       │ ── OpenAI / OpenRouter
   └────────┬─────────┘
            │   reply text
            ▼
   ┌──────────────────────────┐
   │  persist + extract       │
   │   • save user turn       │ ── Redis
   │   • save assistant turn  │ ── Redis
   │   • extract_fact()       │ ── regex, then LLM if needed
   │   • if hit: save_fact    │ ── Redis (separate keyspace)
   └────────┬─────────────────┘
            │
            ▼
        { reply, fact_captured }
```

### Code references

- The whole flow: `main.py:39-65` (the `/chat` handler)
- Context assembly: `services/context_builder.py:18-25`
- Persistence: `memory.py:18-25` (chat) and `memory.py:39-46` (facts)

### Key insight

> **Every interesting AI app is some shape of this loop.** The "magic" is in
> what you put into step 3 (context assembly) and what you extract in step 5
> (memory writes). The LLM call itself is the boring middle.

### Name this

- **Request-response server** — stateless over HTTP, stateful inside (Redis).
- **Context assembly** is the job done in step 3. Also called **prompt
  construction** or **context engineering**.

---

## Stop 2 — Why we refactored before adding the feature

> **The question:** We wanted to add long-term memory. Why didn't we just open
> `main.py` and add it? Why a refactor first?

### The story

Yesterday `main.py` did everything: parsed requests, built prompts, kept the
persona, formatted history, called the LLM, persisted turns. **One file, many
reasons to change.** Tomorrow if we wanted to:

- tweak BD-42's voice → open `main.py`
- change how history is formatted → open `main.py`
- switch model providers → open `main.py`
- add long-term memory → open `main.py`

Pretty soon `main.py` is 600 lines and nobody can find anything. So before
adding the next thing, we split it.

After the refactor, each file has **one reason to change**:

| File                              | Changes when…                          |
|-----------------------------------|----------------------------------------|
| `main.py`                         | the HTTP shape changes                 |
| `services/context_builder.py`    | the prompt structure changes           |
| `services/fact_extractor.py`     | how we detect facts changes            |
| `personality.py`                  | BD-42's voice changes                  |
| `memory.py`                       | the storage layer changes              |

### The tradeoff

More files. For a project this small, splitting into a `services/` package can
feel like overkill. But it's the *exact* moment to do it — splitting a 50-line
file is trivial, splitting a 600-line file is a weekend.

### Key insight

> Refactor when you can predict the next 2–3 features. If you can't, you don't
> know what seams to draw yet — wait until you do.

We did the refactor *because* we could name what was coming (long-term memory,
semantic retrieval, brain hub). Each one plugs into the new shape cleanly. If
we couldn't have named them, this would have been premature abstraction.

### Name this

- **Separation of concerns** — break a system along lines of "reason to change."
- **Single Responsibility Principle (SRP)** — each module has one job.
- **Three-layer architecture** — handler → service → store. Older than dirt,
  works everywhere. In our project: `main.py` (handler) → `services/` (logic)
  → `memory.py` (store).

### Interview line

> *"I extracted a service layer between the HTTP handler and the storage layer
> so that adding the long-term memory feature didn't require touching the HTTP
> handler at all."*

---

## Stop 3 — Memory has two shapes, on purpose

> **The question:** Why does `memory.py` have *two* sets of functions
> (`save_message`/`get_history` and `save_fact`/`get_facts`)? Couldn't we have
> just used one?

### The story

We could have. But chat history and facts are two genuinely different kinds
of information, with different lifespans and different access patterns. Lumping
them together would force one set of rules to fit both.

Compare:

|                        | **Chat history**             | **Facts**                       |
|------------------------|------------------------------|---------------------------------|
| What it is             | Raw transcript               | Distilled knowledge             |
| Lifespan               | Short (minutes / hours)      | Long (ideally forever)          |
| Volume growth          | Fast (every turn)            | Slow (only on extraction hits)  |
| Bounded?               | Yes — last 12 messages       | No                              |
| Auto-expires?          | Yes — 2-hour TTL             | No                              |
| Redis key              | `chat:<session_id>`          | `bd42:facts:<session_id>`       |

The boundedness and TTL on chat history aren't laziness — they're
**deliberate**. Chat history is allowed to forget, because anything important
in it should have already been extracted into facts.

### The Redis idiom worth noticing

`memory.py:19-22`:

```python
redis_client.rpush(key, json.dumps(msg))
redis_client.ltrim(key, -12, -1)          # keep only the last 12
redis_client.expire(key, 7200)            # 2-hour TTL
```

`LTRIM` keeps a Redis list bounded — "keep the last 12 elements, drop the
rest." `EXPIRE` sets a TTL — "if nobody touches this key for 7200 seconds,
delete it." Together they let Redis enforce the "small and hot" property
automatically — no cron job, no cleanup script. The database is doing the
work.

The facts bucket (`memory.py:39-46`) has *neither* call. That's the long-term
half.

### Key insight

> **Hot data lives close. Cold data lives far.** This idea — storage tiers
> sized and aged differently — shows up in CPUs (L1 → L2 → L3 → RAM), operating
> systems (page cache → memory → SSD), and AI products (working memory →
> long-term memory → vector store). When you see *one* storage type doing
> *everything*, that's a smell.

### Name this

- **Multi-tier memory** (or **memory hierarchy**).
- **TTL** = "time to live." A field on a record that tells the database when
  to auto-delete it.

### Try this

After running the demo flow, in a Redis shell:

```
KEYS *
TTL chat:demo1
TTL bd42:facts:demo1     # should return -1, meaning "no expiry"
LLEN chat:demo1          # should never exceed 12
LLEN bd42:facts:demo1
```

Notice the asymmetry. That's the architecture in action.

---

## Stop 4 — The LLM is stateless. **You** manufacture the memory.

> **The question:** How does BD-42 "remember" anything if the LLM has no idea
> who you are between calls?

This is the single most important AI concept in the whole project. Get this
straight and a lot of "magic" stops being mysterious.

### The story

When `main.py:43` calls `openai_client.responses.create(...)`, the OpenAI
servers have **zero** recollection of any prior call you made. Every request
arrives cold. The model does not "remember" your last conversation. It does
not even know that *there was* a last conversation.

The illusion that "ChatGPT remembers what we said" comes entirely from the
*application* — it stores the conversation, and re-sends the whole history
along with each new message. The model only sees what's in **this one
prompt**.

### What the LLM actually sees

Open `services/context_builder.py:28-35`. The `_assemble_user_block` function
literally concatenates a giant string. For a request mid-conversation, the
LLM receives something like:

```
You are BD-42, a small intelligent space exploration droid... (persona)

Known about user:
- (preference) favorite game | No Man's Sky

Conversation so far:
user: hey BD-42
assistant: Boop! What are we looking at today?
user: tell me about gravity
assistant: ...

Simulation context:
{ "view": "saturn_rings", "zoom": 0.7 }

User: what should I play tonight?
```

That's it. That's the whole "memory." There is no hidden state on the server
side. Everything the model knows about the user lives in those few lines we
glued together.

### Why this matters

Every feature that *feels* like memory in an AI product is actually a system
that:

1. **Stores** information somewhere (Redis, Postgres, a vector DB…).
2. **Selects** what's relevant for this specific request.
3. **Injects** it into the prompt.

That's the whole game. RAG (retrieval-augmented generation)? Step 1 + 2 + 3
with embeddings. Tool use? "Here are tools you can call" — also in the prompt.
Long-term user preferences? Step 1 + 2 + 3 with a facts table.

### The cost dimension

Because everything is in the prompt, **every byte you inject costs tokens**,
and tokens cost money and latency. So you can't just stuff every fact and
every past message into every call. You need to **rank and trim**.

That's why your spec talks about hybrid retrieval:

```
score = 0.6 * semantic_similarity
      + 0.2 * recency
      + 0.2 * importance
```

The whole point of that formula is to pick the top-N items worth spending
tokens on, given that you can't include everything.

### Key insight

> **The LLM is a stateless function. Memory is something the surrounding
> system manufactures by curating the prompt.**

### Name this

- **Stateless model** — the LLM call has no server-side memory between requests.
- **Context engineering** — the discipline of choosing what goes in the prompt.
- **Context window** — the maximum tokens the model can see at once. Treat it
  as a budget, not a bucket.

---

## Stop 5 — Cheap-path-first: regex before LLM

> **The question:** Why does `fact_extractor.py` run regex first and only call
> the LLM as a fallback, instead of just calling the LLM every time?

### The story

Look at the heart of `services/fact_extractor.py:75`:

```python
return _extract_with_patterns(message) or _extract_with_llm(message, openai_client)
```

That `or` is the entire pattern. Python's `or` short-circuits: if the left
side returns a truthy value (a dict), the right side never runs. So we **try
regex first** and only fall back to the LLM if regex misses.

### Why?

Most user messages don't contain a persistent fact at all. Greetings, idle
chat, questions about the simulation — noise, from a fact-extraction point of
view. Of the messages that *do* contain a fact, many follow obvious shapes:

- "my favorite X is Y"
- "I love / like / enjoy Z"
- "I'm a / an X"
- "my name is X"

Regex catches these in nanoseconds, for free. Only the *ambiguous* cases —
the user phrasing something in a way regex didn't anticipate — fall through
to the LLM.

The LLM call is the expensive thing. We want it to be **rare-case work**,
not every-case work.

### Visual

```
user message
     │
     ▼
┌──────────────────┐
│  regex pass      │  cost: ~microseconds, money: $0
└────────┬─────────┘
         │
   match?├── yes ─→  return fact
         │
         no
         │
         ▼
┌──────────────────┐
│  LLM call        │  cost: ~hundreds of ms, money: a fraction of a cent
└────────┬─────────┘
         │
   hit? ├── yes ─→ return fact
         │
         no / error
         │
         ▼
     return None
```

### Where else this pattern lives

You'll see this cascade shape *everywhere*:

| System                   | Cheap path                  | Expensive fallback          |
|--------------------------|-----------------------------|-----------------------------|
| CPU                      | L1 cache                    | L2 → L3 → RAM               |
| CDN                      | Edge node                   | Origin server               |
| Database query           | Query cache                 | Full table scan             |
| Spam filter              | Heuristic rules             | ML classifier               |
| Search                   | Bloom filter                | Full index lookup           |
| **BD-42 fact extraction**| **Regex patterns**          | **LLM call**                |

### One more thing in this file worth noticing

`services/fact_extractor.py:49`:

```python
try:
    response = openai_client.responses.create(...)
    raw = (response.output_text or "").strip()
except Exception:
    return None
```

The `try / except` here is a **boundary**. Fact extraction is *secondary* to
chat. If the secondary feature breaks, the chat reply must still work. So we
swallow extraction errors silently and return `None`, instead of letting the
exception propagate up and 500 the whole `/chat` request.

> **Name this:** **graceful degradation** — when a non-essential subsystem
> fails, the primary feature still works. Architectural decision, not just a
> coding habit.

### Key insight

> **The cheapest path that solves the problem wins.** Reach for the expensive
> tool only on the cases the cheap tool can't handle. Demanding every problem
> be solved by the same hammer (LLM-for-everything) wastes money and latency
> on cases a regex would have caught for free.

---

## Stop 6 — Python craft

A handful of Python idioms in our code that are doing real work. These are
the kind of things a senior reviewer notices.

### Type hints with `|` for unions

`services/fact_extractor.py:71`:

```python
def extract_fact(message: str, openai_client) -> dict | None:
```

The `dict | None` is "dict OR None." That `|` syntax landed in Python 3.10.
Before that you'd write `Optional[dict]` (which means the same thing).

Type hints don't enforce anything at runtime. They exist for:

- humans reading the code
- IDEs giving you autocomplete
- static type checkers (`mypy`, `pyright`)

Unlike comments, they can't drift out of date silently — a type checker will
yell at you if the code stops matching the hint.

### Dependency injection

Same line — notice `openai_client` is a *parameter*, not an import:

```python
def extract_fact(message: str, openai_client) -> dict | None:
```

We could have written `from main import openai_client` at the top of the
file. That would have:

1. Created a circular import (main imports fact_extractor, fact_extractor
   imports main).
2. Made `fact_extractor` impossible to test without a real OpenAI client.
3. Coupled `fact_extractor` to `main`'s specific client setup.

By taking the client as a parameter, `fact_extractor` just says: "I need *an*
OpenAI-shaped client. Caller, you give me one." The caller can pass a real
client, a mock client, a different vendor's client with a matching shape.

> **Name this:** **dependency injection** — the caller provides the
> dependency instead of the callee importing it. It's a fancy name for a
> simple idea.

### Compiled regex at module load

`services/fact_extractor.py:4-11`:

```python
_PATTERNS = [
    (re.compile(r"\bmy favou?rite ([\w\s]+?) (?:is|are) (.+)", re.I), "preference"),
    ...
]
```

Things to notice:

- `re.compile(...)` happens **once**, at module load, not every time
  `_extract_with_patterns` runs. Compiling regex is expensive; matching is
  cheap. Compiling at module load means each pattern is compiled exactly
  once, ever.
- `\b` is a **word boundary** — matches "my favorite", not "smyfavorite".
- `re.I` is the `IGNORECASE` flag.
- `favou?rite` — the `u?` means "u is optional." Handles British and American
  spelling without two patterns.
- `(?:is|are)` — the `?:` makes it a **non-capturing group**. We match "is or
  are" but don't reserve a capture slot for it.

### The Strategy pattern

`services/context_builder.py:38-46`:

```python
def render_as_single_input(ctx: dict) -> str: ...
def render_as_messages(ctx: dict) -> list[dict]: ...
```

Two different *strategies* for turning the same logical context into something
an LLM API will accept. The caller picks which one based on which provider it's
hitting.

If we add a third provider tomorrow (say, Anthropic), we add
`render_as_anthropic_messages` and don't have to touch `build_context`. The
strategies are interchangeable behind a common shape.

> **Name this:** the **Strategy pattern** — interchangeable algorithms behind
> a common interface.

### Truthiness checks

`services/context_builder.py:12`:

```python
if not facts:
    return ""
```

In Python, empty containers are **falsy**. Empty list, empty dict, empty
string, `None`, `0`, all evaluate to `False` in a boolean context. So
`not facts` reads as "if the list is empty."

This is more idiomatic than `if len(facts) == 0:` and also more *correct* in
the case where `facts` might be `None` instead of an empty list.

### Packages vs. modules

A folder with an `__init__.py` (even an empty one) is a **package**.
`services/context_builder.py` is a **module** inside the `services` package.

From `main.py` we write:

```python
from services.context_builder import build_context
```

Python knows `services` is a package because of the `__init__.py`. Without
it, that import path doesn't resolve cleanly.

---

## Stop 7 — Seams that absorb change

> **The question:** What did this refactor *actually buy* us, in terms of
> features we can now add without rewriting things?

### The story

Look at `build_context` in `services/context_builder.py`. It returns a dict:

```python
{
    "system":       PERSONA,
    "history":      ...,
    "facts":        ...,
    "sim_context":  ...,
    "user_message": ...,
}
```

The next big features in BD-42's roadmap plug into this dict **without
touching `main.py`**:

**Semantic memory (pgvector layer).**
Add a `"relevant_memories"` key. The builder calls a function like
`search_semantic(message, top_k=5)` that does a vector similarity search over
past embedded conversations or notes, and returns the most relevant chunks.
The renderers add a "Relevant past conversations:" section to the prompt.
`main.py`: untouched.

**Hybrid retrieval scoring** (`0.6 * similarity + 0.2 * recency + 0.2 * importance`).
Lives entirely inside whatever module does the retrieval. The builder just
calls it. `main.py`: still untouched.

**Brain hub.**
A separate read-only endpoint like `GET /graph/{session_id}` that walks the
facts and turns them into nodes/edges. The chat path doesn't change at all.

### Visual

```
   now:                                            after pgvector:

   ctx = build_context(...)                        ctx = build_context(...)

   {                                               {
     system:       PERSONA,                          system:       PERSONA,
     history:      ...,                              history:      ...,
     facts:        ...,                              facts:        ...,
     sim_context:  ...,                              sim_context:  ...,
                                                    relevant_chunks: ...,   ← NEW
     user_message: ...,                              user_message: ...,
   }                                               }

   main.py:        unchanged                       main.py:        unchanged
   renderers:      slightly updated                renderers:      slightly updated
```

### Key insight

> **A good seam absorbs change.** When you add a feature, ask: how many
> existing files do I have to touch, and are they the ones that conceptually
> own this change? If the answer is "one or two, the right ones," the
> architecture is healthy. If it's "seven files in five packages," the seams
> are in the wrong places.

### The honest version

This *only* works because we could name the next three features when we did
the refactor. If we couldn't, we'd have drawn the seam in the wrong place
and made things worse. Refactoring without a concrete next feature in mind
is gambling.

---

## Glossary

Quick-reference table of every concept we named:

| Concept                          | Where it shows up in BD-42                    |
|----------------------------------|-----------------------------------------------|
| Request-response server          | The whole `/chat` lifecycle                   |
| Context assembly / engineering   | `services/context_builder.py`                 |
| Stateless model                  | The OpenAI / OpenRouter call                  |
| Context window                   | Token budget you're filling                   |
| Separation of concerns           | The split between `main.py` / `services/`     |
| Single Responsibility Principle  | One reason to change per file                 |
| Three-layer architecture         | handler → service → store                     |
| Multi-tier memory                | `chat:*` vs `bd42:facts:*`                    |
| TTL (time-to-live)               | `redis_client.expire(key, 7200)`              |
| LTRIM-style bounded list         | `redis_client.ltrim(key, -12, -1)`            |
| Cheap-path-first / tiered work   | Regex before LLM in `fact_extractor`          |
| Graceful degradation             | `try/except` around the LLM extractor call    |
| Dependency injection             | Passing `openai_client` into `extract_fact`   |
| Strategy pattern                 | `render_as_single_input` / `render_as_messages` |
| Compile-once regex               | `_PATTERNS` at module load                    |
| Packages vs. modules             | `services/__init__.py`                        |
| Seams that absorb change         | The dict returned by `build_context`          |

---

## Where to go next

Three directions, ordered by how grounding they are. Pick one:

1. **Verify the demo first.** Spin up Redis + uvicorn, run the curl
   walkthrough we built, watch BD-42 actually pull off the No Man's Sky
   callback. This is the moment where everything in this doc stops being
   abstract.

2. **Make `importance` earn its keep.** Right now `_format_facts` sorts by
   importance, but we hardcode 0.7 everywhere. A small project: have the LLM
   fallback return real importance scores and use them to rank facts when the
   list grows past N. Teaches you basic ranking and threshold tuning.

3. **Add the semantic memory layer** (pgvector + embeddings). Bigger jump.
   Teaches you embeddings, vector search, approximate nearest neighbor
   (ANN) indexes. Right next stop on the AI/ML curriculum.

Any stop above can also be drilled deeper. If you want a whole walkthrough on
just embeddings, just RAG, just Redis internals, just Python's import
machinery — say the word.
