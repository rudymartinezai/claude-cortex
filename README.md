# claude-cortex

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/rudymartinezai/claude-cortex/actions/workflows/ci.yml/badge.svg)](https://github.com/rudymartinezai/claude-cortex/actions)
[![ChromaDB](https://img.shields.io/badge/vector--db-ChromaDB-orange.svg)](https://www.trychroma.com/)

**Auto-capture + structured semantic recall for AI coding agents.**

The memory system Claude Code should have had. One install. Zero config. Your AI remembers everything.

## What it does

1. **Captures** — hooks into Claude Code's session lifecycle and records every conversation, tool use, and decision automatically
2. **Indexes** — pipes captured content into a local ChromaDB vector store in real-time, classified by topic
3. **Recalls** — provides semantic search + temporal knowledge graph via MCP tools, so your AI finds relevant context instantly

No cloud. No API keys. No subscriptions. Everything runs on your machine.

## Install

```bash
pip install claude-cortex
cortex init
cortex install
```

That's it. Restart Claude Code and you have persistent memory.

### What `cortex install` does

1. **Registers as a Claude Code plugin** — hooks into SessionStart, PostToolUse, SessionEnd, and PreCompact
2. **Registers an MCP server** — exposes 10 tools (search, KG, status) to your AI agent

### From source (development)

```bash
git clone https://github.com/rudymartinezai/claude-cortex.git
cd claude-cortex
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cortex init
cortex install
```

## Quick start

```bash
# Mine existing files into the cortex
cortex mine ~/my-project --region myproject

# Search your memory
cortex search "authentication flow"

# Check what's stored
cortex status

# Knowledge graph
cortex kg stats
cortex kg query "Rudy"
cortex kg timeline "project-x"
```

## How it works

### The Cortex Structure

| Concept | What it is | Example |
|---------|-----------|---------|
| **Region** | Top-level domain | `myproject`, `health`, `trading` |
| **Cluster** | Topic within a region | `auth`, `database`, `api-design` |
| **Trace** | One chunk of stored memory | A paragraph from a conversation |
| **Synapse** | Cross-region connection | Links `auth` in project A to `auth` in project B |

### Memory Stack

| Layer | Size | When |
|-------|------|------|
| **L0** — Identity | ~50 tokens | Every session |
| **L1** — Critical facts | ~120 tokens | Every session |
| **L2** — Topic recall | On demand | When topic mentioned |
| **L3** — Deep search | On demand | When explicitly needed |

Your AI wakes up with ~170 tokens of context. Not 10,000. Just enough to know who you are and what matters.

### Auto-Capture Pipeline (Claude Code Hooks)

Four hooks fire automatically during every Claude Code session:

```
SessionStart
  → session-start.py fires
  → Loads L0 + L1 from cortex → injected as system message
  → AI starts with relevant context, zero manual effort

PostToolUse (Write | Edit | Bash)
  → post-tool-use.py fires
  → Captures operation to ~/.cortex/captures/{session}.jsonl
  → Fast: local file write only, no ChromaDB during session

PreCompact
  → pre-compact.py fires
  → Injects cortex context before context window compression
  → Critical state survives compaction

SessionEnd
  → session-end.py fires
  → Reads all captured observations
  → Classifies each by topic (keyword matching against clusters)
  → Vectorizes and stores as traces in ChromaDB
  → Builds session summary trace
  → Update knowledge graph
  → Ready for next session
```

## MCP Tools

When connected to Claude Code, these tools are available:

| Tool | Description |
|------|-------------|
| `cortex_status` | Cortex overview — traces, regions, clusters |
| `cortex_search` | Semantic search with optional filters |
| `cortex_add_trace` | Store content into region/cluster |
| `cortex_delete_trace` | Remove a trace by ID |
| `cortex_kg_query` | Query entity relationships |
| `cortex_kg_add` | Add temporal fact |
| `cortex_kg_invalidate` | Mark fact as no longer true |
| `cortex_kg_timeline` | Chronological entity history |
| `cortex_kg_stats` | Knowledge graph overview |
| `cortex_reconnect` | Force reconnect |

## Configuration

```yaml
# ~/.cortex/config.yaml
region: default
store_path: ~/.cortex/store

clusters:
  - name: code
    description: Code changes, architecture, debugging
    keywords: [function, class, bug, fix, refactor, api]
  - name: decisions
    description: Architecture choices, strategy
    keywords: [decided, chose, strategy, plan, design]
  - name: general
    description: Everything else
    keywords: []
```

## vs. existing tools

| | claude-cortex | claude-mem | MemPalace |
|---|---|---|---|
| Auto-capture | Yes | Yes | No |
| Structured recall | Yes | Basic | Yes |
| Knowledge graph | Yes | No | Yes |
| Real-time indexing | Yes | No | No |
| MCP tools | 10+ | 3-4 | 29 |
| One install | Yes | Yes | Yes |
| License | MIT | AGPL | MIT |

claude-cortex combines the best of both: automatic capture from session hooks + structured semantic recall with a knowledge graph. One tool, not two.

## Credits

Storage engine inspired by [MemPalace](https://github.com/milla-jovovich/mempalace) (MIT). Auto-capture architecture inspired by [claude-mem](https://github.com/thedotmack/claude-mem). Built from scratch by [CodeBloodedAI](https://github.com/codedbloodedai).

## License

MIT — do whatever you want with it.
