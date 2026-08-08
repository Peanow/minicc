# 014-workspace-sandbox checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_sandbox.py::test_workspace_read_write_success`
- [x] AC1 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC2 pytest: `tests/test_sandbox.py::test_workspace_escape_is_denied`
- [x] AC2 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC3 pytest: `tests/test_sandbox.py::test_network_defaults_to_deny`
- [x] AC3 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC4 pytest: `tests/test_sandbox.py::test_network_allow_does_not_bypass_policy`
- [x] AC4 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC5 pytest: `tests/test_sandbox.py::test_read_only_and_full_access_modes`
- [x] AC5 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC6 pytest: `tests/test_sandbox.py::test_unavailable_backend_fails_closed`
- [x] AC6 trace: `tests/test_sandbox.py::test_unavailable_backend_is_traced`
- [x] AC7 pytest: `tests/test_config.py::test_sandbox_network_configuration_sources`
- [x] AC7 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC8 pytest: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] AC8 trace: `tests/test_sandbox.py::test_sandbox_trace_is_safe`
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/runtime.md`
- [x] Ready to archive.
