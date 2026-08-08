"""Agent-owned access to cross-session memory."""

from __future__ import annotations

from pathlib import Path

from .embedding import EmbeddingService
from .memory import MemoryStore, Observation, extract_observations


class MemoryService:
    """A persistence boundary that can be disabled without touching the disk."""

    def __init__(
        self,
        *,
        db_path: str | Path,
        project_id: str,
        embedding: EmbeddingService,
        enabled: bool = True,
        writable: bool = True,
    ) -> None:
        self.db_path = Path(db_path)
        self.project_id = project_id
        self.embedding = embedding
        self.enabled = enabled
        self.writable = writable

    def _store(self) -> MemoryStore:
        if not self.enabled:
            raise RuntimeError("memory is disabled for this agent")
        return MemoryStore(
            db_path=self.db_path,
            embedding_dims=self.embedding.dims,
            readonly=not self.writable,
        )

    def recent_titles(self, limit: int = 20) -> list[dict]:
        if not self.enabled or not self.db_path.exists():
            return []
        store = self._store()
        try:
            return store.get_recent_titles(self.project_id, limit=limit)
        finally:
            store.close()

    def search(self, query: str, limit: int = 10):
        if not self.enabled or not self.db_path.exists():
            return []
        query_embedding = (
            self.embedding.embed(query) if self.embedding.is_available() else None
        )
        store = self._store()
        try:
            if query_embedding:
                return store.hybrid_search(
                    self.project_id,
                    query,
                    query_embedding,
                    limit=limit,
                )
            return store.search(self.project_id, query, limit=limit)
        finally:
            store.close()

    def save(
        self,
        title: str,
        content: str | None = None,
        kind: str = "discovery",
    ) -> tuple[int | None, bool]:
        if not self.enabled or not self.writable:
            raise PermissionError("memory writes are disabled")
        if content is None:
            content = title
            title = title.strip().splitlines()[0][:80] or "Manual memory"
        embedding = (
            self.embedding.embed(f"{title}: {content}")
            if self.embedding.is_available()
            else None
        )
        store = self._store()
        try:
            row_id = store.save(
                Observation(
                    project=self.project_id,
                    kind="manual",
                    type=kind,
                    title=title,
                    content=content,
                ),
                embedding=embedding,
            )
        finally:
            store.close()
        return row_id, embedding is not None

    def save_conversation(self, messages: list[dict]) -> int:
        if not self.enabled or not self.writable or not messages:
            return 0
        observations = extract_observations(messages, project=self.project_id)
        if not observations:
            return 0
        texts = [f"{item.title}: {item.content}" for item in observations]
        embeddings = (
            self.embedding.embed_batch(texts)
            if self.embedding.is_available()
            else None
        )
        store = self._store()
        try:
            results = store.save_many(observations, embeddings=embeddings)
        finally:
            store.close()
        return sum(result is not None for result in results)

    def close(self) -> None:
        """MemoryStore connections are short lived, so closing is idempotent."""

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "writable": self.writable,
            "path": str(self.db_path),
        }

    def clear(self) -> int:
        if not self.enabled or not self.writable:
            raise PermissionError("memory writes are disabled")
        if not self.db_path.exists():
            return 0
        store = self._store()
        try:
            return store.delete_project(self.project_id)
        finally:
            store.close()
