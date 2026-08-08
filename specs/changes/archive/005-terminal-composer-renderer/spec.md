# 005-terminal-composer-renderer — Inline Terminal UX

- Change type: behavior
- Status: archived

## Why

The old terminal had no durable prompt session, completion, structured tool
status, or safe slash-command handling.

## Goals

- Add a long-lived PromptSession, command registry, completion, and Rich event
  renderer with deterministic degradation.

## Non-goals

- Adopt a full-screen Textual interface.

## Requirements

### R1: Make interactive input discoverable and cancellable

The Terminal supports completion, multiline/editor input, literal `//` text,
unknown-command suggestions, and Ctrl+C/Ctrl+D behavior.

### R2: Render observable tool progress and diffs

Tool status, approvals, final Markdown, and structured diffs are rendered
without mixing diagnostics into plain stdout.

## Acceptance scenarios

### AC1: Discover commands and preserve literal slash text

- Requirements: R1
- Given: a user completes a slash command or enters `//text`
- When: the prompt session dispatches input
- Then: commands are completed and literal text is sent without stripping

### AC2: Keep plain output pipeline-safe

- Requirements: R2
- Given: a run streams text and executes a tool
- When: plain rendering finishes
- Then: stdout contains only the final answer and diagnostics are on stderr

## Compatibility and migration

The existing prompt module remains importable; the new Terminal owns public
interactive behavior.

## Trace contract

- AC1 pytest: `tests/test_terminal.py::test_terminal_sends_double_slash_as_literal_without_stripping`
- AC1 trace: the observer receives the exact literal prompt.
- AC2 pytest: `tests/test_terminal.py::test_plain_renderer_keeps_diagnostics_off_stdout`
- AC2 trace: tool events remain observable while final answer is rendered once.

## Risks and rollback

Disable the inline composer and fall back to headless plain mode if terminal
capabilities are unavailable.

## Capability impact

- Update `specs/capabilities/terminal.md`.
