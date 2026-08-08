"""Slash command registry shared by parsing, help, and completion."""

from __future__ import annotations

import difflib
import shlex
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from rich.table import Table

from corecoder.skills import discover_skills

from corecoder.commandline.runtime import (
    activate_agent_skill,
    clear_agent,
    compact_agent,
    status_from_agent,
    switch_agent_model,
)


class TerminalContext(Protocol):
    agent: Any
    bundle: Any
    registry: "CommandRegistry"
    verbose: bool
    multiline_mode: bool

    @property
    def console(self): ...
    def request_exit(self) -> None: ...
    def show_diff(self) -> None: ...
    def resume_session(self, session_id: str | None = None) -> None: ...
    def open_editor(self) -> None: ...
    def observe(self) -> None: ...
    def set_verbose(self, value: bool) -> None: ...
    def set_multiline(self, value: bool) -> None: ...


Handler = Callable[[TerminalContext, list[str]], None]


@dataclass(frozen=True)
class Command:
    name: str
    help: str
    handler: Handler
    usage: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display_usage(self) -> str:
        return f"/{self.name}{(' ' + self.usage) if self.usage else ''}"


class CommandRegistry:
    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._aliases: dict[str, str] = {}

    def register(self, command: Command) -> None:
        if command.name in self._commands or command.name in self._aliases:
            raise ValueError(f"Duplicate slash command: /{command.name}")
        self._commands[command.name] = command
        for alias in command.aliases:
            if alias in self._commands or alias in self._aliases:
                raise ValueError(f"Duplicate slash command alias: /{alias}")
            self._aliases[alias] = command.name

    @property
    def commands(self) -> tuple[Command, ...]:
        return tuple(self._commands[name] for name in sorted(self._commands))

    @property
    def command_names(self) -> tuple[str, ...]:
        names = set(self._commands) | set(self._aliases)
        return tuple(f"/{name}" for name in sorted(names))

    def resolve(self, name: str) -> Command | None:
        canonical = self._aliases.get(name, name)
        return self._commands.get(canonical)

    def dispatch(self, text: str, context: TerminalContext) -> bool:
        """Handle one slash command. Unknown commands are consumed safely."""
        if not text.startswith("/") or text.startswith("//"):
            return False
        try:
            parts = shlex.split(text[1:])
        except ValueError as exc:
            context.console.print(f"[red]Invalid command: {exc}[/red]")
            return True
        if not parts:
            context.console.print("[dim]Type /help to list commands.[/dim]")
            return True
        command = self.resolve(parts[0])
        if command is None:
            match = difflib.get_close_matches(parts[0], self._commands, n=1)
            suggestion = f" Did you mean /{match[0]}?" if match else ""
            context.console.print(
                f"[red]Unknown command /{parts[0]}.[/red]{suggestion}"
            )
            return True
        try:
            command.handler(context, parts[1:])
        except Exception as exc:
            context.console.print(f"[red]{exc}[/red]")
            if command.usage:
                context.console.print(f"[dim]Usage: {command.display_usage}[/dim]")
        return True

    def help_table(self) -> Table:
        table = Table(title="CoreCoder commands", box=None, show_header=False)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description")
        for command in self.commands:
            table.add_row(command.display_usage, command.help)
        return table


def _require_at_most(args: list[str], count: int) -> None:
    if len(args) > count:
        raise ValueError("Too many arguments.")


def _help(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    context.console.print(context.registry.help_table())
    context.console.print(
        "[dim]Enter submits · Esc+Enter adds a line · Ctrl+C clears/cancels · "
        "Ctrl+D exits on an empty prompt · // sends a literal slash[/dim]"
    )


def _clear(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    clear_agent(context.agent)
    context.console.print("[green]Conversation cleared.[/green]")


def _resume(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 1)
    context.resume_session(args[0] if args else None)


def _model(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 1)
    if not args:
        context.console.print(
            f"Current model: [cyan]{status_from_agent(context.agent).get('model')}[/cyan]"
        )
        return
    switch_agent_model(context.agent, args[0])
    context.bundle.config.model = args[0]
    context.console.print(f"Switched to [cyan]{args[0]}[/cyan]")


def _tokens(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    status = status_from_agent(context.agent)
    prompt = int(status.get("prompt_tokens", 0) or 0)
    completion = int(status.get("completion_tokens", 0) or 0)
    total = int(status.get("total_tokens", prompt + completion) or 0)
    line = f"Tokens: {prompt} prompt + {completion} completion = {total} total"
    if status.get("cost") is not None:
        line += f" (~${float(status['cost']):.4f})"
    context.console.print(line)


def _compact(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    before = status_from_agent(context.agent).get("context_tokens")
    changed = compact_agent(context.agent)
    after = status_from_agent(context.agent).get("context_tokens")
    if before is not None and after is not None:
        context.console.print(f"[green]Context: {before} → {after} tokens[/green]")
    elif changed:
        context.console.print("[green]Context compacted.[/green]")
    else:
        context.console.print("[dim]Nothing to compact.[/dim]")


def _diff(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    context.show_diff()


def _session(context: TerminalContext, args: list[str]) -> None:
    action = args[0] if args else "list"
    if action == "list" and len(args) == 1 or not args:
        records = context.bundle.sessions.list()
        if not records:
            context.console.print("[dim]No saved sessions for this project.[/dim]")
            return
        for record in records:
            preview = next(
                (
                    str(message.get("content", "")).replace("\n", " ")[:70]
                    for message in record.messages
                    if message.get("role") == "user" and message.get("content")
                ),
                "",
            )
            context.console.print(
                f"[cyan]{record.id}[/cyan] · {record.model} · "
                f"{record.updated_at} · {preview}"
            )
        return
    if action == "resume" and len(args) == 2:
        context.resume_session(args[1])
        return
    if action == "delete" and len(args) == 2:
        deleted = context.bundle.sessions.delete(args[1])
        if not deleted:
            raise ValueError(f"Session {args[1]!r} was not found.")
        context.console.print(f"[yellow]Deleted session {args[1]}.[/yellow]")
        return
    raise ValueError("Usage: /session [list|resume ID|delete ID]")


def _skills(context: TerminalContext, args: list[str]) -> None:
    if args not in ([], ["reload"]):
        raise ValueError("Usage: /skills [reload]")
    if args == ["reload"]:
        context.agent.skills = discover_skills(cwd=context.bundle.workspace)
        refresh = getattr(context.agent, "refresh_system_prompt", None)
        if callable(refresh):
            refresh()
        context.console.print("[green]Skills reloaded.[/green]")
    skills = list(getattr(context.agent, "skills", []))
    active = set(status_from_agent(context.agent).get("active_skills", []))
    if not skills:
        context.console.print("[dim]No project skills found.[/dim]")
        return
    for skill in skills:
        marker = " *" if skill.name in active else ""
        description = f" — {skill.description}" if skill.description else ""
        context.console.print(f"[cyan]{skill.name}[/cyan]{marker}{description}")


def _skill(context: TerminalContext, args: list[str]) -> None:
    if len(args) != 1:
        raise ValueError("Skill name is required.")
    activate_agent_skill(context.agent, args[0])
    context.console.print(f"[green]Activated skill {args[0]}.[/green]")


def _memory(context: TerminalContext, args: list[str]) -> None:
    memory = getattr(context.agent, "memory", None) or getattr(
        context.agent, "memory_service", None
    )
    if memory is None:
        context.console.print("[dim]Memory is unavailable for this runtime.[/dim]")
        return
    if not args and hasattr(memory, "status"):
        context.console.print(str(memory.status()))
        return
    if not args and hasattr(memory, "recent_titles"):
        titles = memory.recent_titles(limit=10)
        enabled = getattr(memory, "enabled", True)
        context.console.print(
            f"Memory {'enabled' if enabled else 'disabled'} · {len(titles)} recent item(s)"
        )
        for item in titles:
            context.console.print(f"  {item}")
        return
    if args[:1] == ["search"] and len(args) > 1 and hasattr(memory, "search"):
        context.console.print(str(memory.search(" ".join(args[1:]))))
        return
    if args[:1] == ["save"] and len(args) > 1 and hasattr(memory, "save"):
        text = " ".join(args[1:])
        try:
            result = memory.save(title=text[:80], content=text)
        except TypeError:
            result = memory.save(text)
        context.console.print(str(result))
        return
    if args == ["clear"] and hasattr(memory, "clear"):
        context.console.print(str(memory.clear()))
        return
    raise ValueError("Usage: /memory [search QUERY|save TEXT|clear]")


def _observe(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    context.observe()


def _multiline(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 1)
    if not args:
        value = not context.multiline_mode
    elif args[0] in {"on", "true", "1"}:
        value = True
    elif args[0] in {"off", "false", "0"}:
        value = False
    else:
        raise ValueError("Expected on or off.")
    context.set_multiline(value)
    behavior = "newline" if value else "submit"
    context.console.print(
        "Enter now inserts a newline." if value else "Enter now submits the prompt."
    )


def _editor(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    context.open_editor()


def _verbose(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 1)
    if not args:
        value = not context.verbose
    elif args[0] in {"on", "true", "1"}:
        value = True
    elif args[0] in {"off", "false", "0"}:
        value = False
    else:
        raise ValueError("Expected on or off.")
    context.set_verbose(value)
    context.console.print(f"Verbose tool output {'enabled' if value else 'disabled'}.")


def _exit(context: TerminalContext, args: list[str]) -> None:
    _require_at_most(args, 0)
    context.request_exit()


def default_registry() -> CommandRegistry:
    registry = CommandRegistry()
    for command in (
        Command("help", "show command and input help", _help),
        Command("clear", "clear conversation context", _clear),
        Command("resume", "resume the latest or a named session", _resume, "[ID]"),
        Command("model", "show or switch the active model", _model, "[NAME]"),
        Command("tokens", "show token and cost totals", _tokens),
        Command("compact", "compact conversation context", _compact),
        Command("diff", "show the session diff journal", _diff),
        Command("session", "list, resume, or delete sessions", _session, "[ACTION]"),
        Command("skills", "list or reload project skills", _skills, "[reload]"),
        Command("skill", "activate a project skill", _skill, "NAME"),
        Command("memory", "inspect or update project memory", _memory, "[ACTION]"),
        Command("observe", "start/open local Phoenix", _observe),
        Command("multiline", "toggle Enter between submit and newline", _multiline, "[on|off]"),
        Command("editor", "compose the next prompt in $VISUAL/$EDITOR", _editor),
        Command("verbose", "toggle complete tool output", _verbose, "[on|off]"),
        Command("exit", "exit CoreCoder", _exit, aliases=("quit",)),
    ):
        registry.register(command)
    return registry


__all__ = ["Command", "CommandRegistry", "default_registry"]
