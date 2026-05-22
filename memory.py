import redis
import json
import time
import os

redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", "6379")),
    decode_responses=True,
)

def _key(session_id: str):
    return f"chat:{session_id}"

def _facts_key(session_id: str):
    return f"bd42:facts:{session_id}"

def save_message(session_id: str, role: str, content: str):
    key = _key(session_id)
    msg = {"role": role, "content": content}
    redis_client.rpush(key, json.dumps(msg))
    # keep only last 12 messages (6 turns)
    redis_client.ltrim(key, -12, -1)
    # expire after 2 hours (tweak later)
    redis_client.expire(key, 7200)

def get_history(session_id: str, limit: int = 12):
    key = _key(session_id)
    items = redis_client.lrange(key, -limit, -1)
    return [json.loads(x) for x in items]

def history_exists(session_id: str) -> bool:
    """True while the session's short-term chat key is still live in Redis.

    That key carries a 2h TTL, so this doubles as a "was the user here
    recently?" signal — warm means a quick return/refresh, cold means a real
    absence. The /resume endpoint uses it to choose restore vs. greeting.
    """
    return bool(redis_client.exists(_key(session_id)))

def clear_history(session_id: str):
    redis_client.delete(_key(session_id))


def save_fact(session_id: str, facts: list):
    key = _facts_key(session_id)
    for f in facts:
        fact = {
        "content": f.get("content"),
        "category": f.get("category"),
        "importance": f.get("importance"),
        "timestamp": time.time(),
        }
        redis_client.rpush(key, json.dumps(fact))

def get_facts(session_id: str, limit: int = 20):
    key = _facts_key(session_id)
    items = redis_client.lrange(key, -limit, -1)
    return [json.loads(x) for x in items]

def clear_facts(session_id: str):
    redis_client.delete(_facts_key(session_id))