# 006-session-recovery — Atomic session recovery

- Change type: behavior
- Status: archived

## Why

Session files could be ambiguous across projects and partial writes could leave
users unable to resume a conversation.

## Goals

- Add project-scoped schema v2 sessions, atomic checkpoints, continue/resume,
  corruption diagnostics, and ephemeral mode.

## Non-goals

- Restore a prior permission mode or credentials.

## Requirements

### R1: Recover only complete project-local checkpoints

Session checkpoints are atomic, private, project-isolated, and corrupted files
produce a readable error without deletion.

### R2: Make persistence explicit

Interactive sessions persist by default while non-interactive runs persist only
with `--save-session`; `--ephemeral` writes no CoreCoder state.

## Acceptance scenarios

### AC1: Preserve a session checkpoint safely

- Requirements: R1
- Given: a session is saved and then loaded for its project
- When: the checkpoint is read or a corrupt file is encountered
- Then: valid data restores and corrupt data remains available for diagnosis

### AC2: Isolate ephemeral execution

- Requirements: R2
- Given: a non-interactive ephemeral run completes
- When: the runtime closes
- Then: no session, history, or memory files are written

## Compatibility and migration

Legacy function-based session helpers remain as thin adapters and do not share
mutable runtime state with the v2 store.

## Trace contract

- AC1 pytest: `tests/test_session.py::test_session_store_atomic_and_project_scoped`
- AC1 trace: session checkpoint status is retained independently of run traces.
- AC2 pytest: `tests/test_runtime_v2.py::test_ephemeral_agent_does_not_create_corecoder_state`
- AC2 trace: the run finishes without persistence artifacts.

## Risks and rollback

Keep the last complete JSON file and disable automatic continue if migration
validation fails.

## Capability impact

- Update `specs/capabilities/session.md`.
