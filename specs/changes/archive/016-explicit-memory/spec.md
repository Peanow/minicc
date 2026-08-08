# 016-explicit-memory — Explicit cross-session memory

- Change type: behavior
- Created: 2026-08-08

## Why

The Agent currently searches memory before the first user task and persists
conversation-derived observations during `close()`. These implicit lifecycle
operations make memory behavior surprising and can create state without an
explicit user or model decision.

## Goals

- Make cross-session memory retrieval and persistence explicit.
- Keep the existing memory tools, slash commands, directory hint, session
  recovery, ephemeral mode, and permission behavior compatible.
- Keep memory hook symbols available for host integrations while documenting
  that the default Agent lifecycle no longer dispatches them.

## Non-goals

- Remove or migrate existing SQLite memory databases.
- Remove `MemoryService.search()`, `save()`, or `save_conversation()`.
- Change session checkpointing or the memory database schema.

## Requirements

### R1: Do not automatically retrieve memory for a task

Starting or running an Agent task does not call `MemoryService.search()` as a
pre-task lifecycle step and does not add relevant-memory content to model
messages or context-token accounting.

### R2: Do not automatically persist a conversation on close

Closing an Agent does not call `save_conversation()` and does not emit
automatic `memory_written` or memory-search-failure Trace events, including
when the conversation is empty.

### R3: Preserve explicit memory operations

The default tool registry continues to expose `memory_search` and
`memory_save` with their existing schemas, effects, and policy behavior;
explicit tool calls, `MemoryService` calls, and `/memory search` or
`/memory save` remain available.

### R4: Preserve memory hints and runtime compatibility

When historical memories exist, the system prompt still contains their
lightweight directory and tells the model to call `memory_search` when it
needs history and to call `memory_save` only for information with
cross-session value. Existing memories remain searchable across Agent
instances and processes; session resume, `--ephemeral`, and read-only
behavior remain unchanged.

### R5: Keep memory hook API symbols without implying automatic behavior

`HookEvent.MemorySave`, `HookEvent.MemoryInject`, and their environment
variable mappings remain available to hook consumers, while hook
documentation states that they are not dispatched by the default Agent
lifecycle.

## Acceptance scenarios

### AC1: First task does not search or inject memory

- Requirements: R1
- Given: an Agent has historical memory and a spy memory service
- When: the Agent runs its first task
- Then: the service search count remains zero, no relevant-memory message is
  sent, and no automatic search-failure Trace event is emitted

### AC2: Closing does not save conversation memory

- Requirements: R2
- Given: an Agent has messages, or has no messages
- When: the Agent is closed
- Then: `save_conversation()` is not called, no `memory_written` event is
  emitted, and an empty close does not create a memory database

### AC3: Explicit memory tools remain stable

- Requirements: R3
- Given: the default tool registry and a writable Agent
- When: callers inspect schemas or invoke explicit search/save operations
- Then: both tools retain their names, required parameters, declared effects,
  and cross-Agent search/save behavior

### AC4: Directory hints and lifecycle modes remain compatible

- Requirements: R4
- Given: historical memory, an existing session, ephemeral mode, or a
  read-only policy
- When: the Agent is initialized, resumed, closed, or asked to save memory
- Then: the directory hint and explicit-search guidance remain present,
  session restoration works, ephemeral state is not persisted, and read-only
  writes remain denied

### AC5: Memory hook compatibility is explicit

- Requirements: R5
- Given: a host imports the memory hook enum or environment mapping
- When: it uses those public hook definitions directly
- Then: the symbols and mappings remain available and documentation makes no
  claim that the default Agent lifecycle dispatches them

## Compatibility and migration

No data migration is required. Existing SQLite memories remain available to
explicit search. Hosts that directly call `MemoryService.save_conversation()`
or dispatch memory hooks retain those APIs; only the default Agent lifecycle
stops invoking them.

## Trace contract

- AC1 pytest: `tests/test_memory.py::test_agent_does_not_auto_search_or_inject_memory`
- AC1 trace: the task trace contains no automatic `memory_failed` event with
  `operation=search`.
- AC2 pytest: `tests/test_memory.py::test_agent_close_does_not_auto_save_memory`
- AC2 trace: close produces no `memory_written` event.
- AC3 pytest: `tests/test_memory.py::test_explicit_memory_tools_keep_schema_and_effects`
- AC3 trace: explicit tool execution remains observable through the normal
  `tool_started`/`tool_finished` lifecycle events.
- AC4 pytest: `tests/test_memory.py::test_memory_directory_and_runtime_modes_remain_compatible`
- AC4 trace: no automatic memory lifecycle event is emitted while the
  directory, session, ephemeral, and read-only checks pass.
- AC5 pytest: `tests/test_hooks.py::test_memory_hook_symbols_remain_compatible`
- AC5 trace: hook environment mappings continue to expose the original event
  names when invoked directly.

## Risks and rollback

Models will no longer see historical memory unless they choose
`memory_search`, so the system prompt must retain a clear directory hint.
Rollback is limited to restoring the two Agent lifecycle dispatches; existing
memory data and the explicit APIs remain compatible either way.

## Capability impact

- Update `specs/capabilities/runtime.md` with explicit memory lifecycle
  behavior before archive.
