# 015-session-resume-window — Display complete resumed sessions

- Change type: behavior
- Created: 2026-08-08

## Why

Session resume currently restores messages into the Agent model context but
does not show the recovered conversation in the interactive terminal. Users
also have to remember the longer `/session resume ID` command.

## Goals

- Display every persisted session message in the terminal after resume.
- Add `/resume [ID]`, where no ID selects the latest project session.
- Keep existing CLI and `/session resume ID` behavior compatible.

## Non-goals

- Change the session schema or persist system prompts.
- Restore permissions, credentials, diff journals, or other non-session state.

## Requirements

### R1: Show the complete resumed conversation

After a successful interactive resume, the terminal shows all checkpointed
messages in their persisted order, with role labels and structured message
fields preserved without truncation.

### R2: Provide a concise interactive resume command

`/resume` restores the latest project-local session and `/resume ID` restores a
specific session. `/session resume ID` remains supported.

### R3: Make resume observable without exposing content

A successful interactive resume emits a `session_resumed` Trace event containing
resume metadata but never the session message bodies.

## Acceptance scenarios

### AC1: Render a complete session after resume

- Requirements: R1
- Given: a project session contains user, assistant, and tool messages
- When: the session is resumed through an interactive entry point
- Then: the terminal displays every message in order and keeps the prompt input
  buffer available for a new request

### AC2: Resume latest or named session with slash commands

- Requirements: R2
- Given: project sessions exist
- When: the user enters `/resume`, `/resume ID`, or `/session resume ID`
- Then: the expected session is restored; missing or invalid IDs produce a
  readable command error

### AC3: Trace resume metadata safely

- Requirements: R3
- Given: a resume succeeds
- When: the terminal finishes loading the session window
- Then: one `session_resumed` event records the session ID and message count,
  while message text is absent from the event payload

## Compatibility and migration

No session file migration is required. The existing `corecoder --continue` and
`corecoder session resume ID` entry points continue to work and gain the same
terminal display behavior. Session persistence and redaction remain unchanged.

## Trace contract

- AC1 pytest: `tests/test_terminal.py::test_resume_renders_all_session_messages`
- AC1 trace: `session_resumed` is emitted after the complete checkpoint is loaded.
- AC2 pytest: `tests/test_terminal.py::test_resume_slash_command_accepts_latest_or_id`
- AC2 trace: failed command resolution emits no `session_resumed` event.
- AC3 pytest: `tests/test_terminal.py::test_resume_trace_contains_metadata_only`
- AC3 trace: the event contains `session_id` and `message_count`, not message text.

## Risks and rollback

Long sessions can produce substantial terminal output; rendering remains in
scrollback and does not populate the editable input buffer. If the new command
or rendering causes regressions, remove the top-level slash command and retain
the existing restore path; session files remain compatible.

## Capability impact

- Update `specs/capabilities/session.md` and `specs/capabilities/terminal.md`.
