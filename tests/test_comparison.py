"""Tests for offline evaluation comparison reports."""

import json

import pytest

from corecoder.comparison import (
    generate_comparison_report,
    load_eval_records,
    summarize_comparison,
)


def _record(task, model, strategy, success, **overrides):
    record = {
        "task_id": task,
        "model_profile": model,
        "strategy_profile": strategy,
        "success": success,
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "duration_ms": 500,
        "wall_duration_ms": 550,
        "estimated_cost_usd": None,
        "policy_denials": 0,
        "protected_files_unchanged": True,
    }
    record.update(overrides)
    return record


def _write_results(path, records):
    path.mkdir()
    (path / "results.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records)
    )


def test_comparison_aggregates_profiles_and_tasks(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_results(first, [
        _record("task-a", "model-a", "hybrid", True),
        _record("task-b", "model-a", "hybrid", False, policy_denials=2),
    ])
    _write_results(second, [
        _record("task-a", "model-b", "truncate", True),
    ])

    records, labels = load_eval_records([first, second])
    summary = summarize_comparison(records, source_count=len(labels))

    assert summary.source_count == 2
    assert summary.record_count == 3
    assert summary.tasks == ["task-a", "task-b"]
    assert summary.profiles[0].success_rate == 0.5
    assert summary.profiles[0].policy_denials == 2
    assert summary.profiles[0].estimated_cost_usd is None


def test_comparison_report_is_self_contained_and_escapes_labels(tmp_path):
    source = tmp_path / "source"
    _write_results(source, [
        _record("task<script>", "model-a", "hybrid", True),
        _record("task-b", "model-b", "truncate", False),
    ])
    output = tmp_path / "comparison.html"

    summary = generate_comparison_report([source], output)
    document = output.read_text()

    assert summary.record_count == 2
    assert "<style>" in document
    assert "Task matrix" in document
    assert "task<script>" not in document
    assert "task&lt;script&gt;" in document
    assert 'class="pass">pass' in document
    assert 'class="fail">fail' in document


def test_comparison_cli(tmp_path, monkeypatch, capsys):
    from corecoder.cli import main

    source = tmp_path / "source"
    _write_results(source, [_record("task-a", "model-a", "hybrid", True)])
    output = tmp_path / "comparison.html"
    monkeypatch.setattr(
        "sys.argv",
        ["corecoder", "compare", str(source), "-o", str(output)],
    )

    main()

    assert output.is_file()
    assert "1 records" in capsys.readouterr().out


def test_comparison_rejects_empty_results(tmp_path):
    source = tmp_path / "empty"
    _write_results(source, [])

    with pytest.raises(ValueError, match="empty"):
        load_eval_records([source])
