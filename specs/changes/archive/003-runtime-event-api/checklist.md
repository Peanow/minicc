# 003-runtime-event-api checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_commandline.py::test_runtime_adapter_consumes_agent_observer_api`
- [x] AC1 trace: lifecycle event order is asserted by the observer test.
- [x] AC2 pytest: `tests/test_runtime_v2.py::test_compaction_model_call_has_purpose_and_trace`
- [x] AC2 trace: `model_started` has `purpose=compaction`.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/runtime.md`
- [x] Ready to archive.
