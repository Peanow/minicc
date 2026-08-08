# 002-effects-memory-model — Effects, policy, and memory boundary

- Change type: behavior
- Status: archived

## Why

Stringly-typed tool results and implicit effects made approvals and memory
writes impossible to reason about safely.

## Goals

- Require explicit effects and structured tool results.
- Enforce read-only and ephemeral memory behavior.

## Non-goals

- Add a new configuration file format.

## Requirements

### R1: Enforce declared effects

Tools declare effects and undeclared effects are approved interactively or
blocked in headless execution.

### R2: Respect persistence modes

Read-only and ephemeral agents do not write workspace, memory, or application
state through model-driven tools.

## Acceptance scenarios

### AC1: Block an undeclared effect headlessly

- Requirements: R1
- Given: a custom tool has no effect declaration
- When: a headless agent receives a call to that tool
- Then: execution is blocked and a structured tool-finished event is emitted

### AC2: Keep ephemeral runs stateless

- Requirements: R2
- Given: an agent is created with ephemeral mode
- When: it completes and closes a task
- Then: no CoreCoder state directory is created

## Compatibility and migration

Legacy string tool returns are coerced to `ToolResult` for migration.

## Trace contract

- AC1 pytest: `tests/test_runtime_v2.py::test_undeclared_effect_is_blocked_headlessly_and_traced`
- AC1 trace: `approval_requested` and blocked `tool_finished` identify the tool and effect decision.
- AC2 pytest: `tests/test_runtime_v2.py::test_ephemeral_agent_does_not_create_corecoder_state`
- AC2 trace: `run_finished` records the terminal status without persistence artifacts.

## Risks and rollback

Restore the compatibility coercion and disable effect enforcement if a custom
tool cannot be migrated immediately.

## Capability impact

- Update `specs/capabilities/runtime.md`.
