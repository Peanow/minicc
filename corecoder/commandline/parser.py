"""The public ``corecoder`` command tree.

The parser is deliberately kept separate from command execution.  Besides
making ``--help`` cheap, this ensures trace/evaluation commands never require
model credentials merely to parse their arguments.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from corecoder import __version__
from corecoder.policy import PermissionMode


FORMATS = ("auto", "plain", "jsonl")
CONTEXT_STRATEGIES = ("truncate", "summary", "hybrid")
TOKENIZERS = ("auto", "approx", "tiktoken")


def _runtime_options(
    parser: argparse.ArgumentParser,
    *,
    suppress_defaults: bool = False,
) -> None:
    default = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "-m", "--model",
        default=default,
        help="model name (default: $CORECODER_MODEL or gpt-4o)",
    )
    parser.add_argument(
        "--base-url",
        default=default,
        help="OpenAI-compatible API base URL (default: $OPENAI_BASE_URL)",
    )
    parser.add_argument(
        "--permission-mode",
        default=default,
        choices=[mode.value for mode in PermissionMode],
        help="application tool policy (not an OS sandbox)",
    )
    parser.add_argument(
        "--context-strategy",
        default=default,
        choices=CONTEXT_STRATEGIES,
        help="context compression strategy",
    )
    parser.add_argument(
        "--tokenizer",
        default=default,
        choices=TOKENIZERS,
        help="token counter backend",
    )
    parser.add_argument(
        "--trace",
        default=default,
        metavar="PATH",
        help="write a structured JSONL execution trace",
    )


def _eval_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("manifest_path")
    parser.add_argument("-o", "--output")
    parser.add_argument("--task", action="append", dest="eval_tasks")
    parser.add_argument("--model-profile", action="append", dest="eval_models")
    parser.add_argument("--strategy", action="append", dest="eval_strategies")
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and print the case plan without calling a model",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corecoder",
        description="Observable, policy-aware coding agent runtime.",
        allow_abbrev=False,
    )
    _runtime_options(parser)
    parser.add_argument(
        "--continue",
        action="store_true",
        dest="continue_session",
        help="resume the newest complete session for this project",
    )
    parser.add_argument(
        "--ephemeral",
        action="store_true",
        help="do not write history, sessions, or memory",
    )
    parser.add_argument(
        "--observe",
        action="store_true",
        help="start Phoenix and export this interactive session",
    )
    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    run = commands.add_parser("run", help="run one non-interactive task")
    _runtime_options(run, suppress_defaults=True)
    run.add_argument("prompt", nargs="?", help="task prompt")
    run.add_argument(
        "--prompt-file",
        metavar="PATH|-",
        help="read the prompt from a file, or '-' for stdin",
    )
    run.add_argument("--format", choices=FORMATS, default="auto")
    run.add_argument(
        "--save-session",
        action="store_true",
        help="persist this otherwise-ephemeral run",
    )

    session = commands.add_parser("session", help="manage project sessions")
    session_commands = session.add_subparsers(
        dest="session_command", required=True, metavar="ACTION"
    )
    session_commands.add_parser("list", help="list sessions for this project")
    resume = session_commands.add_parser("resume", help="resume a session")
    resume.add_argument("session_id", metavar="ID")
    delete = session_commands.add_parser("delete", help="delete a session")
    delete.add_argument("session_id", metavar="ID")

    trace = commands.add_parser("trace", help="inspect or replay traces")
    trace_commands = trace.add_subparsers(
        dest="trace_command", required=True, metavar="ACTION"
    )
    replay = trace_commands.add_parser(
        "replay", help="validate and summarize a trace without side effects"
    )
    replay.add_argument("trace_path")
    report = trace_commands.add_parser(
        "report", help="generate a self-contained HTML trace report"
    )
    report.add_argument("trace_path")
    report.add_argument("-o", "--output")
    runtime_replay = trace_commands.add_parser(
        "runtime-replay", help="re-execute recorded decisions in a fresh fixture"
    )
    runtime_replay.add_argument("trace_path")
    runtime_replay.add_argument("--fixture", required=True)
    runtime_replay.add_argument("-o", "--output", required=True)

    lab = commands.add_parser("lab", help="run and compare experiments")
    lab_commands = lab.add_subparsers(
        dest="lab_command", required=True, metavar="ACTION"
    )
    evaluation = lab_commands.add_parser("eval", help="run a benchmark manifest")
    _eval_options(evaluation)
    compare = lab_commands.add_parser("compare", help="compare evaluation results")
    compare.add_argument("results", nargs="+")
    compare.add_argument("-o", "--output", required=True)
    evidence = lab_commands.add_parser("evidence", help="export commit-safe evidence")
    evidence.add_argument("evaluation_dir")
    evidence.add_argument("-o", "--output", required=True)

    observe = commands.add_parser("observe", help="manage local Phoenix")
    observe.add_argument("action", choices=("up", "open", "status", "down"))

    doctor = commands.add_parser("doctor", help="diagnose local configuration")
    doctor.add_argument(
        "--connect",
        action="store_true",
        help="also verify the configured model endpoint",
    )

    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)
