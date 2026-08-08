"""PromptSession construction, key bindings, and context-aware completion."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings

from .commands import CommandRegistry


@dataclass
class PromptState:
    multiline_mode: bool = False
    model: str = "unknown"
    permission_mode: str = "workspace-write"
    context: str = ""
    observability: str = "OFF"

    def toolbar(self) -> FormattedText:
        # Pure cached state: prompt redraw must never perform I/O.
        parts = [
            ("class:toolbar", f" {self.model} "),
            ("class:toolbar", f"· {self.permission_mode} "),
        ]
        if self.context:
            parts.append(("class:toolbar", f"· {self.context} "))
        parts.append(("class:toolbar", f"· observe {self.observability} "))
        return FormattedText(parts)


class SlashCompleter(Completer):
    def __init__(
        self,
        registry: CommandRegistry,
        sources: dict[str, Callable[[], list[str]]] | None = None,
    ):
        self.registry = registry
        self.sources = sources or {}
        self.path = PathCompleter(expanduser=True)

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or text.startswith("//"):
            yield from self.path.get_completions(document, complete_event)
            return
        if " " not in text:
            for name in self.registry.command_names:
                if name.startswith(text):
                    command = self.registry.resolve(name[1:])
                    yield Completion(
                        name,
                        start_position=-len(text),
                        display_meta=command.help if command else "alias",
                    )
            return
        command_name, argument = text[1:].split(" ", 1)
        source_name = command_name
        if command_name == "session":
            words = argument.split()
            if not words or (len(words) == 1 and not argument.endswith(" ")):
                for action in ("list", "resume", "delete"):
                    if action.startswith(argument):
                        yield Completion(action, start_position=-len(argument))
                return
            if words[0] in {"resume", "delete"}:
                source_name = "session"
                argument = argument[len(words[0]):].lstrip()
        source = self.sources.get(source_name)
        if source is not None:
            for value in source():
                if value.startswith(argument):
                    yield Completion(value, start_position=-len(argument))
            return
        yield from self.path.get_completions(
            Document(argument, cursor_position=len(argument)), complete_event
        )


def create_key_bindings(state: PromptState) -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def enter(event) -> None:
        if state.multiline_mode:
            event.current_buffer.insert_text("\n")
        else:
            event.current_buffer.validate_and_handle()

    @bindings.add("escape", "enter")
    def escape_enter(event) -> None:
        if state.multiline_mode:
            event.current_buffer.validate_and_handle()
        else:
            event.current_buffer.insert_text("\n")

    @bindings.add("c-c")
    def clear_input(event) -> None:
        event.current_buffer.reset()

    @bindings.add("c-d")
    def eof_or_delete(event) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.delete()
        else:
            event.app.exit(exception=EOFError)

    return bindings


def create_prompt_session(
    registry: CommandRegistry,
    state: PromptState,
    *,
    history_file: Path | None,
    sources: dict[str, Callable[[], list[str]]] | None = None,
) -> PromptSession:
    history = InMemoryHistory()
    if history_file is not None:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_file))
    return PromptSession(
        history=history,
        completer=SlashCompleter(registry, sources),
        auto_suggest=AutoSuggestFromHistory(),
        key_bindings=create_key_bindings(state),
        multiline=True,
        enable_history_search=True,
        complete_while_typing=False,
        prompt_continuation="...  ",
        bottom_toolbar=state.toolbar,
    )


__all__ = [
    "PromptState", "SlashCompleter", "create_key_bindings", "create_prompt_session"
]
