import redis
import json
import time

redis_client = redis.Redis(
    host="localhost",
    port=6379,
    decode_responses=True
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

def clear_history(session_id: str):
    redis_client.delete(_key(session_id))


def save_fact(session_id: str, content: str, category: str = "general", importance: float = 0.5):
    key = _facts_key(session_id)
    fact = {
        "content": content,
        "category": category,
        "importance": importance,
        "timestamp": time.time(),
    }
    redis_client.rpush(key, json.dumps(fact))

def get_facts(session_id: str, limit: int = 20):
    key = _facts_key(session_id)
    items = redis_client.lrange(key, -limit, -1)
    return [json.loads(x) for x in items]

def clear_facts(session_id: str):
    redis_client.delete(_facts_key(session_id))