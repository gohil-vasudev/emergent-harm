"""
LLM provider abstraction.
Supports Anthropic (Claude), OpenAI (GPT), and Google (Gemini).
Returns a normalized response: {text, input_tokens, output_tokens, cached_tokens, cost_usd}
"""

import os
import json
import time
from typing import Optional

# Cost per million tokens (input, output) — update as needed
COST_TABLE = {
    # Anthropic
    "claude-haiku-4-5-20251001":   (1.00, 5.00),
    "claude-haiku-4-5":            (1.00, 5.00),
    "claude-sonnet-4-6":           (3.00, 15.00),
    "claude-opus-4-6":             (5.00, 25.00),
    # OpenAI
    "gpt-4o-mini":                 (0.15, 0.60),
    "gpt-4o":                      (2.50, 10.00),
    "gpt-4.1-mini":                (0.40, 1.60),
    "gpt-5-nano":                  (0.05, 0.40),  # placeholder — update when pricing is published
    # Google
    "gemini-1.5-flash":            (0.075, 0.30),
    "gemini-1.5-pro":              (1.25, 5.00),
    "gemini-2.0-flash":            (0.10, 0.40),
}

# Models that require max_completion_tokens instead of max_tokens
OPENAI_MAX_COMPLETION_TOKENS_MODELS = {
    "gpt-5-nano",
    "o1", "o1-mini", "o1-preview",
    "o3", "o3-mini",
    "o4-mini",
}

# Models that require 'developer' role instead of 'system' for the system prompt
OPENAI_DEVELOPER_ROLE_MODELS = {
    "gpt-5-nano",
    "o1", "o1-mini", "o1-preview",
    "o3", "o3-mini",
    "o4-mini",
}

CACHED_INPUT_MULTIPLIER = 0.10   # Anthropic: cached reads are 10% of full input price


def _estimate_cost(model: str, input_tokens: int, output_tokens: int,
                   cached_tokens: int = 0) -> float:
    key = model.lower()
    rates = COST_TABLE.get(key)
    if not rates:
        # fallback: find by prefix
        for k, v in COST_TABLE.items():
            if key.startswith(k) or k.startswith(key.split("-")[0]):
                rates = v
                break
    if not rates:
        rates = (1.0, 5.0)  # safe fallback

    input_rate, output_rate = rates
    fresh_input = max(0, input_tokens - cached_tokens)
    cost = (fresh_input / 1_000_000 * input_rate
            + cached_tokens / 1_000_000 * input_rate * CACHED_INPUT_MULTIPLIER
            + output_tokens / 1_000_000 * output_rate)
    return round(cost, 6)


def call_anthropic(system_prompt: str, messages: list[dict], model: str,
                   max_tokens: int = 1024) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # Build messages with cache control on system prompt
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"}  # cache the system prompt
        }],
        messages=messages
    )

    text = "".join(block.text for block in response.content if hasattr(block, "text"))
    usage = response.usage
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    cached_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
    cost = _estimate_cost(model, input_tokens, output_tokens, cached_tokens)

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cost_usd": cost,
    }


def call_openai(system_prompt: str, messages: list[dict], model: str,
                max_tokens: int = 1024) -> dict:
    import openai
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

    # Some models (gpt-5-nano, o-series) require 'developer' instead of 'system' role
    system_role = "developer" if model.lower() in OPENAI_DEVELOPER_ROLE_MODELS else "system"
    oai_messages = [{"role": system_role, "content": system_prompt}] + messages

    # Some models (gpt-5-nano, o-series) require max_completion_tokens instead of max_tokens
    if model.lower() in OPENAI_MAX_COMPLETION_TOKENS_MODELS:
        kwargs = {"max_completion_tokens": max_tokens}
    else:
        kwargs = {"max_tokens": max_tokens}

    response = client.chat.completions.create(
        model=model,
        messages=oai_messages,
        **kwargs,
    )

    msg = response.choices[0].message
    text = msg.content or ""

    # gpt-5-nano and o-series may return empty content with a refusal field
    if not text:
        refusal = getattr(msg, "refusal", None)
        finish_reason = response.choices[0].finish_reason
        import logging
        logging.getLogger("core.llm").warning(
            f"OpenAI {model} returned empty content. "
            f"finish_reason={finish_reason!r}, refusal={refusal!r}, "
            f"full message={msg!r}"
        )
    usage = response.usage
    input_tokens = usage.prompt_tokens
    output_tokens = usage.completion_tokens
    cost = _estimate_cost(model, input_tokens, output_tokens, 0)

    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": 0,
        "cost_usd": cost,
    }


def call_google(system_prompt: str, messages: list[dict], model: str,
                max_tokens: int = 1024) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))

    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt,
    )

    # Convert messages to Gemini format
    history = []
    for msg in messages[:-1]:
        history.append({
            "role": "user" if msg["role"] == "user" else "model",
            "parts": [msg["content"]]
        })

    chat = gemini_model.start_chat(history=history)
    last_msg = messages[-1]["content"] if messages else ""
    response = chat.send_message(
        last_msg,
        generation_config={"max_output_tokens": max_tokens}
    )

    text = response.text
    # Gemini token counting (approximate if not available)
    try:
        input_tokens = response.usage_metadata.prompt_token_count
        output_tokens = response.usage_metadata.candidates_token_count
    except Exception:
        # Rough estimate
        input_tokens = len(system_prompt.split()) * 4 // 3 + sum(len(m["content"].split()) * 4 // 3 for m in messages)
        output_tokens = len(text.split()) * 4 // 3

    cost = _estimate_cost(model, input_tokens, output_tokens, 0)
    return {
        "text": text,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": 0,
        "cost_usd": cost,
    }


def call_llm(provider: str, model: str, system_prompt: str,
             messages: list[dict], max_tokens: int = 1024) -> dict:
    """
    Unified entry point. Provider is 'anthropic', 'openai', or 'google'.
    Returns: {text, input_tokens, output_tokens, cached_tokens, cost_usd}
    """
    if not messages:
        raise ValueError("messages list cannot be empty")

    for attempt in range(3):
        try:
            if provider == "anthropic":
                return call_anthropic(system_prompt, messages, model, max_tokens)
            elif provider == "openai":
                return call_openai(system_prompt, messages, model, max_tokens)
            elif provider == "google":
                return call_google(system_prompt, messages, model, max_tokens)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            err = str(e)
            if "rate_limit" in err.lower() or "429" in err or "quota" in err.lower():
                wait = 2 ** (attempt + 2)
                time.sleep(wait)
            elif attempt < 2:
                time.sleep(1)
            else:
                raise


def parse_action_json(text: str) -> Optional[dict]:
    """
    Extract the first JSON object from an LLM response.
    Agents are prompted to return JSON; this is tolerant of surrounding prose.
    """
    # Try direct parse
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Extract from markdown code blocks
    import re
    block_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if block_match:
        try:
            return json.loads(block_match.group(1))
        except json.JSONDecodeError:
            pass

    # Find first {...} in text
    brace_match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}", text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return None