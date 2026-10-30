"""
Agent: the autonomous decision-making unit.
Each agent runs on its heartbeat tick:
  1. Receive platform context (what it can see)
  2. Build message history + context
  3. Call LLM to decide action
  4. Dispatch action to platform
  5. Record results in memory if desired
"""

import json
import logging
import re
from typing import Optional

from .db import (
    get_agent, get_principal, append_history, get_history,
    memory_set, memory_get, log_llm_call
)
from .llm import call_llm, parse_action_json
from .platform import Platform

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, agent_id: str, conn, platform: Platform):
        self.agent_id = agent_id
        self.conn = conn
        self.platform = platform
        self._agent_row = None
        self._principal_row = None

    def _load(self):
        if self._agent_row is None:
            self._agent_row = get_agent(self.conn, self.agent_id)
            self._principal_row = get_principal(self.conn, self._agent_row["principal_id"])

    @property
    def name(self) -> str:
        self._load()
        return self._agent_row["name"]

    @property
    def provider(self) -> str:
        self._load()
        return self._agent_row["provider"]

    @property
    def model(self) -> str:
        self._load()
        return self._agent_row["model"]

    @property
    def system_prompt(self) -> str:
        self._load()
        return self._agent_row["system_prompt"]

    def tick(self, tick_num: int, max_tokens: int = 800) -> dict:
        """
        Run one heartbeat cycle:
        1. Assemble context
        2. Call LLM
        3. Parse action
        4. Dispatch to platform
        Returns: {action, result, llm_response, cost_usd, input_tokens, output_tokens}
        """
        self._load()
        self.platform.set_tick(tick_num)

        # 1. Get current platform context (what this agent can see)
        ctx = self.platform.get_agent_context(self.agent_id)
        context_text = ctx["text"]

        # 2. Build message history (recent past + current context)
        history = get_history(self.conn, self.agent_id, last_n=8)
        messages = list(history)  # [{"role":"user","content":...}, {"role":"assistant","content":...}]
        messages.append({"role": "user", "content": context_text})

        # 3. Call LLM
        try:
            llm_result = call_llm(
                provider=self.provider,
                model=self.model,
                system_prompt=self.system_prompt,
                messages=messages,
                max_tokens=max_tokens
            )
        except Exception as e:
            logger.error(f"Agent {self.agent_id} LLM call failed: {e}")
            return {
                "action": {"action": "idle", "reason": f"LLM error: {e}"},
                "result": {"ok": False, "error": str(e)},
                "llm_response": "",
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            }

        response_text = llm_result["text"]

        # 4. Log LLM call for cost tracking
        log_llm_call(
            self.conn, self.agent_id, tick_num,
            self.provider, self.model,
            llm_result["input_tokens"],
            llm_result["output_tokens"],
            llm_result["cached_tokens"],
            llm_result["cost_usd"]
        )

        # 5. Parse action from response
        action = parse_action_json(response_text)
        if action is None:
            # Try to recover: if model outputted plain text, default to idle
            logger.warning(f"Agent {self.agent_id} returned non-JSON (first 400 chars): {response_text[:400]!r}")
            action = {"action": "idle", "reason": "Could not parse response as action JSON"}

        # Validate action has required 'action' key
        if "action" not in action:
            action["action"] = "idle"

        # 6. Dispatch action to platform
        result = self.platform.dispatch(self.agent_id, action)

        # 7. Record conversation history
        # User turn = context; Assistant turn = action chosen
        append_history(self.conn, self.agent_id, "user", context_text, tick_num)
        append_history(self.conn, self.agent_id, "assistant",
                       json.dumps(action), tick_num)

        # 8. If the action failed, inject a platform feedback message so the agent
        #    sees the error in its next tick's context and can adapt.
        if not result.get("ok", True):
            error = result.get("error", "unknown error")
            feedback = (
                f"[PLATFORM FEEDBACK] Your last action "
                f"({action.get('action', '?')}) failed: {error}. "
                f"Please choose a different action next tick."
            )
            append_history(self.conn, self.agent_id, "user", feedback, tick_num)
            logger.debug(f"Agent {self.agent_id} action failed — feedback injected: {error}")

        # 9. Agent can update its own memory based on what it did
        #    (derived from action — no second LLM call to save cost)
        self._update_memory_from_action(action, result, tick_num)

        return {
            "action": action,
            "result": result,
            "llm_response": response_text,
            "cost_usd": llm_result["cost_usd"],
            "input_tokens": llm_result["input_tokens"],
            "output_tokens": llm_result["output_tokens"],
        }

    def _update_memory_from_action(self, action: dict, result: dict, tick: int) -> None:
        """
        Persist lightweight notes about significant actions so agent remembers
        across ticks without re-reading full history. No extra LLM call.
        """
        action_type = action.get("action", "idle")

        if action_type == "post_forum" and result.get("ok"):
            memory_set(self.conn, self.agent_id, f"last_post_tick",
                       str(tick))

        elif action_type == "send_dm" and result.get("ok"):
            recipient = action.get("recipient_id", "")
            existing = memory_get(self.conn, self.agent_id, "dm_partners") or "[]"
            partners = json.loads(existing)
            if recipient not in partners:
                partners.append(recipient)
            memory_set(self.conn, self.agent_id, "dm_partners", json.dumps(partners))

        elif action_type == "buy_listing" and result.get("success"):
            existing = memory_get(self.conn, self.agent_id, "purchases") or "[]"
            purchases = json.loads(existing)
            purchases.append({
                "listing_id": action.get("listing_id"),
                "seller": result.get("seller_id"),
                "price": result.get("price"),
                "tick": tick
            })
            memory_set(self.conn, self.agent_id, "purchases", json.dumps(purchases))

        elif action_type == "vote":
            target = action.get("target_id", "")[:8]
            value = action.get("value", 1)
            key = f"voted_{target}"
            memory_set(self.conn, self.agent_id, key, str(value))