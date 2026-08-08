"""Interactive approval cards with lossless, redacted command display."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.text import Text


_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/-]+=*"),
    re.compile(
        r"(?i)(api[_-]?key|password|passwd|access[_-]?token|client[_-]?secret)"
        r"(\s*[=:]\s*)([^\s,;&]+)"
    ),
    re.compile(r"(?i)(https?://[^\s:/]+:)([^@\s]+)(@)"),
)


class ApprovalChoice(str, Enum):
    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


def redact_secret_text(value: str) -> str:
    """Redact credentials without shortening the surrounding command."""
    text = _SECRET_PATTERNS[0].sub("[REDACTED_API_KEY]", value)
    text = _SECRET_PATTERNS[1].sub(r"\1[REDACTED_TOKEN]", text)
    text = _SECRET_PATTERNS[2].sub(r"\1\2[REDACTED]", text)
    return _SECRET_PATTERNS[3].sub(r"\1[REDACTED]\3", text)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        sensitive = {
            "api_key", "authorization", "password", "passwd", "access_token",
            "refresh_token", "client_secret", "secret",
        }
        return {
            str(key): (
                "[REDACTED]"
                if str(key).lower() in sensitive and item
                else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_value(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, str):
        return redact_secret_text(value)
    return value


@dataclass(frozen=True)
class ApprovalDetails:
    tool: str
    arguments: dict[str, Any]
    reason: str
    effect: str = "UNKNOWN"
    risk: str = "unknown"
    cwd: str = ""
    reusable_rule: str | None = None

    @classmethod
    def from_request(cls, request: Any) -> "ApprovalDetails":
        if isinstance(request, dict):
            get = request.get
        else:
            get = lambda name, default=None: getattr(request, name, default)
        arguments = get("arguments", get("args", {})) or {}
        effect = get("effect", get("effects", "UNKNOWN"))
        if isinstance(effect, (set, tuple, list)):
            effect = ", ".join(
                getattr(item, "value", str(item)) for item in effect
            )
        else:
            effect = getattr(effect, "value", str(effect))
        risk = get("risk", "unknown")
        risk = getattr(risk, "value", str(risk))
        rule = get("reusable_rule", get("session_rule"))
        return cls(
            tool=str(get("tool", get("tool_name", "unknown"))),
            arguments=dict(arguments),
            reason=str(get("reason", "user approval is required")),
            effect=effect,
            risk=risk,
            cwd=str(get("cwd", "")),
            reusable_rule=str(rule) if rule else None,
        )

    @classmethod
    def legacy(cls, tool: str, arguments: dict, reason: str) -> "ApprovalDetails":
        return cls(
            tool=tool,
            arguments=arguments,
            reason=reason,
            cwd=str(Path.cwd()),
        )

    @property
    def command(self) -> str | None:
        command = self.arguments.get("command")
        return redact_secret_text(str(command)) if command is not None else None

    @property
    def targets(self) -> list[str]:
        paths: list[str] = []
        for name in ("file_path", "path", "target", "cwd"):
            value = self.arguments.get(name)
            if value is not None:
                paths.append(redact_secret_text(str(value)))
        return paths

    def as_text(self, *, details: bool = False) -> str:
        lines = [
            f"tool: {self.tool}",
            f"effect: {self.effect}",
            f"risk: {self.risk}",
            f"cwd: {redact_secret_text(self.cwd) if self.cwd else '(workspace)'}",
        ]
        if self.command is not None:
            lines.append(f"command: {self.command}")
        if self.targets:
            lines.append("targets: " + ", ".join(self.targets))
        lines.append(f"reason: {redact_secret_text(self.reason)}")
        if details:
            payload = json.dumps(
                redact_value(self.arguments),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
            lines.extend(("arguments:", payload))
            if self.reusable_rule:
                lines.append(f"session rule: {redact_secret_text(self.reusable_rule)}")
        return "\n".join(lines)


class ApprovalPrompt:
    """Callable compatible with both legacy and structured policy callbacks."""

    def __init__(
        self,
        console: Console | None = None,
        read: Callable[[str], str] | None = None,
    ):
        self.console = console or Console(stderr=True)
        self._read = read or self.console.input

    def decide(self, details: ApprovalDetails) -> ApprovalChoice:
        self.console.print(
            Panel(
                Text(details.as_text(), overflow="fold", no_wrap=False),
                title="Approval required",
                border_style="yellow",
            )
        )
        choices = "[y] once  [n] deny  [d] details"
        if details.reusable_rule:
            choices += "  [s] session"
        while True:
            answer = self._read(f"{choices}\n> ").strip().lower()
            if answer in {"y", "yes", "once"}:
                return ApprovalChoice.ONCE
            if answer in {"", "n", "no", "deny"}:
                return ApprovalChoice.DENY
            if answer in {"s", "session"} and details.reusable_rule:
                return ApprovalChoice.SESSION
            if answer in {"d", "details"}:
                self.console.print(
                    Panel(
                        Text(details.as_text(details=True), overflow="fold"),
                        title="Approval details",
                        border_style="dim",
                    )
                )
                continue
            expected = "y, n, d, or s" if details.reusable_rule else "y, n, or d"
            self.console.print(f"[yellow]Choose {expected}.[/yellow]")

    def __call__(self, *args: Any) -> ApprovalChoice | bool:
        # ExecutionPolicy v1 passes (tool_name, arguments, reason) and expects a
        # bool.  Runtime v2 passes one ApprovalRequest and consumes the enum.
        legacy = len(args) == 3
        details = (
            ApprovalDetails.legacy(str(args[0]), dict(args[1]), str(args[2]))
            if legacy
            else ApprovalDetails.from_request(args[0])
        )
        choice = self.decide(details)
        return choice is ApprovalChoice.ONCE if legacy else choice
