"""Shell command execution with safety checks.

Claude Code's BashTool is 1,143 lines. This is the distilled version:
- Output capture with truncation (head+tail preserved)
- Timeout support
- Dangerous command detection
- Working directory tracking (cd awareness)
"""

import re
import shlex
import subprocess
from pathlib import Path

from .base import Effect, Tool, ToolResult
from .sandbox import SandboxExecutor, SandboxUnavailable

# patterns that could wreck the filesystem or leak secrets
_DANGEROUS_PATTERNS = [
    (r"\brm\s+(-\w*)?-r\w*\s+(/|~|\$HOME)", "recursive delete on home/root"),
    (r"\brm\s+(-\w*)?-rf\s", "force recursive delete"),
    (r"\bmkfs\b", "format filesystem"),
    (r"\bdd\s+.*of=/dev/", "raw disk write"),
    (r">\s*/dev/sd[a-z]", "overwrite block device"),
    (r"\bchmod\s+(-R\s+)?777\s+/", "chmod 777 on root"),
    (r":\(\)\s*\{.*:\|:.*\}", "fork bomb"),
    (r"\bcurl\b.*\|\s*(sudo\s+)?bash", "pipe curl to bash"),
    (r"\bwget\b.*\|\s*(sudo\s+)?bash", "pipe wget to bash"),
]


class BashTool(Tool):
    effects = frozenset({Effect.EXECUTE})
    name = "bash"
    description = (
        "Execute a shell command. Returns stdout, stderr, and exit code. "
        "Use this for running tests, installing packages, git operations, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to run",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 120)",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        workspace=None,
        *,
        permission_mode: str = "workspace-write",
        network: str = "deny",
        trace=None,
    ):
        super().__init__(workspace)
        self._permission_mode = permission_mode
        self._network = network
        self._sandbox = None
        self._sandbox_key = None
        # A standalone legacy tool has no Agent-owned workspace to contain.
        # Agent composition always binds WorkspaceState before execution and
        # therefore always takes the sandboxed path.
        self._sandbox_required = workspace is not None
        self.bind_trace(trace)

    def bind_workspace(self, workspace) -> None:
        super().bind_workspace(workspace)
        self._sandbox_required = True
        self._configure_sandbox()

    def bind_trace(self, trace) -> None:
        super().bind_trace(trace)
        self._configure_sandbox()

    def configure_sandbox(self, *, permission_mode: str, network: str) -> None:
        self._permission_mode = permission_mode
        self._network = network
        self._configure_sandbox()

    def _configure_sandbox(self) -> None:
        if not self._sandbox_required:
            self._sandbox = None
            self._sandbox_key = None
            return
        workspace = self.workspace
        root = getattr(workspace, "root", None) or Path.cwd()
        key = (str(Path(root).expanduser().resolve()), self._permission_mode, self._network)
        if self._sandbox is not None and self._sandbox_key == key:
            return
        self._sandbox = SandboxExecutor(
            root,
            permission_mode=self._permission_mode,
            network=self._network,
            trace=self.trace,
        )
        self._sandbox_key = key

    def execute(self, command: str, timeout: int = 120) -> ToolResult:
        # safety check
        warning = _check_dangerous(command)
        if warning:
            return ToolResult.blocked(
                f"Blocked: {warning}\nCommand: {command}\n"
                "If intentional, modify the command to be more specific."
            )

        if self._sandbox is None and self._sandbox_required:
            self._configure_sandbox()
        cwd = self.workspace.cwd if self.workspace is not None else self.resolve_path(".")

        try:
            if self._sandbox_required:
                proc = self._sandbox.run(command, cwd=cwd, timeout=timeout)
            else:
                # Compatibility for direct, unbound tool callers.  The Agent
                # path never reaches here because it owns a WorkspaceState.
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=cwd,
                )

            # track cd commands so next command runs in the right place
            if proc.returncode == 0:
                self._update_cwd(command)
            out = proc.stdout
            if proc.stderr:
                out += f"\n[stderr]\n{proc.stderr}"
            if proc.returncode != 0:
                out += f"\n[exit code: {proc.returncode}]"
            # keep head + tail to preserve the most useful info
            if len(out) > 15_000:
                out = (
                    out[:6000]
                    + f"\n\n... truncated ({len(out)} chars total) ...\n\n"
                    + out[-3000:]
                )
            content = out.strip() or "(no output)"
            if proc.returncode:
                return ToolResult.error(
                    content,
                    error_type="ProcessExitError",
                    exit_code=proc.returncode,
                )
            return ToolResult.success(content, exit_code=0)
        except SandboxUnavailable as exc:
            return ToolResult.error(str(exc), error_type="SandboxUnavailable")
        except subprocess.TimeoutExpired:
            return ToolResult.error(
                f"timed out after {timeout}s",
                error_type="TimeoutExpired",
            )
        except Exception as e:
            return ToolResult.error(str(e), error_type=type(e).__name__)

    def _update_cwd(self, command: str) -> None:
        """Persist only a standalone successful ``cd`` command."""
        if self.workspace is None or any(token in command for token in ("&&", ";", "|", "\n")):
            return
        try:
            parts = shlex.split(command)
        except ValueError:
            return
        if len(parts) == 2 and parts[0] == "cd":
            self.workspace.chdir(parts[1])


def _check_dangerous(cmd: str) -> str | None:
    """Return a warning string if the command looks destructive, else None."""
    for pattern, reason in _DANGEROUS_PATTERNS:
        if re.search(pattern, cmd):
            return reason
    return None
