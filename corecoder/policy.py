"""Application-level execution policy for agent tool calls."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .runtime.workspace import WorkspaceState
from .tools.base import Effect, Tool


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


@dataclass(frozen=True)
class ApprovalRequest:
    tool: str
    arguments: dict[str, Any]
    reason: str
    effects: tuple[Effect, ...]
    risk: RiskClass
    cwd: str
    reusable_rule: str | None = None


ApprovalCallback = Callable[..., Any]


class ExecutionPolicy:
    """Decide whether a model-requested tool call may execute.

    This is a product policy layer, not an OS sandbox. Direct library calls to
    tools and subprocesses outside the Agent runtime are not contained by it.
    """

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
    _BUILTIN_EFFECTS = {
        "bash": frozenset({Effect.EXECUTE}),
        "read_file": frozenset({Effect.READ_FS}),
        "glob": frozenset({Effect.READ_FS}),
        "grep": frozenset({Effect.READ_FS}),
        "agent": frozenset({Effect.READ_FS}),
        "memory_search": frozenset({Effect.READ_FS}),
        "write_file": frozenset({Effect.WRITE_FS}),
        "edit_file": frozenset({Effect.WRITE_FS}),
        "skill": frozenset({Effect.APP_STATE_WRITE}),
        "memory_save": frozenset({Effect.APP_STATE_WRITE}),
    }

    def __init__(
        self,
        mode: PermissionMode | str = PermissionMode.WORKSPACE_WRITE,
        workspace: str | Path | WorkspaceState | None = None,
        approval_callback: ApprovalCallback | None = None,
    ):
        self.mode = PermissionMode(mode)
        self.workspace_state = (
            workspace
            if isinstance(workspace, WorkspaceState)
            else WorkspaceState(workspace or Path.cwd())
        )
        self.approval_callback = approval_callback
        self._session_rules: set[str] = set()

    @property
    def workspace(self) -> Path:
        return self.workspace_state.root

    def evaluate(self, tool: Tool | str, arguments: dict) -> PolicyDecision:
        tool_name = tool.name if isinstance(tool, Tool) else str(tool)
        effects = (
            tool.effects
            if isinstance(tool, Tool)
            else self._BUILTIN_EFFECTS.get(tool_name, frozenset())
        )

        # A missing declaration is never silently treated as safe.  Interactive
        # callers may approve once; headless callers have no callback and deny.
        if not effects:
            return PolicyDecision(
                Decision.ASK,
                "tool has no declared effects",
                RiskClass.UNKNOWN,
            )

        if tool_name == "bash":
            return self._evaluate_bash(str(arguments.get("command", "")))

        if self.mode == PermissionMode.FULL_ACCESS:
            return PolicyDecision(
                Decision.ALLOW,
                "full-access mode permits declared effects",
                self._risk_for_effects(effects),
            )

        if effects <= {Effect.READ_FS}:
            return PolicyDecision(
                Decision.ALLOW,
                "declared read-only effects",
                RiskClass.READ_ONLY,
            )

        if Effect.APP_STATE_WRITE in effects:
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(
                    Decision.DENY,
                    "application-state writes disabled in read-only mode",
                    RiskClass.WORKSPACE_EXECUTION,
                )

        if Effect.WRITE_FS in effects:
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

        if Effect.NETWORK in effects or Effect.EXECUTE in effects:
            if self.mode == PermissionMode.READ_ONLY:
                return PolicyDecision(
                    Decision.DENY,
                    "execution or network effects are disabled in read-only mode",
                    self._risk_for_effects(effects),
                )
            return PolicyDecision(
                Decision.ASK,
                "declared execution or network effect requires approval",
                self._risk_for_effects(effects),
            )

        return PolicyDecision(
            Decision.ALLOW,
            "declared application-state effect",
            self._risk_for_effects(effects),
        )

    def authorize(self, tool: Tool | str, arguments: dict) -> PolicyDecision:
        tool_name = tool.name if isinstance(tool, Tool) else str(tool)
        effects = (
            tool.effects
            if isinstance(tool, Tool)
            else self._BUILTIN_EFFECTS.get(tool_name, frozenset())
        )
        decision = self.evaluate(tool, arguments)
        if decision.decision != Decision.ASK:
            return decision
        rule = self.reusable_rule(tool, arguments, decision)
        if rule and rule in self._session_rules:
            return PolicyDecision(
                Decision.ALLOW,
                f"session rule approved: {decision.reason}",
                decision.risk,
            )
        approved = False
        session = False
        if self.approval_callback:
            request = ApprovalRequest(
                tool=tool_name,
                arguments=dict(arguments),
                reason=decision.reason,
                effects=tuple(sorted(effects, key=lambda item: item.value)),
                risk=decision.risk,
                cwd=str(self.workspace_state.cwd),
                reusable_rule=rule,
            )
            try:
                choice = self.approval_callback(request)
            except TypeError:
                choice = self.approval_callback(tool_name, arguments, decision.reason)
            value = getattr(choice, "value", choice)
            approved = value in {True, "once", "session", "allow", "yes"}
            session = value == "session"
        if approved:
            if session and rule:
                self._session_rules.add(rule)
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
        return self.workspace_state.contains(target)

    @staticmethod
    def _risk_for_effects(effects: frozenset[Effect]) -> RiskClass:
        if Effect.NETWORK in effects:
            return RiskClass.NETWORK
        if Effect.EXECUTE in effects:
            return RiskClass.WORKSPACE_EXECUTION
        if Effect.WRITE_FS in effects or Effect.APP_STATE_WRITE in effects:
            return RiskClass.WORKSPACE_EXECUTION
        if effects <= {Effect.READ_FS}:
            return RiskClass.READ_ONLY
        return RiskClass.UNKNOWN

    def reusable_rule(
        self,
        tool: Tool | str,
        arguments: dict,
        decision: PolicyDecision | None = None,
    ) -> str | None:
        """Return an exact, displayable rule or ``None`` when unsafe to reuse."""
        name = tool.name if isinstance(tool, Tool) else str(tool)
        if name != "bash":
            return None
        command = str(arguments.get("command", "")).strip()
        if not command or "\n" in command:
            return None
        risk = (decision or self.evaluate(tool, arguments)).risk
        if risk in {RiskClass.DESTRUCTIVE, RiskClass.UNKNOWN}:
            return None
        return f"bash exact: {command}"

    def _evaluate_bash(self, command: str) -> PolicyDecision:
        if not command.strip():
            return PolicyDecision(
                Decision.DENY,
                "empty command",
                RiskClass.UNKNOWN,
            )
        risk, detail = self.classify_shell(command)
        if self.mode == PermissionMode.FULL_ACCESS:
            return PolicyDecision(Decision.ALLOW, f"full-access mode: {detail}", risk)
        if self.mode == PermissionMode.WORKSPACE_WRITE:
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
        if executable == "cd":
            return RiskClass.WORKSPACE_EXECUTION, "logical workspace directory change"
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
