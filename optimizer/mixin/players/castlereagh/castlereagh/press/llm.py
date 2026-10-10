"""The LLM side: model through the Coworld sidecar, per-call logging, one agent wake.

The only LLM path is COWORLD_LLM_ENDPOINT (the per-pod sidecar; locally, an emulator such
as the lab's `tools/llm_sidecar_local.py`). Requests are non-streaming OpenAI chat
completions through pydantic-ai. The model is COWORLD_LLM_MODEL (fixed per uploaded policy
version), with config.PRESS_MODEL as the local default.

pydantic-ai is imported lazily, so the search and gunboat modes run without it.
"""

import json
import os
import threading
from pathlib import Path

from castlereagh import config

HERE = Path(__file__).resolve().parent
SPEND_HEADER = "x-coworld-spend-usd"


def llm_available():
    return bool(os.environ.get("COWORLD_LLM_ENDPOINT"))


def model_name():
    return os.environ.get("COWORLD_LLM_MODEL") or config.PRESS_MODEL


def model_settings(name):
    """Request settings for `name`: PRESS_* defaults with the first matching MODEL_QUIRKS entry applied.

    Returns (settings dict for pydantic-ai, the effective values for the log)."""
    effective = {"PRESS_TEMPERATURE": config.PRESS_TEMPERATURE, "PRESS_REASONING": config.PRESS_REASONING,
                 "PRESS_MAX_TOKENS": config.PRESS_MAX_TOKENS}
    for fragment, quirk in config.MODEL_QUIRKS:
        if fragment in name:
            effective.update(quirk)
            break
    settings = {"max_tokens": effective["PRESS_MAX_TOKENS"]}
    if effective["PRESS_TEMPERATURE"] is not None:
        settings["temperature"] = effective["PRESS_TEMPERATURE"]
    if effective["PRESS_REASONING"]:
        settings["extra_body"] = {"reasoning": {"effort": effective["PRESS_REASONING"]}}
    return settings, effective


def build_model(log, ledger, tracker):
    """OpenAI-compatible model on the sidecar. Every request and response is logged.

    `tracker` is the player's {"wake": id, "logged": n} dict. A request logs only the messages
    not yet logged in this wake (the first request of a wake carries the briefing; later ones
    carry the assistant turns and tool results since), so the log reconstructs every
    conversation without repeating it. The system prompt is logged once, at press_start."""
    import httpx2
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    async def record_request(request):
        try:
            body = json.loads(request.content or b"{}")
        except ValueError:
            return
        messages = body.get("messages") or []
        fresh = messages[tracker["logged"]:]
        tracker["logged"] = len(messages)
        fresh = [{"role": "system", "content": "(system prompt: see press_start)"} if m.get("role") == "system" else m
                 for m in fresh]
        log(event="llm_request", wake=tracker["wake"], model=body.get("model"), messages=fresh)

    async def record(response):
        await response.aread()
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        usage = body.get("usage") or {}
        call = {"status": response.status_code, "model": body.get("model"),
                "prompt_tokens": usage.get("prompt_tokens") or 0,
                "completion_tokens": usage.get("completion_tokens") or 0,
                "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0,
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                "cost_usd": float(usage.get("cost") or 0.0),
                "sidecar_spend_usd": response.headers.get(SPEND_HEADER)}
        if response.status_code != 200:
            call["error"] = (body.get("error") or {}).get("message")
        ledger.append(call)
        reply = ((body.get("choices") or [{}])[0] or {}).get("message")
        log(event="llm_call", wake=tracker["wake"], generation_id=body.get("id"), reply=reply, **call)

    client = httpx2.AsyncClient(event_hooks={"request": [record_request], "response": [record]},
                                timeout=config.PRESS_CALL_TIMEOUT_S)
    endpoint = os.environ["COWORLD_LLM_ENDPOINT"].rstrip("/")
    # The sidecar ignores the auth header; the SDK still wants a key.
    provider = OpenAIProvider(base_url=endpoint + "/v1", api_key="coworld-sidecar", http_client=client)
    return OpenAIChatModel(model_name(), provider=provider)


def system_prompt(soul):
    soul_text = (HERE / "souls" / soul / "SOUL.md").read_text()
    harness = (HERE / "HARNESS.md").read_text()
    skills = []
    for path in sorted((HERE / "skills").glob("*/SKILL.md")):
        first = path.read_text().split("\n", 3)
        description = next((line[len("description:"):].strip() for line in first
                            if line.startswith("description:")), "")
        skills.append(f"- {path.parent.name}: {description}")
    return f"{soul_text}\n\n{harness}\n\n## Skills (load with read_skill)\n" + "\n".join(skills)


def make_agent(model, soul, tools):
    from pydantic_ai import Agent

    settings, _ = model_settings(model_name())
    return Agent(model, instructions=system_prompt(soul), tools=tools, model_settings=settings, retries=2)


def run_wake(agent, prompt, seconds, request_limit):
    """One agent run with a request cap and a wall-clock limit. Returns (final text, status)."""
    from pydantic_ai import CancellationToken
    from pydantic_ai.exceptions import RunCancelled, UsageLimitExceeded
    from pydantic_ai.usage import UsageLimits

    token = CancellationToken()
    timer = threading.Timer(seconds, token.cancel)
    timer.start()
    try:
        result = agent.run_sync(prompt, usage_limits=UsageLimits(request_limit=request_limit),
                                cancellation_token=token)
        return str(result.output), "ok"
    except RunCancelled:
        return "", "time_limit"
    except UsageLimitExceeded:
        return "", "request_limit"
    finally:
        timer.cancel()
