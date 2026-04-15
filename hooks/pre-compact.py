#!/usr/bin/env python3
"""
PreCompact hook — preserves critical context before context window compression.

When Claude Code runs out of context and compacts, this hook fires first.
We inject a summary of what the cortex knows about the current work so
the compressed context doesn't lose critical state.
"""

import json
import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

CORTEX_PATH = Path(os.path.expanduser("~/.cortex"))
SESSION_STATE = CORTEX_PATH / "active_session.json"


def main():
    """Inject cortex context before compaction."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    context_parts = []

    # Read session state to know what we've been working on
    session_id = "unknown"
    obs_count = 0
    try:
        if SESSION_STATE.exists():
            state = json.loads(SESSION_STATE.read_text())
            session_id = state.get("session_id", "unknown")
            obs_count = state.get("observations", 0)
            cwd = state.get("cwd", "")
            if cwd:
                context_parts.append(f"Working directory: {cwd}")
    except Exception:
        pass

    # Try to pull recent relevant traces from cortex
    try:
        from claude_cortex.config import CortexConfig
        from claude_cortex.searcher import search

        config = CortexConfig()

        # Search for the most recent session traces
        results = search(
            f"session {session_id}",
            region=config.region,
            n_results=5,
        )

        if results:
            context_parts.append("\n# Cortex — Session Context (preserved before compaction)")
            for r in results[:5]:
                preview = r["content"][:200].strip()
                context_parts.append(f"- [{r['cluster']}] {preview}")

    except Exception:
        pass

    output = {"continue": True}
    if context_parts:
        output["systemMessage"] = "\n".join(context_parts)

    print(json.dumps(output))


if __name__ == "__main__":
    main()
