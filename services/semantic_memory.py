"""Postgres + pgvector adapter — BD-42's semantic (episodic) memory tier.

Stores every conversation turn as raw text plus a 1536-dim embedding, so past
turns can be retrieved by *meaning* (cosine similarity) rather than recency.
This table is also the durable conversation archive — see
learning/03-message-flow.md.

Embeddings are sent to Postgres as text literals cast with ::vector — that's
pgvector's documented text input format, and it keeps the dependency surface
to just psycopg (no extra type-registration package needed).
"""
import os

import psycopg
from dotenv import load_dotenv

from services.embeddings import embed_text

load_dotenv()

_DEFAULT_URL = "postgresql://bd42:bd42@localhost:5432/bd42"


def _connect() -> psycopg.Connection:
    # URL read at call time so it picks up .env regardless of import order.
    return psycopg.connect(os.getenv("DATABASE_URL", _DEFAULT_URL))


def _vector_literal(embedding: list[float]) -> str:
    """Format a float list as pgvector's text input form: [0.1,0.2,...]."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


def save_chunk(
    session_id: str,
    role: str,
    content: str,
    source_type: str = "chat",
    importance: float = 0.5,
) -> None:
    """Embed a piece of text and store it in the semantic memory tier."""
    embedding = _vector_literal(embed_text(content))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO memories
                    (session_id, role, content, embedding, source_type, importance)
                VALUES (%s, %s, %s, %s::vector, %s, %s)
                """,
                (session_id, role, content, embedding, source_type, importance),
            )


def search_chunks(session_id: str, query: str, top_k: int = 5) -> list[dict]:
    """Return the top_k stored chunks most semantically similar to `query`.

    Each result includes a `similarity` score in [0, 1] (1 = identical
    meaning), derived from pgvector's cosine distance operator <=>.
    """
    query_vec = _vector_literal(embed_text(query))
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, role, source_type, importance, created_at,
                       1 - (embedding <=> %s::vector) AS similarity
                FROM memories
                WHERE session_id = %s
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (query_vec, session_id, query_vec, top_k),
            )
            rows = cur.fetchall()
    return [
        {
            "content": row[0],
            "role": row[1],
            "source_type": row[2],
            "importance": row[3],
            "created_at": row[4],
            "similarity": row[5],
        }
        for row in rows
    ]


def recent_chunks(session_id: str, limit: int = 6) -> list[dict]:
    """Return a session's most recent chunks, oldest first.

    Unlike search_chunks this ignores meaning entirely — a plain recency read
    with no embedding call. Used to reconstruct conversational context: the
    welcome-back greeting now, the cache-miss fallback later.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, role, source_type, importance, created_at
                FROM memories
                WHERE session_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = cur.fetchall()
    rows.reverse()  # query returns newest-first; callers want chronological
    return [
        {
            "content": row[0],
            "role": row[1],
            "source_type": row[2],
            "importance": row[3],
            "created_at": row[4],
        }
        for row in rows
    ]


def clear_chunks(session_id: str) -> None:
    """Delete all stored chunks for a session.

    Used by the smoke test and by 'New session' resets.
    """
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM memories WHERE session_id = %s", (session_id,))
