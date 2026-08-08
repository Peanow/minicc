"""Implementation of the public command tree."""

from __future__ import annotations

import json
import os
import select
import stat
import sys
import time
from argparse import Namespace
from pathlib import Path
from typing import TextIO

from rich.console import Console
from rich.table import Table

from corecoder.comparison import generate_comparison_report
from corecoder.config import Config
from corecoder.eval import load_manifest, plan_cases, run_evaluation
from corecoder.evidence import export_evidence
from corecoder.observability import ObservabilityConfig, ObservabilityError, PhoenixManager
from corecoder.paths import AppPaths
from corecoder.replay import generate_html_report, replay_trace
from corecoder.runtime_replay import runtime_replay
from corecoder.session import SessionError, SessionStore
from corecoder.terminal.approval import ApprovalPrompt
from corecoder.terminal.app import TerminalApp
from corecoder.terminal.render import EventRenderer, NormalizedEvent, OutputMode, result_data

from .runtime import (
    ConfigurationError,
    apply_runtime_options,
    build_runtime,
    run_agent,
    start_agent_session,
)


def _consoles(stdout: TextIO, stderr: TextIO) -> tuple[Console, Console]:
    return Console(file=stdout), Console(file=stderr)


def _stream_has_data(stream: TextIO) -> bool:
    """Best-effort non-blocking detection of actual redirected input."""
    if hasattr(stream, "getvalue"):
        try:
            value = stream.getvalue()
            position = stream.tell() if hasattr(stream, "tell") else 0
            return bool(value[position:])
        except (OSError, TypeError, ValueError):
            pass
    try:
        if stream.isatty():
            return False
    except (AttributeError, OSError):
        return False
    try:
        descriptor = stream.fileno()
        mode = os.fstat(descriptor).st_mode
    except (AttributeError, OSError, ValueError):
        return False
    if stat.S_ISREG(mode):
        try:
            return os.fstat(descriptor).st_size > stream.tell()
        except (OSError, ValueError):
            return True
    if stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode):
        try:
            ready, _, _ = select.select([descriptor], [], [], 0)
            return bool(ready)
        except (OSError, ValueError):
            return True
    return False


def resolve_prompt(args: Namespace, stdin: TextIO) -> str:
    prompt = getattr(args, "prompt", None)
    prompt_file = getattr(args, "prompt_file", None)
    piped = _stream_has_data(stdin)
    sources = int(prompt is not None) + int(prompt_file is not None) + int(
        piped and prompt_file != "-"
    )
    if sources > 1:
        raise ValueError(
            "Provide exactly one prompt source: PROMPT, --prompt-file, or stdin."
        )
    if prompt_file == "-":
        return stdin.read()
    if prompt_file is not None:
        try:
            return Path(prompt_file).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Unable to read prompt file {prompt_file!r}: {exc}") from exc
    if prompt is not None:
        return prompt
    if piped:
        return stdin.read()
    raise ValueError("No prompt was supplied. Pass PROMPT, --prompt-file, or stdin.")


def _resolved_mode(requested: str, stdout: TextIO) -> OutputMode:
    if requested != "auto":
        return OutputMode(requested)
    try:
        return OutputMode.PRETTY if stdout.isatty() else OutputMode.PLAIN
    except (AttributeError, OSError):
        return OutputMode.PLAIN


def run_once(
    args: Namespace,
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    try:
        prompt = resolve_prompt(args, stdin)
    except ValueError as exc:
        Console(file=stderr).print(f"[red]Input error:[/red] {exc}")
        return 2
    if not prompt.strip():
        Console(file=stderr).print("[red]Input error:[/red] The prompt is empty.")
        return 2
    mode = _resolved_mode(args.format, stdout)
    renderer = EventRenderer(
        mode,
        stdout=stdout,
        stderr=stderr,
        no_color=bool(os.getenv("NO_COLOR")),
    )
    try:
        bundle = build_runtime(args, ephemeral=not args.save_session)
    except (ConfigurationError, ObservabilityError, RuntimeError, ValueError) as exc:
        Console(file=stderr).print(f"[red]Configuration error:[/red] {exc}")
        return 2
    try:
        try:
            start_agent_session(bundle.agent)
            result = run_agent(bundle.agent, prompt, renderer)
            renderer.finish(result)
        except KeyboardInterrupt:
            if not renderer.finished:
                renderer.emit(NormalizedEvent(
                    "run_finished", renderer.run_id, time.time(),
                    {"status": "cancelled", "error": "interrupted"},
                ))
            return 130
        except Exception as exc:
            if not renderer.finished:
                renderer.emit(NormalizedEvent(
                    "run_finished", renderer.run_id, time.time(),
                    {"status": "error", "error": str(exc), "error_type": type(exc).__name__},
                ))
            return 1
        data = result_data(result)
        status = str(data.get("status", "completed"))
        if args.save_session and status in {"completed", "success", "done"}:
            try:
                bundle.sessions.checkpoint(bundle.agent, bundle.config, status=status)
            except (OSError, SessionError, TypeError, ValueError) as exc:
                Console(file=stderr).print(f"Session checkpoint failed: {exc}", markup=False)
                return 1
        return 0 if status in {"completed", "success", "done"} else 1
    finally:
        renderer.close()
        bundle.close()


def run_interactive(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
    resume_id: str | None = None,
    continue_latest: bool = False,
) -> int:
    console = Console(file=stdout)
    approval = ApprovalPrompt(console=Console(file=stderr))
    try:
        bundle = build_runtime(
            args,
            approval_callback=approval,
            ephemeral=bool(getattr(args, "ephemeral", False)),
        )
    except (ConfigurationError, ObservabilityError, RuntimeError, ValueError) as exc:
        Console(file=stderr).print(f"[red]Configuration error:[/red] {exc}")
        return 2
    try:
        if resume_id or continue_latest:
            try:
                record = bundle.sessions.load(resume_id) if resume_id else bundle.sessions.latest()
                bundle.sessions.restore(bundle.agent, record)
                bundle.config.model = record.model
            except SessionError as exc:
                Console(file=stderr).print(f"[red]Session error:[/red] {exc}")
                return 1
        return TerminalApp(
            bundle,
            console=console,
            initial_session=record if resume_id or continue_latest else None,
        ).run()
    except KeyboardInterrupt:
        console.print("[yellow]Interrupted.[/yellow]")
        return 130
    finally:
        bundle.close()


def handle_session(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    if args.session_command == "resume":
        return run_interactive(
            args,
            stdout=stdout,
            stderr=stderr,
            resume_id=args.session_id,
        )
    store = SessionStore(AppPaths(), Path.cwd())
    console, errors = _consoles(stdout, stderr)
    try:
        if args.session_command == "list":
            records = store.list(limit=20)
            if not records:
                console.print("[dim]No saved sessions for this project.[/dim]")
                return 0
            for record in records:
                console.print(
                    f"[cyan]{record.id}[/cyan]\t{record.model}\t"
                    f"{record.updated_at}\t{record.last_run_status}"
                )
            return 0
        if not store.delete(args.session_id):
            errors.print(f"[red]Session {args.session_id!r} was not found.[/red]")
            return 1
        console.print(f"Deleted session {args.session_id}.")
        return 0
    except SessionError as exc:
        errors.print(f"[red]Session error:[/red] {exc}")
        return 1


def handle_trace(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    console, errors = _consoles(stdout, stderr)
    try:
        if args.trace_command == "replay":
            summary = replay_trace(args.trace_path)
            stdout.write(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2) + "\n")
            return 0 if summary.valid else 1
        if args.trace_command == "report":
            output = args.output or str(Path(args.trace_path).with_suffix(".html"))
            summary = generate_html_report(args.trace_path, output)
            console.print(f"[green]Report written:[/green] {Path(output).resolve()}")
            if not summary.valid:
                errors.print("[yellow]Warning: trace validation reported errors.[/yellow]")
            return 0
        result = runtime_replay(args.trace_path, args.fixture, args.output)
        stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n")
        return 0 if result.valid else 1
    except (OSError, ValueError) as exc:
        errors.print(f"[red]Trace command failed:[/red] {exc}")
        return 2


def handle_lab(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    console, errors = _consoles(stdout, stderr)
    try:
        if args.lab_command == "compare":
            summary = generate_comparison_report(args.results, args.output)
            console.print(
                f"[green]Comparison written:[/green] {Path(args.output).resolve()} "
                f"({summary.record_count} records)"
            )
            return 0
        if args.lab_command == "evidence":
            exported = export_evidence(args.evaluation_dir, args.output)
            stdout.write(json.dumps(exported.to_dict(), ensure_ascii=False, indent=2) + "\n")
            return 0

        manifest = load_manifest(args.manifest_path)
        cases = plan_cases(
            manifest,
            task_ids=set(args.eval_tasks or []),
            model_ids=set(args.eval_models or []),
            strategy_ids=set(args.eval_strategies or []),
            repetitions=args.repeat,
            limit=args.limit,
        )
        if args.dry_run:
            payload = {
                "manifest": manifest.name,
                "tier": manifest.tier,
                "repetitions": (
                    cases[0].repetition_count if cases else args.repeat or manifest.repetitions
                ),
                "case_count": len(cases),
                "cases": [case.id for case in cases],
            }
            stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            return 0
        if not cases:
            console.print("[yellow]Evaluation plan has no enabled cases.[/yellow]")
            return 0
        output = args.output or str(
            Path("benchmarks") / "results" /
            f"{manifest.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        )
        summary = run_evaluation(manifest, cases, output)
        console.print(
            f"[green]Evaluation complete:[/green] "
            f"{summary.successful_cases}/{summary.total_cases} passed"
        )
        console.print(f"[dim]Evidence: {Path(output).resolve()}[/dim]")
        return 0
    except (OSError, ValueError) as exc:
        errors.print(f"[red]Lab command failed:[/red] {exc}")
        return 2


def handle_observe(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    console, errors = _consoles(stdout, stderr)
    try:
        manager = PhoenixManager(ObservabilityConfig.from_env())
        if args.action == "status":
            if manager.is_healthy():
                console.print(f"[green]Phoenix is running:[/green] {manager.config.ui_url}")
                return 0
            errors.print("[yellow]Phoenix is not running.[/yellow]")
            return 1
        if args.action == "down":
            manager.down()
            console.print("[green]Phoenix stopped; trace data was preserved.[/green]")
            return 0
        if args.action == "up":
            started = manager.up()
            label = "started" if started else "already running"
            console.print(f"[green]Phoenix {label}:[/green] {manager.config.ui_url}")
            return 0
        opened = manager.open()
        console.print(f"[green]Phoenix ready:[/green] {manager.config.ui_url}")
        if not opened:
            errors.print("[yellow]Browser could not be opened; use the URL above.[/yellow]")
        return 0
    except (ObservabilityError, ValueError) as exc:
        errors.print(f"[red]Observability error:[/red] {exc}")
        return 2


def handle_doctor(
    args: Namespace,
    *,
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    console, errors = _consoles(stdout, stderr)
    config = apply_runtime_options(Config.from_env(), args)
    checks = [
        ("model", bool(config.model), config.model or "missing"),
        ("API key", bool(config.api_key), "configured" if config.api_key else "missing"),
        ("workspace", Path.cwd().is_dir(), str(Path.cwd())),
        ("permission", True, config.permission_mode),
        ("context", True, config.context_strategy),
    ]
    table = Table(title="CoreCoder doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for name, ok, detail in checks:
        table.add_row(name, "[green]ok[/green]" if ok else "[red]failed[/red]", detail)
    console.print(table)
    if not all(ok for _, ok, _ in checks):
        return 1
    if not args.connect:
        return 0
    try:
        bundle = build_runtime(args, ephemeral=True)
        try:
            client = getattr(getattr(bundle.agent, "llm", None), "client", None)
            if client is None or not hasattr(client, "models"):
                raise ConfigurationError("this provider does not expose a model-list probe")
            client.models.list()
        finally:
            bundle.close()
    except Exception as exc:
        errors.print(f"[red]Endpoint check failed:[/red] {exc}")
        return 1
    console.print("[green]Model endpoint reachable.[/green]")
    return 0


def dispatch(
    args: Namespace,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    if args.command == "run":
        return run_once(args, stdin=stdin, stdout=stdout, stderr=stderr)
    if args.command == "session":
        return handle_session(args, stdout=stdout, stderr=stderr)
    if args.command == "trace":
        return handle_trace(args, stdout=stdout, stderr=stderr)
    if args.command == "lab":
        return handle_lab(args, stdout=stdout, stderr=stderr)
    if args.command == "observe":
        return handle_observe(args, stdout=stdout, stderr=stderr)
    if args.command == "doctor":
        return handle_doctor(args, stdout=stdout, stderr=stderr)
    return run_interactive(
        args,
        stdout=stdout,
        stderr=stderr,
        continue_latest=bool(args.continue_session),
    )


__all__ = ["dispatch", "resolve_prompt", "run_interactive", "run_once"]
