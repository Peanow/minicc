# 010-approval-ux — Approval UX

- Change type: behavior
- Created: 2026-08-08

## Why

The interactive terminal currently prints a text prompt and calls
`Console.input()` while the main `PromptSession` is paused. Users must know
which letters are accepted, and the prompt does not make the safe default or
the available approval scope obvious. This is especially awkward for model
tool calls because the approval step looks like an unrelated second input
prompt.

## Goals

- Make tool approval feel like a focused terminal decision with visible,
  numbered choices, arrow-key navigation, and an explicit safe default.
- Preserve one-time approval, exact-rule session approval, denial, and the
  redacted details view.
- Record the approval outcome so a run can be understood from its Trace
  without relying on terminal output.

## Non-goals

- Change the application permission model or make application checks an OS
  sandbox.
- Persist approval rules beyond the lifetime of the Agent.
- Auto-approve commands when stdin is unavailable.

## Requirements

### R1: Focused interactive approval

In interactive mode, an approval request presents the tool, effect, risk, cwd,
and redacted command/targets, followed by numbered choices for allowing once,
allowing an eligible exact rule for the session, viewing details, and denying.
The deny choice is selected by default; Enter therefore cannot accidentally
authorize a tool. The user can select with arrow keys or the displayed number.
Details returns to the same decision without losing the request.

### R2: Approval outcome observability

Every approval request produces an `approval_decided` Trace event containing the
tool call id, tool, selected outcome (`once`, `session`, or `deny`), final
policy decision, risk, and reason. Arguments and secrets are not copied into
this event.

## Acceptance scenarios

### AC1: Choose a tool approval without free-form command input

- Requirements: R1
- Given: an interactive approval request for a non-destructive shell command
- When: the user navigates the numbered approval choices and confirms
- Then: the selected choice is returned, the default selection is denial, and
  choosing details renders the expanded redacted arguments before asking again

### AC2: Record the approval outcome

- Requirements: R2
- Given: an Agent receives an approval-required tool call
- When: the approval callback returns once, session, or deny
- Then: the Trace includes one `approval_decided` event with the outcome and
  no tool arguments

## Compatibility and migration

The legacy three-argument approval callback remains supported. Injected `read`
callbacks remain available for deterministic hosts and existing integrations;
the interactive CLI uses the selector by default. Headless runs continue to
deny approval-required tools when no callback is supplied.

## Trace contract

- AC1: selector output and choice are asserted by
  `tests/test_terminal.py::test_approval_selector_uses_safe_default_and_details`
  and the emitted terminal output is the trace of the visible decision card.
- AC2: `tests/test_trace.py::test_approval_decision_is_recorded_without_arguments`
  asserts the `approval_decided` event and its redaction boundary.

## Risks and rollback

Nested prompt-toolkit applications may behave differently on unusual terminal
streams. The injected selector/read seams provide deterministic fallback
coverage; rollback is to use the existing line reader while retaining the
same ApprovalChoice contract and Trace event.

## Capability impact

- Update `specs/capabilities/terminal.md` before archive.
