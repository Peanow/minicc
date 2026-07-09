"""Cross-session memory with SQLite + FTS5 + ChromaDB semantic search.

Dual-store architecture:

    **SQLite** — full observation content, structured metadata, FTS5
    keyword index.  The source of truth for complete records.

    **ChromaDB** — vector embeddings + lightweight metadata (project,
    type).  Used for semantic similarity search only.

Two-stage retrieval:

    1. ChromaDB semantic search → matching observation IDs
    2. SQLite SELECT by IDs → full content backfill

This mirrors the architecture described in claude-mem where ChromaDB
handles vector indexing and SQLite (or Postgres) stores the complete
records.

Memory is scoped by *project* (derived from the git root), so different
projects never see each other's observations.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .embedding import EmbeddingService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MEMORY_DIR = Path.home() / ".corecoder" / "memory"
_DB_NAME = "memory.db"
_CHROMA_DIR = _MEMORY_DIR / "chroma"


def _db_path() -> Path:
    return _MEMORY_DIR / _DB_NAME


# ---------------------------------------------------------------------------
# Project identification
# ---------------------------------------------------------------------------

def get_project_name(cwd: str | Path | None = None) -> str:
    """Derive a project name from the git root."""
    start = Path(cwd) if cwd else Path.cwd()
    cur = start.resolve()
    home = Path.home()
    while True:
        if (cur / ".git").is_dir():
            parent = cur.parent.name
            return f"{parent}/{cur.name}" if parent else cur.name
        if cur == home or cur == cur.parent:
            break
        cur = cur.parent
    return start.resolve().name


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Observation:
    """A single memory entry."""
    id: int = 0
    project: str = ""
    kind: str = "observation"
    type: str = "discovery"
    title: str = ""
    content: str = ""
    files: list[str] = field(default_factory=list)
    session_id: str = ""
    created_at: str = ""
    content_hash: str = ""
    score: float = 0.0


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'observation',
    type TEXT NOT NULL DEFAULT 'discovery',
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    files TEXT DEFAULT '[]',
    session_id TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    UNIQUE(project, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_obs_project
    ON observations(project, created_at DESC);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS observations_fts
    USING fts5(title, content, files, content='observations', content_rowid='id',
               tokenize='porter unicode61');
"""

_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS obs_ai AFTER INSERT ON observations BEGIN
    INSERT INTO observations_fts(rowid, title, content, files)
    VALUES (new.id, new.title, new.content, new.files);
END;

CREATE TRIGGER IF NOT EXISTS obs_ad AFTER DELETE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, files)
    VALUES ('delete', old.id, old.title, old.content, old.files);
END;

CREATE TRIGGER IF NOT EXISTS obs_au AFTER UPDATE ON observations BEGIN
    INSERT INTO observations_fts(observations_fts, rowid, title, content, files)
    VALUES ('delete', old.id, old.title, old.content, old.files);
    INSERT INTO observations_fts(rowid, title, content, files)
    VALUES (new.id, new.title, new.content, new.files);
END;
"""


class MemoryStore:
    """Dual-store observation manager: SQLite + ChromaDB.

    SQLite stores full content; ChromaDB stores vector embeddings.
    Searches go to ChromaDB for semantic matching, then SQLite
    for content backfill.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        chroma_dir: Path | None = None,
        embedding_dims: int = 512,
    ):
        self._dims = embedding_dims
        self._path = db_path or _db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._chroma_dir = chroma_dir or _CHROMA_DIR

        # SQLite connection
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._init_sqlite_schema()

        # ChromaDB — lazy init on first use
        self._chroma_client = None
        self._chroma_collection = None

    # ---- ChromaDB lazy init ----

    def _ensure_chroma(self):
        """Lazy-initialize ChromaDB client and collection."""
        if self._chroma_client is not None:
            return
        try:
            import chromadb
            self._chroma_client = chromadb.PersistentClient(path=str(self._chroma_dir))
            self._chroma_collection = self._chroma_client.get_or_create_collection(
                name="observations",
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.warning("ChromaDB init failed: %s", e)
            self._chroma_client = None
            self._chroma_collection = None

    def _chroma_available(self) -> bool:
        self._ensure_chroma()
        return self._chroma_collection is not None

    # ---- SQLite schema init ----

    def _init_sqlite_schema(self):
        self._conn.executescript(_SCHEMA)
        try:
            self._conn.executescript(_FTS_SCHEMA)
            self._conn.executescript(_FTS_TRIGGERS)
        except sqlite3.OperationalError:
            self._conn.rollback()
        self._conn.commit()

    # ---- write ----

    def save(self, obs: Observation, embedding: list[float] | None = None) -> int | None:
        """Insert an observation into SQLite and (optionally) ChromaDB.

        Returns the row id, or None on duplicate.
        """
        if not obs.content_hash:
            obs.content_hash = _hash(obs.project, obs.title, obs.content)
        if not obs.created_at:
            obs.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")

        try:
            cur = self._conn.execute(
                """INSERT INTO observations
                   (project, kind, type, title, content, files, session_id,
                    created_at, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    obs.project, obs.kind, obs.type, obs.title, obs.content,
                    json.dumps(obs.files), obs.session_id,
                    obs.created_at, obs.content_hash,
                ),
            )
            self._conn.commit()
            row_id = cur.lastrowid
        except sqlite3.IntegrityError:
            return None

        # write to ChromaDB if embedding provided
        if embedding and self._chroma_available():
            self._save_to_chroma(row_id, obs, embedding)

        return row_id

    def _save_to_chroma(
        self,
        row_id: int,
        obs: Observation,
        embedding: list[float],
    ):
        """Persist vector + metadata to ChromaDB."""
        try:
            self._chroma_collection.upsert(
                ids=[str(row_id)],
                embeddings=[embedding],
                metadatas=[{
                    "project": obs.project,
                    "type": obs.type,
                    "kind": obs.kind,
                }],
                documents=[f"{obs.title}: {obs.content}"],
            )
        except Exception as e:
            logger.warning("ChromaDB upsert failed: %s", e)

    def save_many(
        self,
        observations: list[Observation],
        embeddings: list[list[float] | None] | None = None,
    ) -> list[int | None]:
        """Batch insert."""
        results = []
        for i, obs in enumerate(observations):
            emb = embeddings[i] if embeddings and i < len(embeddings) else None
            results.append(self.save(obs, embedding=emb))
        return results

    # ---- read ----

    def get_recent(self, project: str, limit: int = 10) -> list[Observation]:
        """Return the most recent observations for a project."""
        rows = self._conn.execute(
            "SELECT * FROM observations WHERE project = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        return [_row_to_obs(r) for r in rows]

    def get_recent_titles(self, project: str, limit: int = 20) -> list[dict]:
        """Return lightweight title/type/created_at for system prompt."""
        rows = self._conn.execute(
            "SELECT id, type, title, created_at FROM observations "
            "WHERE project = ? ORDER BY created_at DESC LIMIT ?",
            (project, limit),
        ).fetchall()
        return [
            {"id": r["id"], "type": r["type"], "title": r["title"],
             "created_at": r["created_at"]}
            for r in rows
        ]

    def get_by_ids(self, ids: list[int]) -> list[Observation]:
        """Fetch full observations by IDs. Used after ChromaDB semantic match."""
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT * FROM observations WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        return [_row_to_obs(r) for r in rows]

    def count(self, project: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM observations WHERE project = ?",
            (project,),
        ).fetchone()
        return row[0] if row else 0

    # ---- search ----

    def search(self, project: str, query: str, limit: int = 10) -> list[Observation]:
        """FTS5 keyword search within a project."""
        safe_query = query.replace('"', '""')
        rows = self._conn.execute(
            """SELECT o.* FROM observations o
               JOIN observations_fts fts ON o.id = fts.rowid
               WHERE observations_fts MATCH ?
               AND o.project = ?
               ORDER BY rank
               LIMIT ?""",
            (f'"{safe_query}"', project, limit),
        ).fetchall()

        if not rows and len(query) >= 2:
            rows = self._conn.execute(
                """SELECT * FROM observations
                   WHERE project = ?
                   AND (title LIKE ? OR content LIKE ?)
                   ORDER BY created_at DESC LIMIT ?""",
                (project, f"%{query}%", f"%{query}%", limit),
            ).fetchall()

        return [_row_to_obs(r) for r in rows]

    def semantic_search(
        self,
        project: str,
        query_embedding: list[float],
        limit: int = 10,
    ) -> list[Observation]:
        """Two-stage semantic search: ChromaDB → SQLite backfill.

        1. Query ChromaDB for matching IDs by cosine similarity
        2. Fetch full content from SQLite by those IDs
        """
        if not self._chroma_available():
            return []

        try:
            results = self._chroma_collection.query(
                query_embeddings=[query_embedding],
                where={"project": project},
                n_results=limit,
                include=["distances", "metadatas"],
            )
        except Exception as e:
            logger.warning("ChromaDB query failed: %s", e)
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        # two-stage: ChromaDB gave us IDs → SQLite backfills full content
        chroma_ids = results["ids"][0]
        chroma_distances = results["distances"][0]
        obs_ids = [int(i) for i in chroma_ids]

        observations = self.get_by_ids(obs_ids)

        # attach similarity scores (1 - distance for cosine)
        id_to_obs = {o.id: o for o in observations}
        scored = []
        for cid, dist in zip(chroma_ids, chroma_distances):
            oid = int(cid)
            if oid in id_to_obs:
                obs = id_to_obs[oid]
                obs.score = round(1.0 - dist, 4)
                scored.append(obs)

        return scored

    def hybrid_search(
        self,
        project: str,
        query: str,
        query_embedding: list[float] | None = None,
        limit: int = 10,
    ) -> list[Observation]:
        """Combine FTS5 keyword and ChromaDB semantic search."""
        seen_ids: dict[int, Observation] = {}

        # FTS5 results
        fts_results = self.search(project, query, limit=limit * 2)
        for obs in fts_results:
            obs.score = max(obs.score, 0.5)
            seen_ids[obs.id] = obs

        # Semantic results via ChromaDB
        if query_embedding:
            sem_results = self.semantic_search(project, query_embedding, limit=limit * 2)
            for obs in sem_results:
                if obs.id in seen_ids:
                    existing = seen_ids[obs.id]
                    existing.score = max(existing.score, obs.score)
                else:
                    seen_ids[obs.id] = obs

        results = sorted(seen_ids.values(), key=lambda o: o.score, reverse=True)
        return results[:limit]

    # ---- delete ----

    def delete_project(self, project: str) -> int:
        count = self.count(project)

        # collect IDs before deleting from SQLite
        rows = self._conn.execute(
            "SELECT id FROM observations WHERE project = ?", (project,),
        ).fetchall()
        ids_to_delete = [str(r["id"]) for r in rows]

        self._conn.execute(
            "DELETE FROM observations WHERE project = ?", (project,),
        )
        self._conn.commit()

        # also delete from ChromaDB
        if ids_to_delete and self._chroma_available():
            try:
                self._chroma_collection.delete(ids=ids_to_delete)
            except Exception as e:
                logger.warning("ChromaDB delete failed: %s", e)

        return count

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Row ↔ Observation conversion
# ---------------------------------------------------------------------------

def _row_to_obs(row: sqlite3.Row) -> Observation:
    return Observation(
        id=row["id"],
        project=row["project"],
        kind=row["kind"],
        type=row["type"],
        title=row["title"],
        content=row["content"],
        files=json.loads(row["files"]) if row["files"] else [],
        session_id=row["session_id"],
        created_at=row["created_at"],
        content_hash=row["content_hash"],
    )


# ---------------------------------------------------------------------------
# Dedup hash
# ---------------------------------------------------------------------------

def _hash(project: str, title: str, content: str) -> str:
    raw = f"{project}::{title}::{content[:500]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Observation extraction from conversation
# ---------------------------------------------------------------------------

def extract_observations(
    messages: list[dict],
    project: str,
    session_id: str = "",
) -> list[Observation]:
    """Extract observations from a conversation without LLM."""
    observations: list[Observation] = []

    edited_files = _extract_edited_files(messages)
    if edited_files:
        observations.append(Observation(
            project=project, kind="observation", type="change",
            title=f"Modified {len(edited_files)} file(s)",
            content="Files modified: " + ", ".join(edited_files),
            files=edited_files, session_id=session_id,
        ))

    errors = _extract_errors(messages)
    if errors:
        observations.append(Observation(
            project=project, kind="observation", type="bugfix",
            title=f"Encountered {len(errors)} error(s)",
            content="\n".join(errors[:5]),
            files=[], session_id=session_id,
        ))

    decisions = _extract_decisions(messages)
    if decisions:
        observations.append(Observation(
            project=project, kind="observation", type="decision",
            title=f"{len(decisions)} decision(s) made",
            content="\n".join(decisions[:5]),
            files=[], session_id=session_id,
        ))

    return observations


def _extract_edited_files(messages: list[dict]) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        for pattern in [
            r"(?:Wrote|Edited|Created|Modified|Updated)\s+[`']?([^\s:`']+)",
            r"(?:File|file):\s*([^\s,:]+)",
        ]:
            for match in re.finditer(pattern, content):
                f = match.group(1).strip().rstrip(":")
                if f and f not in seen and not f.startswith("Error"):
                    seen.add(f)
                    files.append(f)
    return files


def _extract_errors(messages: list[dict]) -> list[str]:
    errors: list[str] = []
    for m in messages:
        if m.get("role") != "tool":
            continue
        content = m.get("content", "")
        if "Error" in content or "error" in content or "FAILED" in content:
            for line in content.splitlines():
                line = line.strip()
                if "Error" in line or "error" in line or "FAILED" in line:
                    if len(line) > 10:
                        errors.append(line[:200])
                        break
    return errors[:5]


def _extract_decisions(messages: list[dict]) -> list[str]:
    decisions: list[str] = []
    patterns = [
        r"(?:决定|decided|should|will|going to|plan to|let's|we'll)[^.]*\.",
        r"(?:架构|architecture|approach|strategy|pattern)[^.]*\.",
    ]
    for m in messages:
        if m.get("role") != "assistant":
            continue
        content = m.get("content", "")
        if not content:
            continue
        for pattern in patterns:
            for match in re.finditer(pattern, content, re.IGNORECASE):
                text = match.group(0).strip()
                if len(text) > 15 and len(text) < 200:
                    decisions.append(text)
    return decisions[:5]


# ---------------------------------------------------------------------------
# Context formatting
# ---------------------------------------------------------------------------

def format_memory_directory(titles: list[dict]) -> str:
    """Lightweight memory directory for the system prompt (titles only)."""
    if not titles:
        return ""
    lines = [
        "# Memory",
        f"You have {len(titles)} memory item(s) from previous sessions. "
        "Use the `memory_search` tool to retrieve relevant ones when needed.",
    ]
    for t in titles[:10]:
        lines.append(f"- [{t['type']}] {t['title']}")
    return "\n".join(lines)


def format_memory_context(observations: list[Observation]) -> str:
    """Format observations for on-demand injection (content included)."""
    if not observations:
        return ""
    lines = ["[Relevant memories from previous sessions]"]
    for obs in reversed(observations):
        age = _time_ago(obs.created_at)
        lines.append(f"- [{obs.type}] {obs.title} ({age})")
        snippet = obs.content[:200]
        if len(obs.content) > 200:
            snippet += "..."
        lines.append(f"  {snippet}")
        if obs.files:
            lines.append(f"  Files: {', '.join(obs.files[:5])}")
    return "\n".join(lines)


def _time_ago(created_at: str) -> str:
    try:
        t = time.mktime(time.strptime(created_at, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, OverflowError):
        return created_at
    diff = time.time() - t
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff / 60)}m ago"
    if diff < 86400:
        return f"{int(diff / 3600)}h ago"
    if diff < 604800:
        return f"{int(diff / 86400)}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(t))


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def get_store(embedding_dims: int = 512) -> MemoryStore:
    return MemoryStore(embedding_dims=embedding_dims)
