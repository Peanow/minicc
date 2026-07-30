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


class RiskClass(str, Enum):
    READ_ONLY = "read-only"
    VALIDATION = "workspace-validation"
    WORKSPACE_EXECUTION = "workspace-execution"
    NETWORK = "network"
    DESTRUCTIVE = "destructive"
    SHELL_COMPOSITION = "shell-composition"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason: str
    risk: RiskClass = RiskClass.UNKNOWN


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
    _NETWORK_COMMANDS = {
        "curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "telnet",
    }
    _WORKSPACE_EXECUTION_COMMANDS = {
        "python", "python3", "tox", "nox", "make",
        "node", "deno", "bun", "cargo", "go", "java", "mvn", "gradle",
        "sh", "bash", "zsh",
    }
    _VALIDATION_COMMANDS = {"pytest", "py.test"}
    _DESTRUCTIVE_COMMANDS = {
        "rm", "rmdir", "shred", "mkfs", "dd", "chmod", "chown",
    }
    _NETWORK_GIT_SUBCOMMANDS = {"clone", "fetch", "pull", "push"}
    _DESTRUCTIVE_GIT_SUBCOMMANDS = {"clean", "reset"}
    _PACKAGE_COMMANDS = {"pip", "pip3", "uv", "npm", "yarn", "pnpm"}
    _PACKAGE_NETWORK_SUBCOMMANDS = {
        "install", "add", "update", "upgrade", "sync", "download",
        "view", "info", "search", "audit", "publish", "login",
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
            risk, detail = (
                self.classify_shell(str(arguments.get("command", "")))
                if tool_name == "bash"
                else (RiskClass.UNKNOWN, "non-shell tool")
            )
            return PolicyDecision(
                Decision.ALLOW,
                f"full-access mode: {detail}",
                risk,
            )

        if tool_name in self._READ_TOOLS:
            return PolicyDecision(
                Decision.ALLOW,
                "read-only tool",
                RiskClass.READ_ONLY,
            )

        if tool_name == "memory_save":
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(
                    Decision.DENY,
                    "memory writes disabled in read-only mode",
                    RiskClass.WORKSPACE_EXECUTION,
                )
            return PolicyDecision(
                Decision.ALLOW,
                "agent state write",
                RiskClass.WORKSPACE_EXECUTION,
            )

        if tool_name in self._WRITE_TOOLS:
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(
                    Decision.DENY,
                    "file writes disabled in read-only mode",
                    RiskClass.WORKSPACE_EXECUTION,
                )
            target = arguments.get("file_path")
            if not target:
                return PolicyDecision(
                    Decision.DENY,
                    "missing file_path",
                    RiskClass.WORKSPACE_EXECUTION,
                )
            if not self._inside_workspace(target):
                return PolicyDecision(
                    Decision.DENY,
                    "target is outside the workspace",
                    RiskClass.WORKSPACE_EXECUTION,
                )
            return PolicyDecision(
                Decision.ALLOW,
                "target is inside the workspace",
                RiskClass.WORKSPACE_EXECUTION,
            )

        if tool_name == "bash":
            return self._evaluate_bash(str(arguments.get("command", "")))

        # Custom tools remain compatible, but their policy should be supplied
        # explicitly by applications that expose side effects.
        return PolicyDecision(
            Decision.ALLOW,
            "custom tool (unclassified)",
            RiskClass.UNKNOWN,
        )

    def authorize(self, tool_name: str, arguments: dict) -> PolicyDecision:
        decision = self.evaluate(tool_name, arguments)
        if decision.decision != Decision.ASK:
            return decision
        if self.approval_callback and self.approval_callback(
            tool_name, arguments, decision.reason
        ):
            return PolicyDecision(
                Decision.ALLOW,
                f"user approved: {decision.reason}",
                decision.risk,
            )
        return PolicyDecision(
            Decision.DENY,
            f"approval unavailable or denied: {decision.reason}",
            decision.risk,
        )

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
            return PolicyDecision(
                Decision.DENY,
                "empty command",
                RiskClass.UNKNOWN,
            )
        risk, detail = self.classify_shell(command)
        if self.mode == PermissionMode.WORKSPACE_WRITE:
            if risk in {RiskClass.READ_ONLY, RiskClass.VALIDATION}:
                return PolicyDecision(
                    Decision.ALLOW,
                    detail,
                    risk,
                )
            return PolicyDecision(
                Decision.ASK,
                f"{detail}; shell command requires approval",
                risk,
            )

        if risk != RiskClass.READ_ONLY:
            return PolicyDecision(
                Decision.DENY,
                f"{detail}; not allowed in read-only mode",
                risk,
            )
        return PolicyDecision(Decision.ALLOW, detail, risk)

    @classmethod
    def classify_shell(cls, command: str) -> tuple[RiskClass, str]:
        """Classify a shell command without executing it."""
        if any(
            token in command
            for token in (";", "|", ">", "<", "$(", "`", "&&", "||", "\n")
        ):
            return (
                RiskClass.SHELL_COMPOSITION,
                "shell composition or redirection",
            )
        try:
            parts = shlex.split(command)
        except ValueError:
            return RiskClass.UNKNOWN, "invalid shell syntax"
        if not parts:
            return RiskClass.UNKNOWN, "empty command"
        executable = Path(parts[0]).name
        arguments = parts[1:]
        if executable in cls._NETWORK_COMMANDS:
            return RiskClass.NETWORK, f"network command: {executable}"
        if executable in cls._DESTRUCTIVE_COMMANDS:
            return RiskClass.DESTRUCTIVE, f"destructive command: {executable}"
        if executable in cls._PACKAGE_COMMANDS:
            subcommand = next(
                (argument for argument in arguments if not argument.startswith("-")),
                "",
            )
            if subcommand in cls._PACKAGE_NETWORK_SUBCOMMANDS:
                return (
                    RiskClass.NETWORK,
                    f"package network operation: {executable} {subcommand}",
                )
            return (
                RiskClass.WORKSPACE_EXECUTION,
                f"package command execution: {executable}",
            )
        if executable == "git":
            subcommand = arguments[0] if arguments else ""
            if subcommand in cls._NETWORK_GIT_SUBCOMMANDS:
                return RiskClass.NETWORK, f"git network operation: {subcommand}"
            if subcommand in cls._DESTRUCTIVE_GIT_SUBCOMMANDS:
                return RiskClass.DESTRUCTIVE, f"destructive git operation: {subcommand}"
            if subcommand in cls._SAFE_GIT_SUBCOMMANDS:
                git_arguments = arguments[1:]
                if subcommand == "branch" and any(
                    argument not in {
                        "--list", "--show-current", "-a", "--all", "-r",
                        "--remotes", "-v", "-vv", "--verbose",
                    }
                    for argument in git_arguments
                ):
                    risk = (
                        RiskClass.DESTRUCTIVE
                        if any(argument in {"-d", "-D", "--delete"} for argument in git_arguments)
                        else RiskClass.WORKSPACE_EXECUTION
                    )
                    return risk, "git branch mutation"
                if any(
                    argument == "--output" or argument.startswith("--output=")
                    for argument in git_arguments
                ):
                    return RiskClass.WORKSPACE_EXECUTION, "git command writes output file"
                return RiskClass.READ_ONLY, f"read-only git command: {subcommand}"
            return RiskClass.WORKSPACE_EXECUTION, f"git workspace operation: {subcommand or 'unknown'}"
        if executable in cls._SAFE_READ_COMMANDS:
            if executable == "sed" and any(
                argument == "-i" or argument.startswith("-i")
                for argument in arguments
            ):
                return RiskClass.WORKSPACE_EXECUTION, "sed in-place edit"
            if executable == "find" and "-delete" in arguments:
                return RiskClass.DESTRUCTIVE, "find delete operation"
            if executable == "find" and any(
                argument in {"-exec", "-execdir", "-ok", "-okdir"}
                for argument in arguments
            ):
                return RiskClass.WORKSPACE_EXECUTION, "find executes another command"
            return RiskClass.READ_ONLY, f"allowlisted read-only command: {executable}"
        if executable in cls._VALIDATION_COMMANDS:
            return RiskClass.VALIDATION, f"workspace test execution: {executable}"
        if (
            executable in {"python", "python3"}
            and len(arguments) >= 2
            and arguments[0] == "-m"
            and arguments[1] in {"pytest", "unittest"}
        ):
            return (
                RiskClass.VALIDATION,
                f"workspace test execution: {executable} -m {arguments[1]}",
            )
        if executable in cls._WORKSPACE_EXECUTION_COMMANDS:
            return RiskClass.WORKSPACE_EXECUTION, f"workspace code execution: {executable}"
        return RiskClass.UNKNOWN, f"unclassified command: {executable}"
