# Changelog

All notable changes to this project are documented in this file. CoreCoder uses
semantic versioning; pre-1.0 minor releases may intentionally break APIs when
the migration is called out here.

## [0.4.0] - 2026-08-08

### Breaking changes

- Replaced `Agent.chat` and token/tool callbacks with `Agent.run(prompt,
  observer=...)` and a per-task `RunResult`.
- Replaced legacy `-p`, `-r`, `--api-key`, and top-level replay/evaluation
  commands with the `run`, `session`, `trace`, `lab`, `observe`, and `doctor`
  command tree.
- Replaced global tool lookup with Agent-owned registries, mandatory tool
  effects, and structured `ToolResult` values.
- Started writing Trace schema v2. Trace replay remains compatible with v1.

### Added

- Long-lived inline `PromptSession` with command/model/skill/session/path
  completion, multiline input, editor composition, reliable interrupt
  handling, tool state, syntax-highlighted diffs, and structured approvals.
- Deterministic pretty/plain/JSONL output adapters and documented exit codes for
  headless use.
- Injectable `AppPaths`, shared `WorkspaceState`, explicit Agent/Run state, and
  per-run token/change accounting.
- Project-scoped schema v2 sessions with atomic checkpoints, `--continue`,
  corruption diagnostics, and cross-project rejection.
- `--ephemeral` operation that suppresses CoreCoder session, history, and memory
  writes.
- A repository-local, standard-library-only SDD workflow with templates,
  validation, approval, status inference, archival, and traceability checks.
- Unified runtime/model events with purpose-tagged agent, compaction, and memory
  calls.

### Changed

- Read-only mode now disables model-driven workspace and memory writes.
- Only explicitly parallel-safe tools whose effects are entirely read-only may
  execute concurrently; unknown effects require approval or are denied
  headlessly.
- `AGENTS.md` is the sole engineering constitution. User guidance, development
  workflow, benchmark evidence, and change specifications now have distinct
  documentation roles.

## [0.3.0]

- Experimental observable runtime baseline with skills, hooks, memory,
  application permission policy, evaluation tooling, and JSONL traces.
