# 003-runtime-event-api — Runtime events and public Agent API

- Change type: behavior
- Status: archived

## Why

The old callback API and mixed trace event names prevented Terminal, replay, and
tests from sharing one observable lifecycle.

## Goals

- Provide `Agent.run` and structured RunEvent/Trace schema v2.
- Route agent and compaction calls through ModelGateway with a purpose.

## Non-goals

- Rebuild evaluation storage or observability backends.

## Requirements

### R1: Expose one observable run API

`Agent.run(prompt, observer=...)` emits the common lifecycle and returns a
task-local `RunResult`.

### R2: Tag model purposes

Agent and compaction model calls emit purpose-tagged model events and preserve
failure information in Trace.

## Acceptance scenarios

### AC1: Observe a completed run

- Requirements: R1
- Given: a model returns one final answer
- When: `Agent.run` is invoked with an observer
- Then: the observer receives run, model, text, and finish events in order

### AC2: Trace a compaction call

- Requirements: R2
- Given: context exceeds its configured limit
- When: compaction invokes the model gateway
- Then: Trace records a `compaction` purpose and context-compacted event

## Compatibility and migration

Trace replay accepts v1 and v2 names; removed callbacks are adapted only at CLI
boundaries.

## Trace contract

- AC1 pytest: `tests/test_commandline.py::test_runtime_adapter_consumes_agent_observer_api`
- AC1 trace: observer receives `run_started`, `model_started`, `text_delta`, `model_finished`, `run_finished`.
- AC2 pytest: `tests/test_runtime_v2.py::test_compaction_model_call_has_purpose_and_trace`
- AC2 trace: `model_started.data.purpose` equals `compaction`.

## Risks and rollback

Keep the v1 replay reader and restore the CLI bridge if an integration still
emits legacy lifecycle names.

## Capability impact

- Update `specs/capabilities/runtime.md`.
