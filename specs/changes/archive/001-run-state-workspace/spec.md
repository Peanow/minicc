# 001-run-state-workspace — Run state and workspace boundary

- Change type: behavior
- Status: archived

## Why

The previous runtime mixed process paths and cumulative counters, making a
second task depend on the first task's state.

## Goals

- Make workspace resolution and task accounting instance-owned.

## Non-goals

- Redesign the complete agent loop.

## Requirements

### R1: Isolate workspace and run state

Policy, file tools, Bash, and task results use one workspace boundary and each
run reports only its own token and changed-file delta.

## Acceptance scenarios

### AC1: Isolate consecutive runs

- Requirements: R1
- Given: an agent runs two prompts with separate model usage
- When: both runs complete
- Then: each result contains only that run's token and file deltas

## Compatibility and migration

The old helper APIs remain available while new composition uses `AppPaths` and
`WorkspaceState`.

## Trace contract

- AC1 pytest: `tests/test_runtime_v2.py::test_run_result_and_trace_are_task_local`
- AC1 trace: `run_started` and `run_finished` contain the same run id and task-local token data.

## Risks and rollback

Revert the runtime state adapters while retaining the existing tool behavior.

## Capability impact

- Update `specs/capabilities/runtime.md`.
