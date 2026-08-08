"""End-to-end tests for the repository-local SDD workflow."""

from pathlib import Path
import shutil
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPOSITORY_ROOT / "scripts" / "spec.py"
TEMPLATES = REPOSITORY_ROOT / "specs" / "_templates"


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _initialize(root: Path) -> None:
    shutil.copytree(TEMPLATES, root / "specs" / "_templates")
    (root / "specs" / "changes" / "archive").mkdir(parents=True)
    (root / "specs" / "capabilities").mkdir(parents=True)


def _write_valid_change(root: Path, name: str = "000-example") -> Path:
    change = root / "specs" / "changes" / name
    change.mkdir(parents=True)
    (change / "spec.md").write_text(
        f"""# {name} — Example

- Change type: behavior

## Why

Users need deterministic workflow behavior.

## Goals

- Report observable lifecycle states.

## Non-goals

- Add an external service.

## Requirements

### R1: Report lifecycle state

The command reports state from document content.

## Acceptance scenarios

### AC1: Complete a change

- Requirements: R1
- Given: a valid draft change
- When: its tasks and checklist are completed
- Then: its inferred state becomes DONE

## Compatibility and migration

This is an additive repository tool.

## Trace contract

- AC1 produces a deterministic status line.

## Risks and rollback

Remove the repository tool to roll back.

## Capability impact

- Update `specs/capabilities/workflow.md`.
""",
        encoding="utf-8",
    )
    (change / "tasks.md").write_text(
        f"""# {name} tasks

- [ ] T1 [R1, AC1] Implement lifecycle inference.
- [ ] T2 [R1, AC1] Verify lifecycle inference.
""",
        encoding="utf-8",
    )
    (change / "checklist.md").write_text(
        f"""# {name} checklist

- [ ] Specification approved <!-- sdd:approval -->
- [ ] Specification matches implementation.
- [ ] AC1 pytest: `tests/test_spec_workflow.py::test_lifecycle_and_archive`
- [ ] AC1 trace: status output contains the inferred lifecycle state.
- [ ] Capability updated: `specs/capabilities/workflow.md`
- [ ] Ready to archive.
""",
        encoding="utf-8",
    )
    return change


def test_new_creates_next_numbered_draft_from_templates(tmp_path):
    _initialize(tmp_path)

    first = _run(tmp_path, "new", "terminal-input")
    second = _run(tmp_path, "new", "session-recovery")

    assert first.returncode == 0, first.stderr
    assert "000-terminal-input\tDRAFT" in first.stdout
    assert second.returncode == 0, second.stderr
    assert "001-session-recovery\tDRAFT" in second.stdout
    created = tmp_path / "specs" / "changes" / "000-terminal-input"
    assert {path.name for path in created.iterdir()} == {
        "spec.md",
        "tasks.md",
        "checklist.md",
    }
    assert "000-terminal-input" in (created / "spec.md").read_text(encoding="utf-8")


def test_lifecycle_and_archive(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)

    assert "000-example\tDRAFT" in _run(tmp_path, "status", "000").stdout

    approved = _run(tmp_path, "approve", "000-example")
    assert approved.returncode == 0, approved.stderr
    assert "READY" in approved.stdout

    tasks = change / "tasks.md"
    task_text = tasks.read_text(encoding="utf-8")
    tasks.write_text(task_text.replace("[ ] T1", "[x] T1"), encoding="utf-8")
    assert "IMPLEMENTING" in _run(tmp_path, "status", "example").stdout

    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace("[ ] T2", "[x] T2"),
        encoding="utf-8",
    )
    assert "VERIFYING" in _run(tmp_path, "status", "000-example").stdout

    capability = tmp_path / "specs" / "capabilities" / "workflow.md"
    capability.write_text("# Workflow\n\nUpdated by 000-example.\n", encoding="utf-8")
    checklist = change / "checklist.md"
    checklist.write_text(
        checklist.read_text(encoding="utf-8").replace("[ ]", "[x]"),
        encoding="utf-8",
    )
    assert "DONE" in _run(tmp_path, "status", "000-example").stdout

    archived = _run(tmp_path, "archive", "000-example")
    assert archived.returncode == 0, archived.stderr
    assert "000-example\tARCHIVED" in archived.stdout
    assert not change.exists()
    assert (tmp_path / "specs" / "changes" / "archive" / "000-example").is_dir()
    assert "ARCHIVED" in _run(tmp_path, "status", "000-example").stdout


def test_validation_rejects_bad_references_and_placeholders(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace("[R1, AC1]", "[R9, AC1]", 1),
        encoding="utf-8",
    )
    spec = change / "spec.md"
    spec.write_text(
        spec.read_text(encoding="utf-8").replace(
            "This is an additive repository tool.", "TBD"
        ),
        encoding="utf-8",
    )

    checked = _run(tmp_path, "check", "000-example")
    assert checked.returncode == 1
    assert "T1 references unknown IDs: R9" in checked.stderr

    approved = _run(tmp_path, "approve", "000-example")
    assert approved.returncode == 1
    assert "spec.md contains TBD" in approved.stderr
    assert "T1 references unknown IDs: R9" in approved.stderr
    assert "DRAFT" in _run(tmp_path, "status", "000-example").stdout


def test_check_rejects_duplicate_uncovered_and_incomplete_scenarios(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    spec = change / "spec.md"
    text = spec.read_text(encoding="utf-8")
    text = text.replace(
        "The command reports state from document content.",
        """The command reports state from document content.

### R1: Duplicate lifecycle requirement

This duplicate must be rejected.

### R2: Uncovered requirement

This requirement intentionally has no acceptance scenario.""",
    )
    text = text.replace("- Given: a valid draft change\n", "")
    spec.write_text(text, encoding="utf-8")

    result = _run(tmp_path, "check", "000-example")

    assert result.returncode == 1
    assert "duplicate requirement IDs: R1" in result.stderr
    assert "R2 is not covered by an acceptance scenario" in result.stderr
    assert "AC1 is missing a Given: step" in result.stderr


def test_check_requires_all_three_documents(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    (change / "tasks.md").unlink()

    result = _run(tmp_path, "check", "000-example")

    assert result.returncode == 1
    assert "missing required documents: tasks.md" in result.stderr


def test_strict_check_requires_task_and_per_scenario_evidence(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace("[R1, AC1]", "[R1]"),
        encoding="utf-8",
    )
    checklist = change / "checklist.md"
    checklist.write_text(
        "\n".join(
            line
            for line in checklist.read_text(encoding="utf-8").splitlines()
            if "AC1 trace:" not in line
        )
        + "\n",
        encoding="utf-8",
    )

    result = _run(tmp_path, "check", "000-example", "--strict")

    assert result.returncode == 1
    assert "T1 must reference at least one R and one AC" in result.stderr
    assert "AC1 is not covered by a task" in result.stderr
    assert "AC1 is missing trace evidence" in result.stderr


def test_archive_requires_capability_evidence(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    assert _run(tmp_path, "approve", "000-example").returncode == 0
    for filename in ("tasks.md", "checklist.md"):
        path = change / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace("[ ]", "[x]"),
            encoding="utf-8",
        )

    result = _run(tmp_path, "archive", "000-example")

    assert result.returncode == 1
    assert "capability evidence does not exist" in result.stderr
    assert change.is_dir()


def test_preflight_reports_strict_validation_failure(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8").replace("[R1, AC1]", "[R9, AC1]", 1),
        encoding="utf-8",
    )

    result = _run(tmp_path, "preflight", "000-example")

    assert result.returncode == 1
    assert "Preflight FAILED 000-example\tDRAFT" in result.stderr
    assert "T1 references unknown IDs: R9" in result.stderr


def test_preflight_does_not_modify_specification_files(tmp_path):
    _initialize(tmp_path)
    change = _write_valid_change(tmp_path)
    files = sorted(path for path in change.iterdir() if path.is_file())
    before = {path.name: path.read_bytes() for path in files}

    result = _run(tmp_path, "preflight", "000-example")

    assert result.returncode == 0, result.stderr
    assert "Preflight OK 000-example\tDRAFT" in result.stdout
    assert {path.name: path.read_bytes() for path in files} == before
    assert sorted(path for path in change.iterdir() if path.is_file()) == files


def _complete_change(tmp_path):
    change = _write_valid_change(tmp_path)
    capability = tmp_path / "specs" / "capabilities" / "workflow.md"
    capability.write_text("# Workflow\n\nUpdated by the test.\n", encoding="utf-8")
    assert _run(tmp_path, "approve", "000-example").returncode == 0
    for filename in ("tasks.md", "checklist.md"):
        path = change / filename
        path.write_text(
            path.read_text(encoding="utf-8").replace("[ ]", "[x]"),
            encoding="utf-8",
        )
    return change


def test_preflight_for_commit_rejects_active_done_change(tmp_path):
    _initialize(tmp_path)
    _complete_change(tmp_path)

    result = _run(tmp_path, "preflight", "000-example", "--for-commit")

    assert result.returncode == 1
    assert "archive it before commit" in result.stderr


def test_preflight_for_commit_accepts_archived_change(tmp_path):
    _initialize(tmp_path)
    _complete_change(tmp_path)
    archived = _run(tmp_path, "archive", "000-example")
    assert archived.returncode == 0, archived.stderr

    result = _run(tmp_path, "preflight", "000-example", "--for-commit")

    assert result.returncode == 0, result.stderr
    assert "Preflight OK 000-example\tARCHIVED" in result.stdout


def test_repository_bootstrap_change_passes_strict_validation():
    result = _run(REPOSITORY_ROOT, "check", "000-sdd-bootstrap", "--strict")

    assert result.returncode == 0, result.stderr
    assert "000-sdd-bootstrap\tARCHIVED" in result.stdout
