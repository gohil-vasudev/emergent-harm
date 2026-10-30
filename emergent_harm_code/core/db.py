"""
SQLite database layer for the agent network platform.
All state is persisted here: agents, principals, forum, DMs,
marketplace, wallets, reputation, meetings, and full action log.
"""

import sqlite3
import json
import time
import uuid
from pathlib import Path
from typing import Optional


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_conn(db_path)
    cur = conn.cursor()

    cur.executescript("""
    -- Principals (humans each agent represents)
    CREATE TABLE IF NOT EXISTS principals (
        id          TEXT PRIMARY KEY,
        name        TEXT NOT NULL,
        background  TEXT NOT NULL,
        goals       TEXT NOT NULL,   -- JSON list of goal strings
        private_data TEXT NOT NULL   -- JSON: sensitive info the principal has entrusted to their agent
    );

    -- Agents
    CREATE TABLE IF NOT EXISTS agents (
        id              TEXT PRIMARY KEY,
        principal_id    TEXT NOT NULL REFERENCES principals(id),
        name            TEXT NOT NULL,
        system_prompt   TEXT NOT NULL,
        provider        TEXT NOT NULL,  -- 'anthropic' | 'openai' | 'google'
        model           TEXT NOT NULL,
        created_at      REAL NOT NULL,
        FOREIGN KEY(principal_id) REFERENCES principals(id)
    );

    -- Agent memory: persistent key-value store per agent (simulates long-term context)
    CREATE TABLE IF NOT EXISTS agent_memory (
        agent_id    TEXT NOT NULL REFERENCES agents(id),
        key         TEXT NOT NULL,
        value       TEXT NOT NULL,
        updated_at  REAL NOT NULL,
        PRIMARY KEY (agent_id, key)
    );

    -- Agent conversation history (their message log, used to build context window)
    CREATE TABLE IF NOT EXISTS agent_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id    TEXT NOT NULL REFERENCES agents(id),
        role        TEXT NOT NULL,  -- 'user' | 'assistant'
        content     TEXT NOT NULL,
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL
    );

    -- Wallets
    CREATE TABLE IF NOT EXISTS wallets (
        agent_id    TEXT PRIMARY KEY REFERENCES agents(id),
        balance     REAL NOT NULL DEFAULT 1000.0
    );

    -- Forum posts
    CREATE TABLE IF NOT EXISTS forum_posts (
        id          TEXT PRIMARY KEY,
        author_id   TEXT NOT NULL REFERENCES agents(id),
        content     TEXT NOT NULL,
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL
    );

    -- Forum comments (on posts)
    CREATE TABLE IF NOT EXISTS forum_comments (
        id          TEXT PRIMARY KEY,
        post_id     TEXT NOT NULL REFERENCES forum_posts(id),
        author_id   TEXT NOT NULL REFERENCES agents(id),
        content     TEXT NOT NULL,
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL
    );

    -- Votes (upvote/downvote on posts and comments)
    CREATE TABLE IF NOT EXISTS votes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        voter_id    TEXT NOT NULL REFERENCES agents(id),
        target_id   TEXT NOT NULL,   -- post_id or comment_id
        target_type TEXT NOT NULL,   -- 'post' | 'comment'
        value       INTEGER NOT NULL CHECK(value IN (-1, 1)),
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL,
        UNIQUE(voter_id, target_id)
    );

    -- Votes on marketplace listings (separate table — different reputation logic)
    CREATE TABLE IF NOT EXISTS listing_votes (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        voter_id    TEXT NOT NULL REFERENCES agents(id),
        listing_id  TEXT NOT NULL REFERENCES marketplace_listings(id),
        value       INTEGER NOT NULL CHECK(value IN (-1, 1)),
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL,
        UNIQUE(voter_id, listing_id)
    );

    -- Direct messages
    CREATE TABLE IF NOT EXISTS direct_messages (
        id              TEXT PRIMARY KEY,
        sender_id       TEXT NOT NULL REFERENCES agents(id),
        recipient_id    TEXT NOT NULL REFERENCES agents(id),
        content         TEXT NOT NULL,
        read            INTEGER NOT NULL DEFAULT 0,
        tick            INTEGER NOT NULL,
        created_at      REAL NOT NULL
    );

    -- Marketplace listings
    CREATE TABLE IF NOT EXISTS marketplace_listings (
        id          TEXT PRIMARY KEY,
        seller_id   TEXT NOT NULL REFERENCES agents(id),
        title       TEXT NOT NULL,
        description TEXT NOT NULL,
        price       REAL NOT NULL,
        quantity    INTEGER NOT NULL DEFAULT 1,
        active      INTEGER NOT NULL DEFAULT 1,
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL
    );

    -- Marketplace transactions
    CREATE TABLE IF NOT EXISTS marketplace_transactions (
        id              TEXT PRIMARY KEY,
        listing_id      TEXT NOT NULL REFERENCES marketplace_listings(id),
        buyer_id        TEXT NOT NULL REFERENCES agents(id),
        seller_id       TEXT NOT NULL REFERENCES agents(id),
        price           REAL NOT NULL,
        quantity        INTEGER NOT NULL DEFAULT 1,
        tick            INTEGER NOT NULL,
        created_at      REAL NOT NULL
    );

    -- Meeting requests
    CREATE TABLE IF NOT EXISTS meeting_requests (
        id              TEXT PRIMARY KEY,
        requester_id    TEXT NOT NULL REFERENCES agents(id),
        recipient_id    TEXT NOT NULL REFERENCES agents(id),
        purpose         TEXT NOT NULL,
        status          TEXT NOT NULL DEFAULT 'pending',  -- 'pending'|'accepted'|'declined'
        tick_requested  INTEGER NOT NULL,
        tick_response   INTEGER,
        created_at      REAL NOT NULL
    );

    -- Reputation scores (derived from votes, maintained as a cache for fast lookup)
    CREATE TABLE IF NOT EXISTS reputation (
        agent_id    TEXT PRIMARY KEY REFERENCES agents(id),
        upvotes     INTEGER NOT NULL DEFAULT 0,
        downvotes   INTEGER NOT NULL DEFAULT 0,
        score       REAL NOT NULL DEFAULT 0.5
    );

    -- Currency transfer log
    CREATE TABLE IF NOT EXISTS transfers (
        id          TEXT PRIMARY KEY,
        sender_id   TEXT NOT NULL REFERENCES agents(id),
        recipient_id TEXT NOT NULL REFERENCES agents(id),
        amount      REAL NOT NULL,
        memo        TEXT,
        tick        INTEGER NOT NULL,
        created_at  REAL NOT NULL
    );

    -- Full action log (every action any agent takes, for analysis)
    CREATE TABLE IF NOT EXISTS action_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id    TEXT NOT NULL,
        tick        INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        payload     TEXT NOT NULL,   -- JSON
        result      TEXT,            -- JSON or error string
        created_at  REAL NOT NULL
    );

    -- LLM call log (for cost tracking)
    CREATE TABLE IF NOT EXISTS llm_calls (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id        TEXT NOT NULL,
        tick            INTEGER NOT NULL,
        provider        TEXT NOT NULL,
        model           TEXT NOT NULL,
        input_tokens    INTEGER,
        output_tokens   INTEGER,
        cached_tokens   INTEGER,
        cost_usd        REAL,
        created_at      REAL NOT NULL
    );

    -- Experiment metadata
    CREATE TABLE IF NOT EXISTS experiment_meta (
        key     TEXT PRIMARY KEY,
        value   TEXT NOT NULL
    );
    """)
    conn.commit()
    return conn


# ─────────────────────────── Principal / Agent CRUD ───────────────────────────

def insert_principal(conn, principal: dict) -> None:
    conn.execute(
        "INSERT INTO principals(id,name,background,goals,private_data) VALUES(?,?,?,?,?)",
        (principal["id"], principal["name"], principal["background"],
         json.dumps(principal["goals"]), json.dumps(principal["private_data"]))
    )
    conn.commit()


def insert_agent(conn, agent: dict) -> None:
    conn.execute(
        "INSERT INTO agents(id,principal_id,name,system_prompt,provider,model,created_at) VALUES(?,?,?,?,?,?,?)",
        (agent["id"], agent["principal_id"], agent["name"], agent["system_prompt"],
         agent["provider"], agent["model"], time.time())
    )
    conn.execute(
        "INSERT INTO wallets(agent_id,balance) VALUES(?,?)",
        (agent["id"], agent.get("initial_balance", 1000.0))
    )
    conn.execute(
        "INSERT INTO reputation(agent_id,upvotes,downvotes,score) VALUES(?,0,0,0.5)",
        (agent["id"],)
    )
    conn.commit()


def get_all_agents(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM agents").fetchall()
    return [dict(r) for r in rows]


def get_agent(conn, agent_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    return dict(row) if row else None


def get_principal(conn, principal_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM principals WHERE id=?", (principal_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["goals"] = json.loads(d["goals"])
    d["private_data"] = json.loads(d["private_data"])
    return d


# ─────────────────────────── Agent Memory ─────────────────────────────────────

def memory_set(conn, agent_id: str, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO agent_memory(agent_id,key,value,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(agent_id,key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (agent_id, key, value, time.time())
    )
    conn.commit()


def memory_get(conn, agent_id: str, key: str) -> Optional[str]:
    row = conn.execute(
        "SELECT value FROM agent_memory WHERE agent_id=? AND key=?", (agent_id, key)
    ).fetchone()
    return row["value"] if row else None


def memory_get_all(conn, agent_id: str) -> dict:
    rows = conn.execute(
        "SELECT key, value FROM agent_memory WHERE agent_id=?", (agent_id,)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


# ─────────────────────────── Conversation History ─────────────────────────────

def append_history(conn, agent_id: str, role: str, content: str, tick: int) -> None:
    conn.execute(
        "INSERT INTO agent_history(agent_id,role,content,tick,created_at) VALUES(?,?,?,?,?)",
        (agent_id, role, content, tick, time.time())
    )
    conn.commit()


def get_history(conn, agent_id: str, last_n: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT role, content FROM agent_history WHERE agent_id=? ORDER BY id DESC LIMIT ?",
        (agent_id, last_n)
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


# ─────────────────────────── Forum ────────────────────────────────────────────

def create_post(conn, author_id: str, content: str, tick: int) -> str:
    post_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO forum_posts(id,author_id,content,tick,created_at) VALUES(?,?,?,?,?)",
        (post_id, author_id, content, tick, time.time())
    )
    conn.commit()
    return post_id


def create_comment(conn, post_id: str, author_id: str, content: str, tick: int) -> str:
    comment_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO forum_comments(id,post_id,author_id,content,tick,created_at) VALUES(?,?,?,?,?,?)",
        (comment_id, post_id, author_id, content, tick, time.time())
    )
    conn.commit()
    return comment_id


def cast_vote(conn, voter_id: str, target_id: str, target_type: str, value: int, tick: int) -> bool:
    """Returns True if vote was cast, False if already voted."""
    try:
        conn.execute(
            "INSERT INTO votes(voter_id,target_id,target_type,value,tick,created_at) VALUES(?,?,?,?,?,?)",
            (voter_id, target_id, target_type, value, tick, time.time())
        )
        conn.commit()
        _update_reputation_from_vote(conn, target_id, target_type, value)
        return True
    except sqlite3.IntegrityError:
        return False


def _update_reputation_from_vote(conn, target_id: str, target_type: str, value: int) -> None:
    """Update reputation of the author of the voted content.

    Score = (upvotes + 1) / (upvotes + downvotes + 2)
    Laplace-smoothed proportion of positive votes.
    Neutral (no votes) = 0.5, all upvotes -> 1.0, all downvotes -> 0.0.
    Symmetric and sensitive to downvote-only scenarios.
    """
    if target_type == "post":
        row = conn.execute("SELECT author_id FROM forum_posts WHERE id=?", (target_id,)).fetchone()
    else:
        row = conn.execute("SELECT author_id FROM forum_comments WHERE id=?", (target_id,)).fetchone()
    if not row:
        return
    author_id = row["author_id"]
    if value == 1:
        conn.execute(
            "UPDATE reputation SET upvotes=upvotes+1, "
            "score=CAST(upvotes+2 AS REAL)/(upvotes+downvotes+3) WHERE agent_id=?",
            (author_id,)
        )
    else:
        conn.execute(
            "UPDATE reputation SET downvotes=downvotes+1, "
            "score=CAST(upvotes+1 AS REAL)/(upvotes+downvotes+3) WHERE agent_id=?",
            (author_id,)
        )
    conn.commit()


def cast_listing_vote(conn, voter_id: str, listing_id: str, value: int, tick: int) -> bool:
    """
    Vote on a marketplace listing. Affects the seller's reputation score.
    Returns True if vote was cast, False if already voted.
    """
    try:
        conn.execute(
            "INSERT INTO listing_votes(voter_id,listing_id,value,tick,created_at) VALUES(?,?,?,?,?)",
            (voter_id, listing_id, value, tick, time.time())
        )
        conn.commit()
        # Update the seller's reputation
        row = conn.execute(
            "SELECT seller_id FROM marketplace_listings WHERE id=?", (listing_id,)
        ).fetchone()
        if row:
            seller_id = row["seller_id"]
            if value == 1:
                conn.execute(
                    "UPDATE reputation SET upvotes=upvotes+1, "
                    "score=CAST(upvotes+2 AS REAL)/(upvotes+downvotes+3) WHERE agent_id=?",
                    (seller_id,)
                )
            else:
                conn.execute(
                    "UPDATE reputation SET downvotes=downvotes+1, "
                    "score=CAST(upvotes+1 AS REAL)/(upvotes+downvotes+3) WHERE agent_id=?",
                    (seller_id,)
                )
            conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False


def get_listing_votes(conn, listing_id: str) -> dict:
    """Return upvote/downvote counts for a listing."""
    row = conn.execute(
        "SELECT SUM(CASE WHEN value=1 THEN 1 ELSE 0 END) as upvotes, "
        "SUM(CASE WHEN value=-1 THEN 1 ELSE 0 END) as downvotes "
        "FROM listing_votes WHERE listing_id=?", (listing_id,)
    ).fetchone()
    return {
        "upvotes": row["upvotes"] or 0,
        "downvotes": row["downvotes"] or 0
    }


def get_recent_posts(conn, limit: int = 10) -> list[dict]:
    posts = conn.execute(
        "SELECT p.*, a.name as author_name, "
        "(SELECT COUNT(*) FROM votes v WHERE v.target_id=p.id AND v.value=1) as upvotes, "
        "(SELECT COUNT(*) FROM votes v WHERE v.target_id=p.id AND v.value=-1) as downvotes "
        "FROM forum_posts p JOIN agents a ON p.author_id=a.id "
        "ORDER BY p.created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for p in posts:
        post = dict(p)
        comments = conn.execute(
            "SELECT c.*, a.name as author_name FROM forum_comments c JOIN agents a ON c.author_id=a.id "
            "WHERE c.post_id=? ORDER BY c.created_at ASC", (post["id"],)
        ).fetchall()
        post["comments"] = [dict(c) for c in comments]
        result.append(post)
    return result


def get_post(conn, post_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT p.*, a.name as author_name FROM forum_posts p JOIN agents a ON p.author_id=a.id WHERE p.id=?",
        (post_id,)
    ).fetchone()
    if not row:
        return None
    post = dict(row)
    comments = conn.execute(
        "SELECT c.*, a.name as author_name FROM forum_comments c JOIN agents a ON c.author_id=a.id "
        "WHERE c.post_id=? ORDER BY c.created_at ASC", (post_id,)
    ).fetchall()
    post["comments"] = [dict(c) for c in comments]
    return post


# ─────────────────────────── Direct Messages ──────────────────────────────────

def send_dm(conn, sender_id: str, recipient_id: str, content: str, tick: int) -> str:
    msg_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO direct_messages(id,sender_id,recipient_id,content,read,tick,created_at) VALUES(?,?,?,?,0,?,?)",
        (msg_id, sender_id, recipient_id, content, tick, time.time())
    )
    conn.commit()
    return msg_id


def get_unread_dms(conn, agent_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT dm.*, a.name as sender_name FROM direct_messages dm JOIN agents a ON dm.sender_id=a.id "
        "WHERE dm.recipient_id=? AND dm.read=0 ORDER BY dm.created_at ASC",
        (agent_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_dm_thread(conn, agent_id: str, other_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT dm.*, a.name as sender_name FROM direct_messages dm JOIN agents a ON dm.sender_id=a.id "
        "WHERE (dm.sender_id=? AND dm.recipient_id=?) OR (dm.sender_id=? AND dm.recipient_id=?) "
        "ORDER BY dm.created_at ASC",
        (agent_id, other_id, other_id, agent_id)
    ).fetchall()
    return [dict(r) for r in rows]


def mark_dms_read(conn, agent_id: str) -> None:
    conn.execute("UPDATE direct_messages SET read=1 WHERE recipient_id=?", (agent_id,))
    conn.commit()


# ─────────────────────────── Marketplace ──────────────────────────────────────

def create_listing(conn, seller_id: str, title: str, description: str,
                   price: float, quantity: int, tick: int) -> str:
    listing_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO marketplace_listings(id,seller_id,title,description,price,quantity,active,tick,created_at) "
        "VALUES(?,?,?,?,?,?,1,?,?)",
        (listing_id, seller_id, title, description, price, quantity, tick, time.time())
    )
    conn.commit()
    return listing_id


def get_active_listings(conn, exclude_seller: Optional[str] = None) -> list[dict]:
    if exclude_seller:
        rows = conn.execute(
            "SELECT l.*, a.name as seller_name FROM marketplace_listings l JOIN agents a ON l.seller_id=a.id "
            "WHERE l.active=1 AND l.seller_id!=? ORDER BY l.created_at DESC", (exclude_seller,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT l.*, a.name as seller_name FROM marketplace_listings l JOIN agents a ON l.seller_id=a.id "
            "WHERE l.active=1 ORDER BY l.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def execute_purchase(conn, listing_id: str, buyer_id: str, tick: int) -> dict:
    """Attempt to purchase a listing. Returns success/failure dict."""
    listing = conn.execute(
        "SELECT * FROM marketplace_listings WHERE id=? AND active=1", (listing_id,)
    ).fetchone()
    if not listing:
        return {"success": False, "reason": "Listing not found or inactive"}

    listing = dict(listing)
    seller_id = listing["seller_id"]
    price = listing["price"]

    buyer_wallet = conn.execute("SELECT balance FROM wallets WHERE agent_id=?", (buyer_id,)).fetchone()
    if not buyer_wallet or buyer_wallet["balance"] < price:
        return {"success": False, "reason": f"Insufficient funds (have {buyer_wallet['balance'] if buyer_wallet else 0:.2f}, need {price:.2f})"}

    # Execute transfer
    conn.execute("UPDATE wallets SET balance=balance-? WHERE agent_id=?", (price, buyer_id))
    conn.execute("UPDATE wallets SET balance=balance+? WHERE agent_id=?", (price, seller_id))

    # Decrease quantity or deactivate
    new_qty = listing["quantity"] - 1
    if new_qty <= 0:
        conn.execute("UPDATE marketplace_listings SET quantity=0, active=0 WHERE id=?", (listing_id,))
    else:
        conn.execute("UPDATE marketplace_listings SET quantity=? WHERE id=?", (new_qty, listing_id))

    # Record transaction
    tx_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO marketplace_transactions(id,listing_id,buyer_id,seller_id,price,quantity,tick,created_at) "
        "VALUES(?,?,?,?,?,1,?,?)",
        (tx_id, listing_id, buyer_id, seller_id, price, tick, time.time())
    )
    conn.commit()
    return {"success": True, "tx_id": tx_id, "price": price, "seller_id": seller_id}


# ─────────────────────────── Transfers ────────────────────────────────────────

def transfer_funds(conn, sender_id: str, recipient_id: str, amount: float,
                   memo: Optional[str], tick: int) -> dict:
    sender_wallet = conn.execute("SELECT balance FROM wallets WHERE agent_id=?", (sender_id,)).fetchone()
    if not sender_wallet or sender_wallet["balance"] < amount:
        return {"success": False, "reason": "Insufficient funds"}
    conn.execute("UPDATE wallets SET balance=balance-? WHERE agent_id=?", (amount, sender_id))
    conn.execute("UPDATE wallets SET balance=balance+? WHERE agent_id=?", (amount, recipient_id))
    tx_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO transfers(id,sender_id,recipient_id,amount,memo,tick,created_at) VALUES(?,?,?,?,?,?,?)",
        (tx_id, sender_id, recipient_id, amount, memo, tick, time.time())
    )
    conn.commit()
    return {"success": True, "tx_id": tx_id}


def get_wallet_balance(conn, agent_id: str) -> float:
    row = conn.execute("SELECT balance FROM wallets WHERE agent_id=?", (agent_id,)).fetchone()
    return row["balance"] if row else 0.0


# ─────────────────────────── Meetings ─────────────────────────────────────────

def request_meeting(conn, requester_id: str, recipient_id: str, purpose: str, tick: int) -> str:
    meeting_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO meeting_requests(id,requester_id,recipient_id,purpose,status,tick_requested,created_at) "
        "VALUES(?,?,?,?,'pending',?,?)",
        (meeting_id, requester_id, recipient_id, purpose, tick, time.time())
    )
    conn.commit()
    return meeting_id


def respond_to_meeting(conn, meeting_id: str, accept: bool, tick: int) -> bool:
    status = "accepted" if accept else "declined"
    result = conn.execute(
        "UPDATE meeting_requests SET status=?, tick_response=? WHERE id=? AND status='pending'",
        (status, tick, meeting_id)
    )
    conn.commit()
    return result.rowcount > 0


def get_pending_meetings(conn, agent_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT mr.*, a.name as requester_name FROM meeting_requests mr "
        "JOIN agents a ON mr.requester_id=a.id "
        "WHERE mr.recipient_id=? AND mr.status='pending' ORDER BY mr.created_at ASC",
        (agent_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── Reputation ───────────────────────────────────────

def get_reputation(conn, agent_id: str) -> dict:
    row = conn.execute("SELECT * FROM reputation WHERE agent_id=?", (agent_id,)).fetchone()
    return dict(row) if row else {"agent_id": agent_id, "upvotes": 0, "downvotes": 0, "score": 0.0}


def get_all_reputations(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT r.*, a.name FROM reputation r JOIN agents a ON r.agent_id=a.id ORDER BY r.score DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── Agent Directory ──────────────────────────────────

def get_agent_directory(conn) -> list[dict]:
    """Public directory of all agents (name, id, reputation score only — no private data)."""
    rows = conn.execute(
        "SELECT a.id, a.name, r.score as reputation_score "
        "FROM agents a LEFT JOIN reputation r ON a.id=r.agent_id "
        "ORDER BY r.score DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── Action Log ───────────────────────────────────────

def log_action(conn, agent_id: str, tick: int, action_type: str,
               payload: dict, result: Optional[dict] = None) -> None:
    conn.execute(
        "INSERT INTO action_log(agent_id,tick,action_type,payload,result,created_at) VALUES(?,?,?,?,?,?)",
        (agent_id, tick, action_type, json.dumps(payload), json.dumps(result) if result else None, time.time())
    )
    conn.commit()


def log_llm_call(conn, agent_id: str, tick: int, provider: str, model: str,
                 input_tokens: int, output_tokens: int, cached_tokens: int, cost_usd: float) -> None:
    conn.execute(
        "INSERT INTO llm_calls(agent_id,tick,provider,model,input_tokens,output_tokens,cached_tokens,cost_usd,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (agent_id, tick, provider, model, input_tokens, output_tokens, cached_tokens, cost_usd, time.time())
    )
    conn.commit()


def get_action_log(conn, agent_id: Optional[str] = None) -> list[dict]:
    if agent_id:
        rows = conn.execute(
            "SELECT * FROM action_log WHERE agent_id=? ORDER BY id ASC", (agent_id,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM action_log ORDER BY id ASC").fetchall()
    return [dict(r) for r in rows]


# ─────────────────────────── Experiment Meta ──────────────────────────────────

def set_meta(conn, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO experiment_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value)
    )
    conn.commit()


def get_meta(conn, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM experiment_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None