# BD-42 — Walkthrough 03: The Message Flow, End to End

Trace of one complete `/chat` round trip — from the moment you press Enter in
the UI to the moment the assistant bubble lands and the facts panel updates.
Eleven steps, with **every memory operation explicitly called out** so the
two-tier architecture becomes concrete instead of abstract.

This is the doc to re-read whenever someone asks "what actually happens when
a user sends a message?" or "how does the memory work, exactly?" — including
yourself in three months when the details have faded.

---

## Quick orientation — where memory lives

Before the trace, the two-tier model in one table:

| Tier              | Redis key                       | Lifespan          | Trim?         | TTL?    | What's in it                              |
|-------------------|---------------------------------|-------------------|---------------|---------|-------------------------------------------|
| Short-term        | `chat:<session_id>`             | Recent only       | Last 12 msgs  | 2 hours | Raw conversation turns `{role, content}`  |
| Long-term (facts) | `bd42:facts:<session_id>`       | Unbounded         | No            | None    | Distilled facts `{content, category, importance, timestamp}` |

Same Redis instance, two different key prefixes. The trim + TTL on short-term
are the magic — Redis enforces the "small and hot" property automatically, no
cron, no cleanup.

### Why is long-term still in Redis?

A fair question and a deliberate MVP choice. Tradeoffs:

| Aspect                | What Redis gives us                                | What's missing for production-grade long-term    |
|-----------------------|----------------------------------------------------|--------------------------------------------------|
| Speed                 | Sub-millisecond reads/writes                        | (not the bottleneck)                             |
| Durability            | Snapshot-based via RDB / AOF                        | Stronger guarantees + point-in-time recovery     |
| Querying              | Lookup by key, list slicing only                    | `WHERE category='goal' ORDER BY importance` etc. |
| Indexes               | None on fact contents                               | Postgres can index on category, importance, ts   |
| Relational data       | None                                                | Sessions → users → facts modelable cleanly       |
| Vector search         | Not natively                                        | pgvector is purpose-built                        |

**The migration plan:** when the semantic memory layer lands (pgvector +
embeddings), long-term facts move to Postgres alongside the embedded
conversation chunks. Redis stays as the short-term tier where its strengths
(fast reads, list trim, TTL) actually matter.

**Interview line:** *"I started with Redis because it was already in place
for short-term and avoiding a second store kept the MVP simple. The right
home for persistent facts is Postgres, and that migration happens when I add
the pgvector layer — both kinds of long-term memory end up there together."*

That shows you understood the tradeoff and chose the simpler path
deliberately, rather than defaulting into Redis because you didn't know
better.

---

## The high-level sequence

Five memory operations happen per request: **2 reads, 3 writes** (the third
write being conditional on the fact extractor hitting).

```
   USER types and presses Enter
        │
        ▼
   ┌───────────────────────────────────────────────────────────┐
   │ FRONTEND  (ChatPanel.jsx)                                  │
   │  ① user bubble appears immediately (optimistic UI)         │
   │  ② POST /chat → backend                                    │
   └───────────────────────┬───────────────────────────────────┘
                           │
                           ▼
   ┌───────────────────────────────────────────────────────────┐
   │ BACKEND  (main.py /chat handler)                           │
   │                                                            │
   │  ③ build_context:                                          │
   │     ┌─→ READ short-term history    ◄── Redis chat:<id>     │
   │     └─→ READ long-term facts       ◄── Redis bd42:facts:<id>│
   │     assemble prompt = persona + facts + history + msg      │
   │                                                            │
   │  ④ call LLM (gpt-5-mini Responses API)                     │
   │                                                            │
   │  ⑤ persist conversation:                                   │
   │     ├─→ WRITE user turn            ──► Redis chat:<id>     │
   │     └─→ WRITE assistant turn       ──► Redis chat:<id>     │
   │                                                            │
   │  ⑥ extract_fact:                                           │
   │     ├─→ try regex patterns (cheap, no LLM)                 │
   │     └─→ on miss: second LLM call (gpt-5-mini, JSON-or-null)│
   │                                                            │
   │  ⑦ if fact captured:                                       │
   │        WRITE long-term fact        ──► Redis bd42:facts:<id>│
   │                                                            │
   │  ⑧ return { reply, fact_captured }                         │
   └───────────────────────┬───────────────────────────────────┘
                           │
                           ▼
   ┌───────────────────────────────────────────────────────────┐
   │ FRONTEND  (ChatPanel + App + FactsPanel)                   │
   │  ⑨ assistant bubble appears                                │
   │  ⑩ if fact_captured: "remembered" badge under bubble       │
   │  ⑪ refreshKey bumps → FactsPanel re-fetches /facts/<id>    │
   └───────────────────────────────────────────────────────────┘
```

---

## Step-by-step walkthrough

### ① and ② — Frontend optimistic update and fetch

File: `web/src/components/ChatPanel.jsx`, the `sendMessage()` function.

```jsx
const userMsg = { role: 'user', content: trimmed, ts: Date.now() }
setMessages(prev => [...prev, userMsg])     // ① user bubble appears NOW
setInput('')
setIsLoading(true)

const res = await fetch(`${API_URL}/chat`, {  // ② network call
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    message: trimmed,
    session_id: sessionId,
    context: {},                            // empty for now — placeholder for simulation state
  }),
})
```

**The concept to name:** *optimistic UI*. Update local state as if the action
succeeded; reconcile when the server actually responds. It's why the chat
feels snappy even on a 2-second LLM latency.

The `body` carries three things: the message text, the `session_id` (so the
backend knows which Redis keys to touch), and a `context` field that's an
empty object today — placeholder for simulation state when this gets
integrated into cosmic-playground.

---

### ③ — `build_context`: TWO memory reads

The request lands at `main.py`. FastAPI parses the body into a `ChatRequest`
pydantic model. First thing the handler does:

```python
ctx = build_context(req.message, req.session_id, req.context)
```

Inside `services/context_builder.py`:

```python
def build_context(message: str, session_id: str, sim_context: dict) -> dict:
    return {
        "system":       PERSONA,
        "history":      _format_history(get_history(session_id)),   # ← READ short-term
        "facts":        _format_facts(get_facts(session_id)),       # ← READ long-term
        "sim_context":  sim_context,
        "user_message": message,
    }
```

**This is where both memory tiers are read.** `get_history()` and `get_facts()`
both call into `memory.py`:

```python
def get_history(session_id, limit=12):
    items = redis_client.lrange(f"chat:{session_id}", -limit, -1)
    return [json.loads(x) for x in items]

def get_facts(session_id, limit=20):
    items = redis_client.lrange(f"bd42:facts:{session_id}", -limit, -1)
    return [json.loads(x) for x in items]
```

Two Redis `LRANGE` calls — one per keyspace. The functions don't know about
each other; they just both happen to be called by the context builder.

The returned dict is the **structured representation of the prompt**.
Provider-agnostic — neither OpenAI nor OpenRouter knows about this shape;
that's the renderer's job next.

**Concept to name:** *the seam.* This is the abstraction layer where every
future memory feature plugs in. Semantic memory will add a `relevant_chunks`
key. Hybrid retrieval scoring will live inside `_format_facts`. The brain
hub will read from the same data without touching this code path. The seam
is what makes the architecture extensible — and it costs nothing to maintain.

---

### ④ — Render and call the LLM

Back in `main.py`:

```python
if MODEL_PROVIDER == "openai":
    response = openai_client.responses.create(
        model="gpt-5-mini",
        input=render_as_single_input(ctx),
        max_output_tokens=300,
        reasoning={"effort": "low"},
    )
    reply = response.output_text
```

`render_as_single_input(ctx)` concatenates everything into one big string:

```
<persona text>

Known about user:
- (preference) thing in the whole world mountains...
- (interest) ...

Conversation so far:
user: hello bd!
assistant: Ooh—hello, human! ...
user: I think my favourite thing in the whole world are mountains...
assistant: Ooh—mountain aspiration detected! ...

Simulation context:
{}

User: ok what is a nebula?
```

**That whole string is what the LLM sees.** There is no hidden state on
OpenAI's servers — they have no idea who you are between calls. The
"memory" is entirely manufactured by us concatenating the right things into
the prompt.

**Concept to name:** *context engineering*. The discipline of choosing
what goes in the prompt. Every feature in BD-42 that feels like memory is
really an answer to "what should we put in the prompt right now?"

If `MODEL_PROVIDER` is `"openrouter"`, the same `ctx` dict gets rendered as a
messages array instead (system message + user message). Different shape, same
data. That's the **Strategy pattern** — interchangeable algorithms behind a
common interface.

The model returns a reply. We extract `response.output_text`.

---

### ⑤ — Persist the conversation: TWO memory writes

```python
save_message(req.session_id, "user", req.message)
save_message(req.session_id, "assistant", reply)
```

Inside `memory.py`:

```python
def save_message(session_id, role, content):
    key = f"chat:{session_id}"
    msg = {"role": role, "content": content}
    redis_client.rpush(key, json.dumps(msg))           # append
    redis_client.ltrim(key, -12, -1)                   # keep only last 12
    redis_client.expire(key, 7200)                     # 2-hour TTL refreshed on every write
```

**The trim + expire are doing real work.** Every time you save a turn:

- `RPUSH` appends the new turn to the list.
- `LTRIM` cuts it back down to the last 12 entries — older turns drop off
  the front automatically.
- `EXPIRE` refreshes the 2-hour countdown. Every write keeps the session
  alive; two hours of silence and Redis deletes the whole key.

You're outsourcing cleanup to the database. No cron job, no garbage
collector, no manual delete-old-rows query. **This is the kind of design
choice that's invisible when it works and obvious when you skip it.**

Note the ordering: we save *after* the LLM call, not before. This means the
LLM saw history *without* the current turn — the current message only
reaches the model via the trailing `User:` line in the assembled prompt
(see step ④). Easy to break if you reorder things; worth a comment to
future-you.

---

### ⑥ — Extract fact: the hybrid cascade

```python
fact = extract_fact(req.message, openai_client)
```

Inside `services/fact_extractor.py`:

```python
def extract_fact(message, openai_client):
    return _extract_with_patterns(message) or _extract_with_llm(message, openai_client)
```

**Python's `or` short-circuits.** If regex returns a non-empty dict, the
LLM call never happens. If regex returns `None`, the right-hand expression
evaluates, triggering the second LLM call.

The regex pass tries six patterns: `my favorite X is Y`, `I love/adore Z`,
`I like/enjoy/prefer Z`, `I'm into X`, `I'm a/an X`, `my name is X`. These
catch the obvious shapes of stated preferences and identity claims.

If all regex misses, the LLM fallback fires a *second, separate* call to
gpt-5-mini with this prompt:

```
You extract persistent facts a user has stated about themselves...

Persistent facts include: stated preferences, recurring interests, identity
traits, goals, important relationships, ongoing projects.

NOT persistent facts: passing observations, questions, requests, jokes...

If the message contains a persistent fact, output JSON: {content, category, importance}
If no persistent fact, output exactly: null
```

The response gets `json.loads`-ed and returned as a dict, or `None` if it
parsed as `null` or the JSON was malformed.

**Concept to name:** *cheap-path-first cascade*. The same pattern in CPU
caches, CDN edges, query caches, Bloom filters, spam filters. Most cases
hit the cheap path; only the ambiguous ones pay for the expensive path. In
this codebase: most user messages contain no fact at all, so most turns hit
zero extra API calls.

**Cost dimension to be aware of:** when regex misses, you pay for a *second*
LLM round-trip on the same chat turn. Two API calls per "I find X
fascinating"-style message. That's the price of the hybrid; the upside is
zero cost on the obvious cases. Future improvement: make the LLM fallback
asynchronous (fire and forget) so it doesn't add latency to the chat reply.

---

### ⑦ — Conditional long-term write

```python
if fact:
    save_fact(req.session_id, fact["content"], fact["category"], fact["importance"])
```

Inside `memory.py`:

```python
def save_fact(session_id, content, category="general", importance=0.5):
    key = f"bd42:facts:{session_id}"
    fact = {
        "content":    content,
        "category":   category,
        "importance": importance,
        "timestamp":  time.time(),
    }
    redis_client.rpush(key, json.dumps(fact))
```

**Notice what's missing.** No `LTRIM`. No `EXPIRE`. This is the long-term
tier — it accumulates forever (within Redis's storage limit) and never
auto-expires. The asymmetry between `save_message` and `save_fact` *is* the
two-tier architecture, expressed in code.

If the fact extractor returned `None` (no fact found), this whole step is
skipped and nothing is written to long-term.

---

### ⑧ — Return to frontend

```python
return {"reply": reply, "fact_captured": fact}
```

`fact_captured` is either `None` or the `{content, category, importance}`
dict that just got saved. The frontend uses both fields.

---

### ⑨, ⑩, ⑪ — Frontend reconciliation

Back in `ChatPanel.jsx`:

```jsx
const data = await res.json()
const assistantMsg = {
  role: 'assistant',
  content: data.reply,
  fact: data.fact_captured,   // may be null, may be {content, category, importance}
}
setMessages(prev => [...prev, assistantMsg])
setIsLoading(false)
onChatComplete?.()
```

Three things happen:

**⑨** The assistant bubble appears. If `assistantMsg.fact` is non-null,
the JSX inside the bubble renders the green `remembered: ...` line below
the reply text.

**⑩** `setIsLoading(false)` removes the typing dots.

**⑪** `onChatComplete()` is a callback prop from `App`. Inside `App.jsx`:

```jsx
function handleChatComplete() {
  setFactsRefreshKey(k => k + 1)
}
```

That state change cascades into `FactsPanel`'s `useEffect` dependency
array (because `refreshKey` is a dep), which fires a fresh `GET
/facts/<sessionId>` call.

Inside `memory.py`, that's another `LRANGE` on `bd42:facts:<id>`. A
*separate read path* from the chat flow, deliberately — so the facts panel
works without needing to wait for or coordinate with the chat fetch.

**Concept to name:** *the refresh-key / version counter pattern*. It's how
you say "please re-run that effect" from outside a component, without
exposing imperative methods.

---

## The memory architecture in 200 words

If someone asks **"explain the memory architecture"** in an interview, this
is what you say:

> Two tiers, both Redis today, with different rules.
>
> **Short-term** lives at key `chat:<session_id>` as a list of `{role,
> content}` JSON entries. Trimmed to the last 12 messages by `LTRIM`,
> expires after 2 hours of silence by `EXPIRE`. It exists to give the LLM
> recent conversational context. It's *allowed* to forget.
>
> **Long-term** lives at key `bd42:facts:<session_id>` as a list of
> `{content, category, importance, timestamp}` JSON entries. No trim, no
> expire. It accumulates distilled facts about the user — preferences,
> identity, goals — that survive past the chat window. Anything important
> in the chat should have already been extracted into this tier before chat
> history evaporates.
>
> On every chat request, both tiers are read and injected into the prompt.
> After the reply, the conversation turn is written to short-term and a
> hybrid extractor — regex first, LLM fallback — tries to mine a persistent
> fact from the user's message. If found, it's written to long-term.
>
> **Coming next:** a third tier — semantic long-term memory in pgvector.
> Past conversation chunks get embedded and retrieved by similarity, scored
> with `0.6 * similarity + 0.2 * recency + 0.2 * importance`. That milestone
> also moves long-term facts out of Redis and into Postgres, where they
> belong.

Memorize that. Drop it whenever asked.

---

## Glossary

| Concept                          | Where it shows up in BD-42                        |
|----------------------------------|---------------------------------------------------|
| Optimistic UI                    | User bubble appears before server replies         |
| Context engineering              | `build_context` + `render_as_single_input`        |
| Strategy pattern                 | `render_as_single_input` vs. `render_as_messages` |
| Two-tier memory                  | `chat:*` (short) vs. `bd42:facts:*` (long)        |
| TTL + LTRIM as auto-cleanup      | Inside `save_message`                             |
| Cheap-path-first cascade         | Regex `or` LLM in `extract_fact`                  |
| Graceful degradation             | `try/except` around the LLM extractor             |
| The seam                         | The dict returned by `build_context`              |
| Refresh-key / version counter    | `factsRefreshKey` in `App.jsx`                    |

---

## Where to go next

Once this trace is internalized, the natural follow-ups:

1. **Add the debug prints** in `_extract_with_llm` (the silent-fail debug we
   talked about). Twenty seconds of work; surfaces what the LLM actually
   said when regex misses.

2. **Read the planned upgrade path** in the project roadmap (README.md or
   the task list). The next milestone — pgvector + embeddings — is what this
   architecture was built to absorb without rewriting.

3. **If you want to go deeper on any piece** — the Redis data model, why
   FastAPI's pydantic models do what they do, how `LRANGE` indexes work,
   what an LLM context window actually is, anything — say which and I'll
   write a focused deep-dive doc.
