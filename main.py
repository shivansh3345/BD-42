from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

from memory import save_message, save_fact, get_facts
from services.context_builder import (
    build_context,
    render_as_single_input,
    render_as_messages,
)
from services.fact_extractor import extract_fact

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


@app.post("/chat")
def chat(req: ChatRequest):
    ctx = build_context(req.message, req.session_id, req.context)

    if MODEL_PROVIDER == "openai":
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=render_as_single_input(ctx),
            max_output_tokens=300,
            reasoning={"effort": "low"},
        )
        reply = response.output_text
        print(reply)
    else:
        response = openrouter_client.chat.completions.create(
            model="google/gemma-3-4b-it:free",
            messages=render_as_messages(ctx),
        )
        reply = response.choices[0].message.content

    save_message(req.session_id, "user", req.message)
    save_message(req.session_id, "assistant", reply)

    fact = extract_fact(req.message, openai_client)
    if fact:
        save_fact(req.session_id, fact["content"], fact["category"], fact["importance"])

    return {"reply": reply, "fact_captured": fact}


@app.get("/facts/{session_id}")
def list_facts(session_id: str):
    return {"facts": get_facts(session_id)}
