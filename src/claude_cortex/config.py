"""
claude-cortex configuration system.

Priority: env vars > config file (~/.cortex/config.yaml) > defaults

Cortex metaphor:
  - Region  = top-level domain (a project, a person, a topic)
  - Cluster = specific topic within a region
  - Trace   = one chunk of stored memory
  - Synapse = cross-region connection
"""

import json
import os
import re
from pathlib import Path

import yaml

# ── Input validation ─────────────────────────────────────────────────────────

MAX_NAME_LENGTH = 128
_SAFE_NAME_RE = re.compile(r"^(?:[^\W_]|[^\W_][\w .'-]{0,126}[^\W_])$")


def sanitize_name(value: str, field_name: str = "name") -> str:
    """Validate and sanitize a region/cluster name."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    value = value.strip()
    if len(value) > MAX_NAME_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length of {MAX_NAME_LENGTH}")
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} contains invalid path characters")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains null bytes")
    if not _SAFE_NAME_RE.match(value):
        raise ValueError(f"{field_name} contains invalid characters")
    return value


def sanitize_content(value: str, max_length: int = 100_000) -> str:
    """Validate trace content length."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("content must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"content exceeds maximum length of {max_length}")
    if "\x00" in value:
        raise ValueError("content contains null bytes")
    return value


DEFAULT_CORTEX_PATH = os.path.expanduser("~/.cortex/store")
DEFAULT_COLLECTION_NAME = "cortex_traces"
DEFAULT_CONFIG_PATH = os.path.expanduser("~/.cortex/config.yaml")

DEFAULT_REGIONS = [
    "general",
]


class CortexConfig:
    """Central configuration for claude-cortex."""

    def __init__(self, config_path: str = None):
        self.config_path = config_path or os.environ.get(
            "CORTEX_CONFIG_PATH", DEFAULT_CONFIG_PATH
        )
        self._data = {}
        self._load()

    def _load(self):
        if os.path.isfile(self.config_path):
            with open(self.config_path) as f:
                self._data = yaml.safe_load(f) or {}

    @property
    def cortex_path(self) -> str:
        return os.environ.get(
            "CORTEX_STORE_PATH",
            self._data.get("store_path", DEFAULT_CORTEX_PATH),
        )

    @property
    def collection_name(self) -> str:
        return self._data.get("collection_name", DEFAULT_COLLECTION_NAME)

    @property
    def region(self) -> str:
        return self._data.get("region", "default")

    @property
    def clusters(self) -> list:
        raw = self._data.get("clusters", [])
        if isinstance(raw, list):
            return raw
        return DEFAULT_REGIONS

    def get_cluster_keywords(self) -> dict:
        """Return {cluster_name: [keywords]} mapping."""
        result = {}
        for c in self.clusters:
            if isinstance(c, dict):
                name = c.get("name", "general")
                keywords = c.get("keywords", [])
                result[name] = keywords
            elif isinstance(c, str):
                result[c] = []
        return result
