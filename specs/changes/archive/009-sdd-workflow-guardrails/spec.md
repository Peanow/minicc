# 009-sdd-workflow-guardrails — SDD Workflow Guardrails

- Change type: behavior
- Created: 2026-08-08

## Why

The repository workflow is currently described across a short `AGENTS.md`,
the SDD README, and the implementation of `scripts/spec.py`. Contributors
need one clear project-level entry point and a read-only machine check for the
state that is safe to hand off or commit.

## Goals

- Keep the project-level AI workflow in `AGENTS.md` without adding a project
  skill or another instruction source.
- Add a read-only `preflight` command that applies strict SDD validation and
  reports the change state.
- Make the commit handoff explicit: only an archived change passes
  `preflight --for-commit`, and a completed active change is directed to
  `archive` first.

## Non-goals

- Automatically commit, amend, push, or block CI.
- Change the existing `new`, `status`, `approve`, `check`, or `archive`
  command contracts.
- Add a project-level `.agents/skills/` directory.

## Requirements

### R1: Centralize the project workflow entry point

`AGENTS.md` describes when a change specification is required, the status and
verification checkpoints, the archive-before-commit rule, and the explicit
authorization boundary for commit, amend, push, and destructive operations.
It does not depend on a project skill file.

### R2: Provide a strict, read-only preflight

`python scripts/spec.py preflight CHANGE` runs strict validation and reports
the inferred state when validation succeeds. Validation failures produce a
non-zero exit status and actionable errors. The command does not modify any
specification files.

### R3: Guard the commit handoff

`python scripts/spec.py preflight CHANGE --for-commit` succeeds only for an
archived change that passes strict validation. An active `DONE` change is
rejected with guidance to archive it first; other active states are also
rejected without modifying files.

### R4: Document the supported workflow

`specs/README.md` and `specs/capabilities/sdd-workflow.md` document the
centralized rules and both preflight modes, including that preflight never
commits or archives changes.

## Acceptance scenarios

### AC1: Strict preflight catches an invalid change

- Requirements: R2
- Given: an active change with a strict validation error
- When: a maintainer runs `preflight CHANGE`
- Then: the command exits non-zero and reports the validation error

### AC2: Preflight is read-only

- Requirements: R2
- Given: a change with specification documents on disk
- When: a maintainer runs either preflight mode
- Then: the contents and locations of the specification documents are
  unchanged

### AC3: An active completed change is not commit-ready

- Requirements: R1, R3
- Given: an approved active change whose tasks and checklist are complete
- When: a maintainer runs `preflight CHANGE --for-commit`
- Then: the command exits non-zero and tells the maintainer to archive the
  change first

### AC4: An archived completed change passes commit preflight

- Requirements: R3, R4
- Given: a valid completed change has been archived
- When: a maintainer runs `preflight CHANGE --for-commit`
- Then: the command exits zero and reports `ARCHIVED`

## Compatibility and migration

This is additive. Existing commands keep their current behavior. Contributors
can adopt `preflight` before a handoff; no repository state is migrated.

## Trace contract

- AC1: stderr contains the strict validation failure and the exit status is
  non-zero.
- AC2: stdout reports a successful preflight state, or stderr reports the
  guard failure; the document snapshots remain equal.
- AC3: stderr contains `archive it before commit` and the exit status is
  non-zero.
- AC4: stdout contains `Preflight OK`, the change name, and `ARCHIVED`.

## Risks and rollback

The additional guard may expose incomplete existing changes at handoff time;
the existing `check`, `archive`, and document workflow remain available.
Rollback is to remove the `preflight` parser branch and its tests, then restore
the prior documentation wording.

## Capability impact

- Update `specs/capabilities/sdd-workflow.md` before archive.
