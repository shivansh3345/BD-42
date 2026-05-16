from memory import get_history, get_facts
from personality import PERSONA


def _format_history(history):
    return "\n".join(f"{m['role']}: {m['content']}" for m in history)


def _format_facts(facts):
    if not facts:
        return ""
    ranked = sorted(facts, key=lambda f: f.get("importance", 0), reverse=True)
    lines = [f"- ({f['category']}) {f['content']}" for f in ranked[:8]]
    return "\n".join(lines)


def build_context(message: str, session_id: str, sim_context: dict) -> dict:
    return {
        "system": PERSONA,
        "history": _format_history(get_history(session_id)),
        "facts": _format_facts(get_facts(session_id)),
        "sim_context": sim_context,
        "user_message": message,
    }


def _assemble_user_block(ctx: dict) -> str:
    sections = []
    if ctx["facts"]:
        sections.append(f"Known about user:\n{ctx['facts']}")
    sections.append(f"Conversation so far:\n{ctx['history']}")
    sections.append(f"Simulation context:\n{ctx['sim_context']}")
    sections.append(f"User: {ctx['user_message']}")
    return "\n\n".join(sections)


def render_as_single_input(ctx: dict) -> str:
    return f"{ctx['system']}\n\n{_assemble_user_block(ctx)}"


def render_as_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": ctx["system"]},
        {"role": "user", "content": _assemble_user_block(ctx)},
    ]
