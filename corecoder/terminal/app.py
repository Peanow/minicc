"""Interactive inline terminal application."""

from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax

from corecoder import __version__
from corecoder.commandline.runtime import (
    RuntimeBundle,
    attach_observability,
    run_agent,
    start_agent_session,
    status_from_agent,
)
from corecoder.session import SessionError, SessionRecord

from .commands import CommandRegistry, default_registry
from .prompt import PromptState, create_prompt_session
from .render import (
    EventRenderer,
    NormalizedEvent,
    OutputMode,
    render_session_messages,
    result_data,
)


class TerminalApp:
    """Long-lived PromptSession backed by a structured runtime observer."""

    def __init__(
        self,
        bundle: RuntimeBundle,
        *,
        console: Console | None = None,
        registry: CommandRegistry | None = None,
        prompt_session: Any | None = None,
        initial_session: SessionRecord | None = None,
    ):
        self.bundle = bundle
        self.agent = bundle.agent
        self.console = console or Console()
        self.registry = registry or default_registry()
        self.verbose = False
        self.multiline_mode = False
        self._exit_requested = False
        self._diff_journal: list[tuple[str, str]] = []
        self.last_result: Any | None = None
        self._initial_session = initial_session
        self.state = PromptState(
            model=bundle.config.model,
            permission_mode=bundle.config.permission_mode,
        )
        self.prompt_session = prompt_session or create_prompt_session(
            self.registry,
            self.state,
            history_file=bundle.history_file,
            sources={
                "model": self._model_completions,
                "skill": self._skill_completions,
                "session": self._session_completions,
            },
        )

    def run(self) -> int:
        self._show_banner()
        if self._initial_session is not None:
            self._show_resumed_session(self._initial_session)
            self._initial_session = None
        start_message = start_agent_session(self.agent)
        if start_message:
            self.console.print(f"[dim]{start_message}[/dim]")
        while not self._exit_requested:
            self._refresh_toolbar()
            try:
                user_input = self.prompt_session.prompt("❯ ")
            except KeyboardInterrupt:
                # PromptSession's binding normally clears the buffer; this is a
                # fallback for terminals that deliver SIGINT directly.
                self.console.print("[dim]Input cleared.[/dim]")
                continue
            except EOFError:
                break

            # Preserve the exact message. Whitespace is used only to decide
            # whether there is anything to send.
            if not user_input.strip():
                continue
            if user_input.startswith("//"):
                self.run_task(user_input[1:])
                continue
            if self.registry.dispatch(user_input, self):
                continue
            self.run_task(user_input)
        self.console.print("[dim]Bye.[/dim]")
        return 0

    def run_task(self, prompt: str) -> Any | None:
        renderer = EventRenderer(
            OutputMode.PRETTY,
            stdout=self.console.file,
            width=self.console.width,
            no_color=self.console.no_color,
            verbose=self.verbose,
        )

        def observe(value: Any) -> None:
            event = NormalizedEvent.from_value(value)
            if event.event == "tool_finished" and event.data.get("diff"):
                path = str(
                    event.data.get("path")
                    or event.data.get("file_path")
                    or event.data.get("tool")
                    or "change"
                )
                self._diff_journal.append((path, str(event.data["diff"])))
            renderer.emit(event)

        try:
            result = run_agent(self.agent, prompt, observe)
            renderer.finish(result)
        except KeyboardInterrupt:
            renderer.close()
            self.console.print("[yellow]Interrupted. The prompt is ready again.[/yellow]")
            return None
        except Exception as exc:
            renderer.close()
            self.console.print(f"[red]Error: {exc}[/red]")
            return None

        self.last_result = result
        data = result_data(result)
        status = str(data.get("status", "completed"))
        if not self.bundle.ephemeral and status in {"completed", "success", "done"}:
            try:
                record = self.bundle.sessions.checkpoint(
                    self.agent,
                    self.bundle.config,
                    status=status,
                )
                self.console.print(f"[dim]session {record.id} checkpointed[/dim]")
            except (OSError, SessionError, TypeError, ValueError) as exc:
                self.console.print(f"[yellow]Session checkpoint failed: {exc}[/yellow]")
        self.state.model = str(status_from_agent(self.agent).get("model", self.state.model))
        return result

    def request_exit(self) -> None:
        self._exit_requested = True

    def show_diff(self) -> None:
        if self._diff_journal:
            for path, diff in self._diff_journal:
                self.console.print(f"[bold]{path}[/bold]")
                self.console.print(Syntax(diff, "diff", word_wrap=True))
            return
        changed = status_from_agent(self.agent).get("changed_files") or []
        if not changed:
            self.console.print("[dim]No files modified in this session.[/dim]")
            return
        self.console.print("[bold]Files modified in this session:[/bold]")
        for path in changed:
            self.console.print(f"  [cyan]{path}[/cyan]")

    def resume_session(self, session_id: str | None = None) -> None:
        try:
            record = (
                self.bundle.sessions.latest()
                if session_id is None
                else self.bundle.sessions.load(session_id)
            )
            self.bundle.sessions.restore(self.agent, record)
        except SessionError as exc:
            raise ValueError(str(exc)) from exc
        self.bundle.config.model = record.model
        self.state.model = record.model
        self._show_resumed_session(record)

    def _show_resumed_session(self, record: SessionRecord) -> None:
        render_session_messages(self.console, record)
        trace = getattr(self.agent, "trace", None)
        emit = getattr(trace, "emit", None)
        if callable(emit):
            emit(
                "session_resumed",
                session_id=record.id,
                message_count=len(record.messages),
                model=record.model,
            )

    def open_editor(self) -> None:
        editor = os.getenv("VISUAL") or os.getenv("EDITOR")
        if not editor:
            raise ValueError("Set $VISUAL or $EDITOR to use /editor.")
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".md", encoding="utf-8", delete=False
        ) as handle:
            path = Path(handle.name)
        try:
            command = [*shlex.split(editor), str(path)]
            result = subprocess.run(command, check=False)
            if result.returncode:
                raise ValueError(f"Editor exited with status {result.returncode}.")
            prompt = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
        if prompt.strip():
            self.run_task(prompt)

    def observe(self) -> None:
        try:
            url = attach_observability(self.bundle, open_browser=True)
        except Exception as exc:
            self.state.observability = "OFF"
            self.console.print(f"[red]Observability unavailable: {exc}[/red]")
            return
        self.state.observability = "ON"
        self.console.print(f"[green]Observability ready:[/green] {url}")

    def set_verbose(self, value: bool) -> None:
        self.verbose = value

    def set_multiline(self, value: bool) -> None:
        self.multiline_mode = value
        self.state.multiline_mode = value

    def _show_banner(self) -> None:
        base = (
            f"  · {self.bundle.config.base_url}"
            if self.bundle.config.base_url else ""
        )
        persistence = "ephemeral" if self.bundle.ephemeral else "project sessions"
        self.console.print(
            Panel(
                f"[bold]CoreCoder[/bold] {__version__}\n"
                f"[cyan]{self.bundle.config.model}[/cyan]{base} · "
                f"{self.bundle.config.permission_mode} · {persistence}\n"
                "Type [bold]/help[/bold] to discover commands.",
                border_style="blue",
            )
        )

    def _refresh_toolbar(self) -> None:
        # This I/O happens once before entering prompt(), never from its redraw
        # callback. Failure is deliberately represented as cached OFF state.
        try:
            healthy = self.bundle.manager.is_healthy(timeout=0.1)
        except Exception:
            healthy = False
        self.state.observability = "ON" if healthy else "OFF"
        status = status_from_agent(self.agent)
        total = status.get("context_tokens") or status.get("total_tokens")
        self.state.context = f"{total} tokens" if total else ""

    def _model_completions(self) -> list[str]:
        current = str(status_from_agent(self.agent).get("model", self.bundle.config.model))
        configured = os.getenv("CORECODER_MODELS", "")
        return sorted({current, *(item.strip() for item in configured.split(",") if item.strip())})

    def _skill_completions(self) -> list[str]:
        return sorted(skill.name for skill in getattr(self.agent, "skills", []))

    def _session_completions(self) -> list[str]:
        try:
            return [record.id for record in self.bundle.sessions.list()]
        except SessionError:
            return []


__all__ = ["TerminalApp"]
