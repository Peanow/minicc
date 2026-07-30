"""Sub-agent spawning (inspired by Claude Code's AgentTool, 1397 lines).

The idea: for complex sub-tasks, spawn an independent agent with its own
conversation history and tool access. This lets the main agent delegate
work like "go research this codebase and report back" without polluting
its own context window.

The sub-agent runs to completion and returns a text summary.
"""

from .base import Tool


class AgentTool(Tool):
    name = "agent"
    description = (
        "Spawn a read-only sub-agent to research a complex sub-task. "
        "The sub-agent has an isolated context and read/search tools, and "
        "returns a concise report without modifying the workspace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What the sub-agent should accomplish",
            },
        },
        "required": ["task"],
    }

    # set by Agent.__init__ after construction
    _parent_agent = None

    def execute(self, task: str) -> str:
        if self._parent_agent is None:
            return "Error: agent tool not initialized (no parent agent)"

        # import here to avoid circular dep
        from ..agent import Agent

        from ..tools import build_default_tools

        parent = self._parent_agent
        read_only_names = {"read_file", "glob", "grep"}
        read_only_tools = [
            tool for tool in build_default_tools()
            if tool.name in read_only_names
        ]
        sub = Agent(
            llm=parent.llm,
            tools=read_only_tools,
            max_context_tokens=parent.context.max_tokens,
            max_rounds=20,
            hooks=type(parent.hooks)(
                hooks=dict(parent.hooks.hooks),
                source=parent.hooks.source,
            ),
        )

        try:
            result = sub.chat(task)
            # trim long results to avoid blowing up parent's context
            if len(result) > 5000:
                result = result[:4500] + "\n... (sub-agent output truncated)"
            return f"[Sub-agent completed]\n{result}"
        except Exception as e:
            return f"Sub-agent error: {e}"
