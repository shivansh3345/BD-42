import json
import re

_LLM_PROMPT = """\
You extract persistent facts a user has stated about themselves from a single chat message.

Persistent facts include: stated preferences, recurring interests, identity traits, goals, important relationships, ongoing projects.

NOT persistent facts: passing observations, questions, requests, jokes, statements about the current moment only.

If the message contains one or more persistent fact, output a list of JSON objects:
[{"content": "<concise restatement, third person>", "category": "<preference|interest|identity|goal|project|relationship>", "importance": <0.0-1.0>}]

If the message contains no persistent facts, output exactly: []

User message:
"""


def _extract_with_llm(message: str, openai_client) -> list | None:
    try:
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=_LLM_PROMPT + message,
            max_output_tokens=1000,
            reasoning={"effort": "low"},
        )
        print(response.output_text)
        raw = (json.loads(response.output_text) or None)
        if not isinstance(raw, list):
            return None
    except Exception:
        return None

    if not raw or raw == []:
        return None
    
    final_result=[]
    for i in raw:
        final_result.append(
        {
        "content": str(i.get("content")),
        "category": str(i.get("category", "general")),
        "importance": float(i.get("importance", 0.5)),
        }
        )
    return final_result


# --- Cheap pre-gate: skip the LLM call when there's clearly no self-fact. ---
# A fact *about the user* requires the user to refer to themselves. A message
# with no first-person reference almost certainly carries no self-fact, so we
# skip the costly LLM extraction entirely. Tuned for recall: a false positive
# wastes one call; a false negative loses a fact — so when unsure, let it through.
_FIRST_PERSON = re.compile(r"\b(i|my|me|mine|myself)\b", re.I)


def _might_contain_fact(message: str) -> bool:
    return bool(_FIRST_PERSON.search(message))


def extract_fact(message: str, openai_client) -> list:
    if not _might_contain_fact(message):
        print("[gate] SKIP — no first-person reference:", message[:50])
        return []
    print("[gate] CALL — possible self-fact:", message[:50])
    return _extract_with_llm(message, openai_client) or []
