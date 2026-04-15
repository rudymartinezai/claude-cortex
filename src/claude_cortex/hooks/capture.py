"""
capture.py — Auto-capture hooks for Claude Code.

This is the glue layer. Hooks into Claude Code's lifecycle events
and pipes captured content directly into the cortex in real-time.

No cron. No manual mining. Sessions are indexed as they happen.

Hook types:
  - SessionStart: load relevant context from cortex
  - PostToolUse: capture significant tool operations
  - SessionEnd: index the full session into the cortex
"""

import json
import os
import sys
import hashlib
from datetime import datetime
from pathlib import Path

from ..store import get_collection, add_trace
from ..config import CortexConfig
from ..searcher import search


CAPTURE_DIR = Path(os.path.expanduser("~/.cortex/captures"))
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)


def _session_id() -> str:
    """Generate a unique session ID."""
    return hashlib.sha256(
        f"{datetime.now().isoformat()}-{os.getpid()}".encode()
    ).hexdigest()[:12]


def _classify_content(content: str, config: CortexConfig = None) -> str:
    """Auto-classify captured content into a cluster."""
    config = config or CortexConfig()
    cluster_keywords = config.get_cluster_keywords()

    content_lower = content.lower()
    scores = {}
    for cluster_name, keywords in cluster_keywords.items():
        if not keywords:
            continue
        score = sum(
            content_lower.count(kw.lower()) for kw in keywords
        )
        scores[cluster_name] = score

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "general"


class SessionCapture:
    """Captures a single Claude Code session into the cortex."""

    def __init__(self, config: CortexConfig = None):
        self.config = config or CortexConfig()
        self.session_id = _session_id()
        self.start_time = datetime.now()
        self.observations = []
        self._session_file = CAPTURE_DIR / f"{self.session_id}.jsonl"

    def on_session_start(self) -> dict:
        """Called at session start. Returns context to inject."""
        # Could search cortex for recent/relevant traces
        return {
            "session_id": self.session_id,
            "started": self.start_time.isoformat(),
        }

    def on_tool_use(self, tool_name: str, tool_input: dict, tool_output: str):
        """Called after each tool use. Captures significant operations."""
        # Skip noisy tools
        skip_tools = {"Glob", "Grep", "Read", "Bash"}
        if tool_name in skip_tools and len(str(tool_output)) < 200:
            return

        observation = {
            "type": "tool_use",
            "tool": tool_name,
            "timestamp": datetime.now().isoformat(),
            "input_summary": str(tool_input)[:500],
            "output_summary": str(tool_output)[:1000],
        }
        self.observations.append(observation)

        # Write to session file incrementally
        with open(self._session_file, "a") as f:
            f.write(json.dumps(observation) + "\n")

    def on_user_message(self, message: str):
        """Capture user messages."""
        observation = {
            "type": "user_message",
            "timestamp": datetime.now().isoformat(),
            "content": message[:2000],
        }
        self.observations.append(observation)

        with open(self._session_file, "a") as f:
            f.write(json.dumps(observation) + "\n")

    def on_assistant_message(self, message: str):
        """Capture assistant responses (summarized)."""
        observation = {
            "type": "assistant_message",
            "timestamp": datetime.now().isoformat(),
            "content": message[:2000],
        }
        self.observations.append(observation)

        with open(self._session_file, "a") as f:
            f.write(json.dumps(observation) + "\n")

    def on_session_end(self) -> dict:
        """Called at session end. Indexes everything into the cortex."""
        if not self.observations:
            return {"traces_filed": 0}

        col = get_collection(self.config.cortex_path, self.config.collection_name)
        region = self.config.region
        traces_filed = 0

        # Build session summary
        user_messages = [
            o["content"] for o in self.observations
            if o["type"] == "user_message"
        ]
        tool_uses = [
            o for o in self.observations
            if o["type"] == "tool_use"
        ]

        # Index each significant observation as a trace
        for obs in self.observations:
            content = ""
            if obs["type"] == "user_message":
                content = f"[User] {obs['content']}"
            elif obs["type"] == "assistant_message":
                content = f"[Assistant] {obs['content']}"
            elif obs["type"] == "tool_use":
                content = f"[Tool: {obs['tool']}] {obs.get('input_summary', '')} → {obs.get('output_summary', '')}"

            if len(content.strip()) < 50:
                continue

            cluster = _classify_content(content, self.config)

            add_trace(
                col,
                content=content,
                region=region,
                cluster=cluster,
                source=f"session-{self.session_id}",
                agent="cortex-capture",
                metadata={
                    "session_id": self.session_id,
                    "timestamp": obs["timestamp"],
                    "obs_type": obs["type"],
                },
            )
            traces_filed += 1

        # Index a session summary trace
        summary = self._build_summary(user_messages, tool_uses)
        if summary:
            cluster = _classify_content(summary, self.config)
            add_trace(
                col,
                content=summary,
                region=region,
                cluster=cluster,
                source=f"session-summary-{self.session_id}",
                agent="cortex-capture",
                metadata={
                    "session_id": self.session_id,
                    "is_summary": "true",
                    "obs_count": str(len(self.observations)),
                },
            )
            traces_filed += 1

        return {
            "session_id": self.session_id,
            "traces_filed": traces_filed,
            "observations": len(self.observations),
            "duration_seconds": (datetime.now() - self.start_time).total_seconds(),
        }

    def _build_summary(self, user_messages: list, tool_uses: list) -> str:
        """Build a concise session summary."""
        parts = []
        parts.append(f"Session {self.session_id} ({self.start_time.strftime('%Y-%m-%d %H:%M')})")

        if user_messages:
            parts.append(f"User discussed: {'; '.join(m[:100] for m in user_messages[:10])}")

        if tool_uses:
            tools_used = set(t["tool"] for t in tool_uses)
            parts.append(f"Tools used: {', '.join(tools_used)}")

        files_touched = set()
        for t in tool_uses:
            inp = t.get("input_summary", "")
            if "file_path" in inp or ".py" in inp or ".ts" in inp or ".md" in inp:
                files_touched.add(inp[:100])

        if files_touched:
            parts.append(f"Files: {'; '.join(list(files_touched)[:10])}")

        return "\n".join(parts)
