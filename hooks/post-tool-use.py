#!/usr/bin/env python3
"""
PostToolUse hook — captures significant tool operations in real-time.

Fires after Write, Edit, and Bash calls. Captures the operation to a
session-local JSONL file for later indexing at SessionEnd.

Designed to be FAST — writes to a local file and exits. No ChromaDB
operations happen here. All indexing happens at SessionEnd.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

CORTEX_PATH = Path(os.path.expanduser("~/.cortex"))
SESSION_STATE = CORTEX_PATH / "active_session.json"
CAPTURES_DIR = CORTEX_PATH / "captures"


def main():
    """Capture tool use to session file."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # If we can't read input, exit silently
        print(json.dumps({"continue": True}))
        return

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input", {})
    tool_result = hook_input.get("tool_result", "")

    # Skip trivial operations
    result_str = str(tool_result)
    if len(result_str) < 50:
        print(json.dumps({"continue": True}))
        return

    # Read session state
    session_id = "unknown"
    try:
        if SESSION_STATE.exists():
            state = json.loads(SESSION_STATE.read_text())
            session_id = state.get("session_id", "unknown")
            # Increment observation count
            state["observations"] = state.get("observations", 0) + 1
            SESSION_STATE.write_text(json.dumps(state))
    except Exception:
        pass

    # Build observation
    observation = {
        "type": "tool_use",
        "tool": tool_name,
        "timestamp": datetime.now().isoformat(),
        "input_summary": _summarize_input(tool_name, tool_input),
        "output_summary": result_str[:1000],
    }

    # Write to session capture file
    CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CAPTURES_DIR.chmod(0o700)
    except (OSError, NotImplementedError):
        pass
    capture_file = CAPTURES_DIR / f"{session_id}.jsonl"

    try:
        with open(capture_file, "a") as f:
            f.write(json.dumps(observation) + "\n")
    except Exception:
        pass

    # Silent success — don't add noise to the session
    print(json.dumps({"continue": True, "suppressOutput": True}))


def _summarize_input(tool_name: str, tool_input: dict) -> str:
    """Create a compact summary of the tool input."""
    if tool_name == "Write":
        path = tool_input.get("file_path", "unknown")
        content = tool_input.get("content", "")
        return f"Write {path} ({len(content)} chars)"

    elif tool_name == "Edit":
        path = tool_input.get("file_path", "unknown")
        old = tool_input.get("old_string", "")[:100]
        return f"Edit {path} (replacing '{old}...')"

    elif tool_name == "Bash":
        cmd = tool_input.get("command", "")[:200]
        return f"Bash: {cmd}"

    else:
        return str(tool_input)[:300]


if __name__ == "__main__":
    main()
