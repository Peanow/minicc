# 007-release-0-4 checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_core.py::test_version`
- [x] AC1 trace: documentation-only change is verified by CLI help and version smoke checks.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/sdd-workflow.md`
- [x] Ready to archive.
