"""Render structured runtime events for humans and shell pipelines."""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, TextIO

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from .approval import redact_value


class OutputMode(str, Enum):
    PRETTY = "pretty"
    PLAIN = "plain"
    JSONL = "jsonl"


_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _event_name(value: Any) -> str:
    if isinstance(value, Enum):
        value = value.value
    value = str(value or "event")
    if "_" not in value and any(char.isupper() for char in value):
        value = _CAMEL_BOUNDARY.sub("_", value)
    return value.replace("-", "_").lower()


@dataclass(frozen=True)
class NormalizedEvent:
    event: str
    run_id: str
    timestamp: float | str
    data: dict[str, Any]

    @classmethod
    def from_value(cls, value: Any) -> "NormalizedEvent":
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            kind = value.get("kind", value.get("event", "event"))
            run_id = value.get("run_id", "")
            timestamp = value.get("timestamp", time.time())
            data = value.get("data", {})
        else:
            kind = getattr(value, "kind", getattr(value, "event", type(value).__name__))
            run_id = getattr(value, "run_id", "")
            timestamp = getattr(value, "timestamp", time.time())
            data = getattr(value, "data", {})
        if is_dataclass(data):
            data = asdict(data)
        elif not isinstance(data, dict):
            data = vars(data) if hasattr(data, "__dict__") else {"value": data}
        event_name = _event_name(kind)
        data = dict(redact_value(data))
        if event_name == "run_finished" and "token" not in data:
            prompt = int(data.get("prompt_tokens") or 0)
            completion = int(data.get("completion_tokens") or 0)
            data["token"] = {
                "prompt": prompt,
                "completion": completion,
                "total": prompt + completion,
            }
        return cls(
            event=event_name,
            run_id=str(run_id or ""),
            timestamp=timestamp,
            data=data,
        )

    def json_record(self) -> dict[str, Any]:
        return {
            "schema": 2,
            "event": self.event,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


def result_data(result: Any) -> dict[str, Any]:
    if hasattr(result, "to_dict"):
        raw = result.to_dict()
    elif is_dataclass(result):
        raw = asdict(result)
    elif isinstance(result, dict):
        raw = dict(result)
    else:
        raw = {
            name: getattr(result, name)
            for name in (
                "status", "final_answer", "changed_files", "token", "cost",
                "error", "trace_path", "prompt_tokens", "completion_tokens",
                "estimated_cost",
            )
            if hasattr(result, name)
        }
    if "token" not in raw:
        prompt = int(raw.get("prompt_tokens") or 0)
        completion = int(raw.get("completion_tokens") or 0)
        raw["token"] = {
            "prompt": prompt,
            "completion": completion,
            "total": prompt + completion,
        }
    if "cost" not in raw and "estimated_cost" in raw:
        raw["cost"] = raw.get("estimated_cost")
    return dict(redact_value(raw))


class EventRenderer:
    """One observer supporting terminal, plain, and JSONL contracts."""

    def __init__(
        self,
        mode: OutputMode | str = OutputMode.PRETTY,
        *,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        width: int | None = None,
        no_color: bool | None = None,
        verbose: bool = False,
    ):
        self.mode = OutputMode(mode)
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        force_terminal = None if no_color is None else not no_color
        color_system = None if no_color else "auto"
        self.console = Console(
            file=self.stdout,
            width=width,
            force_terminal=force_terminal,
            color_system=color_system,
        )
        self.diagnostics = Console(
            file=self.stderr,
            width=width,
            force_terminal=force_terminal,
            color_system=color_system,
        )
        self.verbose = verbose
        self.finished = False
        self.run_id = ""
        self._answer_parts: list[str] = []
        self._live: Live | None = None
        self._last_refresh = 0.0

    def set_verbose(self, enabled: bool) -> None:
        self.verbose = enabled

    def __call__(self, event: Any) -> None:
        self.emit(event)

    def emit(self, value: Any) -> None:
        event = NormalizedEvent.from_value(value)
        self.run_id = event.run_id or self.run_id
        self.finished = self.finished or event.event == "run_finished"
        if self.mode is OutputMode.JSONL:
            self.stdout.write(
                json.dumps(event.json_record(), ensure_ascii=False, default=str) + "\n"
            )
            self.stdout.flush()
            return
        if self.mode is OutputMode.PLAIN:
            self._render_plain(event)
            return
        self._render_pretty(event)

    def finish(self, result: Any, *, run_id: str = "") -> None:
        if self.finished:
            self.close()
            return
        data = result_data(result)
        self.emit(
            NormalizedEvent(
                event="run_finished",
                run_id=str(data.get("run_id") or run_id or self.run_id),
                timestamp=time.time(),
                data=data,
            )
        )
        self.close()

    def close(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _render_plain(self, event: NormalizedEvent) -> None:
        if event.event == "text_delta":
            self._answer_parts.append(str(event.data.get("text", event.data.get("delta", ""))))
            return
        if event.event in {"tool_requested", "tool_started", "tool_finished"}:
            tool = event.data.get("tool", event.data.get("name", "tool"))
            status = event.data.get("status", event.event.removeprefix("tool_"))
            self.diagnostics.print(f"[{status}] {tool}", markup=False)
            return
        if event.event == "run_finished":
            answer = str(event.data.get("final_answer", ""))
            if not answer:
                answer = "".join(self._answer_parts)
            if answer:
                self.stdout.write(answer)
                if not answer.endswith("\n"):
                    self.stdout.write("\n")
                self.stdout.flush()
            error = event.data.get("error")
            if error:
                self.diagnostics.print(str(error), markup=False)

    def _render_pretty(self, event: NormalizedEvent) -> None:
        name, data = event.event, event.data
        if name == "run_started":
            self.console.print("[cyan]●[/cyan] Thinking…")
            return
        if name == "text_delta":
            self._answer_parts.append(str(data.get("text", data.get("delta", ""))))
            self._refresh_markdown()
            return
        if name == "tool_requested":
            tool = data.get("tool", data.get("name", "tool"))
            self.console.print(f"[dim]  · requested  {tool}[/dim]")
            return
        if name == "approval_requested":
            tool = data.get("tool", data.get("name", "tool"))
            risk = data.get("risk", "unknown")
            self.console.print(f"[yellow]  ? approval   {tool} · {risk}[/yellow]")
            return
        if name == "approval_decided":
            outcome = str(data.get("outcome", "deny"))
            if outcome == "once":
                self.console.print("[green]  ✓ approved   once[/green]")
            elif outcome == "session":
                self.console.print("[green]  ✓ approved   for this session[/green]")
            else:
                self.console.print("[dim]  · denied     tool call blocked[/dim]")
            return
        if name == "tool_started":
            tool = data.get("tool", data.get("name", "tool"))
            self.console.print(f"[cyan]  ↻ running    {tool}[/cyan]")
            return
        if name == "tool_finished":
            self._render_tool_finished(data)
            return
        if name == "context_compacted":
            before = data.get("before_tokens", "?")
            after = data.get("after_tokens", "?")
            self.console.print(f"[dim]  ↳ context compacted {before} → {after}[/dim]")
            return
        if name == "model_failed":
            self.console.print(f"[red]  ✗ model failed: {data.get('error', 'unknown error')}[/red]")
            return
        if name == "run_finished":
            self._render_finish(data)

    def _refresh_markdown(self) -> None:
        if not self.console.is_terminal:
            return
        now = time.monotonic()
        content = "".join(self._answer_parts)
        if self._live is None:
            self._live = Live(
                Markdown(content or " "),
                console=self.console,
                refresh_per_second=12,
                transient=False,
            )
            self._live.start()
            self._last_refresh = now
        elif now - self._last_refresh >= 1 / 12:
            self._live.update(Markdown(content or " "), refresh=True)
            self._last_refresh = now

    def _render_tool_finished(self, data: dict[str, Any]) -> None:
        tool = data.get("tool", data.get("name", "tool"))
        status = str(data.get("status", "success"))
        duration = data.get("duration_ms")
        duration_label = f" · {duration:g}ms" if isinstance(duration, (int, float)) else ""
        if status in {"success", "completed", "ok"}:
            self.console.print(f"[green]  ✓ {tool}{duration_label}[/green]")
        elif status in {"blocked", "denied"}:
            self.console.print(f"[yellow]  ! {tool} · {status}{duration_label}[/yellow]")
        else:
            self.console.print(f"[red]  ✗ {tool} · {status}{duration_label}[/red]")
        diff = data.get("diff")
        if diff:
            self.console.print(Syntax(str(diff), "diff", word_wrap=True))
        output = data.get("content", data.get("output"))
        if output and (self.verbose or status not in {"success", "completed", "ok"}):
            text = str(output)
            if not self.verbose:
                text = "\n".join(text.splitlines()[-12:])
            self.console.print(Text(text, overflow="fold"))

    def _render_finish(self, data: dict[str, Any]) -> None:
        answer = str(data.get("final_answer", ""))
        streamed = "".join(self._answer_parts)
        if self._live is not None:
            self._live.update(Markdown(answer or streamed or " "), refresh=True)
            self._live.stop()
            self._live = None
        elif answer or streamed:
            self.console.print(Markdown(answer or streamed))
        status = str(data.get("status", "completed"))
        changed = data.get("changed_files") or []
        token = data.get("token") or {}
        total = token.get("total") if isinstance(token, dict) else token
        pieces = [status]
        if changed:
            pieces.append(f"{len(changed)} file(s)")
        if total:
            pieces.append(f"{total} tokens")
        style = "green" if status in {"completed", "success", "done"} else "yellow"
        self.console.print(f"[{style}]✓ {' · '.join(pieces)}[/{style}]")
