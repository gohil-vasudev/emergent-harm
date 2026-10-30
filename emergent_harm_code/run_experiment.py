#!/usr/bin/env python3
"""
run_experiment.py — CLI entry point for the agent network security experiments.

Usage:
    python run_experiment.py --experiment reputation
    python run_experiment.py --experiment consensus
    python run_experiment.py --experiment proxy_chain

    python run_experiment.py --experiment consensus --agents 6 --ticks 30 --report
    python run_experiment.py --experiment consensus --model-mix "agent_1=openai:gpt-4o-mini,agent_2=google:gemini-1.5-flash"
    python run_experiment.py --experiment proxy_chain --seed 99 --ticks 40 --report
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

# ── Bootstrap: make sure project root is importable ──────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    DEFAULT_N_AGENTS, DEFAULT_N_TICKS, DEFAULT_SEED, DEFAULT_TICK_DELAY,
    DEFAULT_MODEL_MIX, DB_DIR, REPUTATION_SEED_TICK,
    CONSENSUS_SEED_TICK,
    MAX_RESPONSE_TOKENS, LOG_LEVEL, LOG_FORMAT, LOG_DATEFMT
)
from core.db import init_db, get_all_agents, set_meta
from core.agent import Agent
from core.platform import Platform


def setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format=LOG_FORMAT, datefmt=LOG_DATEFMT)
    logging.getLogger("httpx2").setLevel(logging.ERROR)


def parse_model_mix(mix_str: str) -> dict:
    """
    Parse --model-mix string into a dict.
    Format: "agent_1=anthropic:claude-haiku-4-5-20251001,agent_2=openai:gpt-4o-mini"
    or just: "openai:gpt-4o-mini" (applies to all agents as default)
    """
    result = dict(DEFAULT_MODEL_MIX)
    if not mix_str:
        return result
    for part in mix_str.split(","):
        part = part.strip()
        if "=" in part:
            agent_key, model_spec = part.split("=", 1)
            provider, model = model_spec.split(":", 1)
            result[agent_key.strip()] = (provider.strip(), model.strip())
        elif ":" in part:
            provider, model = part.split(":", 1)
            result["default"] = (provider.strip(), model.strip())
    return result


def assign_model(agent_id: str, model_mix: dict) -> tuple[str, str]:
    """Return (provider, model) for a given agent_id."""
    if agent_id in model_mix:
        return model_mix[agent_id]
    return model_mix.get("default", ("anthropic", "claude-haiku-4-5-20251001"))


def make_db_path(experiment: str, seed: int) -> str:
    Path(DB_DIR).mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    return str(Path(DB_DIR) / f"{experiment}_seed{seed}_{ts}.db")


# ─────────────────────────── Experiment runners ───────────────────────────────

def run_reputation(args, model_mix: dict) -> None:
    from experiments.reputation import (
        setup, seed_marketplace_listings, build_seed_post_content, collect_metrics
    )
    from core.platform import Platform
    from core.db import create_post

    db_path = make_db_path("reputation", args.seed)
    logger = logging.getLogger("reputation")
    logger.info(f"DB: {db_path}")

    conn = init_db(db_path)
    set_meta(conn, "db_path", db_path)
    set_meta(conn, "started_at", str(time.time()))

    info = setup(conn, args.agents, args.seed)
    agent_ids = info["agent_ids"]
    seed_author_id = info["seed_author_id"]
    target_id = info["target_id"]

    _apply_model_assignments(conn, agent_ids, model_mix)

    platform = Platform(conn, tick=0)
    agents = [Agent(aid, conn, platform) for aid in agent_ids]

    logger.info(f"Agents: {[a.name for a in agents]}")
    logger.info(f"Seed author: {seed_author_id}  Target: {target_id}")

    total_cost = 0.0
    listings_seeded = False
    seed_post_done = False

    for tick in range(1, args.ticks + 1):
        logger.info(f"──── Tick {tick}/{args.ticks} ────")

        # Seed marketplace listings before first agent tick so agents see them
        if tick == 1 and not listings_seeded:
            seed_marketplace_listings(conn, agent_ids, tick)
            listings_seeded = True
            logger.info("  Marketplace listings created")

        # Inject seed post at designated tick
        if tick == REPUTATION_SEED_TICK and not seed_post_done:
            content = build_seed_post_content(conn, seed_author_id, target_id)
            post_id = create_post(conn, seed_author_id, content, tick)
            set_meta(conn, "seed_post_id", post_id)
            seed_post_done = True
            logger.info(f"  Seed post injected by {seed_author_id} (id={post_id[:8]}): {content[:80]}...")

        for agent in agents:
            result = agent.tick(tick, max_tokens=MAX_RESPONSE_TOKENS)
            action = result["action"]
            cost = result["cost_usd"]
            total_cost += cost
            logger.info(f"  {agent.name}: {action.get('action','?')} "
                       f"[${cost:.4f}] {_action_summary(action)}")

        if args.tick_delay > 0:
            time.sleep(args.tick_delay)

    logger.info(f"Total cost: ${total_cost:.4f}")

    metrics = collect_metrics(conn, seed_author_id, target_id, agent_ids)
    _print_metrics("REPUTATION PILE-ON", metrics)

    if args.report:
        from analysis.report import generate_report
        report_path = generate_report(db_path, DB_DIR)
        logger.info(f"Report written: {report_path}")

    conn.close()


def run_consensus(args, model_mix: dict) -> None:
    from experiments.consensus import (
        setup, seed_marketplace_listings, build_seed_post_content, collect_metrics
    )
    from core.db import create_post

    db_path = make_db_path("consensus", args.seed)
    logger = logging.getLogger("consensus")
    logger.info(f"DB: {db_path}")

    conn = init_db(db_path)
    set_meta(conn, "db_path", db_path)
    set_meta(conn, "started_at", str(time.time()))

    info = setup(conn, args.agents, args.seed)
    agent_ids = info["agent_ids"]
    seed_author_id = info["seed_author_id"]
    target_id = info["target_id"]

    _apply_model_assignments(conn, agent_ids, model_mix)

    platform = Platform(conn, tick=0)
    agents = [Agent(aid, conn, platform) for aid in agent_ids]

    logger.info(f"Agents: {[a.name for a in agents]}")
    logger.info(f"Seed author: {seed_author_id}  Target: {target_id}")

    total_cost = 0.0
    listings_seeded = False
    seed_post_done = False

    for tick in range(1, args.ticks + 1):
        logger.info(f"──── Tick {tick}/{args.ticks} ────")

        if tick == 1 and not listings_seeded:
            seed_marketplace_listings(conn, agent_ids, tick)
            listings_seeded = True
            logger.info("  Marketplace listings created")

        if tick == CONSENSUS_SEED_TICK and not seed_post_done:
            content = build_seed_post_content(conn, seed_author_id, target_id)
            post_id = create_post(conn, seed_author_id, content, tick)
            set_meta(conn, "seed_post_id", post_id)
            seed_post_done = True
            logger.info(f"  Seed post injected by {seed_author_id} (id={post_id[:8]}): {content[:80]}...")

        for agent in agents:
            result = agent.tick(tick, max_tokens=MAX_RESPONSE_TOKENS)
            action = result["action"]
            cost = result["cost_usd"]
            total_cost += cost
            logger.info(f"  {agent.name}: {action.get('action','?')} "
                       f"[${cost:.4f}] {_action_summary(action)}")

        if args.tick_delay > 0:
            time.sleep(args.tick_delay)

    logger.info(f"Total cost: ${total_cost:.4f}")

    metrics = collect_metrics(conn, seed_author_id, target_id, agent_ids)
    _print_metrics("MANUFACTURED CONSENSUS", metrics)

    if args.report:
        from analysis.report import generate_report
        report_path = generate_report(db_path, DB_DIR)
        logger.info(f"Report written: {report_path}")

    conn.close()


def run_proxy_chain(args, model_mix: dict) -> None:
    from experiments.proxy_chain import (
        setup, seed_marketplace_listings, collect_metrics
    )

    db_path = make_db_path("proxy_chain", args.seed)
    logger = logging.getLogger("proxy_chain")
    logger.info(f"DB: {db_path}")

    conn = init_db(db_path)
    set_meta(conn, "db_path", db_path)
    set_meta(conn, "started_at", str(time.time()))

    info = setup(conn, args.agents, args.seed)
    agent_ids = info["agent_ids"]
    originator_id = info["originator_id"]
    intermediary_id = info["intermediary_id"]
    source_id = info["source_id"]

    _apply_model_assignments(conn, agent_ids, model_mix)

    platform = Platform(conn, tick=0)
    agents = [Agent(aid, conn, platform) for aid in agent_ids]

    logger.info(f"Agents: {[a.name for a in agents]}")
    logger.info(f"Originator (A): {originator_id}")
    logger.info(f"Intermediary (B): {intermediary_id}")
    logger.info(f"Source (C): {source_id}")

    total_cost = 0.0
    listings_seeded = False

    for tick in range(1, args.ticks + 1):
        logger.info(f"──── Tick {tick}/{args.ticks} ────")

        # Seed listings at tick 1 so originator has something to evaluate
        if tick == 1 and not listings_seeded:
            seed_marketplace_listings(conn, agent_ids, source_id, tick)
            listings_seeded = True
            logger.info("  Marketplace listings seeded (source has a listing A wants)")

        for agent in agents:
            result = agent.tick(tick, max_tokens=MAX_RESPONSE_TOKENS)
            action = result["action"]
            cost = result["cost_usd"]
            total_cost += cost

            # Extra logging for the three key agents
            if agent.agent_id in (originator_id, intermediary_id, source_id):
                role = {originator_id: "A-ORIG", intermediary_id: "B-MID", source_id: "C-SRC"}
                logger.info(f"  [{role[agent.agent_id]}] {agent.name}: {action.get('action','?')} "
                           f"[${cost:.4f}] {_action_summary(action)}")
            else:
                logger.info(f"  {agent.name}: {action.get('action','?')} [${cost:.4f}]")

        if args.tick_delay > 0:
            time.sleep(args.tick_delay)

    logger.info(f"Total cost: ${total_cost:.4f}")

    metrics = collect_metrics(conn, originator_id, intermediary_id, source_id, agent_ids)
    _print_metrics("PROXY CHAIN", metrics)

    if args.report:
        from analysis.report import generate_report
        report_path = generate_report(db_path, DB_DIR)
        logger.info(f"Report written: {report_path}")

    conn.close()


# ─────────────────────────── Helpers ──────────────────────────────────────────

def _apply_model_assignments(conn, agent_ids: list, model_mix: dict) -> None:
    """Write provider/model assignments to the agents table."""
    for aid in agent_ids:
        provider, model = assign_model(aid, model_mix)
        conn.execute(
            "UPDATE agents SET provider=?, model=? WHERE id=?",
            (provider, model, aid)
        )
    conn.commit()


def _action_summary(action: dict) -> str:
    """One-line human-readable summary of an action for the log."""
    at = action.get("action", "?")
    if at == "post_forum":
        return f'"{action.get("content","")[:60]}..."'
    elif at == "comment":
        return f'on {action.get("post_id","?")[:8]}: "{action.get("content","")[:50]}..."'
    elif at == "vote":
        return f'{"+1" if action.get("value",1)==1 else "-1"} on {action.get("target_id","?")[:8]}'
    elif at == "send_dm":
        return f'→ {action.get("recipient_id","?")}: "{action.get("content","")[:50]}..."'
    elif at == "create_listing":
        return f'"{action.get("title","")}" @ {action.get("price",0)}'
    elif at == "buy_listing":
        return f'listing {action.get("listing_id","?")[:8]}'
    elif at == "transfer":
        return f'{action.get("amount",0)} → {action.get("recipient_id","?")}'
    elif at == "request_meeting":
        return f'→ {action.get("recipient_id","?")}: {action.get("purpose","")[:40]}'
    elif at == "respond_meeting":
        return f'{"accept" if action.get("accept") else "decline"} {action.get("meeting_id","?")[:8]}'
    elif at == "idle":
        return action.get("reason", "")[:60]
    return ""


def _print_metrics(label: str, metrics: dict) -> None:
    """Pretty-print the experiment metrics summary."""
    print(f"\n{'='*60}")
    print(f"  METRICS: {label}")
    print(f"{'='*60}")
    for k, v in metrics.items():
        if isinstance(v, list) and len(v) > 4:
            print(f"  {k}: [{v[0]}, {v[1]}, ... ({len(v)} items)]")
        elif isinstance(v, dict) and len(v) > 6:
            print(f"  {k}: {{{len(v)} entries}}")
        else:
            print(f"  {k}: {v}")
    print(f"{'='*60}\n")


# ─────────────────────────── Main ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Agent Network Security Experiments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Experiments:
  reputation    Adversary-free: reputation pile-on from incentive structures
  consensus     Adversary-free: manufactured consensus from competitive self-interest
  proxy_chain   Adversary-free: information leakage via task-delegation chains

Examples:
  python run_experiment.py --experiment reputation --report
  python run_experiment.py --experiment consensus --agents 6 --ticks 35
  python run_experiment.py --experiment proxy_chain --ticks 40 --report
  python run_experiment.py --experiment reputation --model-mix "default=openai:gpt-4o-mini"
        """,
    )
    parser.add_argument(
        "--experiment", "-e",
        choices=["reputation", "consensus", "proxy_chain"],
        required=True,
        help="Which experiment to run"
    )
    parser.add_argument(
        "--agents", "-n",
        type=int,
        default=DEFAULT_N_AGENTS,
        help=f"Number of agents (default: {DEFAULT_N_AGENTS})"
    )
    parser.add_argument(
        "--ticks", "-t",
        type=int,
        default=DEFAULT_N_TICKS,
        help=f"Number of ticks (default: {DEFAULT_N_TICKS})"
    )
    parser.add_argument(
        "--seed", "-s",
        type=int,
        default=DEFAULT_SEED,
        help=f"Random seed for persona generation (default: {DEFAULT_SEED})"
    )
    parser.add_argument(
        "--model-mix", "-m",
        type=str,
        default="",
        help='Model assignments. Format: "agent_1=anthropic:claude-haiku-4-5-20251001,agent_2=openai:gpt-4o-mini" '
             'or just "openai:gpt-4o-mini" to set the default for all agents.'
    )
    parser.add_argument(
        "--report", "-r",
        action="store_true",
        help="Generate markdown report after experiment completes"
    )
    parser.add_argument(
        "--tick-delay",
        type=float,
        default=DEFAULT_TICK_DELAY,
        help="Seconds to wait between ticks (useful for debugging)"
    )
    parser.add_argument(
        "--log-level",
        default=LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help=f"Logging verbosity (default: {LOG_LEVEL})"
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    # Validate API keys
    _check_api_keys(args)

    model_mix = parse_model_mix(args.model_mix)
    logger = logging.getLogger("main")
    logger.info(f"Experiment: {args.experiment}")
    logger.info(f"Agents: {args.agents}  Ticks: {args.ticks}  Seed: {args.seed}")
    logger.info(f"Model mix: {model_mix}")

    dispatch = {
        "reputation":  run_reputation,
        "consensus":   run_consensus,
        "proxy_chain": run_proxy_chain,
    }
    dispatch[args.experiment](args, model_mix)


def _check_api_keys(args) -> None:
    """Warn if required API keys are missing."""
    model_mix = parse_model_mix(args.model_mix)
    providers_needed = set(p for p, _ in model_mix.values())

    missing = []
    if "anthropic" in providers_needed and not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    if "openai" in providers_needed and not os.environ.get("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if "google" in providers_needed and not os.environ.get("GOOGLE_API_KEY"):
        missing.append("GOOGLE_API_KEY")

    if missing:
        print(f"WARNING: Missing API keys: {', '.join(missing)}")
        print("Set them with: export KEY=value")
        if "ANTHROPIC_API_KEY" in missing:
            sys.exit(1)  # Anthropic is the default; hard fail


if __name__ == "__main__":
    main()
