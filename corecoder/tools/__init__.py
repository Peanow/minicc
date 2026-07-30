"""Tool registry.

``ALL_TOOLS`` and ``get_tool`` remain as compatibility helpers. Agent
instances use a private :class:`ToolRegistry` so wiring a skill, memory, or
sub-agent tool cannot leak state into another agent.
"""

from collections.abc import Iterable

from .bash import BashTool
from .read import ReadFileTool
from .write import WriteFileTool
from .edit import EditFileTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .agent import AgentTool
from .skill import SkillTool
from .memory_search import MemorySearchTool
from .memory_save import MemorySaveTool
from .edit import _changed_files

def build_default_tools(changed_files: set[str] | None = None):
    """Create a fresh set of built-in tools."""
    changed_files = changed_files if changed_files is not None else set()
    return [
        BashTool(),
        ReadFileTool(),
        WriteFileTool(changed_files),
        EditFileTool(changed_files),
        GlobTool(),
        GrepTool(),
        AgentTool(),
        SkillTool(),
        MemorySearchTool(),
        MemorySaveTool(),
    ]


class ToolRegistry:
    """An ordered, instance-local registry of tools."""

    def __init__(self, tools: Iterable | None = None):
        items = list(tools) if tools is not None else build_default_tools()
        self._tools = {}
        for tool in items:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str):
        return self._tools.get(name)

    def schemas(self) -> list[dict]:
        return [tool.schema() for tool in self._tools.values()]

    def values(self) -> list:
        return list(self._tools.values())

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self):
        return len(self._tools)

    @property
    def changed_files(self) -> set[str]:
        changed: set[str] = set()
        for tool in self._tools.values():
            changed.update(getattr(tool, "changed_files", set()))
        return changed


# Backward-compatible global tools for library users that imported these
# helpers before ToolRegistry existed.
ALL_TOOLS = build_default_tools(_changed_files)


def get_tool(name: str):
    """Look up a tool in the legacy global registry."""
    for t in ALL_TOOLS:
        if t.name == name:
            return t
    return None
