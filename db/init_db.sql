-- BD-42 semantic memory schema.
-- If using Docker: this runs automatically on first container init
-- (mounted into /docker-entrypoint-initdb.d/).
-- If using native/managed Postgres: run it once by hand:
--   psql "<DATABASE_URL>" -f db/init_db.sql
-- Every statement is idempotent, so re-running is safe.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
    id           BIGSERIAL   PRIMARY KEY,
    session_id   TEXT        NOT NULL,
    role         TEXT        NOT NULL,                 -- 'user' | 'assistant'
    content      TEXT        NOT NULL,                 -- raw text; also the durable archive copy
    embedding    VECTOR(1536),                         -- text-embedding-3-small dimensionality
    source_type  TEXT        NOT NULL DEFAULT 'chat',  -- 'chat' | 'fact' | ... (room to grow)
    importance   REAL        NOT NULL DEFAULT 0.5,     -- used by phase B hybrid retrieval scoring
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Lookups by session: recency reads, transcript reads, clears.
CREATE INDEX IF NOT EXISTS idx_memories_session_created
    ON memories (session_id, created_at DESC);

-- Approximate-nearest-neighbour index for cosine similarity search.
-- Not strictly required at small scale (a sequential scan handles a few
-- thousand rows fine) but it's the production-shaped choice and costs
-- nothing to create on an empty table. Matches the <=> cosine operator.
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops);
