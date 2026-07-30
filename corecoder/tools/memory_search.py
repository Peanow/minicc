"""Memory search tool — hybrid keyword and semantic search in SQLite.

When the model needs historical context from previous sessions (past
decisions, files modified, errors encountered), it invokes
``memory_search(query="authentication")`` to retrieve relevant
observations.

Search flow:
    1. Embed the query via local model
    2. Compare with SQLite embedding BLOBs
    3. Merge with FTS5 keyword results
"""

from .base import Tool


class MemorySearchTool(Tool):
    name = "memory_search"
    description = (
        "Search cross-session memory for relevant context from previous "
        "conversations. Uses optional vector similarity and keyword "
        "matching (FTS5) to find observations about past decisions, "
        "file changes, errors, and discoveries."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query — keywords or natural language description",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results to return (default 10)",
            },
        },
        "required": ["query"],
    }

    # set by Agent.__init__ after construction
    _agent = None

    def execute(self, query: str, limit: int = 10) -> str:
        if self._agent is None:
            return "Error: memory search not initialized (no agent)"

        from ..memory import MemoryStore, get_project_name

        project = get_project_name()
        store = MemoryStore(embedding_dims=self._agent.embedding.dims)
        try:
            # embed the query for semantic search
            query_emb = (
                self._agent.embedding.embed(query)
                if self._agent.embedding.is_available()
                else None
            )

            if query_emb:
                results = store.hybrid_search(project, query, query_emb, limit=limit)
            else:
                results = store.search(project, query, limit=limit)
        finally:
            store.close()

        if not results:
            return f"No memories found for query: {query}"

        lines = [f"Found {len(results)} memory item(s) for '{query}':\n"]
        for obs in results:
            score_str = f" (score: {obs.score:.2f})" if obs.score > 0 else ""
            lines.append(f"[{obs.type}] {obs.title}{score_str}")
            lines.append(f"  {obs.content[:300]}")
            if obs.files:
                lines.append(f"  Files: {', '.join(obs.files[:5])}")
            lines.append("")

        return "\n".join(lines)
