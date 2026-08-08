# 011-sdd-human-gates checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_spec_workflow.py::test_sdd_workflow_documents_explore_and_human_confirmation_gates`
- [x] AC1 trace: the workflow documentation contains the Explore evidence
  list, ask-user choices, and implementation ordering.
- [x] AC2 pytest: `tests/test_spec_workflow.py::test_sdd_workflow_documents_explore_and_human_confirmation_gates`
- [x] AC2 trace: the workflow documentation requires evidence and confirmation
  before `spec.py archive` after `DONE`.
- [x] AC3 pytest: `tests/test_spec_workflow.py::test_sdd_workflow_documents_explore_and_human_confirmation_gates`
- [x] AC3 trace: the workflow documentation separates archive and commit
  confirmation and says `git push` is never implicit.
- [x] AC4 pytest: `tests/test_spec_workflow.py::test_lifecycle_and_archive`
- [x] AC4 trace: existing lifecycle command output retains its inferred state
  and archive behavior without an interactive prompt.
- [x] Tests and compile checks pass: `.venv/bin/python -m pytest -q` and
  `.venv/bin/python -m compileall -q corecoder tests`.
- [x] No credentials or generated runtime state are included; `git diff --check`
  passes.

## Completion

- [x] Capability updated: `specs/capabilities/sdd-workflow.md`
- [x] Ready to archive after explicit user confirmation.
