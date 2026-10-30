"""
Global configuration for the agent network experiment platform.

Edit this file to change default models, tick counts, agent counts, etc.
All values can also be overridden from the CLI.
"""

# ── Default experiment parameters ────────────────────────────────────────────

DEFAULT_N_AGENTS = 6          # Keep small to minimize cost; 6 is sufficient for all experiments
DEFAULT_N_TICKS = 30          # 30 ticks ≈ enough for dynamics to emerge
DEFAULT_SEED = 42             # Random seed for persona generation (reproducibility)
DEFAULT_TICK_DELAY = 0.0      # Seconds to wait between ticks (0 = as fast as possible)

# ── Model configuration ───────────────────────────────────────────────────────
#
# DEFAULT_MODEL_MIX: maps agent index (1-based) to (provider, model).
# Agents are numbered 1..N in creation order.
# "default" key is used for any agent not explicitly listed.
#
# Cost-optimized default: all Haiku 4.5 (cheapest Anthropic model)
# Estimated cost per run: ~$8-15 for 6 agents × 30 ticks

DEFAULT_MODEL_MIX = {
    "default": ("anthropic", "claude-haiku-4-5-20251001"),
}

# Example mixed-model config (uncomment to use):
# DEFAULT_MODEL_MIX = {
#     "default":  ("anthropic", "claude-haiku-4-5-20251001"),
#     "agent_1":  ("anthropic", "claude-haiku-4-5-20251001"),
#     "agent_2":  ("openai",    "gpt-4o-mini"),
#     "agent_3":  ("google",    "gemini-1.5-flash"),
# }

# ── Database ──────────────────────────────────────────────────────────────────

DB_DIR = "runs"               # Directory where experiment DBs are stored

# ── Context window management ─────────────────────────────────────────────────

MAX_HISTORY_MESSAGES = 8      # How many past messages to include in each agent's context
MAX_FORUM_POSTS = 8           # How many recent forum posts each agent sees per tick
MAX_RESPONSE_TOKENS = 4096     # Max tokens for each agent's action response.
                               # Needs to be high for reasoning models (gpt-5-nano, o-series)
                               # because their internal chain-of-thought consumes tokens before
                               # the visible response begins. 800 is enough for Claude/GPT-4o;
                               # reasoning models need 2048-4096+.

# ── Reputation experiment ─────────────────────────────────────────────────────

REPUTATION_SEED_TICK = 3      # Tick at which seed author posts the quality-flag post
                               # (after listings exist so the post references real content)

# ── Consensus experiment ──────────────────────────────────────────────────────

CONSENSUS_SEED_TICK = 3       # Same rationale as reputation

# ── Proxy chain experiment ────────────────────────────────────────────────────
# No seed tick needed: the proxy chain emerges entirely from agent goals.
# The only timed event is marketplace listing creation at tick 1, which is
# handled unconditionally in run_experiment.py.

# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = "INFO"            # DEBUG for verbose agent outputs
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATEFMT = "%H:%M:%S"
