"""
store.py — Core storage operations for claude-cortex.

Manages trace storage, retrieval, and deduplication.
A trace is a single chunk of verbatim memory stored in the cortex.
"""

import hashlib
import os
import threading

from .backends.chroma import ChromaBackend
from .config import CortexConfig

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "coverage", ".cortex", ".mempalace",
    ".ruff_cache", ".mypy_cache", ".pytest_cache", ".cache",
    ".tox", ".nox", ".idea", ".vscode", ".ipynb_checkpoints",
    ".eggs", "htmlcov", "target",
}

_DEFAULT_BACKEND = ChromaBackend()
_mine_lock = threading.Lock()

NORMALIZE_VERSION = 1


def get_collection(
    store_path: str,
    collection_name: str = "cortex_traces",
    create: bool = True,
):
    """Get the trace collection through the backend layer."""
    return _DEFAULT_BACKEND.get_collection(
        store_path, collection_name=collection_name, create=create,
    )


def trace_id(content: str, source: str = "", region: str = "", cluster: str = "") -> str:
    """Generate deterministic ID for a trace."""
    key = f"{region}:{cluster}:{source}:{content[:200]}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def trace_exists(collection, tid: str) -> bool:
    """Check if a trace already exists."""
    try:
        result = collection.get(ids=[tid])
        return bool(result and result.get("ids"))
    except Exception:
        return False


def add_trace(
    collection,
    content: str,
    region: str,
    cluster: str,
    source: str = "",
    agent: str = "cortex",
    metadata: dict = None,
):
    """Add a single trace to the cortex."""
    tid = trace_id(content, source, region, cluster)

    meta = {
        "region": region,
        "cluster": cluster,
        "source": source,
        "agent": agent,
        "normalize_version": NORMALIZE_VERSION,
    }
    if metadata:
        meta.update(metadata)

    collection.upsert(
        documents=[content],
        ids=[tid],
        metadatas=[meta],
    )
    return tid


def file_already_mined(collection, file_hash: str, source: str) -> bool:
    """Check if a file has already been mined (by content hash)."""
    try:
        result = collection.get(
            where={"source": source, "file_hash": file_hash},
            limit=1,
        )
        return bool(result and result.get("ids"))
    except Exception:
        return False
