"""Interactive REPL - the user-facing terminal interface."""

import sys
import os
import argparse

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from .agent import Agent
from .llm import LLM, LiteLLM
from .config import Config
from .session import save_session, load_session, list_sessions
from .skills import discover_skills, find_skill_by_name, format_skill_invocation
from .hooks import load_hooks, HookEvent
from .tools.skill import SkillTool
from .memory import MemoryStore, get_project_name, format_memory_context
from .embedding import EmbeddingService
from .prompt import system_prompt
from .trace import JsonlTraceSink
from . import __version__

console = Console()


def _parse_args():
    p = argparse.ArgumentParser(
        prog="corecoder",
        description="Minimal AI coding agent. Works with any OpenAI-compatible LLM.",
    )
    p.add_argument("-m", "--model", help="Model name (default: $CORECODER_MODEL or gpt-4o)")
    p.add_argument("--base-url", help="API base URL (default: $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive mode)")
    p.add_argument("-r", "--resume", metavar="ID", help="Resume a saved session")
    p.add_argument("--trace", metavar="PATH", help="Write a structured JSONL execution trace")
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args()


def main():
    args = _parse_args()
    config = Config.from_env()

    # CLI args override env vars
    if args.model:
        config.model = args.model
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key:
        config.api_key = args.api_key

    if not config.api_key:
        console.print("[red bold]No API key found.[/]")
        console.print(
            "Set one of: OPENAI_API_KEY, DEEPSEEK_API_KEY, or CORECODER_API_KEY\n"
            "\nExamples:\n"
            "  # OpenAI\n"
            "  export OPENAI_API_KEY=sk-...\n"
            "\n"
            "  # DeepSeek\n"
            "  export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com\n"
            "\n"
            "  # Ollama (local)\n"
            "  export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1 CORECODER_MODEL=qwen2.5-coder\n"
        )
        sys.exit(1)

    llm_cls = LiteLLM if config.provider == "litellm" else LLM
    llm = llm_cls(
        model=config.model,
        api_key=config.api_key,
        base_url=config.base_url,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )
    # create embedding service from config
    embedding = EmbeddingService(
        provider=config.embedding_provider,
        model=config.embedding_model,
        dims=config.embedding_dims,
        api_key=config.api_key,
        base_url=config.base_url,
    )

    trace = JsonlTraceSink(args.trace) if args.trace else None
    agent = Agent(
        llm=llm,
        max_context_tokens=config.max_context_tokens,
        skills=discover_skills(),
        hooks=load_hooks(),
        embedding=embedding,
        trace=trace,
    )

    # fire SessionStart hooks
    start_result = agent.hooks.run(HookEvent.SessionStart)
    if start_result.message:
        console.print(f"[dim]{start_result.message}[/dim]")

    # resume saved session
    if args.resume:
        loaded = load_session(args.resume)
        if loaded:
            agent.messages, loaded_model = loaded
            # restore the model from the saved session unless overridden by CLI
            if not args.model:
                agent.llm.model = loaded_model
                config.model = loaded_model
            console.print(f"[green]Resumed session: {args.resume} (model: {agent.llm.model})[/green]")
        else:
            console.print(f"[red]Session '{args.resume}' not found.[/red]")
            sys.exit(1)

    # one-shot mode
    if args.prompt:
        try:
            _run_once(agent, args.prompt)
        finally:
            agent.close()
            agent.trace.close()
        return

    # interactive REPL
    try:
        _repl(agent, config)
    finally:
        agent.close()
        agent.trace.close()


def _run_once(agent: Agent, prompt: str):
    """Non-interactive: run one prompt and exit."""
    def on_token(tok):
        print(tok, end="", flush=True)

    def on_tool(name, kwargs):
        console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

    agent.chat(prompt, on_token=on_token, on_tool=on_tool)
    print()


def _repl(agent: Agent, config: Config):
    """Interactive read-eval-print loop."""
    console.print(Panel(
        f"[bold]CoreCoder[/bold] v{__version__}\n"
        f"Model: [cyan]{config.model}[/cyan]"
        + (f"  Base: [dim]{config.base_url}[/dim]" if config.base_url else "")
        + "\nType [bold]/help[/bold] for commands, [bold]Ctrl+C[/bold] to cancel, [bold]quit[/bold] to exit.",
        border_style="blue",
    ))

    hist_path = os.path.expanduser("~/.corecoder_history")
    history = FileHistory(hist_path)

    # Enter submits, Escape+Enter inserts a newline (for pasting code blocks etc.)
    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    while True:
        try:
            user_input = pt_prompt(
                "You > ",
                history=history,
                multiline=True,
                key_bindings=kb,
                prompt_continuation="...  ",
            ).strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\nBye!")
            break

        if not user_input:
            continue

        # built-in commands
        if user_input.lower() in ("quit", "exit", "bye", "/quit", "/exit", "/bye"):
            break
        if user_input == "/help":
            _show_help()
            continue
        if user_input == "/reset":
            agent.reset()
            console.print("[yellow]Conversation reset.[/yellow]")
            continue
        if user_input == "/tokens":
            p = agent.llm.total_prompt_tokens
            c = agent.llm.total_completion_tokens
            line = f"Tokens: [cyan]{p}[/cyan] prompt + [cyan]{c}[/cyan] completion = [bold]{p+c}[/bold] total"
            cost = agent.llm.estimated_cost
            if cost is not None:
                line += f"  (~${cost:.4f})"
            console.print(line)
            continue
        if user_input == "/model" or user_input.startswith("/model "):
            new_model = user_input[7:].strip() if user_input.startswith("/model ") else ""
            if new_model:
                agent.llm.model = new_model
                config.model = new_model
                console.print(f"Switched to [cyan]{new_model}[/cyan]")
            else:
                console.print(f"Current model: [cyan]{config.model}[/cyan]")
            continue
        if user_input == "/compact":
            from .context import estimate_tokens
            before = estimate_tokens(agent.messages)
            compressed = agent.context.maybe_compress(agent.messages, agent.llm)
            after = estimate_tokens(agent.messages)
            if compressed:
                console.print(f"[green]Compressed: {before} → {after} tokens ({len(agent.messages)} messages)[/green]")
            else:
                console.print(f"[dim]Nothing to compress ({before} tokens, {len(agent.messages)} messages)[/dim]")
            continue
        if user_input == "/save":
            sid = save_session(agent.messages, config.model)
            console.print(f"[green]Session saved: {sid}[/green]")
            console.print(f"Resume with: corecoder -r {sid}")
            continue
        if user_input == "/diff":
            changed_files = agent.changed_files
            if not changed_files:
                console.print("[dim]No files modified this session.[/dim]")
            else:
                console.print(f"[bold]Files modified this session ({len(changed_files)}):[/bold]")
                for f in sorted(changed_files):
                    console.print(f"  [cyan]{f}[/cyan]")
            continue
        if user_input == "/sessions":
            sessions = list_sessions()
            if not sessions:
                console.print("[dim]No saved sessions.[/dim]")
            else:
                for s in sessions:
                    console.print(f"  [cyan]{s['id']}[/cyan] ({s['model']}, {s['saved_at']}) {s['preview']}")
            continue
        if user_input == "/skills" or user_input == "/skills reload":
            if user_input == "/skills reload":
                agent.skills = discover_skills()
                agent._system = system_prompt(agent.tools, agent.skills)
                console.print("[green]Skills reloaded.[/green]")
            if not agent.skills:
                console.print("[dim]No skills loaded. Create .corecoder/skills/*.md in your project.[/dim]")
            else:
                console.print(f"[bold]Available skills ({len(agent.skills)}):[/bold]")
                for s in agent.skills:
                    active = " [green]*[/green]" if s.name in agent.active_skills else ""
                    desc = f" — {s.description}" if s.description else ""
                    console.print(f"  [cyan]{s.name}[/cyan]{desc}{active}")
                console.print("[dim]Use /skill <name> or the skill tool to activate. * = active[/dim]")
            continue
        if user_input.startswith("/skill "):
            skill_name = user_input[7:].strip()
            if not skill_name:
                console.print("[dim]Usage: /skill <name>[/dim]")
                continue
            skill = find_skill_by_name(agent.skills, skill_name)
            if skill is None:
                available = ", ".join(s.name for s in agent.skills) or "none"
                console.print(f"[red]Skill '{skill_name}' not found.[/red] Available: {available}")
                continue
            # Inject skill content as a user message, same effect as SkillTool
            agent.active_skills.add(skill.name)
            invocation = format_skill_invocation(skill)
            agent.messages.append({"role": "user", "content": invocation})
            # Let the LLM acknowledge and follow the skill
            ack = agent.chat("Acknowledge that you have activated this skill and will follow its instructions.", on_token=lambda tok: print(tok, end="", flush=True))
            print()
            continue
        # ── /memory commands ──
        if user_input == "/memory":
            _show_memory(agent)
            continue
        if user_input.startswith("/memory search "):
            query = user_input[15:].strip()
            if query:
                _search_memory(agent, query)
            else:
                console.print("[dim]Usage: /memory search <query>[/dim]")
            continue
        if user_input.startswith("/memory save "):
            text = user_input[13:].strip()
            if text:
                _save_memory(agent, text)
            else:
                console.print("[dim]Usage: /memory save <text>[/dim]")
            continue
        if user_input == "/memory clear":
            _clear_memory(agent)
            continue

        # call the agent
        streamed: list[str] = []

        def on_token(tok):
            streamed.append(tok)
            print(tok, end="", flush=True)

        def on_tool(name, kwargs):
            console.print(f"\n[dim]> {name}({_brief(kwargs)})[/dim]")

        try:
            response = agent.chat(user_input, on_token=on_token, on_tool=on_tool)
            if streamed:
                print()  # newline after streamed tokens
            else:
                # response wasn't streamed (came after tool calls)
                console.print(Markdown(response))
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")


def _show_help():
    console.print(Panel(
        "[bold]Commands:[/bold]\n"
        "  /help          Show this help\n"
        "  /reset         Clear conversation history\n"
        "  /model         Show current model\n"
        "  /model <name>  Switch model mid-conversation\n"
        "  /tokens        Show token usage\n"
        "  /compact       Compress conversation context\n"
        "  /diff          Show files modified this session\n"
        "  /save          Save session to disk\n"
        "  /sessions      List saved sessions\n"
        "  /skills        List available skills\n"
        "  /skills reload Reload skills from .corecoder/skills/\n"
        "  /skill <name>  Activate a skill for this session\n"
        "  /memory        Show memory stats for this project\n"
        "  /memory search <query>  Search memory\n"
        "  /memory save <text>     Save a manual memory\n"
        "  /memory clear           Clear all memories for this project\n"
        "  quit           Exit CoreCoder\n"
        "\n"
        "[bold]Input:[/bold]\n"
        "  Enter          Submit message\n"
        "  Esc+Enter      Insert newline (for pasting code)",
        title="CoreCoder Help",
        border_style="dim",
    ))


def _show_memory(agent: Agent):
    """Show memory stats for the current project."""
    project = get_project_name()
    store = MemoryStore()
    try:
        count = store.count(project)
        recent = store.get_recent(project, limit=5)
    finally:
        store.close()

    console.print(f"[bold]Memory for {project}[/bold] — {count} observation(s)")
    if recent:
        for obs in recent:
            console.print(f"  [cyan][{obs.type}][/cyan] {obs.title} [dim]({obs.created_at})[/dim]")
    else:
        console.print("[dim]No memories yet. Observations are auto-saved at session end.[/dim]")


def _search_memory(agent: Agent, query: str):
    """Search memory for a query."""
    project = get_project_name()
    store = MemoryStore()
    try:
        results = store.search(project, query, limit=10)
    finally:
        store.close()

    if not results:
        console.print(f"[dim]No memories found for '{query}'[/dim]")
        return

    console.print(f"[bold]Memory search: '{query}'[/bold] — {len(results)} result(s)")
    for obs in results:
        snippet = obs.content[:120] + ("..." if len(obs.content) > 120 else "")
        console.print(f"  [cyan][{obs.type}][/cyan] {obs.title}")
        console.print(f"  [dim]{snippet}[/dim]")


def _save_memory(agent: Agent, text: str):
    """Manually save a memory."""
    from .memory import Observation
    project = get_project_name()
    obs = Observation(
        project=project,
        kind="manual",
        type="discovery",
        title=text[:80],
        content=text,
    )
    store = MemoryStore()
    try:
        row_id = store.save(obs)
    finally:
        store.close()

    if row_id:
        console.print(f"[green]Memory saved (id={row_id})[/green]")
    else:
        console.print("[dim]Memory already exists (duplicate)[/dim]")


def _clear_memory(agent: Agent):
    """Clear all memories for the current project."""
    project = get_project_name()
    store = MemoryStore()
    try:
        count = store.delete_project(project)
    finally:
        store.close()

    console.print(f"[yellow]Cleared {count} memory item(s) for {project}[/yellow]")


def _brief(kwargs: dict, maxlen: int = 80) -> str:
    s = ", ".join(f"{k}={repr(v)[:40]}" for k, v in kwargs.items())
    return s[:maxlen] + ("..." if len(s) > maxlen else "")
