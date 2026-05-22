# BD-42 — Session Handoff (updated 2026-05-22)

A snapshot for a fresh Claude Code session. Read this top to bottom before
doing anything. The persistent memory system also auto-loads (user profile,
feedback rules, project context), and `CLAUDE.md` has the durable
architecture + roadmap. This doc is the *tactical resume point* on top of
those.

---

## How to use this doc

1. Read this whole file, then skim `CLAUDE.md` for architecture + roadmap.
2. The memory system auto-loads — trust it for collaboration rules and user
   context, but **verify every code claim against the actual files**.
   Re-read a file immediately before reviewing or asserting its contents.
3. Pick up at "Where we are RIGHT NOW."

---

## What BD-42 is

A **persistent AI companion** — the moat is the *memory architecture*, not
the chat UI or the LLM. Inspired by BD-1 and JARVIS: remembers you across
conversations. It is the owner's (Shiv — 3 yrs full-stack, Python/Node/
Angular, backend-leaning, India-based) **portfolio / interview centerpiece**,
built during a ~6-week job-hunt sprint that started 2026-05-15.

Three-tier memory: short-term (Redis chat), long-term facts (Redis),
semantic episodic (pgvector — wired into the chat loop). Full vision and
roadmap are in `CLAUDE.md`.

---

## Current state — what's built

- **Backend** (FastAPI): `POST /chat`, `POST /resume/{session_id}`,
  `GET /facts/{session_id}`. Redis memory tiers 1 & 2 (`memory.py`); pgvector
  tier 3 (`semantic_memory.py`). `context_builder.py` assembles prompts across
  all three tiers. `fact_extractor.py` — LLM-only with a first-person
  pre-gate, returns a list of facts. Multi-provider LLM.
- **Frontend** (`web/`, React 19 + Vite + Tailwind): chat UI — `ChatPanel`,
  `FactsPanel`. Updated this session to render multiple facts per message.
- **Docker:** full stack — `docker compose up -d` runs postgres (pgvector),
  redis, backend (:8000), frontend (:5174). Working.
- **pgvector / tier 3 — WIRED (Phase B).** Smoke test passed. Every `/chat`
  turn is archived to the `memories` table; `context_builder` retrieves and
  hybrid-ranks past turns into the prompt. See "Where we are RIGHT NOW".
- **Session resume — DONE.** `POST /resume/{session_id}` reopens a chat as
  `restore` / `greeting` / `fresh`; the frontend rehydrates on mount. See
  "Where we are RIGHT NOW".
- **Learning docs** (`learning/`): `01`–`05`. `04` is the fact-extractor
  exercise, `05` documents how it was solved.

---

## Where we are RIGHT NOW (the resume point)

**Session resume is COMPLETE and verified.** A page reload no longer drops
the user into an empty chat. Built this session on top of the Phase B tier-3
archive.

- **New endpoint** — `POST /resume/{session_id}` (`main.py`) returns one of
  three modes:
  - `restore` — Redis `chat:` key still warm (within the 2h TTL) → returns
    the live transcript; the frontend rehydrates it silently.
  - `greeting` — Redis cold but tier-3 history exists → BD-42 generates a
    proactive welcome-back: greets by name, recalls the last topic, asks
    continue-or-new. Saved to tier 1 ONLY — so a "yes, continue" reply has
    context — and never archived to tier 3, so a future greeting can't
    reference a past greeting.
  - `fresh` — no Redis key and no tier-3 history → empty chat.
- `history_exists()` (`memory.py`) reuses the 2h Redis TTL as the
  "was the user here recently?" signal; `recent_chunks()`
  (`semantic_memory.py`) reads tier-3 history with no embedding call.
- **The seam held again** — greeting-mode prompt assembly
  (`build_greeting_context` + greeting renderers) landed entirely inside
  `context_builder.py`; `main.py` only gained the endpoint. A shared
  `_call_llm` helper now backs both `/chat` and `/resume`.
- **Frontend** — `ChatPanel.jsx` calls `/resume` on mount, renders per mode,
  shows a "waking up" state, disables the composer while resuming, and guards
  against a stale resume response racing a new session.
- Degrades gracefully — a tier-3 failure during resume just opens a fresh chat.

**Verified:** all three modes via curl; `restore` and `greeting` confirmed
live in the browser; the greeting fuses tier-2 facts (name, goals) with the
tier-3 last topic; the greeting lands in tier 1 only (1 Redis message, not
archived to `memories`).

**Earlier this session — Phase B (tier 3 wired):** the pgvector `memories`
table is now the durable conversation archive; `context_builder` retrieves
and hybrid-ranks past turns into the prompt.

**Files changed this session (UNCOMMITTED):** `main.py`, `memory.py`,
`services/context_builder.py`, `services/semantic_memory.py`,
`web/src/components/ChatPanel.jsx` — these carry **both Phase B and session
resume**. `personality.py` also has unrelated in-progress persona
experiments. `CLAUDE.md` and this file updated to match. **Verify git state
before assuming anything is pushed.**

**Next work:** tighten fact extraction (traits vs. topics) and the cache-miss
fallback — see CLAUDE.md roadmap items 1–2.

---

## Open tasks

- #10 completed — pgvector Phase A smoke test
- #11 completed — Phase B: tier 3 wired into the chat loop (hybrid retrieval
  + per-turn archival)
- #12 pending — brain hub: topic graph over tier-3 embeddings (see CLAUDE.md
  roadmap #4 for the sharpened design)
- #14 pending — walkthrough video + talking-points doc
- #23 completed — session resume: `POST /resume` + frontend rehydrate
  (restore / greeting / fresh)
- #24 pending — cache-miss fallback: rebuild Redis short-term from pgvector
- #25 completed — Dockerize full stack
- #26 pending — tighten fact extraction: traits vs. topics (CLAUDE.md #1)
- #27 pending — user-editable persona: structured customization (CLAUDE.md #8)
- #28 pending — user accounts / login; bundles the cold-open greeting
  (CLAUDE.md #9)

---

## Future plan (rough order) — full detail in CLAUDE.md "Roadmap & ideas"

1. Tighten fact extraction — traits vs. topics (#26).
2. Cache-miss fallback (#24) — rebuild cold tier-1 context from pgvector.
3. Migrate tier-2 facts from Redis → Postgres (tier 3 has landed).
4. Brain hub (#12) — the companion-style memory graph, *not* a chat-history
   sidebar; a clustering layer over tier-3 embeddings.
5. Production Docker variant; walkthrough video (#14).
6. Cosmic-playground integration (persona's "simulation" framing reworked).
7. User-editable persona (#27) — structured customization, trust-tiered.
8. User accounts / login (#28) — real identity; bundles the cold-open greeting.

---

## How to curb hallucination (the owner explicitly flagged this)

- **Re-read a file immediately before reviewing or asserting its contents.**
  Never trust an earlier read — files change between turns (owner edits,
  linters). This session, an earlier-read `memory.py` was asserted stale and
  the owner had to correct it.
- Cite `file:line`. Verify, don't recall.
- Architectural claims must stay consistent across turns — re-check what was
  said before re-explaining (this session drifted once on Redis-vs-Postgres).
- When uncertain, say so and check. Don't fill gaps with plausible detail.
- Long sessions degrade — hand off to a fresh session when accuracy slips.

---

## Parallel tracks (NOT this session)

- **DSA prep** — separate session/track. 9-week roadmap, interview algorithm
  rounds.
- **Job search** — separate session/track. YC companies, cold email, resume.
  Lives in `../job-search/`.

---

## Hard rules (also in the memory system and CLAUDE.md)

- **Never run git operations.** The owner handles all git — dual work/personal
  accounts on this machine. Suggest commit messages; never execute.
- **BD-42's persona/voice is the owner's creative territory.** Don't rewrite
  `personality.py` wording unprompted.
- **Teach as we go.** The owner learns through this project — name concepts,
  explain tradeoffs.
- **Plain language first** for multi-step work.
