"""Application-level execution policy for agent tool calls."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


class PermissionMode(str, Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    FULL_ACCESS = "full-access"


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str


ApprovalCallback = Callable[[str, dict, str], bool]


class ExecutionPolicy:
    """Decide whether a model-requested tool call may execute.

    This is a product policy layer, not an OS sandbox. Direct library calls to
    tools and subprocesses outside the Agent runtime are not contained by it.
    """

    _READ_TOOLS = {"read_file", "glob", "grep", "memory_search", "skill", "agent"}
    _WRITE_TOOLS = {"write_file", "edit_file"}
    _SAFE_READ_COMMANDS = {
        "pwd", "ls", "find", "rg", "grep", "sed", "head", "tail", "wc",
    }
    _SAFE_GIT_SUBCOMMANDS = {
        "status", "diff", "log", "show", "branch", "rev-parse", "ls-files",
    }

    def __init__(
        self,
        mode: PermissionMode | str = PermissionMode.WORKSPACE_WRITE,
        workspace: str | Path | None = None,
        approval_callback: ApprovalCallback | None = None,
    ):
        self.mode = PermissionMode(mode)
        self.workspace = (
            Path(workspace) if workspace is not None else Path.cwd()
        ).expanduser().resolve()
        self.approval_callback = approval_callback

    def evaluate(self, tool_name: str, arguments: dict) -> PolicyDecision:
        if self.mode == PermissionMode.FULL_ACCESS:
            return PolicyDecision(Decision.ALLOW, "full-access mode")

        if tool_name in self._READ_TOOLS:
            return PolicyDecision(Decision.ALLOW, "read-only tool")

        if tool_name == "memory_save":
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(Decision.DENY, "memory writes disabled in read-only mode")
            return PolicyDecision(Decision.ALLOW, "agent state write")

        if tool_name in self._WRITE_TOOLS:
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(Decision.DENY, "file writes disabled in read-only mode")
            target = arguments.get("file_path")
            if not target:
                return PolicyDecision(Decision.DENY, "missing file_path")
            if not self._inside_workspace(target):
                return PolicyDecision(Decision.DENY, "target is outside the workspace")
            return PolicyDecision(Decision.ALLOW, "target is inside the workspace")

        if tool_name == "bash":
            return self._evaluate_bash(str(arguments.get("command", "")))

        # Custom tools remain compatible, but their policy should be supplied
        # explicitly by applications that expose side effects.
        return PolicyDecision(Decision.ALLOW, "custom tool (unclassified)")

    def authorize(self, tool_name: str, arguments: dict) -> PolicyDecision:
        decision = self.evaluate(tool_name, arguments)
        if decision.decision != Decision.ASK:
            return decision
        if self.approval_callback and self.approval_callback(
            tool_name, arguments, decision.reason
        ):
            return PolicyDecision(Decision.ALLOW, f"user approved: {decision.reason}")
        return PolicyDecision(Decision.DENY, f"approval unavailable or denied: {decision.reason}")

    def _inside_workspace(self, target: str) -> bool:
        path = Path(target).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.workspace)
            return True
        except ValueError:
            return False

    def _evaluate_bash(self, command: str) -> PolicyDecision:
        if not command.strip():
            return PolicyDecision(Decision.DENY, "empty command")
        if self.mode == PermissionMode.WORKSPACE_WRITE:
            return PolicyDecision(Decision.ASK, "shell commands require approval")

        # read-only mode admits a deliberately small, no-metacharacter subset.
        if any(token in command for token in (";", "|", ">", "<", "$(", "`", "&&", "||")):
            return PolicyDecision(Decision.DENY, "shell composition disabled in read-only mode")
        try:
            parts = shlex.split(command)
        except ValueError:
            return PolicyDecision(Decision.DENY, "invalid shell syntax")
        if not parts:
            return PolicyDecision(Decision.DENY, "empty command")
        executable = Path(parts[0]).name
        if executable in self._SAFE_READ_COMMANDS:
            return PolicyDecision(Decision.ALLOW, "allowlisted read-only command")
        if (
            executable == "git"
            and len(parts) > 1
            and parts[1] in self._SAFE_GIT_SUBCOMMANDS
        ):
            return PolicyDecision(Decision.ALLOW, "allowlisted read-only git command")
        return PolicyDecision(Decision.DENY, "command is not read-only allowlisted")
