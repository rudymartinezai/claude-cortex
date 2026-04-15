"""
miner.py — Batch index files into the cortex.

Reads config.yaml to know the region + clusters.
Routes each file to the right cluster based on keywords.
Stores verbatim chunks as traces.
"""

import hashlib
import os
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .store import SKIP_DIRS, get_collection, add_trace, trace_id
from .config import CortexConfig

READABLE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".html", ".css", ".java",
    ".go", ".rs", ".rb", ".sh", ".csv", ".sql", ".toml",
}

SKIP_FILENAMES = {
    "cortex.yaml", "config.yaml", ".gitignore",
    "package-lock.json", "mempalace.yaml",
}

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 50
MAX_FILE_SIZE = 10 * 1024 * 1024


def _chunk_text(text: str) -> list:
    """Split text into overlapping chunks."""
    if len(text) <= CHUNK_SIZE:
        return [text] if len(text) >= MIN_CHUNK_SIZE else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if len(chunk) >= MIN_CHUNK_SIZE:
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP
    return chunks


def _classify_cluster(content: str, filename: str, cluster_keywords: dict) -> str:
    """Classify content into a cluster based on keywords."""
    content_lower = content.lower()
    filename_lower = filename.lower()

    scores = {}
    for cluster_name, keywords in cluster_keywords.items():
        if not keywords:
            continue
        score = 0
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in filename_lower:
                score += 3
            if kw_lower in content_lower:
                score += content_lower.count(kw_lower)
        scores[cluster_name] = score

    if scores:
        best = max(scores, key=scores.get)
        if scores[best] > 0:
            return best
    return "general"


def _file_hash(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def mine_directory(
    directory: str,
    region: str = None,
    agent: str = "cortex",
    config: CortexConfig = None,
    dry_run: bool = False,
    limit: int = 0,
) -> dict:
    """Mine a directory into the cortex. Returns stats."""
    config = config or CortexConfig()
    region = region or config.region
    cluster_keywords = config.get_cluster_keywords()

    col = get_collection(config.cortex_path, config.collection_name)

    stats = {
        "files_processed": 0,
        "files_skipped": 0,
        "traces_filed": 0,
        "by_cluster": defaultdict(int),
    }

    files = []
    for root, dirs, filenames in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in READABLE_EXTENSIONS:
                continue
            if fname in SKIP_FILENAMES:
                continue
            filepath = os.path.join(root, fname)
            if os.path.getsize(filepath) > MAX_FILE_SIZE:
                continue
            files.append(filepath)

    if limit > 0:
        files = files[:limit]

    total = len(files)
    for i, filepath in enumerate(files, 1):
        fname = os.path.basename(filepath)

        try:
            with open(filepath, "r", errors="replace") as f:
                content = f.read()
        except Exception:
            continue

        if len(content.strip()) < MIN_CHUNK_SIZE:
            stats["files_skipped"] += 1
            continue

        fhash = _file_hash(filepath)
        cluster = _classify_cluster(content, fname, cluster_keywords)

        chunks = _chunk_text(content)
        chunk_count = 0

        for chunk in chunks:
            if dry_run:
                chunk_count += 1
                continue

            add_trace(
                col,
                content=chunk,
                region=region,
                cluster=cluster,
                source=fname,
                agent=agent,
                metadata={"file_hash": fhash},
            )
            chunk_count += 1

        action = "DRY RUN" if dry_run else "✓"
        print(f"  {action} [{i:>4}/{total}] {fname:<55} +{chunk_count}")

        stats["files_processed"] += 1
        stats["traces_filed"] += chunk_count
        stats["by_cluster"][cluster] += 1

    return dict(stats)
