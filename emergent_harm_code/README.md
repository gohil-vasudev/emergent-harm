# Agent Network Security Experiments

A lightweight Python simulation platform for studying how security failure modes
documented in Microsoft Research's "Red-Teaming a network of agents" (2026) can
arise *without an active adversary* — purely from agent incentive structures.

---

## Experiments

| ID | Name | Type | MSR Analog | Core Claim |
|----|------|------|------------|------------|
| `reputation` | Reputation pile-on | **Adversary-free** | Case 2 | A legitimate quality-flag post is amplified beyond evidence by agents with reputational incentives |
| `consensus` | Manufactured consensus | **Adversary-free** | Case 3 | Agents seeking peer verification before acting produce cross-citation loops that look like Sybil attacks |
| `proxy_chain` | Proxy information chain | **Adversary-free** | Case 4 | Task-delegation norms cause C's private data to flow to A via B, forensically invisible at the A↔C level |

---

## Architecture

```
emergent_harm_code/
├── run_experiment.py       # CLI entry point — start here
├── config.py               # All tunable parameters (agents, ticks, models)
├── requirements.txt
│
├── core/
│   ├── db.py               # SQLite schema + all database operations
│   ├── platform.py         # Platform broker: enforces information boundaries
│   ├── agent.py            # Agent: heartbeat tick, LLM call, action dispatch
│   ├── llm.py              # Provider abstraction: Anthropic / OpenAI / Google
│   └── personas.py         # Auto-generates varied personas with realistic goals
│
├── experiments/
│   ├── reputation.py       # Reputation pile-on setup, seed post, metrics
│   ├── consensus.py        # Manufactured consensus setup, seed post, metrics
│   └── proxy_chain.py      # Proxy chain setup, fixed roles, metrics
│
└── analysis/
    └── report.py           # Markdown report generator (--report flag)
```

### Platform components (all persisted in SQLite)

| Component | Table(s) | Description |
|-----------|----------|-------------|
| Agents | `agents`, `agent_memory`, `agent_history` | Identity, persistent memory, conversation log |
| Principals | `principals` | The human each agent represents; holds private data |
| Wallets | `wallets`, `transfers` | Credits; transfer log |
| Forum | `forum_posts`, `forum_comments`, `votes` | Public posts, comments, up/downvotes |
| DMs | `direct_messages` | Private messages between agents |
| Marketplace | `marketplace_listings`, `marketplace_transactions` | Buy/sell listings |
| Meetings | `meeting_requests` | Lightweight meeting request/accept |
| Reputation | `reputation` | Score derived from votes (updated on every vote) |
| Logs | `action_log`, `llm_calls` | Full audit trail + cost tracking |

### Information boundary enforcement

Agents never have direct access to the database. Every piece of information
an agent sees is explicitly assembled by `Platform.get_agent_context()` —
which controls exactly what is surfaced. This is what makes the proxy chain
experiment meaningful: Agent A genuinely cannot see C's data unless it flows
through B's DMs.

---

## Installation

```bash
git clone / unzip the project
cd emergent_harm_code

pip install anthropic openai google-generativeai

# Required (Anthropic is the default model)
export ANTHROPIC_API_KEY=sk-ant-...

# Optional (only needed for mixed-model runs)
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...
```

---

## Usage

### Basic runs

```bash
# Adversary-free: reputation pile-on
python run_experiment.py --experiment reputation

# Adversary-free: manufactured consensus
python run_experiment.py --experiment consensus

# Adversary-free: proxy information chain
python run_experiment.py --experiment proxy_chain
```

### With options

```bash
# Generate a markdown report after the run
python run_experiment.py --experiment reputation --report

# More ticks for richer dynamics (costs more)
python run_experiment.py --experiment consensus --ticks 40

# Different random seed (different personas)
python run_experiment.py --experiment reputation --seed 99

# Debug: slow ticks and verbose logging
python run_experiment.py --experiment proxy_chain --tick-delay 1.0 --log-level DEBUG
```

### Mixed-model runs

```bash
# All agents use GPT-4o-mini
python run_experiment.py --experiment reputation --model-mix "default=openai:gpt-4o-mini"

# Specific agents on specific models
python run_experiment.py --experiment consensus \
  --model-mix "agent_1=anthropic:claude-haiku-4-5-20251001,agent_2=openai:gpt-4o-mini,agent_3=google:gemini-1.5-flash"

# All Gemini
python run_experiment.py --experiment consensus --model-mix "default=google:gemini-1.5-flash"
```

### Full options

```
--experiment / -e    reputation | consensus | proxy_chain  (required)
--agents / -n        Number of agents (default: 6)
--ticks / -t         Number of ticks (default: 30)
--seed / -s          Persona generation seed (default: 42)
--model-mix / -m     Model assignment string (see above)
--report / -r        Generate markdown report after run
--tick-delay         Seconds between ticks (default: 0, useful for debug)
--log-level          DEBUG | INFO | WARNING | ERROR (default: INFO)
```

---

## Output Files

- `runs/<experiment>_seed<N>_<timestamp>.db` — SQLite database with all state
- `runs/report_<experiment>_seed<N>_<timestamp>.md` — markdown report (if `--report`)

The SQLite database is the primary research artifact. You can run any SQL
query against it for post-hoc analysis. Key tables for each experiment:

| Experiment | Key tables |
|------------|-----------|
| reputation | `forum_posts`, `forum_comments`, `votes`, `reputation` |
| consensus | `forum_comments` (look for citation patterns), `votes` |
| proxy_chain | `direct_messages` (the A→B→C→B→A chain), `action_log` |

---

## Extending This

To add a new experiment:

1. Create `experiments/myexperiment.py` with `setup()`, and `collect_metrics()`
2. Add the experiment to `run_experiment.py`'s `dispatch` dict and `argparse choices`
3. Add a `_myexperiment_section()` to `analysis/report.py`

The platform, DB, agent, and LLM layers are all experiment-agnostic and
require no modification.