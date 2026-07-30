"""Reproducible benchmark manifests, execution, and metric aggregation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .replay import load_trace, replay_trace


SCHEMA_VERSION = 1
_SENSITIVE_ENV_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")


@dataclass(frozen=True)
class ModelProfile:
    id: str
    model: str
    api_key_env: str
    base_url: str | None = None
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    enabled: bool = True


@dataclass(frozen=True)
class StrategyProfile:
    id: str
    context_strategy: str = "hybrid"
    permission_mode: str = "workspace-write"
    tokenizer: str = "auto"
    enabled: bool = True


@dataclass(frozen=True)
class CheckSpec:
    argv: tuple[str, ...]
    timeout_seconds: int = 30


@dataclass(frozen=True)
class TaskSpec:
    id: str
    fixture: Path
    prompt: str
    checks: tuple[CheckSpec, ...]
    protected_paths: tuple[Path, ...]
    tags: tuple[str, ...] = ()
    timeout_seconds: int = 300


@dataclass(frozen=True)
class EvalManifest:
    name: str
    source_path: Path
    models: tuple[ModelProfile, ...]
    strategies: tuple[StrategyProfile, ...]
    tasks: tuple[TaskSpec, ...]
    schema_version: int = SCHEMA_VERSION


@dataclass(frozen=True)
class EvalCase:
    task: TaskSpec
    model: ModelProfile
    strategy: StrategyProfile

    @property
    def id(self) -> str:
        return f"{self.task.id}__{self.model.id}__{self.strategy.id}"


@dataclass
class EvalRecord:
    case_id: str
    task_id: str
    fixture_digest: str
    model_profile: str
    model: str
    strategy_profile: str
    context_strategy: str
    permission_mode: str
    success: bool
    agent_exit_code: int | None
    replay_valid: bool
    run_status: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    wall_duration_ms: float
    estimated_cost_usd: float | None
    policy_denials: int
    protected_files_unchanged: bool
    changed_files: list[str]
    checks: list[dict[str, Any]]
    trace_path: str
    stdout_path: str
    stderr_path: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalSummary:
    total_cases: int
    successful_cases: int
    success_rate: float
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    wall_duration_ms: float
    estimated_cost_usd: float | None
    policy_denials: int
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    by_strategy: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, label)


def _optional_non_negative_float(value: Any, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{label} must be a non-negative number")
    return float(value)


def _optional_bool(value: Any, label: str, default: bool = True) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _choice(value: str, choices: set[str], label: str) -> str:
    if value not in choices:
        raise ValueError(f"{label} must be one of: {', '.join(sorted(choices))}")
    return value


def _unique(items: Iterable[Any], label: str) -> tuple[Any, ...]:
    result = tuple(items)
    ids = [item.id for item in result]
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise ValueError(f"duplicate {label} id(s): {', '.join(duplicates)}")
    if not result:
        raise ValueError(f"manifest must define at least one {label}")
    return result


def _resolve_fixture(manifest_dir: Path, value: Any, task_id: str) -> Path:
    relative = Path(_require_string(value, f"task {task_id}.fixture"))
    if relative.is_absolute():
        raise ValueError(f"task {task_id}.fixture must be relative to the manifest")
    fixture = (manifest_dir / relative).resolve()
    try:
        fixture.relative_to(manifest_dir)
    except ValueError as exc:
        raise ValueError(f"task {task_id}.fixture escapes the manifest directory") from exc
    if not fixture.is_dir():
        raise ValueError(f"task {task_id}.fixture does not exist: {relative}")
    for entry in fixture.rglob("*"):
        if entry.is_symlink():
            try:
                entry.resolve(strict=True).relative_to(fixture)
            except (OSError, ValueError) as exc:
                raise ValueError(
                    f"task {task_id}.fixture contains an external symlink: "
                    f"{entry.relative_to(fixture)}"
                ) from exc
    return fixture


def _resolve_protected_paths(
    fixture: Path,
    values: Any,
    task_id: str,
) -> tuple[Path, ...]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"task {task_id}.protected_paths must be a non-empty array")
    paths: list[Path] = []
    for index, value in enumerate(values):
        relative = Path(
            _require_string(value, f"task {task_id}.protected_paths[{index}]")
        )
        if relative.is_absolute():
            raise ValueError(
                f"task {task_id}.protected_paths[{index}] must be relative"
            )
        resolved = (fixture / relative).resolve()
        try:
            resolved.relative_to(fixture)
        except ValueError as exc:
            raise ValueError(
                f"task {task_id}.protected_paths[{index}] escapes the fixture"
            ) from exc
        if not resolved.is_file():
            raise ValueError(
                f"task {task_id}.protected_paths[{index}] is not a file: {relative}"
            )
        paths.append(relative)
    return tuple(paths)


def load_manifest(path: str | Path) -> EvalManifest:
    """Load and validate a versioned JSON benchmark manifest."""
    source = Path(path).expanduser().resolve()
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid manifest JSON: {exc}") from exc
    root = _require_mapping(raw, "manifest")
    version = root.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"unsupported manifest schema_version {version!r}; "
            f"expected {SCHEMA_VERSION}"
        )

    models = _unique(
        (
            ModelProfile(
                id=_require_string(item.get("id"), f"models[{index}].id"),
                model=_require_string(item.get("model"), f"models[{index}].model"),
                api_key_env=_require_string(
                    item.get("api_key_env"), f"models[{index}].api_key_env"
                ),
                base_url=_optional_string(
                    item.get("base_url"), f"models[{index}].base_url"
                ),
                input_cost_per_million=_optional_non_negative_float(
                    item.get("input_cost_per_million"),
                    f"models[{index}].input_cost_per_million",
                ),
                output_cost_per_million=_optional_non_negative_float(
                    item.get("output_cost_per_million"),
                    f"models[{index}].output_cost_per_million",
                ),
                enabled=_optional_bool(
                    item.get("enabled"),
                    f"models[{index}].enabled",
                ),
            )
            for index, value in enumerate(root.get("models") or [])
            for item in [_require_mapping(value, f"models[{index}]")]
        ),
        "model",
    )
    strategies = _unique(
        (
            StrategyProfile(
                id=_require_string(item.get("id"), f"strategies[{index}].id"),
                context_strategy=_choice(
                    _require_string(
                        item.get("context_strategy", "hybrid"),
                        f"strategies[{index}].context_strategy",
                    ),
                    {"truncate", "summary", "hybrid"},
                    f"strategies[{index}].context_strategy",
                ),
                permission_mode=_choice(
                    _require_string(
                        item.get("permission_mode", "workspace-write"),
                        f"strategies[{index}].permission_mode",
                    ),
                    {"read-only", "workspace-write", "full-access"},
                    f"strategies[{index}].permission_mode",
                ),
                tokenizer=_choice(
                    _require_string(
                        item.get("tokenizer", "auto"),
                        f"strategies[{index}].tokenizer",
                    ),
                    {"auto", "approx", "tiktoken"},
                    f"strategies[{index}].tokenizer",
                ),
                enabled=_optional_bool(
                    item.get("enabled"),
                    f"strategies[{index}].enabled",
                ),
            )
            for index, value in enumerate(root.get("strategies") or [])
            for item in [_require_mapping(value, f"strategies[{index}]")]
        ),
        "strategy",
    )

    tasks: list[TaskSpec] = []
    for index, value in enumerate(root.get("tasks") or []):
        item = _require_mapping(value, f"tasks[{index}]")
        task_id = _require_string(item.get("id"), f"tasks[{index}].id")
        checks: list[CheckSpec] = []
        for check_index, check_value in enumerate(item.get("checks") or []):
            check = _require_mapping(
                check_value,
                f"task {task_id}.checks[{check_index}]",
            )
            argv = check.get("argv")
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(arg, str) and arg for arg in argv)
            ):
                raise ValueError(
                    f"task {task_id}.checks[{check_index}].argv "
                    "must be a non-empty string array"
                )
            checks.append(
                CheckSpec(
                    argv=tuple(argv),
                    timeout_seconds=_positive_int(
                        check.get("timeout_seconds", 30),
                        f"task {task_id}.checks[{check_index}].timeout_seconds",
                    ),
                )
            )
        if not checks:
            raise ValueError(f"task {task_id} must define at least one check")
        fixture = _resolve_fixture(source.parent, item.get("fixture"), task_id)
        tasks.append(
            TaskSpec(
                id=task_id,
                fixture=fixture,
                prompt=_require_string(item.get("prompt"), f"task {task_id}.prompt"),
                checks=tuple(checks),
                protected_paths=_resolve_protected_paths(
                    fixture,
                    item.get("protected_paths"),
                    task_id,
                ),
                tags=tuple(
                    _require_string(tag, f"task {task_id}.tags")
                    for tag in item.get("tags") or []
                ),
                timeout_seconds=_positive_int(
                    item.get("timeout_seconds", 300),
                    f"task {task_id}.timeout_seconds",
                ),
            )
        )

    return EvalManifest(
        name=_require_string(root.get("name"), "manifest.name"),
        source_path=source,
        models=models,
        strategies=strategies,
        tasks=_unique(tasks, "task"),
        schema_version=version,
    )


def plan_cases(
    manifest: EvalManifest,
    *,
    task_ids: set[str] | None = None,
    model_ids: set[str] | None = None,
    strategy_ids: set[str] | None = None,
    limit: int | None = None,
) -> list[EvalCase]:
    """Expand enabled manifest profiles into a stable cartesian-product plan."""
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    cases = [
        EvalCase(task=task, model=model, strategy=strategy)
        for task in manifest.tasks
        if not task_ids or task.id in task_ids
        for model in manifest.models
        if model.enabled and (not model_ids or model.id in model_ids)
        for strategy in manifest.strategies
        if strategy.enabled and (not strategy_ids or strategy.id in strategy_ids)
    ]
    if task_ids:
        missing = task_ids - {case.task.id for case in cases}
        if missing:
            raise ValueError(f"unknown or disabled task id(s): {', '.join(sorted(missing))}")
    if model_ids:
        missing = model_ids - {case.model.id for case in cases}
        if missing:
            raise ValueError(
                f"unknown or disabled model profile(s): {', '.join(sorted(missing))}"
            )
    if strategy_ids:
        missing = strategy_ids - {case.strategy.id for case in cases}
        if missing:
            raise ValueError(
                "unknown or disabled strategy profile(s): "
                + ", ".join(sorted(missing))
            )
    return cases[:limit] if limit is not None else cases


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "-" for char in value)


def _policy_denials(events: list[dict]) -> int:
    return sum(
        1
        for event in events
        if event["event"] == "policy_decision"
        and (event.get("data") or {}).get("decision") != "allow"
    )


def _workspace_relative_files(paths: Iterable[str], workspace: Path) -> list[str]:
    workspace = workspace.resolve()
    normalized: set[str] = set()
    for value in paths:
        path = Path(value)
        resolved = path.resolve() if path.is_absolute() else (workspace / path).resolve()
        try:
            normalized.add(str(resolved.relative_to(workspace)))
        except ValueError:
            normalized.add(f"[outside-workspace]/{resolved.name}")
    return sorted(normalized)


def _estimate_cost(summary, model: ModelProfile) -> float | None:
    if (
        model.input_cost_per_million is None
        or model.output_cost_per_million is None
    ):
        return None
    return round(
        summary.prompt_tokens / 1_000_000 * model.input_cost_per_million
        + summary.completion_tokens / 1_000_000 * model.output_cost_per_million,
        8,
    )


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(path: Path) -> str:
    digest = hashlib.sha256()
    files = sorted(
        entry
        for entry in path.rglob("*")
        if entry.is_file()
        and "__pycache__" not in entry.parts
        and entry.suffix != ".pyc"
        and entry.name != ".DS_Store"
    )
    for entry in files:
        digest.update(str(entry.relative_to(path)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run_command(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=False,
    )


def _sanitized_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not any(marker in key.upper() for marker in _SENSITIVE_ENV_MARKERS)
    }


def _timeout_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def run_case(case: EvalCase, output_dir: Path) -> EvalRecord:
    """Run one isolated agent/check case and persist all inspectable artifacts."""
    case_dir = output_dir / "cases" / _slug(case.id)
    case_dir.mkdir(parents=True, exist_ok=True)
    trace_path = case_dir / "trace.jsonl"
    stdout_path = case_dir / "agent.stdout.log"
    stderr_path = case_dir / "agent.stderr.log"
    api_key = os.environ.get(case.model.api_key_env)
    if not api_key:
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        return EvalRecord(
            case_id=case.id,
            task_id=case.task.id,
            fixture_digest=_tree_digest(case.task.fixture),
            model_profile=case.model.id,
            model=case.model.model,
            strategy_profile=case.strategy.id,
            context_strategy=case.strategy.context_strategy,
            permission_mode=case.strategy.permission_mode,
            success=False,
            agent_exit_code=None,
            replay_valid=False,
            run_status="not_started",
            prompt_tokens=0,
            completion_tokens=0,
            duration_ms=0,
            wall_duration_ms=0,
            estimated_cost_usd=None,
            policy_denials=0,
            protected_files_unchanged=True,
            changed_files=[],
            checks=[],
            trace_path=str(trace_path.relative_to(output_dir)),
            stdout_path=str(stdout_path.relative_to(output_dir)),
            stderr_path=str(stderr_path.relative_to(output_dir)),
            error=f"missing API key environment variable: {case.model.api_key_env}",
        )

    with tempfile.TemporaryDirectory(prefix=f"corecoder-eval-{_slug(case.task.id)}-") as tmp:
        workspace = Path(tmp) / "workspace"
        shutil.copytree(
            case.task.fixture,
            workspace,
            symlinks=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        protected_digests = {
            relative: _file_digest(workspace / relative)
            for relative in case.task.protected_paths
        }
        command = [
            sys.executable,
            "-m",
            "corecoder",
            "--model",
            case.model.model,
            "--context-strategy",
            case.strategy.context_strategy,
            "--permission-mode",
            case.strategy.permission_mode,
            "--tokenizer",
            case.strategy.tokenizer,
            "--trace",
            str(trace_path),
            "--prompt",
            case.task.prompt,
        ]
        if case.model.base_url:
            command[3:3] = ["--base-url", case.model.base_url]
        env = _sanitized_environment()
        env["CORECODER_API_KEY"] = api_key
        env["CORECODER_EMBEDDING_PROVIDER"] = "none"
        env["CORECODER_MEMORY_DB"] = str(case_dir / "memory.db")
        env["CORECODER_SANITIZE_TOOL_ENV"] = "1"
        source_root = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            os.pathsep.join([source_root, existing_pythonpath])
            if existing_pythonpath
            else source_root
        )

        started = time.perf_counter()
        try:
            agent = _run_command(
                command,
                cwd=workspace,
                env=env,
                timeout=case.task.timeout_seconds,
            )
            agent_exit_code = agent.returncode
            stdout_path.write_text(agent.stdout, encoding="utf-8")
            stderr_path.write_text(agent.stderr, encoding="utf-8")
            error = None
        except subprocess.TimeoutExpired as exc:
            agent_exit_code = None
            stdout_path.write_text(_timeout_text(exc.stdout), encoding="utf-8")
            stderr_path.write_text(_timeout_text(exc.stderr), encoding="utf-8")
            error = f"agent timed out after {case.task.timeout_seconds}s"

        checks: list[dict[str, Any]] = []
        if error is None:
            for check in case.task.checks:
                check_started = time.perf_counter()
                try:
                    result = _run_command(
                        list(check.argv),
                        cwd=workspace,
                        env=_sanitized_environment(),
                        timeout=check.timeout_seconds,
                    )
                    checks.append({
                        "argv": list(check.argv),
                        "exit_code": result.returncode,
                        "passed": result.returncode == 0,
                        "duration_ms": round(
                            (time.perf_counter() - check_started) * 1000,
                            2,
                        ),
                        "stdout": result.stdout[-4000:],
                        "stderr": result.stderr[-4000:],
                    })
                except subprocess.TimeoutExpired:
                    checks.append({
                        "argv": list(check.argv),
                        "exit_code": None,
                        "passed": False,
                        "duration_ms": round(
                            (time.perf_counter() - check_started) * 1000,
                            2,
                        ),
                        "stdout": "",
                        "stderr": f"check timed out after {check.timeout_seconds}s",
                    })

        wall_duration_ms = round((time.perf_counter() - started) * 1000, 2)
        protected_files_unchanged = all(
            (workspace / relative).is_file()
            and _file_digest(workspace / relative) == digest
            for relative, digest in protected_digests.items()
        )
        replay = None
        events: list[dict] = []
        changed_files: list[str] = []
        if trace_path.exists():
            try:
                replay = replay_trace(trace_path)
                events = load_trace(trace_path)
                changed_files = _workspace_relative_files(
                    replay.changed_files,
                    workspace,
                )
            except (OSError, ValueError) as exc:
                error = error or f"trace replay failed: {exc}"

    replay_valid = bool(replay and replay.valid)
    run_status = replay.status if replay else "unknown"
    success = bool(
        error is None
        and agent_exit_code == 0
        and replay_valid
        and run_status == "completed"
        and protected_files_unchanged
        and checks
        and all(check["passed"] for check in checks)
    )
    return EvalRecord(
        case_id=case.id,
        task_id=case.task.id,
        fixture_digest=_tree_digest(case.task.fixture),
        model_profile=case.model.id,
        model=case.model.model,
        strategy_profile=case.strategy.id,
        context_strategy=case.strategy.context_strategy,
        permission_mode=case.strategy.permission_mode,
        success=success,
        agent_exit_code=agent_exit_code,
        replay_valid=replay_valid,
        run_status=run_status,
        prompt_tokens=replay.prompt_tokens if replay else 0,
        completion_tokens=replay.completion_tokens if replay else 0,
        duration_ms=replay.duration_ms if replay else wall_duration_ms,
        wall_duration_ms=wall_duration_ms,
        estimated_cost_usd=_estimate_cost(replay, case.model) if replay else None,
        policy_denials=_policy_denials(events),
        protected_files_unchanged=protected_files_unchanged,
        changed_files=changed_files,
        checks=checks,
        trace_path=str(trace_path.relative_to(output_dir)),
        stdout_path=str(stdout_path.relative_to(output_dir)),
        stderr_path=str(stderr_path.relative_to(output_dir)),
        error=error,
    )


def _group_metrics(records: list[EvalRecord], field_name: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[EvalRecord]] = {}
    for record in records:
        groups.setdefault(str(getattr(record, field_name)), []).append(record)
    return {
        key: {
            "cases": len(group),
            "successful": sum(record.success for record in group),
            "success_rate": round(
                sum(record.success for record in group) / len(group),
                4,
            ),
            "tokens": sum(
                record.prompt_tokens + record.completion_tokens for record in group
            ),
            "duration_ms": round(sum(record.duration_ms for record in group), 2),
            "wall_duration_ms": round(
                sum(record.wall_duration_ms for record in group),
                2,
            ),
        }
        for key, group in sorted(groups.items())
    }


def aggregate_records(records: Iterable[EvalRecord]) -> EvalSummary:
    records = list(records)
    successful = sum(record.success for record in records)
    all_costs_known = bool(records) and all(
        record.estimated_cost_usd is not None for record in records
    )
    return EvalSummary(
        total_cases=len(records),
        successful_cases=successful,
        success_rate=round(successful / len(records), 4) if records else 0.0,
        prompt_tokens=sum(record.prompt_tokens for record in records),
        completion_tokens=sum(record.completion_tokens for record in records),
        duration_ms=round(sum(record.duration_ms for record in records), 2),
        wall_duration_ms=round(sum(record.wall_duration_ms for record in records), 2),
        estimated_cost_usd=(
            round(sum(record.estimated_cost_usd or 0 for record in records), 8)
            if all_costs_known
            else None
        ),
        policy_denials=sum(record.policy_denials for record in records),
        by_model=_group_metrics(records, "model_profile"),
        by_strategy=_group_metrics(records, "strategy_profile"),
    )


def run_evaluation(
    manifest: EvalManifest,
    cases: list[EvalCase],
    output_dir: str | Path,
) -> EvalSummary:
    """Run a plan sequentially and persist append-only evidence."""
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"evaluation output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "manifest.snapshot.json").write_text(
        manifest.source_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    metadata = {
        "schema_version": SCHEMA_VERSION,
        "manifest": manifest.name,
        "manifest_sha256": _file_digest(manifest.source_path),
        "fixture_digests": {
            task.id: _tree_digest(task.fixture) for task in manifest.tasks
        },
        "harness_digest": _tree_digest(Path(__file__).resolve().parent),
        "python": sys.version,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "cases": [case.id for case in cases],
    }
    (output / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    records_path = output / "results.jsonl"
    records: list[EvalRecord] = []
    with records_path.open("a", encoding="utf-8") as stream:
        for case in cases:
            record = run_case(case, output)
            records.append(record)
            stream.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
            stream.flush()

    summary = aggregate_records(records)
    (output / "summary.json").write_text(
        json.dumps(summary.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    metadata["completed_at"] = datetime.now(timezone.utc).isoformat()
    metadata["status"] = "completed"
    (output / "run.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
