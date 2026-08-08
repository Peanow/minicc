# 016-explicit-memory checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_memory.py::test_agent_does_not_auto_search_or_inject_memory`
- [x] AC1 trace: no automatic memory search failure event is emitted.
- [x] AC2 pytest: `tests/test_memory.py::test_agent_close_does_not_auto_save_memory`
- [x] AC2 trace: no automatic memory_written event is emitted.
- [x] AC3 pytest: `tests/test_memory.py::test_explicit_memory_tools_keep_schema_and_effects`
- [x] AC3 trace: explicit tool lifecycle remains observable.
- [x] AC4 pytest: `tests/test_memory.py::test_memory_directory_and_runtime_modes_remain_compatible`
- [x] AC4 trace: compatibility checks emit no automatic memory lifecycle event.
- [x] AC5 pytest: `tests/test_hooks.py::test_memory_hook_symbols_remain_compatible`
- [x] AC5 trace: direct hook mapping retains event names.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/runtime.md`
- [x] Ready to archive.
