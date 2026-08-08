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

from .base import Effect, Tool, ToolResult


class MemorySearchTool(Tool):
    effects = frozenset({Effect.READ_FS})
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

    def execute(self, query: str, limit: int = 10) -> ToolResult:
        if self._agent is None:
            return ToolResult.error(
                "memory search not initialized (no agent)",
                error_type="NotInitialized",
            )

        try:
            results = self._agent.memory_service.search(query, limit=limit)
        except Exception as exc:
            return ToolResult.error(str(exc), error_type=type(exc).__name__)

        if not results:
            return ToolResult.success(f"No memories found for query: {query}")

        lines = [f"Found {len(results)} memory item(s) for '{query}':\n"]
        for obs in results:
            score_str = f" (score: {obs.score:.2f})" if obs.score > 0 else ""
            lines.append(f"[{obs.type}] {obs.title}{score_str}")
            lines.append(f"  {obs.content[:300]}")
            if obs.files:
                lines.append(f"  Files: {', '.join(obs.files[:5])}")
            lines.append("")

        return ToolResult.success("\n".join(lines))
