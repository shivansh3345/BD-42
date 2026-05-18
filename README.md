# BD-42

A persistent AI companion experimenting with memory architecture, context engineering, and personality continuity.

> LLMs are stateless. Every API call arrives cold — the model has no memory of any prior conversation. Anything that *feels* like memory in an AI product is something the surrounding system manufactures by curating what goes into each prompt. BD-42 is an experiment in doing that well.

Inspired by BD-1 (Star Wars Jedi: Survivor) and JARVIS — a companion AI rather than a transactional assistant. The product moat is the memory architecture, not the LLM call or the chat UI.

---

## Status

**MVP scaffolding.** Production-grade architecture, demo-grade depth. The seam is built; the planned layers plug into it cleanly.

### Implemented

- FastAPI `POST /chat` endpoint with multi-provider LLM support (OpenAI Responses API + OpenRouter Chat Completions)
- **Two-tier memory** backed by Redis:
  - Short-term: conversation history per `session_id`, 12-message window, 2-hour TTL
  - Long-term: persistent facts extracted from user messages, separate keyspace, no TTL
- **Hybrid fact extraction** — regex patterns first (cheap path), LLM fallback for cases regex misses
- **Context builder service** that assembles persona + facts + history + simulation context into the prompt, provider-agnostic
- BD-42 persona: curious, observant, slightly mischievous, beep/boop

### Planned

- **Semantic memory layer** — pgvector + embeddings, hybrid retrieval scored as `0.6 * similarity + 0.2 * recency + 0.2 * importance`
- **Brain-hub graph view** — explorable Obsidian-style visualization of facts and their relationships
- **Memory extraction improvements** — real importance scoring, category metadata, async pipeline

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

- `services/context_builder.py` — assembles a structured context dict from persona + multi-tier memory + simulation state, then renders it for whichever LLM API the request is hitting.
- `services/fact_extractor.py` — after each turn, mines the user's message for persistent facts using a regex-first / LLM-fallback hybrid. The cheap path catches obvious shapes (`my favorite X is Y`, `I love Z`, `I'm a/an X`); the LLM fallback handles ambiguity. Most user turns hit zero API calls in the extractor.
- `memory.py` — separate Redis keyspaces for the two tiers, with deliberately different lifespans (`LTRIM` + `EXPIRE` for chat, neither for facts).

For the full architectural walkthrough — including the **seven-stop tour** of why each piece exists and what it costs — see [`learning/01-foundations.md`](learning/01-foundations.md).

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
   │   • extract_fact()       │ ── regex → LLM fallback
   │   • if hit: save_fact    │ ── Redis (facts keyspace)
   └────────┬─────────────────┘
            │
            ▼
        { reply, fact_captured }
```

Three-layer architecture: **handler → service → store.** A new memory layer (semantic, graph, anything else) plugs into the `dict` returned by `build_context()` without touching the HTTP handler.

---

## Tech stack

| Layer            | Choice                                                           |
|------------------|------------------------------------------------------------------|
| Language         | Python 3.12                                                      |
| HTTP framework   | FastAPI                                                          |
| Short-term store | Redis                                                            |
| LLM (default)    | OpenAI Responses API — `gpt-5-mini` with `reasoning.effort=low`  |
| LLM (alt)        | OpenRouter Chat Completions — any model exposed via OpenRouter   |
| Planned          | PostgreSQL + pgvector (semantic memory), React Flow (brain hub)  |

---

## Running locally

### Prerequisites

- Python 3.12
- Redis (running on `localhost:6379` — adjust in `memory.py` if needed)
- OpenAI API key OR OpenRouter API key

### Setup

```bash
# 1. Redis (required runtime dependency)
redis-server                              # or: docker run -p 6379:6379 redis

# 2. Virtualenv + dependencies
python3.12 -m venv venv
./venv/bin/pip install fastapi uvicorn pydantic openai python-dotenv redis

# 3. Configure secrets
echo 'OPENAI_API_KEY=sk-...' > .env       # or OPENROUTER_API_KEY=...

# 4. Run the API
./venv/bin/uvicorn main:app --reload
```

Endpoint at `http://127.0.0.1:8000/chat`; interactive docs at `/docs`.

To switch providers, change `MODEL_PROVIDER` at the top of `main.py` from `"openai"` to `"openrouter"`.

### Web UI (optional)

A minimal React chat client lives in `web/`. Run it alongside the backend.

```bash
cd web
npm install
npm run dev
```

Opens at `http://localhost:5174`. Auto-generates a session ID (persisted in `localStorage`), shows fact-capture indicators below assistant messages when the extractor hits, and has a toggleable "Known about you" panel that fetches `/facts/{session_id}` so you can watch the memory accumulate in real time.

The backend has CORS enabled for `localhost:5173` and `localhost:5174` out of the box.

### Demo flow — the persistent-memory callback

The point of the project. Tell BD-42 a preference; keep chatting about unrelated things; ask BD-42 something tangential later. Watch it bring the preference back unprompted.

```bash
# Drop a fact
curl -sX POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"Beep — my favorite game is No Man'\''s Sky."}'
# Response includes `fact_captured` if extraction hit

# Verify it landed
curl -s http://127.0.0.1:8000/facts/demo

# A few unrelated turns later...
curl -sX POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"session_id":"demo","message":"What should I play tonight?"}'
# BD-42 brings No Man's Sky back unprompted
```

---

## Repository tour

```
BD-42/
├── main.py                          # FastAPI app, /chat handler, /facts/{id}
├── personality.py                   # BD-42 persona — single source of truth
├── memory.py                        # Redis adapter: chat history + facts (two-tier)
├── services/
│   ├── __init__.py
│   ├── context_builder.py           # prompt assembly (provider-agnostic)
│   └── fact_extractor.py            # hybrid regex → LLM fact mining
├── web/                             # React + Vite + Tailwind chat UI
│   ├── src/
│   │   ├── App.jsx                  # layout shell + session/facts state
│   │   ├── components/
│   │   │   ├── ChatPanel.jsx        # message list, composer, fact-capture indicator
│   │   │   └── FactsPanel.jsx       # toggleable 'Known about you' panel
│   │   └── ...
│   └── package.json
├── learning/
│   └── 01-foundations.md            # architectural walkthrough — read this for the why
├── CLAUDE.md                        # guidance for Claude Code sessions on this repo
├── README.md                        # this file
└── .gitignore
```

---

## Design philosophy

A few load-bearing decisions worth calling out, since they shape what the project is *not*:

**The seam matters more than the feature.** Before adding long-term memory, the codebase was refactored so that `main.py` only orchestrates and a `context_builder` service owns all prompt assembly. Reason: the *next three* features (semantic memory, hybrid retrieval scoring, brain-hub graph) all plug into the dict returned by `build_context()`. A good seam absorbs change without touching the surrounding handler.

**Memory has two shapes, on purpose.** Chat history is bounded, TTL'd, and allowed to forget. Facts are unbounded, no TTL, and never trimmed. They're modeling fundamentally different lifespans — same idea as a CPU cache hierarchy or page cache vs. disk. One storage type doing everything is a smell.

**Cheap path before expensive path.** Fact extraction tries regex before calling the LLM. Most user turns contain no fact at all — the LLM-everywhere approach would burn an API call per turn for a 5% hit rate. The cascade is the same pattern as CDN edge → origin, L1 cache → RAM, query cache → table scan.

**Graceful degradation at boundaries.** Fact extraction is a *secondary* path. If it errors, the chat reply must still work. The `try/except` around the LLM fallback in `services/fact_extractor.py` exists for exactly this reason — primary path must not fail because of a secondary feature.

---

## Roadmap

| Milestone                                 | What                                                                       |
|-------------------------------------------|----------------------------------------------------------------------------|
| **M0 — two-tier memory**                  | Done. Redis-backed chat history + persistent facts. Hybrid extractor.       |
| **M1 — semantic memory layer**            | pgvector + embeddings. Recent conversations get embedded and retrieved by similarity. |
| **M2 — hybrid retrieval scoring**         | Combine similarity + recency + importance into a single rank. Top-N items survive the token budget. |
| **M3 — brain hub graph**                  | Read-only `GET /graph/{session_id}` + React Flow component on the frontend. Visualize facts and their relationships. |
| **M4 — extraction improvements**          | Real importance scoring from the LLM extractor, category taxonomy, async pipeline so the extractor never blocks chat reply latency. |

---

## License

MIT (or update to your preference).
