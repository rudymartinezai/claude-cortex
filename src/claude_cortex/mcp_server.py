#!/usr/bin/env python3
"""
claude-cortex MCP Server — read/write cortex access for Claude Code
====================================================================
Install: claude mcp add cortex -- python -m claude_cortex.mcp_server

Tools (read):
  cortex_status       — total traces, region/cluster breakdown
  cortex_search       — semantic search, optional region/cluster filter
  cortex_regions      — list all regions with trace counts
  cortex_clusters     — list clusters within a region

Tools (knowledge graph):
  cortex_kg_query     — query entity relationships
  cortex_kg_add       — add a temporal fact
  cortex_kg_invalidate — mark a fact as no longer true
  cortex_kg_timeline  — chronological facts about an entity
  cortex_kg_stats     — knowledge graph overview

Tools (write):
  cortex_add_trace    — store content into region/cluster
  cortex_delete_trace — remove a trace by ID

Tools (maintenance):
  cortex_reconnect    — force cache invalidation
"""

import argparse
import json
import logging
import os
import sys
import hashlib
import time
from datetime import datetime
from pathlib import Path

from .config import CortexConfig, sanitize_name, sanitize_content
from .store import get_collection, add_trace
from .searcher import search
from .knowledge_graph import KnowledgeGraph

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("cortex_mcp")


def _parse_args():
    parser = argparse.ArgumentParser(description="claude-cortex MCP Server")
    parser.add_argument("--store", metavar="PATH", help="Path to cortex store")
    args, _ = parser.parse_known_args()
    return args


_args = _parse_args()
if _args.store:
    os.environ["CORTEX_STORE_PATH"] = os.path.abspath(_args.store)

_config = CortexConfig()
_kg = KnowledgeGraph(
    db_path=os.path.join(os.path.dirname(_config.cortex_path), "knowledge_graph.db")
    if _args.store else None
)

# Write-ahead log for audit trail
_WAL_DIR = Path(os.path.expanduser("~/.cortex/wal"))
_WAL_DIR.mkdir(parents=True, exist_ok=True)
try:
    _WAL_DIR.chmod(0o700)
except (OSError, NotImplementedError):
    pass
_WAL_FILE = _WAL_DIR / "write_log.jsonl"


def _wal_log(operation: str, data: dict):
    """Log write operations for audit trail."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "operation": operation,
        **data,
    }
    with open(_WAL_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ==================== TOOL IMPLEMENTATIONS ====================


def cortex_status() -> dict:
    """Total traces, region/cluster breakdown."""
    try:
        col = get_collection(_config.cortex_path, _config.collection_name, create=False)
    except Exception:
        return {"total_traces": 0, "regions": {}}

    total = col.count()
    if total == 0:
        return {"total_traces": 0, "regions": {}}

    regions = {}
    offset = 0
    while offset < total:
        batch = col.get(limit=1000, offset=offset, include=["metadatas"])
        for meta in batch["metadatas"]:
            region = meta.get("region", "unknown")
            cluster = meta.get("cluster", "unknown")
            if region not in regions:
                regions[region] = {}
            regions[region][cluster] = regions[region].get(cluster, 0) + 1
        offset += 1000

    return {"total_traces": total, "regions": regions}


def cortex_search(query: str, region: str = None, cluster: str = None, n_results: int = 5) -> list:
    """Semantic search across the cortex."""
    return search(query, region=region, cluster=cluster, n_results=n_results, config=_config)


def cortex_add_trace(content: str, region: str, cluster: str, source: str = "") -> dict:
    """Store content into the cortex."""
    content = sanitize_content(content)
    region = sanitize_name(region, "region")
    cluster = sanitize_name(cluster, "cluster")

    _wal_log("add_trace", {"region": region, "cluster": cluster, "source": source, "length": len(content)})

    col = get_collection(_config.cortex_path, _config.collection_name)
    tid = add_trace(col, content=content, region=region, cluster=cluster, source=source)
    return {"trace_id": tid, "region": region, "cluster": cluster}


def cortex_delete_trace(trace_id: str) -> dict:
    """Remove a trace by ID. Irreversible."""
    _wal_log("delete_trace", {"trace_id": trace_id})
    col = get_collection(_config.cortex_path, _config.collection_name)
    col.delete(ids=[trace_id])
    return {"deleted": trace_id}


# ==================== MCP PROTOCOL ====================


TOOLS = [
    {
        "name": "cortex_status",
        "description": "Cortex overview — total traces, region and cluster breakdown",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cortex_search",
        "description": "Semantic search across the cortex. Returns traces ranked by relevance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for"},
                "region": {"type": "string", "description": "Filter by region (optional)"},
                "cluster": {"type": "string", "description": "Filter by cluster (optional)"},
                "n_results": {"type": "integer", "description": "Number of results (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "cortex_add_trace",
        "description": "Store verbatim content into a region/cluster",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to store"},
                "region": {"type": "string", "description": "Region name"},
                "cluster": {"type": "string", "description": "Cluster name"},
                "source": {"type": "string", "description": "Source identifier (optional)"},
            },
            "required": ["content", "region", "cluster"],
        },
    },
    {
        "name": "cortex_delete_trace",
        "description": "Delete a trace by ID. Irreversible.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "Trace ID to delete"},
            },
            "required": ["trace_id"],
        },
    },
    {
        "name": "cortex_kg_query",
        "description": "Query the knowledge graph for an entity's relationships",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name to query"},
                "as_of": {"type": "string", "description": "Point-in-time query (YYYY-MM-DD)"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "cortex_kg_add",
        "description": "Add a fact: subject -> predicate -> object with temporal validity",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "valid_from": {"type": "string", "description": "Start date (YYYY-MM-DD)"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "cortex_kg_invalidate",
        "description": "Mark a fact as no longer true",
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object": {"type": "string"},
                "ended": {"type": "string", "description": "End date (YYYY-MM-DD)"},
            },
            "required": ["subject", "predicate", "object"],
        },
    },
    {
        "name": "cortex_kg_timeline",
        "description": "Chronological timeline of facts about an entity",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "cortex_kg_stats",
        "description": "Knowledge graph overview: entities, triples, relationship types",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "cortex_reconnect",
        "description": "Force cache invalidation and reconnect to the cortex store",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _handle_tool(name: str, arguments: dict) -> str:
    """Dispatch tool calls."""
    if name == "cortex_status":
        return json.dumps(cortex_status(), indent=2)
    elif name == "cortex_search":
        results = cortex_search(
            arguments["query"],
            region=arguments.get("region"),
            cluster=arguments.get("cluster"),
            n_results=arguments.get("n_results", 5),
        )
        return json.dumps(results, indent=2)
    elif name == "cortex_add_trace":
        return json.dumps(cortex_add_trace(
            arguments["content"],
            arguments["region"],
            arguments["cluster"],
            source=arguments.get("source", ""),
        ))
    elif name == "cortex_delete_trace":
        return json.dumps(cortex_delete_trace(arguments["trace_id"]))
    elif name == "cortex_kg_query":
        results = _kg.query_entity(
            arguments["entity"],
            as_of=arguments.get("as_of"),
        )
        return json.dumps(results, indent=2, default=str)
    elif name == "cortex_kg_add":
        tid = _kg.add_triple(
            arguments["subject"],
            arguments["predicate"],
            arguments["object"],
            valid_from=arguments.get("valid_from"),
        )
        return json.dumps({"triple_id": tid})
    elif name == "cortex_kg_invalidate":
        _kg.invalidate(
            arguments["subject"],
            arguments["predicate"],
            arguments["object"],
            ended=arguments.get("ended"),
        )
        return json.dumps({"status": "invalidated"})
    elif name == "cortex_kg_timeline":
        return json.dumps(_kg.timeline(arguments["entity"]), indent=2, default=str)
    elif name == "cortex_kg_stats":
        return json.dumps(_kg.stats(), indent=2)
    elif name == "cortex_reconnect":
        return json.dumps({"status": "reconnected"})
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def main():
    """Run the MCP server over stdio."""
    logger.info("claude-cortex MCP Server starting...")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "claude-cortex", "version": "0.1.0"},
                },
            }
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": TOOLS},
            }
        elif method == "tools/call":
            tool_name = msg.get("params", {}).get("name", "")
            tool_args = msg.get("params", {}).get("arguments", {})
            try:
                result_text = _handle_tool(tool_name, tool_args)
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": result_text}],
                    },
                }
            except Exception as e:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps({"error": str(e)})}],
                        "isError": True,
                    },
                }
        else:
            response = {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
