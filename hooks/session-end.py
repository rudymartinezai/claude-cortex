#!/usr/bin/env python3
"""
SessionEnd hook — indexes the full session into the cortex.

This is where the magic happens. Reads all captured observations from
the session JSONL file, classifies them by topic, and indexes them into
ChromaDB as traces. Also builds a session summary trace.

This runs once at the END of the session, so ChromaDB write latency
doesn't affect the user's interactive experience.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

# Add src to path
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

CORTEX_PATH = Path(os.path.expanduser("~/.cortex"))
SESSION_STATE = CORTEX_PATH / "active_session.json"
CAPTURES_DIR = CORTEX_PATH / "captures"


def main():
    """Index session captures into the cortex."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        hook_input = {}

    # Read session state
    session_id = "unknown"
    try:
        if SESSION_STATE.exists():
            state = json.loads(SESSION_STATE.read_text())
            session_id = state.get("session_id", "unknown")
    except Exception:
        pass

    # Read captured observations
    capture_file = CAPTURES_DIR / f"{session_id}.jsonl"
    observations = []

    if capture_file.exists():
        try:
            with open(capture_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        observations.append(json.loads(line))
        except Exception:
            pass

    if not observations:
        # Nothing captured — clean up and exit
        _cleanup(session_id)
        print(json.dumps({"continue": True}))
        return

    # Index into cortex
    traces_filed = 0
    try:
        from claude_cortex.config import CortexConfig
        from claude_cortex.store import get_collection, add_trace

        config = CortexConfig()
        col = get_collection(config.cortex_path, config.collection_name)
        region = config.region

        cluster_keywords = config.get_cluster_keywords()

        # Index each significant observation
        for obs in observations:
            content = _observation_to_content(obs)
            if len(content.strip()) < 50:
                continue

            cluster = _classify(content, cluster_keywords)

            add_trace(
                col,
                content=content,
                region=region,
                cluster=cluster,
                source=f"session-{session_id}",
                agent="cortex-capture",
                metadata={
                    "session_id": session_id,
                    "timestamp": obs.get("timestamp", ""),
                    "obs_type": obs.get("type", "unknown"),
                },
            )
            traces_filed += 1

        # Build and index session summary
        summary = _build_summary(session_id, observations)
        if summary and len(summary) > 50:
            cluster = _classify(summary, cluster_keywords)
            add_trace(
                col,
                content=summary,
                region=region,
                cluster=cluster,
                source=f"session-summary-{session_id}",
                agent="cortex-capture",
                metadata={
                    "session_id": session_id,
                    "is_summary": "true",
                    "obs_count": str(len(observations)),
                    "traces_filed": str(traces_filed),
                },
            )
            traces_filed += 1

    except ImportError:
        # claude_cortex not installed — save raw captures for later mining
        pass
    except Exception as e:
        # Log error but don't block session end
        error_log = CORTEX_PATH / "error.log"
        try:
            with open(error_log, "a") as f:
                f.write(f"[{datetime.now().isoformat()}] SessionEnd error: {e}\n")
        except Exception:
            pass

    # Clean up
    _cleanup(session_id)

    # Report
    output = {
        "continue": True,
        "suppressOutput": True,
    }

    if traces_filed > 0:
        output["systemMessage"] = f"cortex: indexed {traces_filed} traces from this session"

    print(json.dumps(output))


def _observation_to_content(obs: dict) -> str:
    """Convert an observation dict to indexable content."""
    obs_type = obs.get("type", "unknown")

    if obs_type == "tool_use":
        tool = obs.get("tool", "unknown")
        inp = obs.get("input_summary", "")
        out = obs.get("output_summary", "")
        content = f"[Tool: {tool}] {inp}\n{out}"
    elif obs_type == "user_message":
        content = f"[User] {obs.get('content', '')}"
    elif obs_type == "assistant_message":
        content = f"[Assistant] {obs.get('content', '')}"
    else:
        content = str(obs)[:500]

    # Scrub potential secrets before indexing
    return _scrub_secrets(content)


def _scrub_secrets(text: str) -> str:
    """Remove potential API keys, tokens, and passwords from text."""
    import re
    # Common secret patterns
    patterns = [
        (r'(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*["\']?([A-Za-z0-9_\-]{20,})["\']?', r'\1=***REDACTED***'),
        (r'(?i)(Bearer\s+)[A-Za-z0-9_\-\.]{20,}', r'\1***REDACTED***'),
        (r'sk-[A-Za-z0-9]{20,}', '***REDACTED_API_KEY***'),
        (r'ghp_[A-Za-z0-9]{36}', '***REDACTED_GH_TOKEN***'),
        (r'xoxb-[A-Za-z0-9\-]{20,}', '***REDACTED_SLACK_TOKEN***'),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def _classify(content: str, cluster_keywords: dict) -> str:
    """Classify content into a cluster based on keyword matching."""
    content_lower = content.lower()
    scores = {}

    for cluster_name, keywords in cluster_keywords.items():
        if not keywords:
            continue
        score = sum(content_lower.count(kw.lower()) for kw in keywords)
        scores[cluster_name] = score

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best

    return "general"


def _build_summary(session_id: str, observations: list) -> str:
    """Build a concise session summary from observations."""
    parts = [f"Session {session_id} ({datetime.now().strftime('%Y-%m-%d %H:%M')})"]

    tools_used = set()
    files_touched = set()

    for obs in observations:
        if obs.get("type") == "tool_use":
            tools_used.add(obs.get("tool", "unknown"))
            inp = obs.get("input_summary", "")
            # Extract file paths
            for ext in [".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".json", ".yaml", ".yml"]:
                if ext in inp:
                    # Try to extract the path
                    words = inp.split()
                    for w in words:
                        if ext in w:
                            files_touched.add(w.strip("'\"()"))
                            break

    if tools_used:
        parts.append(f"Tools: {', '.join(sorted(tools_used))}")

    if files_touched:
        parts.append(f"Files: {', '.join(sorted(list(files_touched)[:15]))}")

    parts.append(f"Observations: {len(observations)}")

    return "\n".join(parts)


def _cleanup(session_id: str):
    """Clean up session state files."""
    try:
        if SESSION_STATE.exists():
            SESSION_STATE.unlink()
    except Exception:
        pass

    # Keep capture files for debugging — they're small JSONL
    # Could add a cleanup cron for old captures if needed


if __name__ == "__main__":
    main()
