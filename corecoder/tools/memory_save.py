"""Memory save tool — lets the LLM manually save observations.

When the model identifies something worth remembering across sessions
(a key decision, an architectural insight, a recurring pattern), it
invokes ``memory_save(title="...", content="...")`` to persist it.
"""

from .base import Effect, Tool, ToolResult


class MemorySaveTool(Tool):
    effects = frozenset({Effect.APP_STATE_WRITE})
    name = "memory_save"
    description = (
        "Save an observation to cross-session memory. Use this to persist "
        "important context that should carry over to future sessions: key "
        "decisions, architectural insights, recurring patterns, or important "
        "discoveries about the codebase."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short title for the observation",
            },
            "content": {
                "type": "string",
                "description": "Full content of the observation to remember",
            },
            "type": {
                "type": "string",
                "description": "Category: decision, bugfix, feature, discovery, change (default: discovery)",
            },
        },
        "required": ["title", "content"],
    }

    # set by Agent.__init__ after construction
    _agent = None

    def execute(self, title: str, content: str, type: str = "discovery") -> ToolResult:
        if self._agent is None:
            return ToolResult.error(
                "memory save not initialized (no agent)",
                error_type="NotInitialized",
            )
        try:
            row_id, embedded = self._agent.memory_service.save(
                title=title,
                content=content,
                kind=type,
            )
        except Exception as exc:
            return ToolResult.error(str(exc), error_type=exc.__class__.__name__)

        if row_id is not None:
            emb_status = "with embedding" if embedded else "without embedding"
            return ToolResult.success(
                f"Memory saved: [{type}] {title} ({emb_status}, id={row_id})"
            )
        else:
            return ToolResult.success(f"Memory already exists: {title} (duplicate)")
