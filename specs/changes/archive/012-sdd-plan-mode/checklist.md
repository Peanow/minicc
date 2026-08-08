# 012-sdd-plan-mode checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_spec_workflow.py::test_sdd_workflow_documents_optional_plan_mode_and_human_gates`
- [x] AC1 trace: active workflow documents contain optional plan-mode guidance
  and no separate pre-implementation planning gate.
- [x] AC2 pytest: `tests/test_spec_workflow.py::test_sdd_workflow_documents_optional_plan_mode_and_human_gates`
- [x] AC2 trace: active workflow documents retain separate archive and commit
  confirmations and the no-implicit-push boundary.
- [x] AC3 pytest: `tests/test_spec_workflow.py::test_lifecycle_and_archive`
- [x] AC3 trace: lifecycle commands retain inferred state and archive output.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/sdd-workflow.md`
- [x] Ready to archive.
