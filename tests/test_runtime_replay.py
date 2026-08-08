"""Tests for deterministic Agent Runtime replay."""

import os
import shutil
from contextlib import contextmanager
from pathlib import Path

from corecoder.agent import Agent
from corecoder.context import create_context_strategy
from corecoder.llm import LLMResponse, ToolCall
from corecoder.policy import ExecutionPolicy
from corecoder.runtime_replay import runtime_replay
from corecoder.tokenizer import ApproxTokenCounter
from corecoder.trace import JsonlTraceSink


class SequenceLLM:
    model = "recorded-test-model"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    @property
    def estimated_cost(self):
        return None

    def chat(self, messages, tools=None, on_token=None):
        response = next(self.responses)
        self.total_prompt_tokens += response.prompt_tokens
        self.total_completion_tokens += response.completion_tokens
        return response


@contextmanager
def _cwd(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _record_edit_trace(tmp_path, monkeypatch):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "app.py").write_text("value = 1\n")
    workspace = tmp_path / "record-workspace"
    shutil.copytree(fixture, workspace)
    trace_path = tmp_path / "recorded.jsonl"
    trace = JsonlTraceSink(trace_path, run_id="recorded-run")
    llm = SequenceLLM([
        LLMResponse(
            tool_calls=[ToolCall("read-1", "read_file", {"file_path": "app.py"})],
            prompt_tokens=10,
            completion_tokens=2,
        ),
        LLMResponse(
            tool_calls=[ToolCall(
                "edit-1",
                "edit_file",
                {
                    "file_path": "app.py",
                    "old_string": "value = 1",
                    "new_string": "value = 2",
                },
            )],
            prompt_tokens=12,
            completion_tokens=3,
        ),
        LLMResponse(content="Done.", prompt_tokens=14, completion_tokens=1),
    ])
    monkeypatch.setenv("CORECODER_MEMORY_DB", str(tmp_path / "record-memory.db"))
    with _cwd(workspace):
        agent = Agent(
            llm=llm,
            trace=trace,
            policy=ExecutionPolicy("workspace-write", workspace=workspace),
            context_strategy=create_context_strategy(
                "hybrid",
                token_counter=ApproxTokenCounter(),
            ),
        )
        agent.run("Change the value to 2.")
        agent.close()
        trace.close()
    return fixture, trace_path


def test_runtime_replay_reexecutes_tools_without_api(tmp_path, monkeypatch):
    fixture, trace_path = _record_edit_trace(tmp_path, monkeypatch)
    output = tmp_path / "replay"

    result = runtime_replay(trace_path, fixture, output)

    assert result.valid
    assert result.run_id == "recorded-run"
    assert result.llm_calls == 3
    assert result.tool_results_match
    assert result.final_answer_match
    assert result.changed_files == ["app.py"]
    assert (output / "workspace" / "app.py").read_text() == "value = 2\n"
    assert (output / "runtime-replay.json").is_file()
    assert (output / "replay.trace.jsonl").is_file()


def test_runtime_replay_detects_fixture_drift(tmp_path, monkeypatch):
    fixture, trace_path = _record_edit_trace(tmp_path, monkeypatch)
    (fixture / "app.py").write_text("value = 99\n")

    result = runtime_replay(trace_path, fixture, tmp_path / "drifted-replay")

    assert not result.valid
    assert any("fingerprint mismatch" in item for item in result.divergences)
    assert not result.tool_results_match


def test_runtime_replay_cli(tmp_path, monkeypatch, capsys):
    from corecoder.cli import main

    fixture, trace_path = _record_edit_trace(tmp_path, monkeypatch)
    output = tmp_path / "cli-replay"
    monkeypatch.setattr(
        "sys.argv",
        [
            "corecoder",
            "trace",
            "runtime-replay",
            str(trace_path),
            "--fixture",
            str(fixture),
            "-o",
            str(output),
        ],
    )

    main()

    assert '"valid": true' in capsys.readouterr().out
