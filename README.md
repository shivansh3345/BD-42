# BD-42

A persistent AI companion experimenting with memory architecture, context engineering, and personality continuity.

> LLMs are stateless. Every API call arrives cold — the model has no memory of any prior conversation. Anything that *feels* like memory in an AI product is something the surrounding system manufactures by curating what goes into each prompt. BD-42 is an experiment in doing that well.

Inspired by BD-1 (Star Wars Jedi: Survivor) and JARVIS — a companion AI rather than a transactional assistant. The product moat is the memory architecture, not the LLM call or the chat UI.

---

## Status

**MVP, actively built.** Tiers 1 and 2 of the memory system are live; tier 3 (semantic) is scaffolded. The architecture is deliberately seam-first so the remaining layers plug in without disturbing the rest.

### Implemented

- FastAPI backend — `POST /chat`, `GET /facts/{session_id}` — with multi-provider LLM support (OpenAI Responses API + OpenRouter Chat Completions).
- **Two of three memory tiers**, both backed by Redis:
  - **Tier 1 — short-term:** conversation history per `session_id`, 12-message window, 2-hour TTL.
  - **Tier 2 — long-term facts:** distilled `{content, category, importance, timestamp}` records, separate keyspace, no TTL.
- **LLM-based multi-fact extraction.** After each turn, the user's message is mined for persistent facts — a single message can yield several. A cheap **first-person regex gate** decides whether to call the LLM at all, so questions and reactions cost zero extraction calls.
- **Context-builder seam** — one service assembles persona + facts + history into the prompt, provider-agnostic.
- **React chat UI** (`web/`) with a toggleable "Known about you" facts panel.
- **Fully Dockerized** — one `docker compose up` runs the whole stack.
- BD-42 persona: curious, observant, slightly mischievous, beep/boop.

### Scaffolded — not yet wired in

- **Tier 3 — semantic episodic memory:** Postgres + pgvector. The schema, embedding service, and adapter exist (`db/`, `services/embeddings.py`, `services/semantic_memory.py`); they are not yet part of the chat flow.

### Planned

- Wire tier 3 into the chat loop with hybrid retrieval scoring — `0.6 * similarity + 0.2 * recency + 0.2 * importance`. The `memories` table also becomes the durable conversation archive (closing the "lost after the 2h TTL" gap).
- **Brain-hub graph view** — explorable Obsidian-style visualization of facts and their relationships.
- Session resume, cache-miss fallback, production Docker variant.

### Explicit non-goals (for now)

Voice systems, avatars, autonomous agents, multi-agent orchestration. The scope is the memory architecture, not breadth of features.

---

## Why this isn't just a chatbot wrapper

If you call any LLM API directly, the model has *zero* recollection of any prior conversation. The illusion of memory in any AI product comes from the *application* — the system that:

1. **Stores** information somewhere
2. **Selects** what's relevant for the current request
3. **Injects** it into the prompt

That's the whole game. RAG, persistent preferences, citations, tool use — every one of them is just "decide what goes in the prompt, then put it there."

BD-42 takes that seriously. The chat loop is a thin orchestrator (`main.py`). The real engineering lives in:

- `services/context_builder.py` — assembles a structured context dict from persona + multi-tier memory, then renders it for whichever LLM API the request is hitting.
- `services/fact_extractor.py` — after each turn, mines the user's message for persistent facts. A cheap first-person regex **gate** decides whether the message could even contain a self-fact; if it can't (a question, a reaction), the LLM is skipped entirely. When the gate passes, an LLM call returns a structured list of facts — multi-fact, categorized, importance-scored.
- `memory.py` — separate Redis keyspaces for the two tiers, with deliberately different lifespans (`LTRIM` + `EXPIRE` for chat, neither for facts).

For the full architectural walkthrough, see the [`learning/`](learning/) docs — a numbered series covering the backend, the frontend, the end-to-end message flow, and a fact-extractor debugging exercise with its solution.

---

## Architecture

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
   │   • get_history          │ ── Redis ──→  recent turns (TTL 2h, last 12)
   │   • get_facts            │ ── Redis ──→  long-term facts (no TTL)
   │   • assemble prompt      │
   └────────┬─────────────────┘
            │
            ▼
   ┌──────────────────┐
   │   LLM call       │ ── OpenAI / OpenRouter (provider-pluggable)
   └────────┬─────────┘
            │   reply text
            ▼
   ┌──────────────────────────┐
   │  persist + extract       │
   │   • save user turn       │ ── Redis (chat keyspace)
   │   • save assistant turn  │ ── Redis (chat keyspace)
   │   • extract_fact()       │ ── first-person gate → LLM (multi-fact)
   │   • if facts: save_fact  │ ── Redis (facts keyspace)
   └────────┬─────────────────┘
            │
            ▼
        { reply, fact_captured }
```

Three-layer architecture: **handler → service → store.** A new memory layer (semantic, graph, anything else) plugs into the `dict` returned by `build_context()` without touching the HTTP handler — that's how tier 3 lands.

---

## Tech stack

| Layer            | Choice                                                           |
|------------------|------------------------------------------------------------------|
| Backend          | Python 3.12, FastAPI                                             |
| Frontend         | React 19, Vite, Tailwind CSS                                     |
| Short-term store | Redis                                                            |
| Semantic store   | PostgreSQL + pgvector (scaffolded), via `psycopg`                |
| LLM (default)    | OpenAI Responses API — `gpt-5-mini`                              |
| LLM (alt)        | OpenRouter Chat Completions                                      |
| Orchestration    | Docker Compose — postgres, redis, backend, frontend              |

---

## Running it

The whole stack is containerized. With Docker installed:

```bash
cp .env.example .env        # fill in OPENAI_API_KEY (and/or OPENROUTER_API_KEY)
docker compose up -d
```

That brings up four services:

| Service  | URL                       |
|----------|---------------------------|
| Frontend | http://localhost:5174     |
| Backend  | http://localhost:8000 — docs at `/docs` |
| Postgres | localhost:5432            |
| Redis    | localhost:6379            |

Code edits to `.py` / `.jsx` hot-reload automatically (source is volume-mounted). Rebuild with `docker compose up -d --build` after changing a `Dockerfile` or dependency manifest. Stop with `docker compose down`.

To switch LLM providers, change `MODEL_PROVIDER` at the top of `main.py`.

### Running the backend without Docker

```bash
python3.12 -m venv venv
./venv/bin/pip install -r requirements.txt
redis-server                                    # tier-1 store, required
./venv/bin/uvicorn main:app --reload
```

### Demo flow — the persistent-memory callback

The point of the project. Tell BD-42 something about yourself, chat about unrelated things, then ask something tangential later — watch it bring the earlier fact back unprompted.

```bash
curl -sX POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"Beep — my favorite game is No Man'\''s Sky."}'

curl -s http://localhost:8000/facts/demo      # confirm the fact was captured

curl -sX POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"What should I play tonight?"}'
```

---

## Repository tour

```
BD-42/
├── main.py                     # FastAPI app — POST /chat, GET /facts/{id}
├── memory.py                   # Redis adapter — tiers 1 & 2
├── personality.py              # BD-42's persona
├── services/
│   ├── context_builder.py      # prompt assembly — the seam
│   ├── fact_extractor.py       # LLM multi-fact extraction + first-person gate
│   ├── embeddings.py           # OpenAI embeddings (tier 3, not wired in)
│   └── semantic_memory.py      # pgvector adapter (tier 3, not wired in)
├── db/init_db.sql              # pgvector schema — memories table + hnsw index
├── scripts/smoke_semantic.py   # tier-3 round-trip test
├── web/                        # React + Vite + Tailwind chat UI
│   └── src/components/         # ChatPanel.jsx, FactsPanel.jsx
├── learning/                   # numbered architectural walkthroughs (01–05)
├── docker-compose.yml          # full stack
├── Dockerfile / web/Dockerfile
├── requirements.txt
└── CLAUDE.md                   # repo guidance + roadmap
```

---

## Design philosophy

A few load-bearing decisions, since they shape what the project is *not*:

**The seam matters more than the feature.** Before adding long-term memory, the codebase was refactored so `main.py` only orchestrates and `context_builder` owns all prompt assembly. Reason: the next memory layers all plug into the dict returned by `build_context()`. A good seam absorbs change without touching the surrounding handler.

**Memory has different shapes, on purpose.** Chat history is bounded, TTL'd, and allowed to forget. Facts are unbounded and never trimmed. They model fundamentally different lifespans — the same idea as a CPU cache hierarchy, or page cache vs. disk. One storage type doing everything is a smell.

**Detector, not extractor — the cheap path before the expensive one.** Fact extraction runs a cheap first-person regex *gate* before the LLM. The regex doesn't extract anything — it just detects whether a message could plausibly contain a fact about the user. Questions and reactions have no first-person reference and skip the LLM entirely. The gate is tuned for recall: a false positive wastes one call, a false negative loses a fact, so when unsure it lets the message through.

**Graceful degradation at boundaries.** Fact extraction is a *secondary* path. If it errors, the chat reply must still work — the extractor's failures are caught and swallowed so a secondary feature can never break the primary one.

---

## Roadmap

| Milestone                          | What                                                                       |
|------------------------------------|----------------------------------------------------------------------------|
| **M0 — two-tier memory**           | Done. Redis chat history + persistent facts. LLM multi-fact extractor with a first-person cost gate. |
| **M1 — semantic memory layer**     | Wire pgvector (tier 3) into the chat loop. Conversations embedded and retrieved by meaning; the table doubles as the durable archive. |
| **M2 — hybrid retrieval scoring**  | Rank candidates by `0.6 * similarity + 0.2 * recency + 0.2 * importance`; top-N survive the prompt's token budget. |
| **M3 — brain hub graph**           | A `GET /graph/{session_id}` endpoint + React Flow view. The companion-style memory interface — explorable, not a chronological chat log. |
| **M4 — durability & resume**       | Migrate facts to Postgres; session-resume endpoint; rebuild short-term context from the archive on a cache miss. |

---

## License

MIT.
