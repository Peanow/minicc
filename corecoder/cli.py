"""Interactive REPL - the user-facing terminal interface."""

import sys
import os
import argparse
import json
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit import prompt as pt_prompt
from prompt_toolkit.application import get_app
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.mouse_events import MouseEventType

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
from .trace import CompositeTraceSink, JsonlTraceSink, OpenTelemetryTraceSink
from .observability import (
    ObservabilityConfig,
    ObservabilityError,
    PhoenixManager,
)
from .policy import ExecutionPolicy, PermissionMode
from .context import create_context_strategy
from .tokenizer import create_token_counter
from .replay import generate_html_report, replay_trace
from .eval import load_manifest, plan_cases, run_evaluation
from .runtime_replay import runtime_replay
from .comparison import generate_comparison_report
from .evidence import export_evidence
from . import __version__

console = Console()


def _run_observe_command(action: str):
    try:
        from .config import _load_dotenv

        _load_dotenv()
        config = ObservabilityConfig.from_env()
        manager = PhoenixManager(config)
        if action == "status":
            if manager.is_healthy():
                console.print(f"[green]Phoenix is running:[/green] {config.ui_url}")
            else:
                console.print("[yellow]Phoenix is not running.[/yellow]")
                sys.exit(1)
        elif action == "down":
            manager.down()
            console.print("[green]Phoenix stopped; trace data was preserved.[/green]")
        elif action == "up":
            started = manager.up()
            label = "started" if started else "already running"
            console.print(f"[green]Phoenix {label}:[/green] {config.ui_url}")
        else:
            opened = manager.open()
            console.print(f"[green]Phoenix ready:[/green] {config.ui_url}")
            if not opened:
                console.print("[yellow]Browser could not be opened; use the URL above.[/yellow]")
    except (ObservabilityError, ValueError) as exc:
        console.print(f"[red]Observability error:[/red] {exc}")
        sys.exit(2)


def _enable_observability(
    agent: Agent,
    manager: PhoenixManager,
    open_browser: bool = True,
) -> bool:
    """Start Phoenix and attach one OTLP sink for subsequent agent runs."""
    try:
        opened = manager.open() if open_browser else True
        if not open_browser:
            manager.up()
        trace = agent.trace
        if not isinstance(trace, CompositeTraceSink):
            raise ObservabilityError("The active Agent trace sink cannot be extended.")
        if not any(isinstance(sink, OpenTelemetryTraceSink) for sink in trace.sinks):
            trace.add_sink(manager.create_trace_sink(trace.session_id))
        console.print(f"[green]Observability ready:[/green] {manager.config.ui_url}")
        if open_browser and not opened:
            console.print("[yellow]Browser could not be opened; use the URL above.[/yellow]")
        return True
    except (ObservabilityError, RuntimeError) as exc:
        console.print(f"[red]Observability unavailable:[/red] {exc}")
        return False


def _parse_args():
    p = argparse.ArgumentParser(
        prog="corecoder",
        description="Observable multi-model coding agent experimentation runtime.",
    )
    p.add_argument("-m", "--model", help="Model name (default: $CORECODER_MODEL or gpt-4o)")
    p.add_argument("--base-url", help="API base URL (default: $OPENAI_BASE_URL)")
    p.add_argument("--api-key", help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("-p", "--prompt", help="One-shot prompt (non-interactive mode)")
    p.add_argument("-r", "--resume", metavar="ID", help="Resume a saved session")
    p.add_argument("--trace", metavar="PATH", help="Write a structured JSONL execution trace")
    p.add_argument(
        "--observe",
        action="store_true",
        help="Start local Phoenix and export this session over OTLP",
    )
    p.add_argument(
        "--permission-mode",
        choices=[mode.value for mode in PermissionMode],
        help="Tool permission mode (default: $CORECODER_PERMISSION_MODE or workspace-write)",
    )
    p.add_argument(
        "--context-strategy",
        choices=["truncate", "summary", "hybrid"],
        help="Context compression strategy (default: hybrid)",
    )
    p.add_argument(
        "--tokenizer",
        choices=["auto", "approx", "tiktoken"],
        help="Token counter backend (default: auto)",
    )
    subcommands = p.add_subparsers(dest="command")
    replay_parser = subcommands.add_parser(
        "replay",
        help="Validate a trace and print a side-effect-free replay summary",
    )
    replay_parser.add_argument("trace_path")
    report_parser = subcommands.add_parser(
        "report",
        help="Generate a self-contained HTML report from a trace",
    )
    report_parser.add_argument("trace_path")
    report_parser.add_argument("-o", "--output")
    eval_parser = subcommands.add_parser(
        "eval",
        help="Run or inspect a reproducible benchmark manifest",
    )
    eval_parser.add_argument("manifest_path")
    eval_parser.add_argument("-o", "--output")
    eval_parser.add_argument("--task", action="append", dest="eval_tasks")
    eval_parser.add_argument("--model-profile", action="append", dest="eval_models")
    eval_parser.add_argument("--strategy", action="append", dest="eval_strategies")
    eval_parser.add_argument(
        "--repeat",
        type=int,
        help="Override manifest repetitions for each task/model/strategy case",
    )
    eval_parser.add_argument("--limit", type=int)
    eval_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print the case plan without calling a model",
    )
    runtime_replay_parser = subcommands.add_parser(
        "runtime-replay",
        help="Re-execute recorded model decisions in a fresh fixture workspace",
    )
    runtime_replay_parser.add_argument("trace_path")
    runtime_replay_parser.add_argument("--fixture", required=True)
    runtime_replay_parser.add_argument("-o", "--output", required=True)
    compare_parser = subcommands.add_parser(
        "compare",
        help="Generate a multi-model and multi-strategy HTML comparison",
    )
    compare_parser.add_argument("results", nargs="+")
    compare_parser.add_argument("-o", "--output", required=True)
    evidence_parser = subcommands.add_parser(
        "evidence",
        help="Audit an evaluation and export commit-safe evidence",
    )
    evidence_parser.add_argument("evaluation_dir")
    evidence_parser.add_argument("-o", "--output", required=True)
    observe_parser = subcommands.add_parser(
        "observe",
        help="Manage the local Phoenix observability platform",
    )
    observe_parser.add_argument(
        "action",
        choices=["up", "open", "status", "down"],
    )
    p.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args()


def main():
    args = _parse_args()
    if args.command == "observe":
        _run_observe_command(args.action)
        return
    if args.command == "replay":
        try:
            summary = replay_trace(args.trace_path)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Replay failed:[/red] {exc}")
            sys.exit(2)
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
        if not summary.valid:
            sys.exit(1)
        return
    if args.command == "report":
        output = args.output or str(
            os.path.splitext(args.trace_path)[0] + ".html"
        )
        try:
            summary = generate_html_report(args.trace_path, output)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Report failed:[/red] {exc}")
            sys.exit(2)
        console.print(f"[green]Report written:[/green] {os.path.abspath(output)}")
        if not summary.valid:
            console.print("[yellow]Warning: trace validation reported errors.[/yellow]")
        return
    if args.command == "eval":
        try:
            manifest = load_manifest(args.manifest_path)
            cases = plan_cases(
                manifest,
                task_ids=set(args.eval_tasks or []),
                model_ids=set(args.eval_models or []),
                strategy_ids=set(args.eval_strategies or []),
                repetitions=args.repeat,
                limit=args.limit,
            )
        except (OSError, ValueError) as exc:
            console.print(f"[red]Evaluation plan failed:[/red] {exc}")
            sys.exit(2)
        if args.dry_run:
            payload = {
                "manifest": manifest.name,
                "tier": manifest.tier,
                "repetitions": (
                    cases[0].repetition_count
                    if cases
                    else args.repeat or manifest.repetitions
                ),
                "case_count": len(cases),
                "cases": [case.id for case in cases],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        if not cases:
            console.print("[yellow]Evaluation plan has no enabled cases.[/yellow]")
            return
        from .config import _load_dotenv

        _load_dotenv()
        output = args.output or os.path.join(
            "benchmarks",
            "results",
            f"{manifest.name}-{time.strftime('%Y%m%d-%H%M%S')}",
        )
        try:
            summary = run_evaluation(manifest, cases, output)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Evaluation failed:[/red] {exc}")
            sys.exit(2)
        console.print(
            f"[green]Evaluation complete:[/green] "
            f"{summary.successful_cases}/{summary.total_cases} passed"
        )
        console.print(f"[dim]Evidence: {os.path.abspath(output)}[/dim]")
        return
    if args.command == "runtime-replay":
        try:
            result = runtime_replay(
                args.trace_path,
                args.fixture,
                args.output,
            )
        except (OSError, ValueError) as exc:
            console.print(f"[red]Runtime replay failed:[/red] {exc}")
            sys.exit(2)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if not result.valid:
            sys.exit(1)
        return
    if args.command == "compare":
        try:
            summary = generate_comparison_report(args.results, args.output)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Comparison failed:[/red] {exc}")
            sys.exit(2)
        console.print(
            f"[green]Comparison written:[/green] {os.path.abspath(args.output)} "
            f"({summary.record_count} records)"
        )
        return
    if args.command == "evidence":
        try:
            exported = export_evidence(args.evaluation_dir, args.output)
        except (OSError, ValueError) as exc:
            console.print(f"[red]Evidence export failed:[/red] {exc}")
            sys.exit(2)
        print(json.dumps(exported.to_dict(), ensure_ascii=False, indent=2))
        return

    config = Config.from_env()
    if os.getenv("CORECODER_SANITIZE_TOOL_ENV") == "1":
        for key in (
            "CORECODER_API_KEY",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
            "CORECODER_EVAL_COMPARISON_API_KEY",
        ):
            os.environ.pop(key, None)
        os.environ.pop("CORECODER_SANITIZE_TOOL_ENV", None)

    # CLI args override env vars
    if args.model:
        config.model = args.model
    if args.base_url:
        config.base_url = args.base_url
    if args.api_key:
        config.api_key = args.api_key
    if args.permission_mode:
        config.permission_mode = args.permission_mode
    if args.context_strategy:
        config.context_strategy = args.context_strategy
    if args.tokenizer:
        config.tokenizer_provider = args.tokenizer

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

    trace_sinks = [JsonlTraceSink(args.trace)] if args.trace else []
    trace = CompositeTraceSink(trace_sinks)
    try:
        observability = ObservabilityConfig.from_env()
    except ValueError as exc:
        console.print(f"[red]Invalid observability configuration:[/red] {exc}")
        sys.exit(2)
    manager = PhoenixManager(observability)
    if args.observe:
        try:
            manager.up()
            console.print(
                f"[green]Observability ready:[/green] {observability.ui_url}"
            )
        except (ObservabilityError, RuntimeError) as exc:
            console.print(f"[red]Observability unavailable:[/red] {exc}")
            sys.exit(2)
    if args.observe or observability.backend == "otel":
        try:
            trace.add_sink(manager.create_trace_sink(trace.session_id))
        except RuntimeError as exc:
            console.print(f"[red]Observability unavailable:[/red] {exc}")
            sys.exit(2)
    approval_callback = None if args.prompt else _approve_tool
    policy = ExecutionPolicy(
        mode=config.permission_mode,
        workspace=os.getcwd(),
        approval_callback=approval_callback,
    )
    token_counter = create_token_counter(config.tokenizer_provider, config.model)
    context = create_context_strategy(
        config.context_strategy,
        max_tokens=config.max_context_tokens,
        token_counter=token_counter,
    )
    agent = Agent(
        llm=llm,
        max_context_tokens=config.max_context_tokens,
        skills=discover_skills(),
        hooks=load_hooks(),
        embedding=embedding,
        trace=trace,
        policy=policy,
        context_strategy=context,
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
                _refresh_context_for_model(agent, config)
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
        _repl(agent, config, manager)
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


def _approve_tool(tool_name: str, arguments: dict, reason: str) -> bool:
    """Interactive approval for policy decisions that require user consent."""
    console.print(
        f"\n[yellow]Approval required:[/yellow] {tool_name}({_brief(arguments)})"
    )
    console.print(f"[dim]{reason}[/dim]")
    answer = console.input("Allow once? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _refresh_context_for_model(agent: Agent, config: Config):
    """Rebuild model-dependent token counting without touching messages."""
    agent.context = create_context_strategy(
        config.context_strategy,
        max_tokens=config.max_context_tokens,
        token_counter=create_token_counter(config.tokenizer_provider, config.model),
    )


def _repl(agent: Agent, config: Config, manager: PhoenixManager):
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

    @kb.add("f2")
    def _open_observability(event):
        event.current_buffer.text = "/observe"
        event.current_buffer.validate_and_handle()

    def _toolbar_click(mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            app = get_app()
            app.current_buffer.text = "/observe"
            app.current_buffer.validate_and_handle()

    def _bottom_toolbar():
        state = "ON" if manager.is_healthy(timeout=0.1) else "OFF"
        style = "class:observe-on" if state == "ON" else "class:observe-off"
        return FormattedText([
            (style, f" [ Observability: {state} · click or F2 ] ", _toolbar_click),
        ])

    while True:
        try:
            user_input = pt_prompt(
                "You > ",
                history=history,
                multiline=True,
                key_bindings=kb,
                prompt_continuation="...  ",
                bottom_toolbar=_bottom_toolbar,
                mouse_support=True,
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
        if user_input == "/observe":
            _enable_observability(agent, manager, open_browser=True)
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
                _refresh_context_for_model(agent, config)
                agent.trace.emit(
                    "model_changed",
                    model=new_model,
                    token_counter=agent.context.token_counter.name,
                )
                console.print(f"Switched to [cyan]{new_model}[/cyan]")
            else:
                console.print(f"Current model: [cyan]{config.model}[/cyan]")
            continue
        if user_input == "/compact":
            before = agent.context_tokens()
            compressed = agent._maybe_compress()
            after = agent.context_tokens()
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
                agent.refresh_system_prompt()
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
            agent.trace.emit(
                "skill_activated",
                skill=skill.name,
                source=str(skill.source_path),
                activation="explicit",
            )
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
        "  /observe       Start/open local Phoenix observability\n"
        "  quit           Exit CoreCoder\n"
        "\n"
        "[bold]Input:[/bold]\n"
        "  Enter          Submit message\n"
        "  Esc+Enter      Insert newline (for pasting code)\n"
        "  F2             Start/open local observability",
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
