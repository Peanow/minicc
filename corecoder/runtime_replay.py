"""Deterministic Agent Runtime replay driven by recorded LLM responses."""

from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

from .agent import Agent
from .context import create_context_strategy
from .embedding import EmbeddingService
from .hooks import HookConfig
from .instructions import load_project_instructions
from .llm import LLMResponse, ToolCall
from .policy import ExecutionPolicy
from .skills import discover_skills
from .tokenizer import create_token_counter
from .trace import JsonlTraceSink, request_fingerprint
from .replay import load_trace, replay_trace


class ReplayDivergence(RuntimeError):
    """Raised when live replay state no longer matches the recording."""


@dataclass(frozen=True)
class RecordedExchange:
    request_fingerprint: str
    response: LLMResponse


@dataclass
class RuntimeReplayResult:
    valid: bool
    run_id: str
    llm_calls: int
    tool_results_match: bool
    final_answer_match: bool
    changed_files: list[str]
    divergences: list[str]
    replay_trace_path: str
    workspace: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _event_data(events: list[dict], name: str) -> list[dict]:
    return [
        event.get("data") or {}
        for event in events
        if event.get("event") == name
    ]


def _rebase(value: Any, source_workspace: Path, replay_workspace: Path) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _rebase(item, source_workspace, replay_workspace)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rebase(item, source_workspace, replay_workspace) for item in value]
    if isinstance(value, str):
        return value.replace(str(source_workspace), str(replay_workspace))
    return value


def _validate_paths(tool_name: str, arguments: dict, workspace: Path) -> None:
    path_keys = {
        "read_file": ("file_path",),
        "write_file": ("file_path",),
        "edit_file": ("file_path",),
        "glob": ("path",),
        "grep": ("path",),
    }.get(tool_name, ())
    for key in path_keys:
        value = arguments.get(key)
        if not isinstance(value, str) or not value:
            continue
        path = Path(value).expanduser()
        resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError as exc:
            raise ReplayDivergence(
                f"recorded {tool_name}.{key} escapes replay workspace"
            ) from exc


class RecordedLLM:
    """LLM-compatible adapter that returns a finite recorded response sequence."""

    def __init__(
        self,
        exchanges: list[RecordedExchange],
        *,
        model: str,
        source_workspace: Path,
        replay_workspace: Path,
    ):
        self.exchanges = exchanges
        self.model = model
        self.source_workspace = source_workspace
        self.replay_workspace = replay_workspace
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self._index = 0

    @property
    def estimated_cost(self) -> None:
        return None

    @property
    def consumed(self) -> int:
        return self._index

    def chat(self, messages: list[dict], tools: list[dict] | None = None, on_token=None):
        if self._index >= len(self.exchanges):
            raise ReplayDivergence("agent requested more LLM calls than recorded")
        exchange = self.exchanges[self._index]
        actual = request_fingerprint(
            messages,
            tools or [],
            self.replay_workspace,
        )
        if actual != exchange.request_fingerprint:
            raise ReplayDivergence(
                f"LLM request {self._index + 1} fingerprint mismatch"
            )

        response = exchange.response
        rebased_calls: list[ToolCall] = []
        for call in response.tool_calls:
            arguments = _rebase(
                call.arguments,
                self.source_workspace,
                self.replay_workspace,
            )
            _validate_paths(call.name, arguments, self.replay_workspace)
            rebased_calls.append(ToolCall(call.id, call.name, arguments))
        replayed = LLMResponse(
            content=_rebase(
                response.content,
                self.source_workspace,
                self.replay_workspace,
            ),
            tool_calls=rebased_calls,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
        )
        self._index += 1
        self.total_prompt_tokens += replayed.prompt_tokens
        self.total_completion_tokens += replayed.completion_tokens
        if on_token and replayed.content:
            on_token(replayed.content)
        return replayed


def _load_recording(events: list[dict]) -> tuple[dict, list[RecordedExchange]]:
    starts = _event_data(events, "run_started")
    if len(starts) != 1:
        raise ValueError("runtime replay requires exactly one run_started event")
    run = starts[0]
    if not run.get("workspace"):
        raise ValueError("trace does not record its source workspace")

    llm_starts = _event_data(events, "model_started") or _event_data(events, "llm_started")
    llm_finishes = _event_data(events, "model_finished") or _event_data(events, "llm_finished")
    if len(llm_starts) != len(llm_finishes) or not llm_finishes:
        raise ValueError("trace has an incomplete LLM lifecycle")

    exchanges: list[RecordedExchange] = []
    for index, (started, finished) in enumerate(zip(llm_starts, llm_finishes)):
        fingerprint = started.get("request_fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            raise ValueError(
                "trace predates request fingerprints and cannot drive runtime replay"
            )
        tool_calls: list[ToolCall] = []
        for call in finished.get("tool_calls") or []:
            if not isinstance(call, dict):
                raise ValueError(f"LLM response {index + 1} has legacy tool calls")
            tool_calls.append(ToolCall(
                id=str(call.get("id") or ""),
                name=str(call.get("name") or ""),
                arguments=dict(call.get("arguments") or {}),
            ))
        exchanges.append(RecordedExchange(
            request_fingerprint=fingerprint,
            response=LLMResponse(
                content=str(finished.get("content") or ""),
                tool_calls=tool_calls,
                prompt_tokens=int(finished.get("prompt_tokens") or 0),
                completion_tokens=int(finished.get("completion_tokens") or 0),
            ),
        ))
    return run, exchanges


def _validate_supported_trace(events: list[dict], permission_mode: str) -> None:
    if permission_mode == "full-access":
        raise ValueError("runtime replay refuses full-access recordings")
    executed_tools = {
        str(data.get("tool") or "")
        for data in _event_data(events, "tool_started")
    }
    unsupported = executed_tools & {"agent", "bash"}
    if unsupported:
        raise ValueError(
            "runtime replay will not re-execute recorded side-effectful tools: "
            + ", ".join(sorted(unsupported))
        )


def _normalize(value: Any, workspace: Path) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize(item, workspace) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, workspace) for item in value]
    if isinstance(value, str):
        return value.replace(str(workspace), "${WORKSPACE}")
    return value


def _compare_tool_results(
    recorded_events: list[dict],
    replay_events: list[dict],
    source_workspace: Path,
    replay_workspace: Path,
) -> tuple[bool, list[str]]:
    recorded = _event_data(recorded_events, "tool_result")
    replayed = _event_data(replay_events, "tool_result")
    divergences: list[str] = []
    if len(recorded) != len(replayed):
        divergences.append(
            f"tool result count mismatch: {len(recorded)} recorded, "
            f"{len(replayed)} replayed"
        )
    def stable(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: stable(item)
                for key, item in value.items()
                if not (key == "duration_ms" or key == "timestamp")
            }
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value

    for index, (expected, actual) in enumerate(zip(recorded, replayed), start=1):
        expected_normalized = stable(_normalize(expected, source_workspace))
        actual_normalized = stable(_normalize(actual, replay_workspace))
        if expected_normalized != actual_normalized:
            divergences.append(f"tool result {index} differs")
    return not divergences, divergences


def _assert_safe_fixture(fixture: Path) -> None:
    if not fixture.is_dir():
        raise ValueError(f"fixture directory does not exist: {fixture}")
    for entry in fixture.rglob("*"):
        if not entry.is_symlink():
            continue
        try:
            entry.resolve(strict=True).relative_to(fixture)
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"fixture contains an external symlink: {entry.relative_to(fixture)}"
            ) from exc


@contextmanager
def _replay_environment(workspace: Path, memory_db: Path) -> Iterator[None]:
    previous_cwd = Path.cwd()
    previous_memory = os.environ.get("CORECODER_MEMORY_DB")
    os.environ["CORECODER_MEMORY_DB"] = str(memory_db)
    os.chdir(workspace)
    try:
        yield
    finally:
        os.chdir(previous_cwd)
        if previous_memory is None:
            os.environ.pop("CORECODER_MEMORY_DB", None)
        else:
            os.environ["CORECODER_MEMORY_DB"] = previous_memory


def runtime_replay(
    trace_path: str | Path,
    fixture_path: str | Path,
    output_dir: str | Path,
) -> RuntimeReplayResult:
    """Replay recorded model decisions against a fresh fixture copy.

    Project shell hooks are intentionally disabled. Recordings that actually
    executed Bash, sub-agents, or full-access policy are rejected.
    """
    recorded_events = load_trace(trace_path)
    lifecycle = replay_trace(trace_path)
    if not lifecycle.valid:
        raise ValueError("runtime replay requires a valid lifecycle trace")
    run, exchanges = _load_recording(recorded_events)
    source_workspace = Path(str(run["workspace"])).expanduser().resolve()
    permission_mode = str(run.get("permission_mode") or "workspace-write")
    _validate_supported_trace(recorded_events, permission_mode)

    fixture = Path(fixture_path).expanduser().resolve()
    _assert_safe_fixture(fixture)
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"runtime replay output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    workspace = output / "workspace"
    shutil.copytree(
        fixture,
        workspace,
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    workspace = workspace.resolve()

    recorded_llm = RecordedLLM(
        exchanges,
        model=str(run.get("model") or "recorded-model"),
        source_workspace=source_workspace,
        replay_workspace=workspace,
    )
    replay_trace_path = output / "replay.trace.jsonl"
    trace = JsonlTraceSink(replay_trace_path)
    tokenizer = (
        "approx"
        if str(run.get("token_counter") or "").startswith("approx")
        else "auto"
    )
    context = create_context_strategy(
        str(run.get("context_strategy") or "hybrid"),
        max_tokens=int(run.get("max_context_tokens") or 128_000),
        token_counter=create_token_counter(tokenizer, recorded_llm.model),
    )
    divergences: list[str] = []
    final_answer = ""
    agent = None
    with _replay_environment(workspace, output / "memory.db"):
        agent = Agent(
            llm=recorded_llm,
            max_rounds=int(run.get("max_rounds") or 50),
            skills=discover_skills(workspace, project_root=workspace),
            hooks=HookConfig(),
            embedding=EmbeddingService(provider="none"),
            trace=trace,
            instruction_sources=load_project_instructions(
                workspace,
                project_root=workspace,
            ),
            # Replay is explicitly driven by an already recorded, validated
            # decision sequence.  Side effects remain confined to the fresh
            # fixture workspace and Bash/sub-agent traces are rejected above.
            policy=ExecutionPolicy(
                permission_mode,
                workspace=workspace,
                approval_callback=lambda *_args: True,
            ),
            context_strategy=context,
        )
        try:
            run_result = agent.run(str(run.get("prompt") or run.get("user_input") or ""))
            final_answer = run_result.final_answer
            if run_result.error:
                divergences.append(run_result.error)
        finally:
            agent.close()
            trace.close()

    replay_events = load_trace(replay_trace_path)
    tool_results_match, tool_divergences = _compare_tool_results(
        recorded_events,
        replay_events,
        source_workspace,
        workspace,
    )
    divergences.extend(tool_divergences)
    recorded_answers = (
        _event_data(recorded_events, "model_finished")
        or _event_data(recorded_events, "llm_finished")
    )
    expected_answer = str(recorded_answers[-1].get("content") or "")
    final_answer_match = (
        _normalize(expected_answer, source_workspace)
        == _normalize(final_answer, workspace)
    )
    if not final_answer_match:
        divergences.append("final answer differs")
    if recorded_llm.consumed != len(exchanges):
        divergences.append(
            f"LLM response count mismatch: consumed {recorded_llm.consumed}, "
            f"recorded {len(exchanges)}"
        )

    result = RuntimeReplayResult(
        valid=not divergences,
        run_id=lifecycle.run_id,
        llm_calls=recorded_llm.consumed,
        tool_results_match=tool_results_match,
        final_answer_match=final_answer_match,
        changed_files=sorted(
            str(Path(path).resolve().relative_to(workspace))
            for path in (agent.changed_files if agent else [])
        ),
        divergences=divergences,
        replay_trace_path=str(replay_trace_path),
        workspace=str(workspace),
    )
    (output / "runtime-replay.json").write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result
