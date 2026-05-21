"""Smoke test for BD-42's semantic memory layer (phase A).

Proves the round trip: embed -> store in Postgres -> retrieve by similarity.
Run from the BD-42 directory:

    ./venv/bin/python scripts/smoke_semantic.py

Requires: Postgres reachable at DATABASE_URL with the memories table created
(db/init_db.sql), and a valid OPENAI_API_KEY in .env.
"""
import os
import sys

# Make the `services` package importable when running this file directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

import psycopg

from services.semantic_memory import clear_chunks, save_chunk, search_chunks

SESSION = "smoke-test-session"

SEED_CHUNKS = [
    ("user", "I love trekking in the Himalayas and want to do 5 treks before I turn 30."),
    ("user", "My favourite game is No Man's Sky — the calm exploration vibe."),
    ("user", "I find black holes and singularities genuinely fascinating."),
    ("assistant", "Beep — Saturn's rings are mostly icy chunks, some as small as dust."),
]

QUERIES = [
    "what outdoor adventures am I into?",
    "tell me about video games I like",
    "which physics topics interest me?",
]


def main() -> int:
    print("Clearing any old smoke-test data...")
    clear_chunks(SESSION)

    print(f"Saving {len(SEED_CHUNKS)} chunks (each makes one embedding call)...")
    for role, content in SEED_CHUNKS:
        save_chunk(SESSION, role, content)
        print(f"  + [{role}] {content[:55]}...")

    for query in QUERIES:
        print(f"\nQuery: {query!r}")
        results = search_chunks(SESSION, query, top_k=2)
        for r in results:
            print(f"  [sim {r['similarity']:.3f}] {r['content']}")

    print("\nCleaning up smoke-test data...")
    clear_chunks(SESSION)
    print("\nSmoke test PASSED — embed -> store -> semantic search all working.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except psycopg.OperationalError as e:
        print(f"\nCould not connect to Postgres: {e}")
        print("Make sure Postgres is running and DATABASE_URL is correct.")
        sys.exit(1)
    except psycopg.errors.UndefinedTable:
        print("\nThe 'memories' table does not exist.")
        print("Run the schema first:  psql \"$DATABASE_URL\" -f db/init_db.sql")
        sys.exit(1)
