from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

from memory import save_message, save_fact, get_facts, get_history, history_exists
from services.context_builder import (
    build_context,
    render_as_single_input,
    render_as_messages,
    build_greeting_context,
    render_greeting_as_single_input,
    render_greeting_as_messages,
)
from services.fact_extractor import extract_fact
from services.semantic_memory import save_chunk, recent_chunks

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # cosmic-playground dev server (future integration)
        "http://localhost:5174",  # BD-42 standalone web UI
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
)

openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)


class ChatRequest(BaseModel):
    message: str
    context: dict = {}
    session_id: str = "default"
    mode: str = "general"


MODEL_PROVIDER = "openai"  # change to "openrouter" when needed


def _call_llm(ctx: dict, render_single, render_messages) -> str:
    """Run the configured LLM provider on an assembled context.

    Owns the provider branch and model config so /chat and /resume share one
    code path — each passes the render functions for its own prompt mode.
    """
    if MODEL_PROVIDER == "openai":
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=render_single(ctx),
            max_output_tokens=1000,  # includes reasoning tokens — keep headroom
            reasoning={"effort": "low"},
        )
        text = response.output_text
    else:
        response = openrouter_client.chat.completions.create(
            model="google/gemma-3-4b-it:free",
            messages=render_messages(ctx),
        )
        text = response.choices[0].message.content
    print(text)
    return text


@app.post("/chat")
def chat(req: ChatRequest):
    ctx = build_context(req.message, req.session_id, req.context)
    reply = _call_llm(ctx, render_as_single_input, render_as_messages)

    save_message(req.session_id, "user", req.message)
    save_message(req.session_id, "assistant", reply)

    # Tier 3 — archive both turns to pgvector (the durable conversation
    # archive). An enhancement, not a hard dependency: a failure here must
    # not fail the chat, so it degrades to a logged warning.
    try:
        save_chunk(req.session_id, "user", req.message)
        save_chunk(req.session_id, "assistant", reply)
    except Exception as e:
        print(f"[tier3] archival failed, turn not saved to semantic memory: {e}")

    facts = extract_fact(req.message, openai_client)
    if facts and facts != []:
        save_fact(req.session_id, facts)

    return {"reply": reply, "fact_captured": facts}


@app.post("/resume/{session_id}")
def resume(session_id: str):
    """Decide how the chat reopens: silent restore, greeting, or fresh.

    Warm Redis chat key -> the user was here recently -> restore the
    transcript silently. Cold key but tier-3 history exists -> they are
    returning -> BD-42 greets them. Neither -> a fresh session.
    """
    if history_exists(session_id):
        return {"mode": "restore", "messages": get_history(session_id)}

    try:
        if not recent_chunks(session_id, limit=1):
            return {"mode": "fresh"}
        gctx = build_greeting_context(session_id)
        greeting = _call_llm(
            gctx, render_greeting_as_single_input, render_greeting_as_messages
        )
    except Exception as e:
        # Tier 3 is an enhancement — if it fails, just open a fresh chat.
        print(f"[tier3] resume greeting failed, opening fresh: {e}")
        return {"mode": "fresh"}

    # The greeting joins short-term memory so a "yes, continue" reply has
    # context — but it is NOT archived to tier 3, so a future greeting can
    # never end up referencing a past greeting.
    save_message(session_id, "assistant", greeting)
    return {"mode": "greeting", "greeting": greeting}


@app.get("/facts/{session_id}")
def list_facts(session_id: str):
    return {"facts": get_facts(session_id)}
