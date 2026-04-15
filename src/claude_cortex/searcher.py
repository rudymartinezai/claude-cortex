"""
searcher.py — Semantic + keyword hybrid search across the cortex.

Hybrid: BM25 keyword matching + ChromaDB vector similarity.
"""

import logging
import math
import re
from pathlib import Path

from .store import get_collection
from .config import CortexConfig

logger = logging.getLogger("cortex")

_TOKEN_RE = re.compile(r"\w{2,}", re.UNICODE)


class SearchError(Exception):
    """Raised when search cannot proceed."""


def _tokenize(text: str) -> list:
    return _TOKEN_RE.findall(text.lower())


def _bm25_scores(query: str, documents: list, k1: float = 1.5, b: float = 0.75) -> list:
    """Okapi-BM25 scores for reranking."""
    n_docs = len(documents)
    query_terms = set(_tokenize(query))
    if not query_terms or n_docs == 0:
        return [0.0] * n_docs

    tokenized = [_tokenize(d) for d in documents]
    doc_lens = [len(toks) for toks in tokenized]
    if not any(doc_lens):
        return [0.0] * n_docs
    avgdl = sum(doc_lens) / n_docs or 1.0

    df = {term: 0 for term in query_terms}
    for toks in tokenized:
        seen = set(toks) & query_terms
        for term in seen:
            df[term] += 1

    idf = {
        term: math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1)
        for term in query_terms
    }

    scores = []
    for toks, dl in zip(tokenized, doc_lens):
        score = 0.0
        tf_map = {}
        for t in toks:
            tf_map[t] = tf_map.get(t, 0) + 1
        for term in query_terms:
            tf = tf_map.get(term, 0)
            if tf > 0:
                numer = tf * (k1 + 1)
                denom = tf + k1 * (1 - b + b * dl / avgdl)
                score += idf[term] * numer / denom
        scores.append(score)
    return scores


def search(
    query: str,
    region: str = None,
    cluster: str = None,
    n_results: int = 5,
    config: CortexConfig = None,
) -> list:
    """Search the cortex. Returns list of {id, content, region, cluster, source, score}."""
    config = config or CortexConfig()

    try:
        col = get_collection(config.cortex_path, config.collection_name, create=False)
    except Exception:
        raise SearchError(f"No cortex found at {config.cortex_path}")

    if col.count() == 0:
        return []

    # Build where filter
    where = {}
    if region:
        where["region"] = region
    if cluster:
        where["cluster"] = cluster

    # Vector search
    kwargs = {
        "query_texts": [query],
        "n_results": min(n_results * 3, col.count()),  # oversample for reranking
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        kwargs["where"] = where

    try:
        raw = col.query(**kwargs)
    except Exception as e:
        raise SearchError(f"Search failed: {e}")

    if not raw or not raw.get("ids") or not raw["ids"][0]:
        return []

    ids = raw["ids"][0]
    docs = raw["documents"][0]
    metas = raw["metadatas"][0]
    distances = raw["distances"][0]

    # BM25 rerank
    bm25 = _bm25_scores(query, docs)

    # Combine: vector similarity (1 - distance) + BM25
    combined = []
    for i in range(len(ids)):
        vec_score = 1.0 - distances[i] if distances[i] <= 1.0 else 0.0
        hybrid_score = 0.7 * vec_score + 0.3 * (bm25[i] / (max(bm25) or 1.0))
        combined.append({
            "id": ids[i],
            "content": docs[i],
            "region": metas[i].get("region", ""),
            "cluster": metas[i].get("cluster", ""),
            "source": metas[i].get("source", ""),
            "score": round(hybrid_score, 3),
        })

    combined.sort(key=lambda x: x["score"], reverse=True)
    return combined[:n_results]
