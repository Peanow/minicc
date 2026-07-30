"""Tests for commit-safe benchmark evidence export."""

import json
from pathlib import Path

import pytest

from corecoder.evidence import export_evidence
from corecoder.trace import JsonlTraceSink


def _build_evaluation(tmp_path):
    evaluation = tmp_path / "evaluation"
    case_dir = evaluation / "cases" / "case-1"
    case_dir.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    trace_path = case_dir / "trace.jsonl"
    trace = JsonlTraceSink(trace_path, run_id="run-1")
    trace.emit("run_started", workspace=str(workspace))
    trace.emit("llm_started", request_fingerprint="a" * 64)
    trace.emit(
        "llm_finished",
        prompt_tokens=10,
        completion_tokens=2,
        content="done",
        tool_calls=[],
    )
    trace.emit(
        "run_finished",
        status="completed",
        changed_files=[str(workspace / "app.py")],
    )
    trace.close()
    stdout_path = case_dir / "agent.stdout.log"
    stderr_path = case_dir / "agent.stderr.log"
    stdout_path.write_text("done\n")
    stderr_path.write_text("")

    record = {
        "case_id": "case-1",
        "task_id": "task-1",
        "fixture_digest": "f" * 64,
        "model_profile": "model",
        "model": "model-id",
        "strategy_profile": "hybrid",
        "context_strategy": "hybrid",
        "permission_mode": "workspace-write",
        "success": True,
        "agent_exit_code": 0,
        "replay_valid": True,
        "run_status": "completed",
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "duration_ms": 1.0,
        "wall_duration_ms": 2.0,
        "estimated_cost_usd": None,
        "policy_denials": 0,
        "policy_denials_by_risk": {},
        "protected_files_unchanged": True,
        "changed_files": ["app.py"],
        "checks": [{"argv": ["python", "verify.py"], "passed": True}],
        "trace_path": str(trace_path.relative_to(evaluation)),
        "stdout_path": str(stdout_path.relative_to(evaluation)),
        "stderr_path": str(stderr_path.relative_to(evaluation)),
        "error": None,
        "repetition": 1,
        "hidden_checks_passed": 1,
        "hidden_checks_total": 1,
        "workspace_changed_files": ["app.py"],
        "expected_change_paths": ["app.py"],
        "unrelated_changed_files": [],
        "edit_precision": 1.0,
        "unrelated_file_modification_rate": 0.0,
        "tool_failures": 0,
        "failure_recovered": None,
        "context_compactions": 0,
    }
    (evaluation / "results.jsonl").write_text(json.dumps(record) + "\n")
    (evaluation / "summary.json").write_text(json.dumps({
        "total_cases": 1,
        "successful_cases": 1,
        "success_rate": 1.0,
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "duration_ms": 1.0,
        "wall_duration_ms": 2.0,
        "estimated_cost_usd": None,
        "policy_denials": 0,
        "policy_denials_by_risk": {},
        "hidden_checks_passed": 1,
        "hidden_checks_total": 1,
        "hidden_pass_rate": 1.0,
        "mean_edit_precision": 1.0,
        "mean_unrelated_file_modification_rate": 0.0,
        "runs_with_tool_failures": 0,
        "recovered_runs": 0,
        "failure_recovery_rate": None,
        "context_compactions": 0,
        "by_model": {},
        "by_strategy": {},
    }))
    (evaluation / "run.json").write_text(json.dumps({
        "schema_version": 1,
        "manifest": "test",
        "status": "completed",
        "cases": ["case-1"],
    }))
    (evaluation / "manifest.snapshot.json").write_text(json.dumps({
        "schema_version": 1,
        "name": "test",
    }))
    return evaluation


def test_export_evidence_audits_and_excludes_runtime_artifacts(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    output = tmp_path / "evidence"

    result = export_evidence(evaluation, output)

    assert result.case_count == 1
    assert result.successful_cases == 1
    assert (output / "results.jsonl").is_file()
    assert (output / "summary.json").is_file()
    assert (output / "manifest.json").is_file()
    assert (output / "evidence.json").is_file()
    assert (output / "report.html").is_file()
    assert not list(output.rglob("trace.jsonl"))
    exported = json.loads((output / "results.jsonl").read_text())
    assert "trace_path" not in exported
    assert len(exported["artifact_hashes"]["trace"]["sha256"]) == 64


def test_export_evidence_rejects_sensitive_result(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    path = evaluation / "results.jsonl"
    record = json.loads(path.read_text())
    record["error"] = "api_key=secret-value"
    path.write_text(json.dumps(record) + "\n")

    with pytest.raises(ValueError, match="credential-like"):
        export_evidence(evaluation, tmp_path / "evidence")


def test_export_evidence_sanitizes_manifest_and_keeps_source_hash(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    path = evaluation / "manifest.snapshot.json"
    manifest = json.loads(path.read_text())
    manifest["tasks"] = [{
        "id": "redaction-task",
        "prompt": "Remove api_key=example-only-value from the fixture.",
    }]
    path.write_text(json.dumps(manifest))

    output = tmp_path / "evidence"
    export_evidence(evaluation, output)

    portable = json.loads((output / "manifest.json").read_text())
    metadata = json.loads((output / "evidence.json").read_text())
    assert "example-only-value" not in json.dumps(portable)
    assert "[REDACTED" in json.dumps(portable)
    assert metadata["manifest_sanitized"] is True
    assert len(metadata["source_hashes"]["manifest"]) == 64


def test_export_evidence_rejects_tampered_summary(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    path = evaluation / "summary.json"
    summary = json.loads(path.read_text())
    summary["successful_cases"] = 0
    path.write_text(json.dumps(summary))

    with pytest.raises(ValueError, match="summary/results mismatch"):
        export_evidence(evaluation, tmp_path / "evidence")


def test_export_evidence_preserves_consistent_incomplete_trace(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    trace_path = evaluation / "cases" / "case-1" / "trace.jsonl"
    events = [
        json.loads(line)
        for line in trace_path.read_text().splitlines()
    ][:-1]
    trace_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )
    results_path = evaluation / "results.jsonl"
    record = json.loads(results_path.read_text())
    record.update({
        "success": False,
        "agent_exit_code": 1,
        "replay_valid": False,
        "run_status": "incomplete",
        "changed_files": [],
    })
    results_path.write_text(json.dumps(record) + "\n")
    summary_path = evaluation / "summary.json"
    summary = json.loads(summary_path.read_text())
    summary.update({
        "successful_cases": 0,
        "success_rate": 0.0,
    })
    summary_path.write_text(json.dumps(summary))

    output = tmp_path / "evidence"
    export_evidence(evaluation, output)

    exported = json.loads((output / "results.jsonl").read_text())
    assert exported["replay_valid"] is False
    assert exported["artifact_hashes"]["trace"]["valid"] is False


def test_export_evidence_includes_compaction_protocol_audit(tmp_path):
    evaluation = _build_evaluation(tmp_path)
    trace_path = evaluation / "cases" / "case-1" / "trace.jsonl"
    events = [
        json.loads(line)
        for line in trace_path.read_text().splitlines()
    ]
    events.insert(3, {
        "schema_version": 1,
        "run_id": "run-1",
        "sequence": 4,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "event": "context_compacted",
        "data": {"protocol_valid": False},
    })
    trace_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )

    output = tmp_path / "evidence"
    export_evidence(evaluation, output)

    exported = json.loads((output / "results.jsonl").read_text())
    audit = exported["artifact_hashes"]["trace"]
    assert audit["context_protocol_checks"] == 1
    assert audit["context_protocol_violations"] == 1


def test_evidence_cli(tmp_path, monkeypatch, capsys):
    from corecoder.cli import main

    evaluation = _build_evaluation(tmp_path)
    output = tmp_path / "cli-evidence"
    monkeypatch.setattr(
        "sys.argv",
        [
            "corecoder",
            "evidence",
            str(evaluation),
            "-o",
            str(output),
        ],
    )

    main()

    assert '"case_count": 1' in capsys.readouterr().out
    assert (output / "README.md").is_file()
