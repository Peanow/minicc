"""Instance-local tool construction and lookup."""

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
def build_default_tools(workspace=None):
    """Create a fresh set of built-in tools."""
    changed_files: set[str] = set()
    return [
        BashTool(workspace),
        ReadFileTool(workspace),
        WriteFileTool(changed_files, workspace),
        EditFileTool(changed_files, workspace),
        GlobTool(workspace),
        GrepTool(workspace),
        AgentTool(workspace),
        SkillTool(workspace),
        MemorySearchTool(workspace),
        MemorySaveTool(workspace),
    ]


class ToolRegistry:
    """An ordered, instance-local registry of tools."""

    def __init__(self, tools: Iterable | None = None, *, workspace=None):
        items = list(tools) if tools is not None else build_default_tools(workspace)
        self._tools = {}
        for tool in items:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            if workspace is not None:
                tool.bind_workspace(workspace)
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


__all__ = ["ToolRegistry", "build_default_tools"]
