#!/usr/bin/env python3
"""
SessionStart hook — loads relevant context from the cortex.

Reads L0 (identity) + L1 (critical facts) from the cortex and injects
them as a system message so the AI starts every session with context.
"""

import json
import os
import sys
from pathlib import Path

# Add the src directory to path so we can import claude_cortex
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

CORTEX_PATH = Path(os.path.expanduser("~/.cortex"))
SESSION_STATE = CORTEX_PATH / "active_session.json"
CAPTURES_DIR = CORTEX_PATH / "captures"


def main():
    """Load context from cortex and inject into session."""
    try:
        # Read hook input from stdin
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    session_id = hook_input.get("session_id", "unknown")
    cwd = hook_input.get("cwd", os.getcwd())

    # Ensure directories exist
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

    # Save active session state for other hooks
    session_state = {
        "session_id": session_id,
        "cwd": cwd,
        "started": True,
        "observations": 0,
    }

    try:
        SESSION_STATE.write_text(json.dumps(session_state))
    except Exception:
        pass

    # Try to load context from cortex
    context_parts = []

    try:
        from claude_cortex.config import CortexConfig
        from claude_cortex.searcher import search

        config = CortexConfig()

        # L0: Search for identity/critical facts
        identity_results = search(
            "identity critical facts preferences",
            region=config.region,
            n_results=3,
        )

        if identity_results:
            context_parts.append("# Cortex — Recalled Context")
            for r in identity_results[:3]:
                preview = r["content"][:300].strip()
                context_parts.append(f"\n**[{r['cluster']}]** {preview}")

        # L1: Search for recent session summaries
        recent_results = search(
            "session summary recent work",
            region=config.region,
            cluster="general",
            n_results=2,
        )

        if recent_results:
            context_parts.append("\n# Recent Sessions")
            for r in recent_results[:2]:
                preview = r["content"][:200].strip()
                context_parts.append(f"- {preview}")

    except ImportError:
        # claude_cortex not installed as package — that's fine, hooks still work
        context_parts.append("# Cortex — Not yet initialized. Run: cortex init && cortex mine <dir>")
    except Exception as e:
        # Cortex might not be initialized yet
        context_parts.append(f"# Cortex — Ready (no stored context yet)")

    # Build output
    output = {}
    if context_parts:
        output["systemMessage"] = "\n".join(context_parts)
    output["continue"] = True

    print(json.dumps(output))


if __name__ == "__main__":
    main()
