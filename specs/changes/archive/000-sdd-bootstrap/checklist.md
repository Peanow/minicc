# 000-sdd-bootstrap checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_spec_workflow.py::test_lifecycle_and_archive`
- [x] AC1 trace: CLI status output is asserted in `test_lifecycle_and_archive`.
- [x] AC2 pytest: `tests/test_spec_workflow.py::test_validation_rejects_bad_references_and_placeholders`
- [x] AC2 trace: CLI stderr and failure exit status are asserted by the validation tests.
- [x] AC3 pytest: `tests/test_spec_workflow.py::test_archive_requires_capability_evidence`
- [x] AC3 trace: CLI archive output and the resulting archive path are asserted by the archive tests.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/sdd-workflow.md`
- [x] Ready to archive.
