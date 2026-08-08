"""Base tool contracts with explicit effects and structured results."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..runtime.workspace import WorkspaceState


class Effect(str, Enum):
    READ_FS = "read_fs"
    WRITE_FS = "write_fs"
    EXECUTE = "execute"
    NETWORK = "network"
    APP_STATE_WRITE = "app_state_write"


class ToolStatus(str, Enum):
    SUCCESS = "success"
    ERROR = "error"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ToolResult:
    """Structured output from a tool before executor-level metrics are added."""

    status: ToolStatus = ToolStatus.SUCCESS
    content: str = ""
    error_type: str | None = None
    exit_code: int | None = None
    changed_files: tuple[str, ...] = ()
    diff: str | None = None
    artifacts: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, content: str, **kwargs: Any) -> "ToolResult":
        return cls(status=ToolStatus.SUCCESS, content=content, **kwargs)

    @classmethod
    def error(
        cls,
        content: str,
        *,
        error_type: str | None = None,
        exit_code: int | None = None,
    ) -> "ToolResult":
        return cls(
            status=ToolStatus.ERROR,
            content=content,
            error_type=error_type,
            exit_code=exit_code,
        )

    @classmethod
    def blocked(cls, content: str) -> "ToolResult":
        return cls(status=ToolStatus.BLOCKED, content=content)

    def to_message(self) -> str:
        return self.content or "(no output)"

    def to_dict(self) -> dict[str, Any]:
        """Return the stable wire representation used by traces and adapters."""
        return {
            "status": self.status.value,
            "content": self.content,
            "error_type": self.error_type,
            "exit_code": self.exit_code,
            "changed_files": list(self.changed_files),
            "diff": self.diff,
            "artifacts": dict(self.artifacts),
        }

    # A small ergonomic bridge for callers migrating from the pre-0.4 string
    # contract.  The runtime itself never infers status from these strings.
    def __contains__(self, value: str) -> bool:
        return value in self.content

    def lower(self) -> str:
        return self.content.lower()


def coerce_tool_result(value: ToolResult | str) -> ToolResult:
    """Normalize third-party tools while the public contract moves to ToolResult."""

    if isinstance(value, ToolResult):
        return value
    if not isinstance(value, str):
        return ToolResult.error(
            f"Tool returned unsupported result type: {type(value).__name__}",
            error_type="InvalidToolResult",
        )
    return ToolResult.success(value)


class Tool(ABC):
    """Tool interface. Effects are mandatory for runtime authorization."""

    name: str
    description: str
    parameters: dict  # JSON Schema for the function args
    parallel_safe: bool = False
    effects: frozenset[Effect] = frozenset()

    def __init__(self, workspace: WorkspaceState | None = None):
        self.workspace = workspace

    def bind_workspace(self, workspace: WorkspaceState) -> None:
        self.workspace = workspace

    def resolve_path(
        self,
        value: str | Path,
        *,
        require_inside: bool = False,
    ) -> Path:
        if self.workspace is not None:
            return self.workspace.resolve(value, require_inside=require_inside)
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve(strict=False)

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult:
        """Run the tool and return a structured result."""
        ...

    def schema(self) -> dict:
        """OpenAI function-calling schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
