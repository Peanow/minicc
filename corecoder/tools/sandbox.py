"""Instance-local OS sandboxing for shell commands.

The application policy decides whether a Bash tool call may run.  This module
adds the second boundary: on macOS, ``sandbox-exec`` limits the process and
its descendants to the Agent workspace.  There is deliberately no fallback
to an unsandboxed subprocess when the backend is unavailable.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class SandboxUnavailable(RuntimeError):
    """Raised when a sandbox-required command cannot be safely started."""


def _profile_path(path: Path) -> str:
    """Return a sandbox profile string literal for an already physical path."""
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


class SandboxExecutor:
    """Run shell commands under the configured OS boundary."""

    def __init__(
        self,
        workspace: str | Path,
        permission_mode: str = "workspace-write",
        network: str = "deny",
        trace: Any | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.permission_mode = str(permission_mode)
        self.network = str(network)
        if self.network not in {"allow", "deny"}:
            raise ValueError("sandbox network must be 'allow' or 'deny'")
        if self.permission_mode not in {"read-only", "workspace-write", "full-access"}:
            raise ValueError(f"unknown permission mode: {self.permission_mode}")
        self.trace = trace
        candidate = self._find_backend()
        self.executable = (
            candidate
            if self.permission_mode == "full-access" or self._backend_usable(candidate)
            else None
        )
        self.backend = "macos-sandbox-exec" if self.executable else "unavailable"
        self.available = self.executable is not None
        self._emit_configuration()

    def _find_backend(self) -> str | None:
        if sys.platform != "darwin":
            return None
        candidate = "/usr/bin/sandbox-exec"
        if Path(candidate).is_file() and Path(candidate).stat().st_mode & 0o111:
            return candidate
        return shutil.which("sandbox-exec")

    def _backend_usable(self, executable: str | None) -> bool:
        if executable is None:
            return False
        try:
            probe = subprocess.run(
                [executable, "-p", self._profile(), "/usr/bin/true"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return probe.returncode == 0

    def _emit(self, **data: Any) -> None:
        if self.trace is not None:
            self.trace.emit("sandbox_decision", **data)

    def _emit_configuration(self) -> None:
        if self.permission_mode == "full-access":
            decision = "bypass"
            result = "configured"
        elif self.available:
            decision = "enable"
            result = "configured"
        else:
            decision = "deny"
            result = "backend_unavailable"
        self._emit(
            stage="configuration",
            backend=self.backend,
            workspace=str(self.workspace),
            permission_mode=self.permission_mode,
            network=self.network,
            decision=decision,
            result=result,
        )

    def _profile(self) -> str:
        workspace = _profile_path(self.workspace)
        rules = [
            "(version 1)",
            "(deny default)",
            "(allow process-fork)",
            "(allow process-exec)",
            "(allow signal (target self))",
            "(allow sysctl-read)",
            # The command interpreter and runtime need their system files,
            # but workspace data remains governed by the workspace rule below.
            '(allow file-read* (subpath "/System"))',
            '(allow file-read* (subpath "/Library"))',
            '(allow file-read* (subpath "/usr"))',
            '(allow file-read* (subpath "/bin"))',
            '(allow file-read* (subpath "/sbin"))',
            '(allow file-read* (subpath "/private/etc"))',
            '(allow file-read* (subpath "/private/var/db"))',
            '(allow file-read* (literal "/dev/null"))',
            '(allow file-read* (literal "/dev/urandom"))',
            '(allow file-write* (literal "/dev/null"))',
            f'(allow file-read* (subpath "{workspace}"))',
        ]
        runtime_prefix = Path(sys.prefix).expanduser().resolve()
        if not str(runtime_prefix).startswith(workspace + "/") and str(runtime_prefix) != workspace:
            rules.append(
                f'(allow file-read* (subpath "{_profile_path(runtime_prefix)}"))'
            )
        if self.permission_mode == "workspace-write":
            rules.append(f'(allow file-write* (subpath "{workspace}"))')
        if self.network == "allow":
            rules.append("(allow network*)")
        return "\n".join(rules) + "\n"

    def run(
        self,
        command: str,
        *,
        cwd: str | Path,
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        """Run ``command`` and record only non-sensitive sandbox facts."""
        if self.permission_mode != "full-access" and not self.available:
            self._emit(
                stage="execution",
                backend=self.backend,
                workspace=str(self.workspace),
                permission_mode=self.permission_mode,
                network=self.network,
                decision="deny",
                result="backend_unavailable",
            )
            raise SandboxUnavailable(
                "OS sandbox backend unavailable; refusing to execute Bash command"
            )

        physical_cwd = Path(cwd).expanduser().resolve()
        try:
            physical_cwd.relative_to(self.workspace)
        except ValueError as exc:
            self._emit(
                stage="execution",
                backend=self.backend,
                workspace=str(self.workspace),
                permission_mode=self.permission_mode,
                network=self.network,
                decision="deny",
                result="cwd_outside_workspace",
            )
            raise SandboxUnavailable("Bash cwd is outside the workspace") from exc

        if self.permission_mode == "full-access":
            argv = ["/bin/sh", "-c", command]
            decision = "bypass"
        else:
            argv = [self.executable, "-p", self._profile(), "/bin/sh", "-c", command]
            decision = "enable"

        try:
            result = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=physical_cwd,
            )
        except subprocess.TimeoutExpired:
            self._emit(
                stage="execution",
                backend=self.backend,
                workspace=str(self.workspace),
                permission_mode=self.permission_mode,
                network=self.network,
                decision=decision,
                result="timeout",
            )
            raise
        except Exception as exc:
            self._emit(
                stage="execution",
                backend=self.backend,
                workspace=str(self.workspace),
                permission_mode=self.permission_mode,
                network=self.network,
                decision=decision,
                result="error",
                error_type=type(exc).__name__,
            )
            raise
        self._emit(
            stage="execution",
            backend=self.backend,
            workspace=str(self.workspace),
            permission_mode=self.permission_mode,
            network=self.network,
            decision=decision,
            result="success" if result.returncode == 0 else "process_error",
            exit_code=result.returncode,
        )
        return result
