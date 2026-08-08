#!/usr/bin/env python3
"""Small, dependency-free workflow for CoreCoder change specifications.

The Markdown files remain the source of truth.  This script intentionally does
not maintain a database or a separate status field: status is inferred from the
approval marker and the checkboxes in ``tasks.md`` and ``checklist.md``.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
import re
import shutil
import sys
from typing import Iterable, Sequence


CHANGE_NAME_RE = re.compile(r"^(?P<number>\d{3,})-(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFINITION_PATTERNS = {
    "requirement": re.compile(
        r"(?mi)^\s{0,3}(#{2,6})\s+(R\d+)\s*(?::|[-\u2013\u2014])"
    ),
    "acceptance": re.compile(
        r"(?mi)^\s{0,3}(#{2,6})\s+(AC\d+)\s*(?::|[-\u2013\u2014])"
    ),
}
TASK_RE = re.compile(r"(?mi)^\s*[-*]\s+\[([ x])\]\s*(T\d+)\b(.*)$")
CHECKBOX_RE = re.compile(r"(?mi)^\s*[-*]\s+\[([ x])\]\s+.+$")
APPROVAL_RE = re.compile(
    r"(?mi)^(?P<prefix>\s*[-*]\s+)\[(?P<mark>[ x])\]"
    r"(?P<body>\s*Specification approved\s*<!--\s*sdd:approval\s*-->\s*)$"
)
EVIDENCE_RE = re.compile(
    r"(?mi)^\s*[-*]\s+\[([ x])\]\s*(AC\d+)\s+"
    r"(pytest|trace)\s*:\s*(.+?)\s*$"
)
CAPABILITY_RE = re.compile(
    r"(?mi)^\s*[-*]\s+\[([ x])\]\s*Capability updated\s*:\s*"
    r"(?:`([^`]+)`|(\S+))"
)
PLACEHOLDER_RE = re.compile(r"(?i)\bTBD\b|NEEDS\s+CLARIFICATION")
REFERENCE_RE = re.compile(r"\b(?:R\d+|AC\d+)\b", re.IGNORECASE)
REQUIRED_DOCUMENTS = ("spec.md", "tasks.md", "checklist.md")


class SpecError(RuntimeError):
    """A user-facing workflow error."""


class ChangeState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    ARCHIVED = "ARCHIVED"


@dataclass(frozen=True)
class Change:
    path: Path
    archived: bool = False

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def number(self) -> int:
        match = CHANGE_NAME_RE.fullmatch(self.name)
        if match is None:
            raise SpecError(f"Invalid change directory name: {self.name}")
        return int(match.group("number"))

    def read(self, filename: str) -> str:
        path = self.path / filename
        try:
            return path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""


@dataclass
class ValidationResult:
    change: Change
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class SpecRepository:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.specs = self.root / "specs"
        self.templates = self.specs / "_templates"
        self.changes = self.specs / "changes"
        self.archive = self.changes / "archive"
        self.capabilities = self.specs / "capabilities"

    def ensure_layout(self) -> None:
        missing = [
            self.templates / filename
            for filename in REQUIRED_DOCUMENTS
            if not (self.templates / filename).is_file()
        ]
        if missing:
            rendered = ", ".join(str(path.relative_to(self.root)) for path in missing)
            raise SpecError(f"Missing SDD templates: {rendered}")
        self.changes.mkdir(parents=True, exist_ok=True)
        self.archive.mkdir(parents=True, exist_ok=True)
        self.capabilities.mkdir(parents=True, exist_ok=True)

    def iter_changes(self, *, include_archived: bool = True) -> list[Change]:
        found: list[Change] = []
        if self.changes.is_dir():
            for path in self.changes.iterdir():
                if path.is_dir() and path.name != "archive" and CHANGE_NAME_RE.fullmatch(path.name):
                    found.append(Change(path))
        if include_archived and self.archive.is_dir():
            for path in self.archive.iterdir():
                if path.is_dir() and CHANGE_NAME_RE.fullmatch(path.name):
                    found.append(Change(path, archived=True))
        return sorted(found, key=lambda change: (change.number, change.name, change.archived))

    def resolve(self, selector: str, *, active_only: bool = False) -> Change:
        candidates = self.iter_changes(include_archived=not active_only)
        exact = [change for change in candidates if change.name == selector]
        if exact:
            return exact[0]

        selector_lower = selector.lower()
        matches = [
            change
            for change in candidates
            if change.name.startswith(selector_lower + "-")
            or change.name.split("-", 1)[1] == selector_lower
        ]
        if not matches:
            raise SpecError(f"Unknown change: {selector}")
        if len(matches) > 1:
            names = ", ".join(change.name for change in matches)
            raise SpecError(f"Ambiguous change {selector!r}: {names}")
        return matches[0]

    def next_number(self) -> int:
        changes = self.iter_changes()
        return max((change.number for change in changes), default=-1) + 1

    def create(self, slug: str) -> Change:
        self.ensure_layout()
        if not SLUG_RE.fullmatch(slug):
            raise SpecError(
                "Slug must contain lowercase letters, digits, and single hyphens only"
            )
        if any(change.name.split("-", 1)[1] == slug for change in self.iter_changes()):
            raise SpecError(f"A change with slug {slug!r} already exists")

        number = self.next_number()
        name = f"{number:03d}-{slug}"
        target = self.changes / name
        if target.exists():
            raise SpecError(f"Change already exists: {name}")

        replacements = {
            "{{CHANGE_ID}}": name.split("-", 1)[0],
            "{{CHANGE_NAME}}": name,
            "{{CHANGE_TITLE}}": slug.replace("-", " ").title(),
            "{{DATE}}": date.today().isoformat(),
        }
        target.mkdir(parents=False)
        try:
            for filename in REQUIRED_DOCUMENTS:
                text = (self.templates / filename).read_text(encoding="utf-8")
                for needle, value in replacements.items():
                    text = text.replace(needle, value)
                (target / filename).write_text(text, encoding="utf-8")
        except Exception:
            shutil.rmtree(target)
            raise
        return Change(target)

    def archive_change(self, change: Change) -> Change:
        if change.archived:
            raise SpecError(f"Change is already archived: {change.name}")
        result = validate_change(change, strict=True, repository=self)
        if not result.ok:
            raise SpecError(_format_validation_failure(result))
        if infer_state(change) != ChangeState.DONE:
            raise SpecError(
                f"{change.name} is {infer_state(change).value}; only DONE changes can be archived"
            )
        _validate_capability_evidence(change, self, result.errors)
        if result.errors:
            raise SpecError(_format_validation_failure(result))

        destination = self.archive / change.name
        if destination.exists():
            raise SpecError(f"Archive destination already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(change.path), str(destination))
        return Change(destination, archived=True)


def infer_state(change: Change) -> ChangeState:
    if change.archived:
        return ChangeState.ARCHIVED

    checklist = change.read("checklist.md")
    approval = APPROVAL_RE.search(checklist)
    if approval is None or approval.group("mark").lower() != "x":
        return ChangeState.DRAFT

    task_marks = [match.group(1).lower() == "x" for match in TASK_RE.finditer(change.read("tasks.md"))]
    if not task_marks or not any(task_marks):
        return ChangeState.READY
    if not all(task_marks):
        return ChangeState.IMPLEMENTING

    checklist_marks = [
        match.group(1).lower() == "x" for match in CHECKBOX_RE.finditer(checklist)
    ]
    if checklist_marks and all(checklist_marks):
        return ChangeState.DONE
    return ChangeState.VERIFYING


def _duplicates(values: Iterable[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count > 1)


def _definition_blocks(text: str, kind: str) -> list[tuple[str, str]]:
    pattern = DEFINITION_PATTERNS[kind]
    matches = list(pattern.finditer(text))
    blocks: list[tuple[str, str]] = []
    heading_re = re.compile(r"(?m)^\s{0,3}(#{1,6})\s+")
    for match in matches:
        level = len(match.group(1))
        end = len(text)
        for heading in heading_re.finditer(text, match.end()):
            if len(heading.group(1)) <= level:
                end = heading.start()
                break
        blocks.append((match.group(2).upper(), text[match.start():end]))
    return blocks


def _checkbox_count(text: str) -> tuple[int, int]:
    marks = [match.group(1).lower() == "x" for match in CHECKBOX_RE.finditer(text)]
    return sum(marks), len(marks)


def _validate_capability_evidence(
    change: Change,
    repository: SpecRepository,
    errors: list[str],
) -> None:
    matches = list(CAPABILITY_RE.finditer(change.read("checklist.md")))
    if len(matches) != 1:
        errors.append("checklist.md must contain exactly one 'Capability updated:' entry")
        return
    match = matches[0]
    if match.group(1).lower() != "x":
        errors.append("capability update evidence must be checked before archive")
        return
    relative = match.group(2) or match.group(3) or ""
    if PLACEHOLDER_RE.search(relative):
        errors.append("capability update evidence still contains a placeholder")
        return
    target = (repository.root / relative).resolve()
    capability_root = repository.capabilities.resolve()
    if target != capability_root and capability_root not in target.parents:
        errors.append("capability evidence must point inside specs/capabilities")
    elif not target.is_file():
        errors.append(f"capability evidence does not exist: {relative}")


def validate_change(
    change: Change,
    *,
    strict: bool = False,
    repository: SpecRepository | None = None,
    for_approval: bool = False,
) -> ValidationResult:
    result = ValidationResult(change)
    missing = [name for name in REQUIRED_DOCUMENTS if not (change.path / name).is_file()]
    if missing:
        result.errors.append(f"missing required documents: {', '.join(missing)}")
        return result

    spec = change.read("spec.md")
    tasks = change.read("tasks.md")
    checklist = change.read("checklist.md")
    requirements = [name for name, _ in _definition_blocks(spec, "requirement")]
    scenarios = _definition_blocks(spec, "acceptance")
    scenario_ids = [name for name, _ in scenarios]
    task_matches = list(TASK_RE.finditer(tasks))
    task_ids = [match.group(2).upper() for match in task_matches]

    if not requirements:
        result.errors.append("spec.md must define at least one requirement (for example, '### R1: ...')")
    if not scenario_ids:
        result.errors.append("spec.md must define at least one acceptance scenario (for example, '### AC1: ...')")
    if not task_ids:
        result.errors.append("tasks.md must define at least one checkbox task (for example, '- [ ] T1 ...')")

    for label, values in (
        ("requirement", requirements),
        ("acceptance scenario", scenario_ids),
        ("task", task_ids),
    ):
        duplicates = _duplicates(values)
        if duplicates:
            result.errors.append(f"duplicate {label} IDs: {', '.join(duplicates)}")

    requirement_set = set(requirements)
    scenario_set = set(scenario_ids)
    requirement_to_scenarios: dict[str, set[str]] = defaultdict(set)
    for scenario_id, block in scenarios:
        references = {ref.upper() for ref in REFERENCE_RE.findall(block)}
        referenced_requirements = {ref for ref in references if ref.startswith("R")}
        unknown = referenced_requirements - requirement_set
        if unknown:
            result.errors.append(
                f"{scenario_id} references unknown requirements: {', '.join(sorted(unknown))}"
            )
        if not referenced_requirements:
            result.errors.append(f"{scenario_id} must reference at least one requirement")
        for requirement in referenced_requirements & requirement_set:
            requirement_to_scenarios[requirement].add(scenario_id)
        for keyword in ("Given", "When", "Then"):
            if not re.search(
                rf"(?mi)^\s*(?:[-*]\s*)?(?:\*\*)?{keyword}(?:\*\*)?\s*:",
                block,
            ):
                result.errors.append(f"{scenario_id} is missing a {keyword}: step")

    for requirement in requirements:
        if not requirement_to_scenarios.get(requirement):
            result.errors.append(f"{requirement} is not covered by an acceptance scenario")

    task_coverage_r: set[str] = set()
    task_coverage_ac: set[str] = set()
    for match in task_matches:
        task_id = match.group(2).upper()
        references = {ref.upper() for ref in REFERENCE_RE.findall(match.group(3))}
        referenced_r = {ref for ref in references if ref.startswith("R")}
        referenced_ac = {ref for ref in references if ref.startswith("AC")}
        unknown_r = referenced_r - requirement_set
        unknown_ac = referenced_ac - scenario_set
        if unknown_r or unknown_ac:
            unknown = sorted(unknown_r | unknown_ac)
            result.errors.append(f"{task_id} references unknown IDs: {', '.join(unknown)}")
        task_coverage_r.update(referenced_r & requirement_set)
        task_coverage_ac.update(referenced_ac & scenario_set)
        if strict and (not referenced_r or not referenced_ac):
            result.errors.append(f"{task_id} must reference at least one R and one AC")

    approval_matches = list(APPROVAL_RE.finditer(checklist))
    if len(approval_matches) != 1:
        result.errors.append(
            "checklist.md must contain exactly one approval marker: "
            "'Specification approved <!-- sdd:approval -->'"
        )
    approved = bool(
        approval_matches and approval_matches[0].group("mark").lower() == "x"
    )
    if approved or for_approval:
        for filename, text in (
            ("spec.md", spec),
            ("tasks.md", tasks),
            ("checklist.md", checklist),
        ):
            if PLACEHOLDER_RE.search(text):
                result.errors.append(
                    f"{filename} contains TBD or NEEDS CLARIFICATION after approval"
                )

    evidence: dict[str, set[str]] = defaultdict(set)
    for match in EVIDENCE_RE.finditer(checklist):
        scenario_id = match.group(2).upper()
        kind = match.group(3).lower()
        value = match.group(4).strip()
        if scenario_id not in scenario_set:
            result.errors.append(f"evidence references unknown scenario: {scenario_id}")
        if kind in evidence[scenario_id]:
            result.errors.append(f"duplicate {kind} evidence for {scenario_id}")
        evidence[scenario_id].add(kind)
        if (approved or for_approval) and PLACEHOLDER_RE.search(value):
            result.errors.append(f"{scenario_id} {kind} evidence is still a placeholder")

    if strict:
        for requirement in requirements:
            if requirement not in task_coverage_r:
                result.errors.append(f"{requirement} is not covered by a task")
        for scenario_id in scenario_ids:
            if scenario_id not in task_coverage_ac:
                result.errors.append(f"{scenario_id} is not covered by a task")
            for kind in ("pytest", "trace"):
                if kind not in evidence.get(scenario_id, set()):
                    result.errors.append(f"{scenario_id} is missing {kind} evidence")
        _, total = _checkbox_count(checklist)
        if total < 4:
            result.errors.append("checklist.md must contain approval, verification, and archive checks")
        if not CAPABILITY_RE.search(checklist):
            result.errors.append("checklist.md is missing capability update evidence")

    if infer_state(change) == ChangeState.DONE or change.archived:
        checked_tasks, total_tasks = _checkbox_count(tasks)
        checked_list, total_list = _checkbox_count(checklist)
        if checked_tasks != total_tasks or checked_list != total_list:
            result.errors.append(
                "DONE and ARCHIVED changes require every task and checklist item to be checked"
            )
        if repository is not None:
            _validate_capability_evidence(change, repository, result.errors)

    return result


def approve_change(change: Change, repository: SpecRepository) -> ChangeState:
    if change.archived:
        raise SpecError(f"Cannot approve archived change: {change.name}")
    result = validate_change(
        change,
        strict=True,
        repository=repository,
        for_approval=True,
    )
    if not result.ok:
        raise SpecError(_format_validation_failure(result))

    checklist_path = change.path / "checklist.md"
    checklist = checklist_path.read_text(encoding="utf-8")
    match = APPROVAL_RE.search(checklist)
    if match is None:
        raise SpecError("checklist.md has no SDD approval marker")
    if match.group("mark").lower() != "x":
        replacement = f"{match.group('prefix')}[x]{match.group('body')}"
        checklist = checklist[: match.start()] + replacement + checklist[match.end() :]
        checklist_path.write_text(checklist, encoding="utf-8")
    return infer_state(change)


def _format_validation_failure(result: ValidationResult) -> str:
    lines = [f"{result.change.name} failed validation:"]
    lines.extend(f"  - {error}" for error in result.errors)
    return "\n".join(lines)


def _default_root() -> Path:
    script_root = Path(__file__).resolve().parents[1]
    for candidate in (Path.cwd(), *Path.cwd().parents):
        if (candidate / "specs" / "_templates").is_dir():
            return candidate
    return script_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage CoreCoder's lightweight specification workflow."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repository root (defaults to the nearest repository with specs/_templates)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new_parser = subparsers.add_parser("new", help="create the next numbered change")
    new_parser.add_argument("slug")

    status_parser = subparsers.add_parser("status", help="show inferred change status")
    status_parser.add_argument("change", nargs="?")

    approve_parser = subparsers.add_parser("approve", help="validate and approve a draft")
    approve_parser.add_argument("change")

    check_parser = subparsers.add_parser("check", help="validate one or all changes")
    check_parser.add_argument("change", nargs="?")
    check_parser.add_argument("--strict", action="store_true")

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="run strict validation and report whether a change is handoff-ready",
    )
    preflight_parser.add_argument("change")
    preflight_parser.add_argument(
        "--for-commit",
        action="store_true",
        help="require the change to already be archived",
    )

    archive_parser = subparsers.add_parser("archive", help="archive a completed change")
    archive_parser.add_argument("change")
    return parser


def _changes_for_command(repository: SpecRepository, selector: str | None) -> list[Change]:
    if selector:
        return [repository.resolve(selector)]
    return repository.iter_changes()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    repository = SpecRepository(args.root or _default_root())

    try:
        if args.command == "new":
            change = repository.create(args.slug)
            print(f"Created {change.name}\t{infer_state(change).value}")
            return 0

        if args.command == "status":
            changes = _changes_for_command(repository, args.change)
            if not changes:
                print("No changes found")
                return 0
            for change in changes:
                print(f"{change.name}\t{infer_state(change).value}")
            return 0

        if args.command == "approve":
            change = repository.resolve(args.change, active_only=True)
            state = approve_change(change, repository)
            print(f"Approved {change.name}\t{state.value}")
            return 0

        if args.command == "check":
            changes = _changes_for_command(repository, args.change)
            if not changes:
                print("No changes found")
                return 0
            failures = 0
            for change in changes:
                result = validate_change(
                    change,
                    strict=args.strict,
                    repository=repository,
                )
                if result.ok:
                    print(f"OK {change.name}\t{infer_state(change).value}")
                else:
                    failures += 1
                    print(_format_validation_failure(result), file=sys.stderr)
            return 1 if failures else 0

        if args.command == "preflight":
            change = repository.resolve(args.change)
            result = validate_change(
                change,
                strict=True,
                repository=repository,
            )
            state = infer_state(change)
            if not result.ok:
                print(
                    f"Preflight FAILED {change.name}\t{state.value}",
                    file=sys.stderr,
                )
                print(_format_validation_failure(result), file=sys.stderr)
                return 1
            if args.for_commit and not change.archived:
                if state == ChangeState.DONE:
                    message = f"{change.name} is DONE; archive it before commit"
                else:
                    message = (
                        f"{change.name} is {state.value}; only ARCHIVED changes "
                        "pass --for-commit"
                    )
                print(f"spec: error: {message}", file=sys.stderr)
                return 1
            print(f"Preflight OK {change.name}\t{state.value}")
            return 0

        if args.command == "archive":
            change = repository.resolve(args.change, active_only=True)
            archived = repository.archive_change(change)
            print(f"Archived {archived.name}\t{ChangeState.ARCHIVED.value}")
            return 0
    except SpecError as exc:
        print(f"spec: error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
