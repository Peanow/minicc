"""Memory save tool — lets the LLM manually save observations.

When the model identifies something worth remembering across sessions
(a key decision, an architectural insight, a recurring pattern), it
invokes ``memory_save(title="...", content="...")`` to persist it.
"""

from .base import Tool


class MemorySaveTool(Tool):
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

    def execute(self, title: str, content: str, type: str = "discovery") -> str:
        if self._agent is None:
            return "Error: memory save not initialized (no agent)"

        from ..memory import MemoryStore, Observation, get_project_name

        project = get_project_name()
        obs = Observation(
            project=project,
            kind="manual",
            type=type,
            title=title,
            content=content,
        )

        # generate embedding if available
        embedding = None
        if self._agent.embedding.is_available():
            embedding = self._agent.embedding.embed(f"{title}: {content}")

        store = MemoryStore(embedding_dims=self._agent.embedding.dims)
        try:
            row_id = store.save(obs, embedding=embedding)
        finally:
            store.close()

        if row_id is not None:
            emb_status = "with embedding" if embedding else "without embedding"
            return f"Memory saved: [{type}] {title} ({emb_status}, id={row_id})"
        else:
            return f"Memory already exists: {title} (duplicate)"
