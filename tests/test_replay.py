"""Tests for side-effect-free trace replay and HTML reporting."""

import json

import pytest

from corecoder.replay import generate_html_report, load_trace, replay_trace
from corecoder.trace import JsonlTraceSink


def _write_complete_trace(path):
    sink = JsonlTraceSink(path, run_id="run-123")
    sink.emit("run_started", model="fake", user_input="fix it")
    sink.emit("llm_started", round=0)
    sink.emit(
        "llm_finished",
        round=0,
        prompt_tokens=10,
        completion_tokens=2,
        content="",
        tool_calls=[{
            "id": "call-1",
            "name": "read_file",
            "arguments": {"file_path": "app.py"},
        }],
    )
    sink.emit("policy_decision", tool="read_file", decision="allow")
    sink.emit("tool_started", tool="read_file")
    sink.emit("tool_finished", tool="read_file", output="<script>alert(1)</script>")
    sink.emit(
        "tool_result",
        tool_call_id="call-1",
        tool="read_file",
        content="<script>alert(1)</script>",
    )
    sink.emit("llm_started", round=1)
    sink.emit(
        "llm_finished",
        round=1,
        prompt_tokens=15,
        completion_tokens=3,
        content="done",
        tool_calls=[],
    )
    sink.emit("run_finished", status="completed", changed_files=["app.py"])
    sink.close()


def test_replay_reconstructs_metrics_without_side_effects(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_complete_trace(path)

    summary = replay_trace(path)

    assert summary.valid
    assert summary.status == "completed"
    assert summary.llm_calls == 2
    assert summary.tool_calls == 1
    assert summary.prompt_tokens == 25
    assert summary.completion_tokens == 5
    assert summary.changed_files == ["app.py"]


def test_replay_detects_missing_tool_result(tmp_path):
    path = tmp_path / "incomplete.jsonl"
    sink = JsonlTraceSink(path, run_id="broken")
    sink.emit("run_started")
    sink.emit("llm_started")
    sink.emit(
        "llm_finished",
        tool_calls=[{"id": "missing", "name": "grep", "arguments": {}}],
    )
    sink.emit("run_finished", status="completed")
    sink.close()

    summary = replay_trace(path)
    assert not summary.valid
    assert any("missing tool result" in error for error in summary.validation_errors)


def test_load_trace_rejects_invalid_json(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"event": "ok"}\nnot-json\n')
    with pytest.raises(ValueError, match="line 2"):
        load_trace(path)


def test_html_report_is_self_contained_and_escapes_outputs(tmp_path):
    trace_path = tmp_path / "run.jsonl"
    report_path = tmp_path / "report.html"
    _write_complete_trace(trace_path)

    summary = generate_html_report(trace_path, report_path)
    document = report_path.read_text()

    assert summary.valid
    assert "<style>" in document
    assert "CoreCoder execution trace" in document
    assert "<script>alert(1)</script>" not in document
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document


def test_replay_summary_is_json_serializable(tmp_path):
    path = tmp_path / "run.jsonl"
    _write_complete_trace(path)
    encoded = json.dumps(replay_trace(path).to_dict())
    assert "run-123" in encoded


def test_replay_cli_does_not_require_api_configuration(tmp_path, monkeypatch, capsys):
    from corecoder.cli import main

    path = tmp_path / "run.jsonl"
    _write_complete_trace(path)
    monkeypatch.setattr("sys.argv", ["corecoder", "replay", str(path)])

    main()

    output = capsys.readouterr().out
    assert '"valid": true' in output
    assert '"run_id": "run-123"' in output


def test_report_cli_uses_default_output_path(tmp_path, monkeypatch):
    from corecoder.cli import main

    path = tmp_path / "run.jsonl"
    _write_complete_trace(path)
    monkeypatch.setattr("sys.argv", ["corecoder", "report", str(path)])

    main()

    assert (tmp_path / "run.html").is_file()
