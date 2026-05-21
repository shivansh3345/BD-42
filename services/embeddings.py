"""OpenAI embedding wrapper for BD-42's semantic memory layer.

Single responsibility: turn text into a vector. Uses text-embedding-3-small
(1536 dimensions) — small, cheap (~$0.02 / 1M tokens), and good enough for
chat-memory retrieval. See learning/03-message-flow.md for the reasoning.
"""
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    # Lazy so importing this module never requires the API key to be set —
    # matters for tests and for tooling that imports but doesn't embed.
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def embed_text(text: str) -> list[float]:
    """Return the embedding vector (length EMBEDDING_DIM) for a piece of text."""
    response = _get_client().embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    return response.data[0].embedding
