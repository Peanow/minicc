# 006-session-recovery checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_session.py::test_session_store_atomic_and_project_scoped`
- [x] AC1 trace: checkpoint status remains independent of trace persistence.
- [x] AC2 pytest: `tests/test_runtime_v2.py::test_ephemeral_agent_does_not_create_corecoder_state`
- [x] AC2 trace: no persistence artifact is created by the run.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/session.md`
- [x] Ready to archive.
