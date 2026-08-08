# 015-session-resume-window checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_terminal.py::test_resume_renders_all_session_messages`
- [x] AC1 trace: `session_resumed` follows a complete restore.
- [x] AC2 pytest: `tests/test_terminal.py::test_resume_slash_command_accepts_latest_or_id`
- [x] AC2 trace: invalid resume commands do not emit resume events.
- [x] AC3 pytest: `tests/test_terminal.py::test_resume_trace_contains_metadata_only`
- [x] AC3 trace: message bodies are absent from the event payload.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/session.md`
- [x] Ready to archive.
