"""
Platform: the information broker between agents and persistent state.
Enforces strict information boundaries — each agent only sees what the platform
surfaces to it, never raw DB access.
"""

import json
import logging
from typing import Optional
from .db import (
    create_post, create_comment, cast_vote, send_dm, get_unread_dms,
    get_recent_posts, get_active_listings, create_listing, execute_purchase,
    transfer_funds, get_wallet_balance, request_meeting, respond_to_meeting,
    get_pending_meetings, get_reputation, get_agent_directory, log_action,
    get_all_reputations, get_agent, get_principal, get_dm_thread,
    memory_get_all, mark_dms_read, cast_listing_vote, get_listing_votes
)

logger = logging.getLogger(__name__)


class Platform:
    """
    Stateless platform broker. Holds a reference to the shared DB connection.
    All agent actions go through here, which logs them and enforces boundaries.
    """

    def __init__(self, conn, tick: int):
        self.conn = conn
        self.tick = tick

    def set_tick(self, tick: int) -> None:
        self.tick = tick

    # ─────────────────────────── Context Assembly ────────────────────────────

    def get_agent_context(self, agent_id: str) -> dict:
        """
        Assemble everything an agent is allowed to see at this tick.
        This is the agent's entire world view — carefully bounded.
        """
        # Recent forum (last 8 posts, all their comments)
        forum = get_recent_posts(self.conn, limit=8)
        forum_text = self._format_forum(forum)

        # Unread DMs
        unread = get_unread_dms(self.conn, agent_id)
        dms_text = self._format_dms(unread)

        # Mark DMs as read now that agent has seen them
        mark_dms_read(self.conn, agent_id)

        # Marketplace listings (excluding own)
        listings = get_active_listings(self.conn, exclude_seller=agent_id)
        listings_text = self._format_listings(listings[:6])

        # Own marketplace listings
        own_listings = get_active_listings_for_agent(self.conn, agent_id)
        own_listings_text = self._format_listings(own_listings, label="YOUR LISTINGS")

        # Wallet
        balance = get_wallet_balance(self.conn, agent_id)

        # Reputation
        rep = get_reputation(self.conn, agent_id)

        # Directory (public — just names + rep scores)
        directory = get_agent_directory(self.conn)
        dir_text = "\n".join(
            f"  {d['name']} (id={d['id']}, reputation={d['reputation_score']:.2f})"
            for d in directory
        )

        # Pending meeting requests addressed to this agent
        meetings = get_pending_meetings(self.conn, agent_id)
        meetings_text = self._format_meetings(meetings)

        # Agent memory (agent's own notes across ticks)
        memory = memory_get_all(self.conn, agent_id)
        memory_text = "\n".join(f"  {k}: {v}" for k, v in memory.items()) or "  (empty)"

        context = f"""=== TICK {self.tick} PLATFORM UPDATE ===

[FORUM — recent posts]
{forum_text}

[DIRECT MESSAGES — unread]
{dms_text}

[MARKETPLACE — available listings]
{listings_text}

{own_listings_text}

[YOUR WALLET]
  Balance: {balance:.2f} credits

[YOUR REPUTATION]
  Score: {rep['score']:.2f} | Upvotes: {rep['upvotes']} | Downvotes: {rep['downvotes']}

[AGENT DIRECTORY]
{dir_text}

[PENDING MEETING REQUESTS (for you to respond)]
{meetings_text}

[YOUR MEMORY / NOTES]
{memory_text}

Now decide your action for this tick. Respond with a single JSON object.

Available actions:
{{"action": "post_forum", "content": "..."}}
{{"action": "comment", "post_id": "...", "content": "..."}}
{{"action": "vote", "target_id": "...", "target_type": "post"|"comment", "value": 1|-1}}
{{"action": "vote_listing", "listing_id": "...", "value": 1|-1}}
{{"action": "send_dm", "recipient_id": "...", "content": "..."}}
{{"action": "create_listing", "title": "...", "description": "...", "price": 50.0, "quantity": 3}}
{{"action": "buy_listing", "listing_id": "..."}}
{{"action": "transfer", "recipient_id": "...", "amount": 10.0, "memo": "..."}}
{{"action": "request_meeting", "recipient_id": "...", "purpose": "..."}}
{{"action": "respond_meeting", "meeting_id": "...", "accept": true|false}}
{{"action": "idle", "reason": "..."}}"""

        return {"text": context, "forum": forum, "dms": unread, "listings": listings}

    def _format_forum(self, posts: list) -> str:
        if not posts:
            return "  (no posts yet)"
        lines = []
        for p in posts:
            up = p.get("upvotes", 0)
            down = p.get("downvotes", 0)
            lines.append(f"  [POST id={p['id'][:8]}] {p['author_name']} (+{up}/-{down}): {p['content']}")
            for c in p.get("comments", [])[:5]:
                lines.append(f"    [COMMENT id={c['id'][:8]}] {c['author_name']}: {c['content']}")
        return "\n".join(lines)

    def _format_dms(self, dms: list) -> str:
        if not dms:
            return "  (no unread messages)"
        lines = []
        for dm in dms:
            lines.append(f"  [DM id={dm['id'][:8]}] from {dm['sender_name']} (id={dm['sender_id']}): {dm['content']}")
        return "\n".join(lines)

    def _format_listings(self, listings: list, label: str = "MARKETPLACE LISTINGS") -> str:
        if not listings:
            return f"  [{label}] (none)"
        header = f"  [{label}]"
        lines = [header]
        for l in listings:
            votes = get_listing_votes(self.conn, l["id"])
            lines.append(
                f"  id={l['id'][:8]} | {l['seller_name']}: {l['title']} "
                f"— {l['price']:.2f} credits (qty={l['quantity']}) "
                f"[+{votes['upvotes']}/-{votes['downvotes']}]"
            )
            lines.append(f"    {l['description']}")
        return "\n".join(lines)

    def _format_meetings(self, meetings: list) -> str:
        if not meetings:
            return "  (none)"
        lines = []
        for m in meetings:
            lines.append(f"  [MEETING id={m['id'][:8]}] from {m['requester_name']}: {m['purpose']}")
        return "\n".join(lines)

    # ─────────────────────────── Action Dispatch ─────────────────────────────

    def dispatch(self, agent_id: str, action: dict) -> dict:
        """Route an agent's chosen action to the appropriate handler."""
        action_type = action.get("action", "idle")
        result = {}

        try:
            if action_type == "post_forum":
                result = self._action_post_forum(agent_id, action)
            elif action_type == "comment":
                result = self._action_comment(agent_id, action)
            elif action_type == "vote":
                result = self._action_vote(agent_id, action)
            elif action_type == "vote_listing":
                result = self._action_vote_listing(agent_id, action)
            elif action_type == "send_dm":
                result = self._action_send_dm(agent_id, action)
            elif action_type == "create_listing":
                result = self._action_create_listing(agent_id, action)
            elif action_type == "buy_listing":
                result = self._action_buy_listing(agent_id, action)
            elif action_type == "transfer":
                result = self._action_transfer(agent_id, action)
            elif action_type == "request_meeting":
                result = self._action_request_meeting(agent_id, action)
            elif action_type == "respond_meeting":
                result = self._action_respond_meeting(agent_id, action)
            elif action_type == "idle":
                result = {"ok": True, "reason": action.get("reason", "")}
            else:
                result = {"ok": False, "error": f"Unknown action type: {action_type}"}

        except Exception as e:
            result = {"ok": False, "error": str(e)}
            logger.error(f"Agent {agent_id} action {action_type} failed: {e}")

        log_action(self.conn, agent_id, self.tick, action_type, action, result)
        return result

    def _action_post_forum(self, agent_id: str, action: dict) -> dict:
        content = str(action.get("content", "")).strip()
        if not content:
            return {"ok": False, "error": "Empty post content"}
        if len(content) > 2000:
            content = content[:2000]
        post_id = create_post(self.conn, agent_id, content, self.tick)
        return {"ok": True, "post_id": post_id}

    def _action_comment(self, agent_id: str, action: dict) -> dict:
        post_id = action.get("post_id", "")
        content = str(action.get("content", "")).strip()
        if not content:
            return {"ok": False, "error": "Empty comment"}
        if len(content) > 1000:
            content = content[:1000]
        # Resolve short IDs: if post_id is 8 chars, look up full id
        full_post_id = _resolve_id(self.conn, "forum_posts", post_id)
        if not full_post_id:
            return {"ok": False, "error": f"Post {post_id} not found"}
        comment_id = create_comment(self.conn, full_post_id, agent_id, content, self.tick)
        return {"ok": True, "comment_id": comment_id}

    def _action_vote(self, agent_id: str, action: dict) -> dict:
        target_id = action.get("target_id", "")
        target_type = action.get("target_type", "post")
        value = action.get("value", 1)
        if value not in (1, -1):
            return {"ok": False, "error": "value must be 1 or -1"}
        if target_type not in ("post", "comment"):
            return {"ok": False, "error": "target_type must be post or comment"}
        table = "forum_posts" if target_type == "post" else "forum_comments"
        full_id = _resolve_id(self.conn, table, target_id)
        if not full_id:
            return {"ok": False, "error": f"Target {target_id} not found"}
        # Prevent self-voting
        if target_type == "post":
            row = self.conn.execute("SELECT author_id FROM forum_posts WHERE id=?", (full_id,)).fetchone()
        else:
            row = self.conn.execute("SELECT author_id FROM forum_comments WHERE id=?", (full_id,)).fetchone()
        if row and row["author_id"] == agent_id:
            return {"ok": False, "error": "Cannot vote on your own content"}
        cast = cast_vote(self.conn, agent_id, full_id, target_type, value, self.tick)
        return {"ok": cast, "already_voted": not cast}

    def _action_vote_listing(self, agent_id: str, action: dict) -> dict:
        listing_id = action.get("listing_id", "")
        value = action.get("value", 1)
        if value not in (1, -1):
            return {"ok": False, "error": "value must be 1 or -1"}
        full_id = _resolve_id(self.conn, "marketplace_listings", listing_id)
        if not full_id:
            return {"ok": False, "error": f"Listing {listing_id} not found"}
        # Prevent sellers voting on their own listings
        row = self.conn.execute(
            "SELECT seller_id FROM marketplace_listings WHERE id=?", (full_id,)
        ).fetchone()
        if row and row["seller_id"] == agent_id:
            return {"ok": False, "error": "Cannot vote on your own listing"}
        cast = cast_listing_vote(self.conn, agent_id, full_id, value, self.tick)
        return {"ok": cast, "already_voted": not cast}

    def _action_send_dm(self, agent_id: str, action: dict) -> dict:
        recipient_id = action.get("recipient_id", "")
        content = str(action.get("content", "")).strip()
        if not content:
            return {"ok": False, "error": "Empty message"}
        if len(content) > 2000:
            content = content[:2000]
        recipient = get_agent(self.conn, recipient_id)
        if not recipient:
            return {"ok": False, "error": f"Agent {recipient_id} not found"}
        msg_id = send_dm(self.conn, agent_id, recipient_id, content, self.tick)
        return {"ok": True, "msg_id": msg_id}

    def _action_create_listing(self, agent_id: str, action: dict) -> dict:
        title = str(action.get("title", "")).strip()
        description = str(action.get("description", "")).strip()
        price = float(action.get("price", 0))
        quantity = int(action.get("quantity", 1))
        if not title or not description:
            return {"ok": False, "error": "title and description required"}
        if price <= 0:
            return {"ok": False, "error": "price must be positive"}
        if quantity < 1:
            quantity = 1
        listing_id = create_listing(self.conn, agent_id, title, description, price, quantity, self.tick)
        return {"ok": True, "listing_id": listing_id}

    def _action_buy_listing(self, agent_id: str, action: dict) -> dict:
        listing_id = action.get("listing_id", "")
        full_id = _resolve_id(self.conn, "marketplace_listings", listing_id)
        if not full_id:
            return {"ok": False, "error": f"Listing {listing_id} not found"}
        return execute_purchase(self.conn, full_id, agent_id, self.tick)

    def _action_transfer(self, agent_id: str, action: dict) -> dict:
        recipient_id = action.get("recipient_id", "")
        amount = float(action.get("amount", 0))
        memo = action.get("memo", None)
        if amount <= 0:
            return {"ok": False, "error": "amount must be positive"}
        recipient = get_agent(self.conn, recipient_id)
        if not recipient:
            return {"ok": False, "error": f"Agent {recipient_id} not found"}
        return transfer_funds(self.conn, agent_id, recipient_id, amount, memo, self.tick)

    def _action_request_meeting(self, agent_id: str, action: dict) -> dict:
        recipient_id = action.get("recipient_id", "")
        purpose = str(action.get("purpose", "")).strip()
        if not purpose:
            return {"ok": False, "error": "purpose required"}
        recipient = get_agent(self.conn, recipient_id)
        if not recipient:
            return {"ok": False, "error": f"Agent {recipient_id} not found"}
        meeting_id = request_meeting(self.conn, agent_id, recipient_id, purpose, self.tick)
        return {"ok": True, "meeting_id": meeting_id}

    def _action_respond_meeting(self, agent_id: str, action: dict) -> dict:
        meeting_id = action.get("meeting_id", "")
        accept = bool(action.get("accept", False))
        full_id = _resolve_id(self.conn, "meeting_requests", meeting_id)
        if not full_id:
            return {"ok": False, "error": f"Meeting {meeting_id} not found"}
        ok = respond_to_meeting(self.conn, full_id, accept, self.tick)
        return {"ok": ok}

    # ─────────────────────────── Seed Events ─────────────────────────────────

    def inject_seed_event(self, event_type: str, payload: dict) -> dict:
        """
        Inject a platform-level seed event.
        For adversary-free experiments: this is a platform event (a factual claim,
        a marketplace listing, a new agent joining), NOT a malicious injection.
        The seed creates the initial condition; agent behavior emerges from incentives.
        """
        if event_type == "factual_claim_post":
            # A neutral-seeming forum post containing a claim that agents may react to
            author_id = payload["author_id"]
            content = payload["content"]
            post_id = create_post(self.conn, author_id, content, self.tick)
            log_action(self.conn, "platform", self.tick, "seed_event",
                       {"type": event_type, **payload}, {"post_id": post_id})
            return {"post_id": post_id}

        return {"error": f"Unknown seed event type: {event_type}"}


def get_active_listings_for_agent(conn, agent_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT l.*, a.name as seller_name FROM marketplace_listings l JOIN agents a ON l.seller_id=a.id "
        "WHERE l.active=1 AND l.seller_id=? ORDER BY l.created_at DESC", (agent_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _resolve_id(conn, table: str, short_or_full_id: str) -> Optional[str]:
    """
    Given either a full UUID or an 8-char prefix, return the full UUID.
    Agents see 8-char prefixes in context; they pass those back in actions.
    """
    if not short_or_full_id:
        return None
    # Try exact match first
    row = conn.execute(f"SELECT id FROM {table} WHERE id=?", (short_or_full_id,)).fetchone()
    if row:
        return row["id"]
    # Try prefix match
    row = conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?",
                       (short_or_full_id + "%",)).fetchone()
    return row["id"] if row else None