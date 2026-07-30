"""Tests for reproducible benchmark manifests and aggregation."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from corecoder.eval import (
    EvalRecord,
    aggregate_records,
    load_manifest,
    plan_cases,
    run_case,
    run_evaluation,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "benchmarks" / "local-v1.json"
TIER2_MANIFEST_PATH = REPO_ROOT / "benchmarks" / "tier2-pilot.json"


def _record(**overrides):
    values = {
        "case_id": "task__model__strategy",
        "task_id": "task",
        "fixture_digest": "abc123",
        "model_profile": "model",
        "model": "model-id",
        "strategy_profile": "strategy",
        "context_strategy": "hybrid",
        "permission_mode": "workspace-write",
        "success": True,
        "agent_exit_code": 0,
        "replay_valid": True,
        "run_status": "completed",
        "prompt_tokens": 10,
        "completion_tokens": 2,
        "duration_ms": 100.0,
        "wall_duration_ms": 120.0,
        "estimated_cost_usd": 0.001,
        "policy_denials": 0,
        "policy_denials_by_risk": {},
        "protected_files_unchanged": True,
        "changed_files": ["app.py"],
        "checks": [{"passed": True}],
        "trace_path": "trace.jsonl",
        "stdout_path": "stdout.log",
        "stderr_path": "stderr.log",
        "error": None,
    }
    values.update(overrides)
    return EvalRecord(**values)


def test_bundled_manifest_expands_enabled_matrix():
    manifest = load_manifest(MANIFEST_PATH)
    cases = plan_cases(manifest)

    assert manifest.name == "local-v1"
    assert manifest.tier == "tier1"
    assert manifest.repetitions == 3
    assert len(manifest.tasks) == 18
    assert len(cases) == 162
    assert cases[0].id == (
        "python-inclusive-range__deepseek-v4-flash__hybrid-workspace__r01"
    )
    assert cases[2].repetition == 3


def test_plan_filters_and_rejects_unknown_ids():
    manifest = load_manifest(MANIFEST_PATH)
    cases = plan_cases(
        manifest,
        task_ids={"python-safe-path"},
        strategy_ids={"hybrid-workspace"},
        repetitions=1,
    )
    assert len(cases) == 1
    assert cases[0].task.id == "python-safe-path"

    with pytest.raises(ValueError, match="unknown or disabled model"):
        plan_cases(manifest, model_ids={"comparison-model"})


def test_manifest_rejects_fixture_escape(tmp_path):
    fixture = tmp_path / "outside"
    fixture.mkdir()
    manifest = {
        "schema_version": 1,
        "name": "bad",
        "models": [{"id": "m", "model": "m", "api_key_env": "KEY"}],
        "strategies": [{"id": "s"}],
        "tasks": [{
            "id": "t",
            "fixture": "../outside",
            "prompt": "work",
            "checks": [{"argv": ["python", "verify.py"]}],
            "protected_paths": ["verify.py"],
        }],
    }
    path = tmp_path / "manifests" / "bad.json"
    path.parent.mkdir()
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="escapes"):
        load_manifest(path)


def test_tier2_manifest_requires_pinned_repository_provenance(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "verify.py").write_text("raise SystemExit(1)\n")
    manifest = {
        "schema_version": 1,
        "name": "tier2-test",
        "tier": "tier2",
        "models": [{"id": "m", "model": "m", "api_key_env": "KEY"}],
        "strategies": [{"id": "s"}],
        "tasks": [{
            "id": "t",
            "fixture": "fixture",
            "prompt": "work",
            "checks": [{"argv": ["python", "verify.py"]}],
            "protected_paths": ["verify.py"],
            "expected_change_paths": ["app.py"],
        }],
    }
    path = tmp_path / "tier2.json"
    path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="must define provenance"):
        load_manifest(path)

    manifest["tasks"][0]["provenance"] = {
        "repository": "https://github.com/example/project",
        "commit": "a" * 40,
        "license": "MIT",
        "issue": "https://github.com/example/project/issues/1",
    }
    path.write_text(json.dumps(manifest))

    loaded = load_manifest(path)
    assert loaded.tasks[0].provenance.commit == "a" * 40

    manifest["tasks"][0]["provenance"].pop("issue")
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="issue or PR provenance"):
        load_manifest(path)


def test_tier2_pilot_is_pinned_and_starts_with_hidden_regression():
    manifest = load_manifest(TIER2_MANIFEST_PATH)
    cases = plan_cases(manifest, repetitions=1)
    task = manifest.tasks[0]

    assert manifest.tier == "tier2"
    assert len(cases) == 3
    assert task.provenance.license == "Apache-2.0"
    assert task.provenance.issue.endswith("/pull/288")
    public = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-o",
            "addopts=",
            "tests/test_deque.py",
        ],
        cwd=task.fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    assert public.returncode == 0
    hidden = subprocess.run(
        [sys.executable, str(task.hidden_checks[0].path)],
        cwd=task.fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    assert hidden.returncode != 0


def test_aggregate_records_does_not_report_partial_cost():
    records = [
        _record(),
        _record(
            case_id="task2__model__strategy",
            task_id="task2",
            success=False,
            prompt_tokens=20,
            completion_tokens=4,
            duration_ms=200,
            wall_duration_ms=250,
            estimated_cost_usd=None,
            policy_denials=2,
            policy_denials_by_risk={"network": 2},
        ),
    ]

    summary = aggregate_records(records)

    assert summary.total_cases == 2
    assert summary.successful_cases == 1
    assert summary.success_rate == 0.5
    assert summary.prompt_tokens == 30
    assert summary.completion_tokens == 6
    assert summary.wall_duration_ms == 370
    assert summary.estimated_cost_usd is None
    assert summary.policy_denials == 2
    assert summary.policy_denials_by_risk == {"network": 2}
    assert summary.by_model["model"]["cases"] == 2


def test_aggregate_records_reports_quality_and_recovery_metrics():
    records = [
        _record(
            hidden_checks_passed=2,
            hidden_checks_total=2,
            edit_precision=1.0,
            unrelated_file_modification_rate=0.0,
            tool_failures=1,
            failure_recovered=True,
            context_compactions=2,
        ),
        _record(
            case_id="task__model__strategy__r02",
            hidden_checks_passed=1,
            hidden_checks_total=2,
            edit_precision=0.5,
            unrelated_file_modification_rate=0.5,
            tool_failures=1,
            failure_recovered=False,
            context_compactions=1,
        ),
    ]

    summary = aggregate_records(records)

    assert summary.hidden_pass_rate == 0.75
    assert summary.mean_edit_precision == 0.75
    assert summary.mean_unrelated_file_modification_rate == 0.25
    assert summary.failure_recovery_rate == 0.5
    assert summary.context_compactions == 3


def test_run_case_missing_key_does_not_start_agent(tmp_path, monkeypatch):
    manifest = load_manifest(MANIFEST_PATH)
    case = plan_cases(manifest, limit=1)[0]
    monkeypatch.delenv(case.model.api_key_env, raising=False)

    record = run_case(case, tmp_path)

    assert not record.success
    assert record.agent_exit_code is None
    assert case.model.api_key_env in record.error
    assert (tmp_path / record.stdout_path).is_file()
    assert (tmp_path / record.stderr_path).is_file()


def test_run_case_rejects_modified_verifier(tmp_path, monkeypatch):
    import corecoder.eval as eval_module
    from corecoder.replay import load_trace
    from corecoder.trace import JsonlTraceSink

    manifest = load_manifest(MANIFEST_PATH)
    case = plan_cases(manifest, limit=1)[0]
    monkeypatch.setenv(case.model.api_key_env, "test-key")
    monkeypatch.setenv("UNRELATED_SERVICE_TOKEN", "must-not-leak")
    seen_environments = []

    def fake_run(argv, *, cwd, env, timeout):
        seen_environments.append(env)
        if "--trace" in argv:
            assert env["CORECODER_API_KEY"] == "test-key"
            assert "UNRELATED_SERVICE_TOKEN" not in env
            trace_path = Path(argv[argv.index("--trace") + 1])
            sink = JsonlTraceSink(trace_path, run_id="integrity-test")
            sink.emit("run_started")
            sink.emit("run_finished", status="completed", changed_files=["verify.py"])
            sink.close()
            (cwd / "verify.py").write_text("pass\n")
            cache = cwd / ".pytest_cache"
            cache.mkdir()
            (cache / "CACHEDIR.TAG").write_text("generated\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(eval_module, "_run_command", fake_run)
    record = run_case(case, tmp_path)

    assert not record.success
    assert not record.protected_files_unchanged
    assert record.changed_files == ["verify.py"]
    assert record.workspace_changed_files == ["verify.py"]
    assert record.ignored_generated_files == [".pytest_cache/CACHEDIR.TAG"]
    assert record.unrelated_file_modification_rate == 1.0
    assert record.hidden_checks_total == 1
    assert seen_environments[0]["CORECODER_MAX_CONTEXT"] == "32000"
    assert "CORECODER_API_KEY" not in seen_environments[-1]
    events = load_trace(tmp_path / record.trace_path)
    measured = events[-1]
    assert measured["event"] == "evaluation_measured"
    assert measured["data"]["ignored_generated_files"] == [
        ".pytest_cache/CACHEDIR.TAG"
    ]
    assert measured["data"]["unrelated_file_modification_rate"] == 1.0


def test_eval_cli_dry_run_needs_no_api_key(monkeypatch, capsys):
    from corecoder.cli import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "corecoder",
            "eval",
            str(MANIFEST_PATH),
            "--dry-run",
            "--repeat",
            "1",
            "--limit",
            "2",
        ],
    )
    main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["manifest"] == "local-v1"
    assert payload["tier"] == "tier1"
    assert payload["repetitions"] == 1
    assert payload["case_count"] == 2


def test_run_evaluation_writes_reproducibility_metadata(tmp_path, monkeypatch):
    import corecoder.eval as eval_module

    manifest = load_manifest(MANIFEST_PATH)
    cases = plan_cases(manifest, limit=1)
    monkeypatch.setattr(eval_module, "run_case", lambda case, output: _record())
    output = tmp_path / "evidence"

    summary = run_evaluation(manifest, cases, output)
    metadata = json.loads((output / "run.json").read_text())

    assert summary.successful_cases == 1
    assert metadata["status"] == "completed"
    assert metadata["tier"] == "tier1"
    assert metadata["repetitions"] == 3
    assert len(metadata["manifest_sha256"]) == 64
    assert len(metadata["harness_digest"]) == 64
    assert len(
        metadata["hidden_check_digests"]["python-inclusive-range"][
            "hidden/local-v1/python-inclusive-range.py"
        ]
    ) == 64
    assert "completed_at" in metadata
    assert (output / "results.jsonl").is_file()
    assert (output / "summary.json").is_file()

    with pytest.raises(ValueError, match="not empty"):
        run_evaluation(manifest, cases, output)


@pytest.mark.parametrize(
    "task",
    [
        "python-inclusive-range",
        "python-record-normalizer",
        "python-ttl-cache",
        "python-safe-path",
        "python-multifile-slug",
        "python-scoped-instructions",
        "python-retry-policy",
        "python-deep-merge",
        "python-topological-order",
        "python-secret-redaction",
        "python-lazy-batches",
        "python-cursor-pagination",
        "python-config-precedence",
        "python-event-deduplication",
        "python-sse-parser",
        "python-tool-arguments",
        "python-message-budget",
        "python-circuit-breaker",
    ],
)
def test_benchmark_fixture_starts_unsolved(task):
    fixture = REPO_ROOT / "benchmarks" / "tasks" / task
    result = subprocess.run(
        [sys.executable, "verify.py"],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0, f"{task} unexpectedly starts solved"


@pytest.mark.parametrize(
    "task",
    [
        "python-inclusive-range",
        "python-safe-path",
        "python-retry-policy",
    ],
)
def test_hidden_validator_rejects_unsolved_fixture(task):
    fixture = REPO_ROOT / "benchmarks" / "tasks" / task
    hidden = REPO_ROOT / "benchmarks" / "hidden" / "local-v1" / f"{task}.py"
    result = subprocess.run(
        [sys.executable, str(hidden)],
        cwd=fixture,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
