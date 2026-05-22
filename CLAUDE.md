# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What BD-42 is

BD-42 is a **persistent AI companion** — an experiment in *memory
architecture*. The product moat is how it remembers a user across
conversations, not the chat UI and not the LLM call. Inspirations: BD-1 (Star
Wars Jedi) and JARVIS — a companion, not a transactional assistant.

It is the owner's **portfolio / interview centerpiece**. Architectural
clarity and code quality are load-bearing — treat changes against the vision,
not against "make the chatbot nicer."

## Architecture

A FastAPI backend with **three memory tiers**, a React frontend, all
containerized.

```
Frontend (React/Vite)  ──HTTP──►  FastAPI handler (main.py)
                                       │
                                       ▼
                                 context_builder.py   ← the "seam"
                                       │
                          ┌────────────┼────────────┐
                          ▼            ▼            ▼
                    Redis chat   Redis facts   pgvector memories
                    (tier 1)     (tier 2)      (tier 3 — wired)
                                       │
                                       ▼
                                  LLM provider
```

**Tier 1 — short-term.** Redis `chat:<session_id>`, last 12 messages, 2h TTL.
Recent conversational context. Implemented.

**Tier 2 — long-term facts.** Redis `bd42:facts:<session_id>`, distilled
`{content, category, importance, timestamp}` records, no TTL. Implemented.

**Tier 3 — semantic episodic.** Postgres + pgvector `memories` table — every
turn embedded, retrieved by meaning; also the durable conversation archive.
**Wired into the chat flow (Phase B).** Write path: `main.py` archives both
turns after each reply. Read path: `context_builder` retrieves a candidate
pool, drops sub-0.18-similarity noise, dedupes against live history, and
re-ranks with a hybrid score (`0.6*similarity + 0.2*recency +
0.2*importance`) before folding the top 4 into the prompt. Both paths degrade
gracefully — a Postgres/embedding failure logs a `[tier3]` warning and the
chat continues on tiers 1 & 2.

**The seam:** `services/context_builder.py` owns *all* prompt assembly. New
memory layers plug into the dict it returns without touching `main.py`. This
is deliberate — and it paid off: tier 3's read path landed entirely inside
the seam, leaving the handler untouched. Only archival (a write) touches
`main.py`, alongside `save_message`.

## Repo layout

```
BD-42/
├── main.py                 # FastAPI app: POST /chat, POST /resume, GET /facts
├── memory.py               # Redis adapter — tiers 1 & 2
├── personality.py          # BD-42's persona (the owner's creative territory)
├── services/
│   ├── context_builder.py  # prompt assembly — the seam
│   ├── fact_extractor.py    # LLM-only fact extraction + first-person gate
│   ├── embeddings.py        # OpenAI embeddings (tier 3)
│   └── semantic_memory.py   # pgvector adapter (tier 3)
├── db/init_db.sql          # pgvector schema (memories table + hnsw index)
├── scripts/smoke_semantic.py  # tier-3 round-trip test (passing)
├── web/                    # React 19 + Vite + Tailwind chat UI
│   └── src/components/     # ChatPanel.jsx, FactsPanel.jsx
├── learning/               # numbered learning docs (01–05) — see below
├── docker-compose.yml      # full stack: postgres, redis, backend, frontend
├── Dockerfile, web/Dockerfile
├── requirements.txt
└── SESSION_HANDOFF.md      # current sprint state — read for tactical detail
```

The `learning/` docs are written for the owner (who uses this project to
learn). `01-foundations` (backend), `02-frontend-foundations` (React),
`03-message-flow` (end-to-end trace), `04-fact-extractor-exercise` +
`05-fact-extractor-solved` (a debugging exercise and its solution).

## Running it

```bash
docker compose up -d        # postgres, redis, backend :8000, frontend :5174
docker compose logs -f backend
docker compose down
```

- Code edits to `.py` / `.jsx` hot-reload (source is volume-mounted; uvicorn
  `--reload` and Vite HMR pick them up). No restart needed.
- `requirements.txt` / `package.json` / Dockerfile changes need
  `docker compose up -d --build`.
- `.env` changes need a container restart (env is read at container start).

## Current state

**Implemented:** `/chat`, `/resume`, `/facts` endpoints; all three memory
tiers — tiers 1 & 2 (Redis) and tier 3 (pgvector semantic memory, wired into
the chat loop with hybrid retrieval + per-turn archival); session resume —
`POST /resume/{session_id}` reopens a chat as `restore` (warm Redis → silent
transcript), `greeting` (cold Redis but tier-3 history → a proactive
welcome-back, saved to tier 1 only), or `fresh`; LLM-only fact extraction
with a first-person pre-gate (returns a list — multi-fact); `context_builder`
seam; multi-provider LLM (OpenAI Responses API + OpenRouter); React chat UI
with a toggleable facts panel; full Docker stack.

**Next:** see roadmap — tighten fact extraction (traits vs. topics), then the
cache-miss fallback (rebuild cold tier-1 context from pgvector).

**Anti-goals (do not build):** voice, avatars, autonomous agents,
multi-agent systems, mobile apps.

## Roadmap & ideas discussed

Rough priority order:

1. **Tighten fact extraction — traits vs. topics.** The extractor currently
   mints a tier-2 fact from topical *questions* ("How does X relate to Y?"
   → "interested in X↔Y" at importance 0.9), conflating *what was discussed*
   with *durable traits of the person* — tier 2 should hold only the latter.
   Fix: have the extractor prompt distinguish an assertion ("I am interested
   in X" → fact) from a request ("explain X" → not a fact). Topics belong in
   the brain hub (item 4), not the facts list.
2. **Cache-miss fallback** — when Redis `chat:` is cold (TTL expired), rebuild
   short-term context from pgvector by timestamp. Makes the 2h TTL a cache
   eviction, not a memory wipe.
3. **Migrate tier-2 facts from Redis → Postgres** now that tier 3 has landed —
   one durable home for all long-term memory.
4. **Brain hub** — an Obsidian-style explorable graph: BD-42's *native*
   memory-browsing interface, deliberately **not** a ChatGPT-style
   chronological chat-history sidebar (transactional-assistant pattern; the
   graph is the companion pattern). Sharpened model: the graph is the
   *topical/episodic* layer, distinct from tier 2 — tier 2 holds durable
   facts about the *person*, the graph holds *topics discussed*. Needs no
   new store: it is a clustering + visualization layer over the tier-3
   embeddings that already exist — nodes = topic clusters (tier-3 turns
   grouped by embedding proximity), edge weight = inter-cluster semantic
   similarity, node strength = recency × frequency. The `context_builder`
   hybrid score (`0.6*sim + 0.2*recency + 0.2*importance`) already weights
   the same signals — the graph is that scoring made visible. A durable
   interest may *emerge* from a dense cluster and be promoted to a tier-2
   fact; a single question must not.
5. **Production Docker variant** — static frontend behind nginx, backend
   without `--reload`. Current compose is dev-oriented.
6. **Walkthrough video + interview talking-points doc.**
7. **Cosmic-playground integration** — BD-42's chat panel eventually embeds
   into the sibling `cosmic-playground` simulation. The persona currently
   references "observing a simulation"; the owner is reworking that framing.
8. **User-editable persona** — let a user customize their droid's
   personality so it feels personal to them. The persona splits by trust
   level into a *constant core* (system-owned: BD-42's identity — an
   intelligent space exploration droid — plus honesty/safety constraints;
   never user-editable) and a *customization layer* (user-owned: tone,
   quirks, behavioral style). Folds into the seam — `personality.py` keeps
   the core, `context_builder` merges the per-user customization, `main.py`
   untouched. Pairs with item 9: a custom persona belongs to a *user*.
   **Customization is structured** — constrained fields (tone, quirks,
   verbosity, droid name) templated into known-safe prompt fragments, not a
   free-text box. Rationale: the customization layer is untrusted input
   placed in a system prompt, so structured fields keep the prompt-injection
   / persona-poisoning surface near zero. The security layer also needs:
   validation + moderation on save, privilege separation in the prompt (the
   custom layer fenced and explicitly subordinate to identity/safety), and
   an immutable safety floor.
9. **User accounts / login** — replace the localStorage `session_id` with a
   real auth + user-identity layer so memory belongs to a *person*, not a
   browser-local session. The precondition for BD-42 being a genuinely
   persistent companion, and for a JARVIS-style "welcome back" greeting to
   mean anything. Implies a data-model shift: facts/memories re-keyed on
   `user_id`, with sessions becoming conversation threads under a user.
   Pairs naturally with item 3 (the tier-2 → Postgres migration). Priority
   and design TBD — discussion deferred. **Bundled here:** the fresh-session
   cold-open greeting — a JARVIS-style "fire it up" welcome — deferred to
   land with login, since a cold open only means something once a fresh
   session belongs to a known person.

Secondary, deferred unless needed: cheaper model/config for the extraction
call, batching K turns per extraction call, async fire-and-forget for the
per-turn embedding work (fact extraction + tier-3 archival currently run
synchronously in the request — 3 embedding calls per `/chat`).

## Persona

`personality.py` holds BD-42's voice — short, curious, observant, slightly
mischievous, reacts before explaining, occasional "beep"/"boop." **The
persona wording is the owner's creative territory.** Surface observations
about it; do not rewrite it unprompted.

## Conventions & hard rules

- **Never run git operations** (add/commit/push/pull, `gh` PR commands). The
  owner handles all git — they have dual work/personal accounts on this
  machine. Suggest commit messages as text; never execute.
- **Teach as we go.** The owner uses this project to learn (system design,
  AI/ML, Python, React). Name concepts, explain tradeoffs.
- **Plain language first** for multi-step work — walk through scope before
  decision questions.
- **Re-read a file before reviewing or asserting its contents.** Files change
  between turns. Never trust a stale read.

## Known gaps

- Tier-2 facts still live in Redis, separate from tier 3 in Postgres — long-
  term memory has two homes until the planned migration.
- Tier-3 archival is synchronous: each `/chat` makes 3 embedding calls (1 for
  retrieval, 2 for archival) inside the request. Fine at current scale;
  async fire-and-forget is the deferred fix.
- No automated tests, linter, or formatter configured.
- `MODEL_PROVIDER` is a hardcoded constant in `main.py`; the OpenRouter
  branch is less exercised than the OpenAI one.
