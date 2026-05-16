import json
import re

_PATTERNS = [
    (re.compile(r"\bmy favou?rite ([\w\s]+?) (?:is|are) (.+)", re.I), "preference"),
    (re.compile(r"\bi (?:love|adore) ([^.,!?]+)", re.I), "preference"),
    (re.compile(r"\bi (?:like|enjoy|prefer) ([^.,!?]+)", re.I), "preference"),
    (re.compile(r"\bi(?:'m| am) (?:really )?into ([^.,!?]+)", re.I), "interest"),
    (re.compile(r"\bi(?:'m| am) (?:a|an) ([^.,!?]+)", re.I), "identity"),
    (re.compile(r"\bmy name is ([^.,!?]+)", re.I), "identity"),
]

_LLM_PROMPT = """\
You extract persistent facts a user has stated about themselves from a single chat message.

Persistent facts include: stated preferences, recurring interests, identity traits, goals, important relationships, ongoing projects.

NOT persistent facts: passing observations, questions, requests, jokes, statements about the current moment only.

If the message contains a persistent fact, output a single JSON object:
{"content": "<concise restatement, third person>", "category": "<preference|interest|identity|goal|project|relationship>", "importance": <0.0-1.0>}

If the message contains no persistent fact, output exactly: null

User message:
"""


def _extract_with_patterns(message: str):
    for pattern, category in _PATTERNS:
        m = pattern.search(message)
        if m:
            phrase = " ".join(g.strip() for g in m.groups() if g)
            return {
                "content": phrase,
                "category": category,
                "importance": 0.7,
            }
    return None


def _extract_with_llm(message: str, openai_client) -> dict | None:
    try:
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=_LLM_PROMPT + message,
            max_output_tokens=120,
            reasoning={"effort": "low"},
        )
        raw = (response.output_text or "").strip()
    except Exception:
        return None

    if not raw or raw.lower() == "null":
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, dict) or "content" not in parsed:
        return None

    return {
        "content": str(parsed["content"]),
        "category": str(parsed.get("category", "general")),
        "importance": float(parsed.get("importance", 0.5)),
    }


def extract_fact(message: str, openai_client) -> dict | None:
    return _extract_with_patterns(message) or _extract_with_llm(message, openai_client)
