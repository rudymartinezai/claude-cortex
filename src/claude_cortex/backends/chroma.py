"""ChromaDB storage backend for claude-cortex."""

import logging
import os
import sqlite3

import chromadb

from .base import BaseCollection

logger = logging.getLogger(__name__)


def _fix_blob_seq_ids(store_path: str):
    """Fix ChromaDB 0.6.x -> 1.5.x migration: BLOB seq_ids -> INTEGER."""
    db_path = os.path.join(store_path, "chroma.sqlite3")
    if not os.path.isfile(db_path):
        return
    try:
        with sqlite3.connect(db_path) as conn:
            for table in ("embeddings", "max_seq_id"):
                try:
                    rows = conn.execute(
                        f"SELECT rowid, seq_id FROM {table} WHERE typeof(seq_id) = 'blob'"
                    ).fetchall()
                except sqlite3.OperationalError:
                    continue
                if not rows:
                    continue
                updates = [
                    (int.from_bytes(blob, byteorder="big"), rowid)
                    for rowid, blob in rows
                ]
                conn.executemany(
                    f"UPDATE {table} SET seq_id = ? WHERE rowid = ?", updates
                )
                logger.info("Fixed %d BLOB seq_ids in %s", len(updates), table)
            conn.commit()
    except Exception:
        logger.exception("Could not fix BLOB seq_ids in %s", db_path)


class ChromaCollection(BaseCollection):
    """Thin adapter over a ChromaDB collection."""

    def __init__(self, collection):
        self._collection = collection

    def add(self, *, documents, ids, metadatas=None):
        self._collection.add(documents=documents, ids=ids, metadatas=metadatas)

    def upsert(self, *, documents, ids, metadatas=None):
        self._collection.upsert(documents=documents, ids=ids, metadatas=metadatas)

    def query(self, **kwargs):
        return self._collection.query(**kwargs)

    def get(self, **kwargs):
        return self._collection.get(**kwargs)

    def count(self) -> int:
        return self._collection.count()

    def delete(self, ids):
        self._collection.delete(ids=ids)


class ChromaBackend:
    """Manages ChromaDB client and collection lifecycle."""

    def get_collection(
        self,
        store_path: str,
        collection_name: str = "cortex_traces",
        create: bool = True,
    ) -> ChromaCollection:
        os.makedirs(store_path, exist_ok=True)
        _fix_blob_seq_ids(store_path)
        client = chromadb.PersistentClient(path=store_path)
        if create:
            col = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            col = client.get_collection(name=collection_name)
        return ChromaCollection(col)
