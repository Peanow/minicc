# 005-terminal-composer-renderer checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_terminal.py::test_terminal_sends_double_slash_as_literal_without_stripping`
- [x] AC1 trace: literal prompt is passed unchanged to the run observer.
- [x] AC2 pytest: `tests/test_terminal.py::test_plain_renderer_keeps_diagnostics_off_stdout`
- [x] AC2 trace: tool diagnostics and run completion remain separate events.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/terminal.md`
- [x] Ready to archive.
