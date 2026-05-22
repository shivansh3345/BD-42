"""Prompt assembly — BD-42's context seam.

Every memory tier feeds into the dict that build_context returns; the two
render_* functions turn that dict into provider-specific payloads. Adding a
memory layer means adding a key here, not touching main.py.

Tier 1 (Redis chat history) and tier 2 (Redis facts) come from memory.py.
Tier 3 (pgvector semantic memory) is retrieved here and re-ranked with a
hybrid score before the most relevant past turns are folded into the prompt.
"""
from datetime import datetime, timezone

from memory import get_history, get_facts
from personality import PERSONA
from services.semantic_memory import search_chunks, recent_chunks

# Tier-3 retrieval knobs. Pull a wide candidate pool by raw similarity, then
# re-rank it and keep only the strongest few — see _retrieve_memories.
_CANDIDATE_POOL = 12        # how many chunks search_chunks returns to re-rank
_MEMORIES_IN_PROMPT = 4     # how many survive the hybrid ranking
_RECENCY_HALFLIFE_DAYS = 7  # a memory's recency score halves every 7 days
_SIMILARITY_FLOOR = 0.18    # drop near-irrelevant chunks before ranking


def _format_history(history):
    return "\n".join(f"{m['role']}: {m['content']}" for m in history)


def _format_facts(facts):
    if not facts:
        return ""
    ranked = sorted(facts, key=lambda f: f.get("importance", 0), reverse=True)
    lines = [f"- ({f['category']}) {f['content']}" for f in ranked[:8]]
    return "\n".join(lines)


def _recency_score(created_at: datetime) -> float:
    """Map a timestamp to (0, 1] — 1.0 just now, 0.5 one half-life ago."""
    age_days = (datetime.now(timezone.utc) - created_at).total_seconds() / 86400
    return 0.5 ** (max(age_days, 0.0) / _RECENCY_HALFLIFE_DAYS)


def _hybrid_score(chunk: dict) -> float:
    """Blend semantic relevance, recency and importance into one rank key.

    Weights are fixed by the roadmap: similarity dominates, recency and
    importance nudge. All three terms are clamped to [0, 1] so the weights
    mean what they say. Pure cosine similarity would ignore "this mattered"
    and "this was recent" — the blend is why we re-rank instead of trusting
    pgvector's raw top-K.
    """
    similarity = min(max(chunk["similarity"], 0.0), 1.0)
    recency = _recency_score(chunk["created_at"])
    importance = min(max(chunk["importance"], 0.0), 1.0)
    return 0.6 * similarity + 0.2 * recency + 0.2 * importance


def _retrieve_memories(message: str, session_id: str, history: list) -> list[dict]:
    """Semantic-memory read path: pull candidates, re-rank, trim.

    Tier 3 is an enhancement, never a hard dependency — if Postgres or the
    embedding call fails, log and return [] so the chat still runs on
    tiers 1 & 2.
    """
    try:
        candidates = search_chunks(session_id, message, top_k=_CANDIDATE_POOL)
    except Exception as e:  # tier 3 must degrade, not crash the chat
        print(f"[tier3] retrieval failed, continuing without semantic memory: {e}")
        return []

    # Drop near-irrelevant chunks outright — a junk filter, not a relevance
    # gate. Cosine similarity is reliable for ranking but noisy as an
    # absolute score, so the floor is deliberately low.
    candidates = [c for c in candidates if c["similarity"] >= _SIMILARITY_FLOOR]

    # Drop chunks the live Redis history already shows — no point spending
    # prompt space on a turn the model can see verbatim a few lines down.
    recent = {m["content"] for m in history}
    candidates = [c for c in candidates if c["content"] not in recent]

    candidates.sort(key=_hybrid_score, reverse=True)
    return candidates[:_MEMORIES_IN_PROMPT]


def _format_memories(memories: list[dict]) -> str:
    if not memories:
        return ""
    speaker = {"user": "You said", "assistant": "I said"}
    return "\n".join(
        f"- {speaker.get(m['role'], m['role'])}: {m['content']}" for m in memories
    )


def build_context(message: str, session_id: str, context: dict) -> dict:
    history = get_history(session_id)
    return {
        "system": PERSONA,
        "history": _format_history(history),
        "facts": _format_facts(get_facts(session_id)),
        "memories": _format_memories(
            _retrieve_memories(message, session_id, history)
        ),
        "user_message": message,
    }


def _assemble_user_block(ctx: dict) -> str:
    sections = []
    if ctx["facts"]:
        sections.append(f"Known about user:\n{ctx['facts']}")
    if ctx["memories"]:
        sections.append(
            f"Relevant moments from earlier conversations:\n{ctx['memories']}"
        )
    sections.append(f"Conversation so far:\n{ctx['history']}")
    sections.append(f"User: {ctx['user_message']}")
    return "\n\n".join(sections)


def render_as_single_input(ctx: dict) -> str:
    return f"{ctx['system']}\n\n{_assemble_user_block(ctx)}"


def render_as_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": ctx["system"]},
        {"role": "user", "content": _assemble_user_block(ctx)},
    ]


# --- Greeting mode -----------------------------------------------------------
# A proactive welcome-back when a returning user reopens the chat. Same seam,
# a different prompt: BD-42 initiates instead of replying.
_GREETING_RECENT_TURNS = 6
_GREETING_INSTRUCTION = (
    "The user has just reopened the chat after being away — there is no new "
    "message from them yet. Open the conversation yourself: greet them by "
    "name in your voice, recall in one sentence what you were last talking "
    "about, and ask whether they want to continue that thread or start "
    "something new. Keep it short and warm; do not answer a question — there "
    "isn't one yet."
)


def build_greeting_context(session_id: str) -> dict:
    """Assemble the prompt for a proactive welcome-back greeting (tier 3).

    Reads tier-2 facts and the last few tier-3 turns so the greeting can be
    personal and name the previous topic. The caller must ensure the session
    actually has history — see main.py's /resume handler.
    """
    recent = recent_chunks(session_id, limit=_GREETING_RECENT_TURNS)
    return {
        "system": PERSONA,
        "facts": _format_facts(get_facts(session_id)),
        "last_turns": "\n".join(f"{c['role']}: {c['content']}" for c in recent),
    }


def _assemble_greeting_block(ctx: dict) -> str:
    sections = []
    if ctx["facts"]:
        sections.append(f"Known about the user:\n{ctx['facts']}")
    if ctx["last_turns"]:
        sections.append(f"Your last conversation with them:\n{ctx['last_turns']}")
    sections.append(_GREETING_INSTRUCTION)
    return "\n\n".join(sections)


def render_greeting_as_single_input(ctx: dict) -> str:
    return f"{ctx['system']}\n\n{_assemble_greeting_block(ctx)}"


def render_greeting_as_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": ctx["system"]},
        {"role": "user", "content": _assemble_greeting_block(ctx)},
    ]
