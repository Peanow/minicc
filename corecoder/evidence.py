"""Review and export commit-safe benchmark evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .comparison import generate_comparison_report
from .replay import load_trace, replay_trace
from .trace import redact


EVIDENCE_SCHEMA_VERSION = 1
_ARTIFACT_PATH_FIELDS = {"trace_path", "stdout_path", "stderr_path"}


@dataclass(frozen=True)
class EvidenceExport:
    output_dir: str
    case_count: int
    successful_cases: int
    trace_count: int
    results_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "case_count": self.case_count,
            "successful_cases": self.successful_cases,
            "trace_count": self.trace_count,
            "results_sha256": self.results_sha256,
        }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _load_results(path: Path) -> list[dict]:
    records: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"unable to read evaluation results: {path}") from exc
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"invalid results JSON at line {line_number}: {exc}"
            ) from exc
        if not isinstance(record, dict) or not record.get("case_id"):
            raise ValueError(f"invalid result at line {line_number}")
        records.append(record)
    if not records:
        raise ValueError("evaluation results are empty")
    return records


def _assert_no_sensitive_value(value: Any, label: str) -> None:
    if redact(value) != value:
        raise ValueError(f"{label} contains a credential-like or oversized value")


def _relative_artifact(root: Path, value: Any, field: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"result is missing {field}")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{field} must be relative to the evaluation directory")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the evaluation directory") from exc
    if not resolved.is_file():
        raise ValueError(f"result artifact does not exist: {value}")
    return resolved


def _audit_trace(trace_path: Path, record: dict) -> dict[str, Any]:
    events = load_trace(trace_path)
    replay = replay_trace(trace_path)
    event_counts = {
        event_name: sum(
            event.get("event") == event_name for event in events
        )
        for event_name in (
            "empty_response_retry",
            "empty_response_exhausted",
            "stagnation_recovery",
            "stagnation_exhausted",
        )
    }
    protocol_checks = [
        bool((event.get("data") or {}).get("protocol_valid"))
        for event in events
        if event.get("event") == "context_compacted"
        and "protocol_valid" in (event.get("data") or {})
    ]
    expected = {
        "replay_valid": replay.valid,
        "run_status": replay.status,
        "prompt_tokens": replay.prompt_tokens,
        "completion_tokens": replay.completion_tokens,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise ValueError(
                f"trace/result mismatch for {record['case_id']}: {field}"
            )
    run_started = next(
        (
            event.get("data") or {}
            for event in events
            if event.get("event") == "run_started"
        ),
        {},
    )
    workspace_value = run_started.get("workspace")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise ValueError(f"trace for {record['case_id']} has no workspace")
    workspace = Path(workspace_value).expanduser().resolve()
    normalized_files: list[str] = []
    for value in replay.changed_files:
        path = Path(value)
        resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        try:
            normalized_files.append(str(resolved.relative_to(workspace)))
        except ValueError:
            normalized_files.append(f"[outside-workspace]/{resolved.name}")
    if sorted(record.get("changed_files") or []) != sorted(normalized_files):
        raise ValueError(
            f"trace/result mismatch for {record['case_id']}: changed_files"
        )
    return {
        "sha256": _sha256(trace_path),
        "run_id": replay.run_id,
        "event_count": replay.event_count,
        "valid": replay.valid,
        "context_protocol_checks": len(protocol_checks),
        "context_protocol_violations": sum(
            not valid for valid in protocol_checks
        ),
        **event_counts,
    }


def _portable_record(root: Path, record: dict) -> dict:
    _assert_no_sensitive_value(record, f"result {record['case_id']}")
    trace = _relative_artifact(root, record.get("trace_path"), "trace_path")
    stdout = _relative_artifact(root, record.get("stdout_path"), "stdout_path")
    stderr = _relative_artifact(root, record.get("stderr_path"), "stderr_path")
    trace_audit = _audit_trace(trace, record)

    portable = {
        key: value
        for key, value in record.items()
        if key not in _ARTIFACT_PATH_FIELDS
    }
    portable["artifact_hashes"] = {
        "trace": trace_audit,
        "stdout_sha256": _sha256(stdout),
        "stderr_sha256": _sha256(stderr),
    }
    return portable


def _validate_summary(summary: dict, records: list[dict]) -> None:
    expected = {
        "total_cases": len(records),
        "successful_cases": sum(bool(record.get("success")) for record in records),
        "prompt_tokens": sum(int(record.get("prompt_tokens") or 0) for record in records),
        "completion_tokens": sum(
            int(record.get("completion_tokens") or 0) for record in records
        ),
        "policy_denials": sum(
            int(record.get("policy_denials") or 0) for record in records
        ),
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            raise ValueError(f"summary/results mismatch: {field}")
    hidden_total = sum(
        int(record.get("hidden_checks_total") or 0) for record in records
    )
    runs_with_failures = [
        record for record in records if int(record.get("tool_failures") or 0) > 0
    ]
    quality_expected = {
        "hidden_checks_passed": sum(
            int(record.get("hidden_checks_passed") or 0) for record in records
        ),
        "hidden_checks_total": hidden_total,
        "hidden_pass_rate": (
            round(
                sum(
                    int(record.get("hidden_checks_passed") or 0)
                    for record in records
                ) / hidden_total,
                4,
            )
            if hidden_total
            else None
        ),
        "mean_edit_precision": round(
            sum(float(record.get("edit_precision") or 0) for record in records)
            / len(records),
            4,
        ),
        "mean_unrelated_file_modification_rate": round(
            sum(
                float(record.get("unrelated_file_modification_rate") or 0)
                for record in records
            ) / len(records),
            4,
        ),
        "runs_with_tool_failures": len(runs_with_failures),
        "recovered_runs": sum(
            record.get("failure_recovered") is True
            for record in runs_with_failures
        ),
        "failure_recovery_rate": (
            round(
                sum(
                    record.get("failure_recovered") is True
                    for record in runs_with_failures
                ) / len(runs_with_failures),
                4,
            )
            if runs_with_failures
            else None
        ),
        "context_compactions": sum(
            int(record.get("context_compactions") or 0) for record in records
        ),
    }
    for field, value in quality_expected.items():
        if field in summary and summary[field] != value:
            raise ValueError(f"summary/results mismatch: {field}")


def export_evidence(
    evaluation_dir: str | Path,
    output_dir: str | Path,
) -> EvidenceExport:
    """Audit an evaluation and export only commit-safe evidence files."""
    source = Path(evaluation_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError(f"evaluation directory does not exist: {source}")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"evidence output directory is not empty: {output}")

    run_path = source / "run.json"
    summary_path = source / "summary.json"
    manifest_path = source / "manifest.snapshot.json"
    results_path = source / "results.jsonl"
    run = _load_json(run_path, "run metadata")
    summary = _load_json(summary_path, "summary")
    manifest = _load_json(manifest_path, "manifest snapshot")
    records = _load_results(results_path)
    if run.get("status") != "completed":
        raise ValueError("evaluation run is not complete")
    _assert_no_sensitive_value(run, "run metadata")
    _assert_no_sensitive_value(summary, "summary")
    portable_manifest = redact(manifest)
    _validate_summary(summary, records)

    portable_records = [_portable_record(source, record) for record in records]
    output.mkdir(parents=True, exist_ok=True)
    exported_results = output / "results.jsonl"
    exported_results.write_text(
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in portable_records
        ),
        encoding="utf-8",
    )
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "manifest.json").write_text(
        json.dumps(
            portable_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    evidence = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_run": run,
        "source_hashes": {
            "run": _sha256(run_path),
            "summary": _sha256(summary_path),
            "manifest": _sha256(manifest_path),
            "results": _sha256(results_path),
        },
        "manifest_sanitized": portable_manifest != manifest,
        "excluded_artifacts": [
            "trace contents",
            "agent stdout/stderr contents",
            "SQLite memory",
            "temporary workspaces",
        ],
    }
    _assert_no_sensitive_value(evidence, "evidence metadata")
    (output / "evidence.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    generate_comparison_report([exported_results], output / "report.html")
    (output / "README.md").write_text(
        "# Reviewed benchmark evidence\n\n"
        "This directory was produced by `corecoder evidence`. Trace bodies, "
        "agent logs, memory databases, and temporary workspaces are excluded. "
        "Their SHA-256 hashes and audited lifecycle metadata remain in "
        "`results.jsonl`.\n",
        encoding="utf-8",
    )
    return EvidenceExport(
        output_dir=str(output),
        case_count=len(portable_records),
        successful_cases=sum(bool(record.get("success")) for record in records),
        trace_count=len(portable_records),
        results_sha256=_sha256(exported_results),
    )
