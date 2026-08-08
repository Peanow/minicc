# 009-sdd-workflow-guardrails checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_spec_workflow.py::test_preflight_reports_strict_validation_failure`
- [x] AC1 trace: stderr contains the strict validation error and the command exits non-zero.
- [x] AC2 pytest: `tests/test_spec_workflow.py::test_preflight_does_not_modify_specification_files`
- [x] AC2 trace: preflight output is observed and before/after document snapshots are equal.
- [x] AC3 pytest: `tests/test_spec_workflow.py::test_preflight_for_commit_rejects_active_done_change`
- [x] AC3 trace: stderr contains `archive it before commit`.
- [x] AC4 pytest: `tests/test_spec_workflow.py::test_preflight_for_commit_accepts_archived_change`
- [x] AC4 trace: stdout contains `Preflight OK` and `ARCHIVED`.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/sdd-workflow.md`
- [x] Ready to archive.
