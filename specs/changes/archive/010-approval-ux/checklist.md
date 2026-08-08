# 010-approval-ux checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_terminal.py::test_approval_selector_uses_safe_default_and_details`
- [x] AC1 trace: selector output records the visible approval decision card and
  selected outcome.
- [x] AC2 pytest: `tests/test_trace.py::test_approval_decision_is_recorded_without_arguments`
- [x] AC2 trace: `approval_decided` contains outcome/policy metadata and no
  `arguments` field.
- [x] Tests and compile checks pass: `.venv/bin/python -m pytest -q` (349
  passed) and `.venv/bin/python -m compileall -q corecoder tests`.
- [x] No credentials or generated runtime state are included; `git diff
  --check` passes.

## Completion

- [x] Capability updated: `specs/capabilities/terminal.md`
- [x] Ready to archive.
