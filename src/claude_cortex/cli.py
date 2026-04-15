#!/usr/bin/env python3
"""
cortex CLI — command-line interface for claude-cortex.

Usage:
  cortex status                          Show cortex overview
  cortex search "query"                  Semantic search
  cortex mine /path/to/dir               Index files into the cortex
  cortex init                            Initialize a new cortex
  cortex install                         Wire into Claude Code as MCP server
  cortex kg stats                        Knowledge graph overview
  cortex kg query "entity"               Query entity relationships
  cortex kg timeline "entity"            Entity timeline
"""

import argparse
import json
import os
import sys
from pathlib import Path

from .config import CortexConfig, DEFAULT_CONFIG_PATH


def cmd_status(args):
    from .store import get_collection
    config = CortexConfig()
    try:
        col = get_collection(config.cortex_path, config.collection_name, create=False)
    except Exception:
        print(f"  No cortex found at {config.cortex_path}")
        print(f"  Run: cortex init")
        return

    total = col.count()
    if total == 0:
        print("  Cortex is empty. Run: cortex mine <dir>")
        return

    # Count by region/cluster
    regions = {}
    offset = 0
    while offset < total:
        batch = col.get(limit=1000, offset=offset, include=["metadatas"])
        for meta in batch["metadatas"]:
            region = meta.get("region", "unknown")
            cluster = meta.get("cluster", "unknown")
            key = f"{region}/{cluster}"
            regions[key] = regions.get(key, 0) + 1
        offset += 1000

    print(f"\n{'=' * 60}")
    print(f"  claude-cortex — {total} traces")
    print(f"{'=' * 60}\n")

    current_region = None
    for key in sorted(regions.keys()):
        region, cluster = key.split("/", 1)
        if region != current_region:
            current_region = region
            print(f"  REGION: {region}")
        print(f"    CLUSTER: {cluster:<25} {regions[key]} traces")
    print(f"\n{'=' * 60}")


def cmd_search(args):
    from .searcher import search, SearchError
    try:
        results = search(
            args.query,
            region=args.region,
            cluster=args.cluster,
            n_results=args.n or 5,
        )
    except SearchError as e:
        print(f"  Error: {e}")
        return

    if not results:
        print(f"  No results for: \"{args.query}\"")
        return

    print(f"\n{'=' * 60}")
    print(f"  Results for: \"{args.query}\"")
    print(f"{'=' * 60}\n")

    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r['region']} / {r['cluster']}")
        print(f"      Source: {r['source']}")
        print(f"      Score:  {r['score']}")
        print()
        # Show preview (first 300 chars)
        preview = r["content"][:300].strip()
        for line in preview.split("\n"):
            print(f"      {line}")
        print(f"\n  {'─' * 56}")


def cmd_mine(args):
    from .miner import mine_directory
    config = CortexConfig()

    directory = args.dir
    if not os.path.isdir(directory):
        print(f"  Error: {directory} is not a directory")
        return

    print(f"\n{'=' * 60}")
    print(f"  claude-cortex Mine")
    print(f"{'=' * 60}")
    print(f"  Region:  {args.region or config.region}")
    print(f"  Store:   {config.cortex_path}")
    if args.dry_run:
        print(f"  DRY RUN — nothing will be stored")
    print(f"{'─' * 60}\n")

    stats = mine_directory(
        directory,
        region=args.region,
        agent=args.agent or "cortex",
        config=config,
        dry_run=args.dry_run,
        limit=args.limit or 0,
    )

    print(f"\n{'=' * 60}")
    print(f"  Done.")
    print(f"  Files processed: {stats['files_processed']}")
    print(f"  Traces filed: {stats['traces_filed']}")
    if stats.get("by_cluster"):
        print(f"\n  By cluster:")
        for cluster, count in sorted(stats["by_cluster"].items(), key=lambda x: -x[1]):
            print(f"    {cluster:<25} {count} files")
    print(f"\n{'=' * 60}")


def cmd_init(args):
    """Initialize a new cortex."""
    config_dir = Path(os.path.expanduser("~/.cortex"))
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "config.yaml"
    if config_path.exists() and not args.force:
        print(f"  Cortex already initialized at {config_dir}")
        print(f"  Use --force to reinitialize")
        return

    default_config = """# claude-cortex configuration
region: default
store_path: ~/.cortex/store

clusters:
  - name: general
    description: Everything else
    keywords: []
"""

    config_path.write_text(default_config)
    store_path = config_dir / "store"
    store_path.mkdir(exist_ok=True)

    print(f"\n  claude-cortex initialized at {config_dir}")
    print(f"  Config: {config_path}")
    print(f"  Store:  {store_path}")
    print(f"\n  Next: cortex mine <directory>")
    print(f"  Or:   cortex install  (wire into Claude Code)")


def cmd_install(args):
    """Wire claude-cortex into Claude Code as plugin + MCP server."""
    import subprocess
    import shutil
    python_path = sys.executable

    # Find the plugin root (where hooks/ and .claude-plugin/ live)
    plugin_root = _find_plugin_root()

    print(f"\n{'=' * 60}")
    print(f"  claude-cortex Install")
    print(f"{'=' * 60}\n")

    success_count = 0
    total_steps = 2

    # Step 1: Register as Claude Code plugin (hooks for auto-capture)
    if plugin_root:
        plugin_cache = Path(os.path.expanduser("~/.claude/plugins/cache/local/claude-cortex/0.1.0"))
        plugin_cache.parent.mkdir(parents=True, exist_ok=True)

        # Symlink instead of copy — updates flow through automatically
        if plugin_cache.exists() or plugin_cache.is_symlink():
            if plugin_cache.is_symlink():
                plugin_cache.unlink()
            else:
                shutil.rmtree(plugin_cache)

        try:
            plugin_cache.symlink_to(plugin_root)
            print(f"  [1/{total_steps}] ✓ Plugin linked: {plugin_cache} → {plugin_root}")
            print(f"           Hooks: SessionStart, PostToolUse, SessionEnd, PreCompact")

            # Register in installed_plugins.json
            _register_plugin(plugin_root)
            success_count += 1
        except Exception as e:
            print(f"  [1/{total_steps}] ✗ Plugin link failed: {e}")
            print(f"           Manual: claude --plugin-dir {plugin_root}")
    else:
        print(f"  [1/{total_steps}] ⚠ Plugin root not found (hooks won't auto-capture)")
        print(f"           Install from source: pip install -e /path/to/claude-cortex")

    # Step 2: Register MCP server (10 search/KG tools)
    result = subprocess.run(
        ["claude", "mcp", "add", "cortex", "--", python_path, "-m", "claude_cortex.mcp_server"],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"  [2/{total_steps}] ✓ MCP server registered: {python_path} -m claude_cortex.mcp_server")
        print(f"           Tools: cortex_search, cortex_status, cortex_kg_query, +7 more")
        success_count += 1
    else:
        print(f"  [2/{total_steps}] ✗ MCP registration failed: {result.stderr.strip()}")

    print(f"\n{'─' * 60}")
    if success_count == total_steps:
        print(f"  ✓ Full install complete ({success_count}/{total_steps})")
        print(f"\n  Auto-capture: ON (every session indexed automatically)")
        print(f"  MCP tools:    ON (search, KG, status available)")
    elif success_count > 0:
        print(f"  ⚠ Partial install ({success_count}/{total_steps})")
    else:
        print(f"  ✗ Install failed")

    print(f"\n  Restart Claude Code to activate.")
    print(f"{'=' * 60}")


def _find_plugin_root() -> Path | None:
    """Find the claude-cortex plugin root directory."""
    # Check if we're running from the repo (development install)
    # __file__ = src/claude_cortex/cli.py → .parent×3 = repo root
    candidates = [
        Path(__file__).parent.parent.parent,  # src/claude_cortex/cli.py -> src/ -> repo root
        Path(os.path.expanduser("~/.cortex/plugin")),  # alternative install location
    ]

    for candidate in candidates:
        if (candidate / ".claude-plugin" / "plugin.json").exists():
            return candidate.resolve()
        if (candidate / "hooks" / "hooks.json").exists():
            return candidate.resolve()

    return None


def _register_plugin(plugin_root: Path):
    """Add claude-cortex to installed_plugins.json."""
    from datetime import datetime

    plugins_file = Path(os.path.expanduser("~/.claude/plugins/installed_plugins.json"))
    if not plugins_file.exists():
        return

    try:
        data = json.loads(plugins_file.read_text())
        plugins = data.get("plugins", {})

        now = datetime.now().isoformat() + "Z"
        plugins["claude-cortex@local"] = [
            {
                "scope": "user",
                "installPath": str(plugin_root),
                "version": "0.1.0",
                "installedAt": now,
                "lastUpdated": now,
            }
        ]

        data["plugins"] = plugins
        plugins_file.write_text(json.dumps(data, indent=2))
    except Exception:
        pass  # Non-fatal — plugin will still work via symlink


def cmd_kg(args):
    """Knowledge graph operations."""
    from .knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()

    if args.kg_command == "stats":
        stats = kg.stats()
        print(f"\n  Knowledge Graph: {stats['entities']} entities, {stats['triples']} triples")
        print(f"  Active facts: {stats['active_facts']}")
        if stats["relationship_types"]:
            print(f"  Relationships: {', '.join(stats['relationship_types'])}")

    elif args.kg_command == "query":
        results = kg.query_entity(args.entity, as_of=args.as_of)
        if not results:
            print(f"  No facts found for: {args.entity}")
            return
        print(f"\n  Facts about: {args.entity}\n")
        for r in results:
            vf = r.get("valid_from", "?")
            vt = r.get("valid_to", "current")
            print(f"  {r['subject_name']} —[{r['predicate']}]→ {r['object_name']}  ({vf} → {vt})")

    elif args.kg_command == "timeline":
        results = kg.timeline(args.entity)
        if not results:
            print(f"  No timeline for: {args.entity}")
            return
        print(f"\n  Timeline: {args.entity}\n")
        for r in results:
            ts = r.get("valid_from") or r.get("created_at", "?")
            end = f" → {r['valid_to']}" if r.get("valid_to") else ""
            print(f"  [{ts}{end}] {r['subject_name']} —[{r['predicate']}]→ {r['object_name']}")


def main():
    parser = argparse.ArgumentParser(
        prog="cortex",
        description="claude-cortex — Auto-capture + structured semantic recall for AI agents",
    )
    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", help="Show cortex overview")

    # search
    p_search = sub.add_parser("search", help="Semantic search")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--region", help="Filter by region")
    p_search.add_argument("--cluster", help="Filter by cluster")
    p_search.add_argument("-n", type=int, help="Number of results")

    # mine
    p_mine = sub.add_parser("mine", help="Index files into the cortex")
    p_mine.add_argument("dir", help="Directory to mine")
    p_mine.add_argument("--region", help="Region name")
    p_mine.add_argument("--agent", help="Agent name")
    p_mine.add_argument("--dry-run", action="store_true")
    p_mine.add_argument("--limit", type=int, help="Max files")

    # init
    p_init = sub.add_parser("init", help="Initialize a new cortex")
    p_init.add_argument("--force", action="store_true")

    # install
    sub.add_parser("install", help="Wire into Claude Code as MCP server")

    # kg
    p_kg = sub.add_parser("kg", help="Knowledge graph operations")
    kg_sub = p_kg.add_subparsers(dest="kg_command")
    kg_sub.add_parser("stats", help="KG overview")
    p_kgq = kg_sub.add_parser("query", help="Query entity")
    p_kgq.add_argument("entity", help="Entity name")
    p_kgq.add_argument("--as-of", help="Point-in-time (YYYY-MM-DD)")
    p_kgt = kg_sub.add_parser("timeline", help="Entity timeline")
    p_kgt.add_argument("entity", help="Entity name")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    dispatch = {
        "status": cmd_status,
        "search": cmd_search,
        "mine": cmd_mine,
        "init": cmd_init,
        "install": cmd_install,
        "kg": cmd_kg,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
