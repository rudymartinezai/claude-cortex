"""
knowledge_graph.py — Temporal Entity-Relationship Graph for claude-cortex.

Real knowledge graph with:
  - Entity nodes (people, projects, tools, concepts)
  - Typed relationship edges
  - Temporal validity (valid_from -> valid_to — knows WHEN facts are true)
  - Trace references (links back to verbatim memory)

Storage: SQLite (local, no dependencies, free)
"""

import hashlib
import json
import os
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

DEFAULT_KG_PATH = os.path.expanduser("~/.cortex/knowledge_graph.db")


class KnowledgeGraph:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DEFAULT_KG_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = None
        self._lock = threading.Lock()
        self._init_db()

    def _conn(self):
        if self._connection is None:
            self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def _init_db(self):
        conn = self._conn()
        conn.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT DEFAULT 'unknown',
                properties TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS triples (
                id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL DEFAULT 1.0,
                source_trace TEXT,
                source_file TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (subject) REFERENCES entities(id),
                FOREIGN KEY (object) REFERENCES entities(id)
            );

            CREATE INDEX IF NOT EXISTS idx_triples_subject ON triples(subject);
            CREATE INDEX IF NOT EXISTS idx_triples_object ON triples(object);
            CREATE INDEX IF NOT EXISTS idx_triples_predicate ON triples(predicate);
        """)
        conn.commit()

    def _entity_id(self, name: str) -> str:
        return hashlib.sha256(name.lower().strip().encode()).hexdigest()[:12]

    def _triple_id(self, subject: str, predicate: str, obj: str) -> str:
        key = f"{subject.lower()}|{predicate.lower()}|{obj.lower()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _ensure_entity(self, name: str, entity_type: str = "unknown"):
        eid = self._entity_id(name)
        conn = self._conn()
        conn.execute(
            "INSERT OR IGNORE INTO entities (id, name, type) VALUES (?, ?, ?)",
            (eid, name.strip(), entity_type),
        )
        conn.commit()
        return eid

    def add_triple(
        self,
        subject: str,
        predicate: str,
        obj: str,
        valid_from: str = None,
        valid_to: str = None,
        confidence: float = 1.0,
        source_trace: str = None,
        source_file: str = None,
    ) -> str:
        """Add a fact: subject -> predicate -> object with temporal validity."""
        with self._lock:
            sid = self._ensure_entity(subject)
            oid = self._ensure_entity(obj)
            tid = self._triple_id(subject, predicate, obj)

            conn = self._conn()
            conn.execute(
                """INSERT OR REPLACE INTO triples
                   (id, subject, predicate, object, valid_from, valid_to,
                    confidence, source_trace, source_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, sid, predicate.strip(), oid,
                 valid_from, valid_to, confidence,
                 source_trace, source_file),
            )
            conn.commit()
            return tid

    def invalidate(self, subject: str, predicate: str, obj: str, ended: str = None):
        """Mark a fact as no longer true."""
        ended = ended or datetime.now().isoformat()[:10]
        tid = self._triple_id(subject, predicate, obj)
        with self._lock:
            self._conn().execute(
                "UPDATE triples SET valid_to = ? WHERE id = ?", (ended, tid)
            )
            self._conn().commit()

    def query_entity(self, name: str, as_of: str = None, direction: str = "both") -> list:
        """Query all facts about an entity."""
        eid = self._entity_id(name)
        conn = self._conn()
        results = []

        queries = []
        if direction in ("out", "both"):
            queries.append(("subject", eid))
        if direction in ("in", "both"):
            queries.append(("object", eid))

        for col, val in queries:
            rows = conn.execute(
                f"""SELECT t.*,
                       s.name as subject_name, o.name as object_name
                    FROM triples t
                    JOIN entities s ON t.subject = s.id
                    JOIN entities o ON t.object = o.id
                    WHERE t.{col} = ?""",
                (val,),
            ).fetchall()

            for row in rows:
                if as_of:
                    vf = row["valid_from"] or "0000-01-01"
                    vt = row["valid_to"] or "9999-12-31"
                    if not (vf <= as_of <= vt):
                        continue
                results.append(dict(row))

        return results

    def timeline(self, name: str) -> list:
        """Chronological timeline of all facts about an entity."""
        eid = self._entity_id(name)
        conn = self._conn()
        rows = conn.execute(
            """SELECT t.*, s.name as subject_name, o.name as object_name
               FROM triples t
               JOIN entities s ON t.subject = s.id
               JOIN entities o ON t.object = o.id
               WHERE t.subject = ? OR t.object = ?
               ORDER BY COALESCE(t.valid_from, t.created_at) ASC""",
            (eid, eid),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Knowledge graph overview."""
        conn = self._conn()
        entities = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        triples = conn.execute("SELECT COUNT(*) FROM triples").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM triples WHERE valid_to IS NULL"
        ).fetchone()[0]
        predicates = conn.execute(
            "SELECT DISTINCT predicate FROM triples"
        ).fetchall()
        return {
            "entities": entities,
            "triples": triples,
            "active_facts": active,
            "relationship_types": [r[0] for r in predicates],
        }
