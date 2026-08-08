# 002-effects-memory-model checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_runtime_v2.py::test_undeclared_effect_is_blocked_headlessly_and_traced`
- [x] AC1 trace: blocked `tool_finished` and `approval_requested` are asserted.
- [x] AC2 pytest: `tests/test_runtime_v2.py::test_ephemeral_agent_does_not_create_corecoder_state`
- [x] AC2 trace: `run_finished` is emitted without state writes.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/runtime.md`
- [x] Ready to archive.
