# 007-release-0-4 — CoreCoder 0.4 release documentation

- Change type: documentation
- Status: archived

## Why

The public documentation and version metadata still described the pre-0.4
runtime and mixed user guidance with architecture notes.

## Goals

- Publish the 0.4 user guide, architecture snapshot, roadmap lanes, changelog,
  and compatibility notice.

## Non-goals

- Add runtime behavior beyond the preceding changes.

## Requirements

### R1: Describe the 0.4 contract accurately

Version metadata and user-facing documentation identify the 0.4 CLI, Terminal,
SDD, session, and Trace behavior without exposing credentials or generated state.

## Acceptance scenarios

### AC1: Verify release metadata and docs

- Requirements: R1
- Given: the repository is installed or its help is rendered
- When: version and documentation are inspected
- Then: they consistently describe CoreCoder 0.4 and its supported workflows

## Compatibility and migration

Historical articles are marked with their applicable pre-0.4 version and
`CLAUDE.md` links back to `AGENTS.md`.

## Trace contract

- AC1 pytest: `tests/test_core.py::test_version`
- AC1 trace: documentation-only release change has no runtime Trace requirement; CLI help smoke is the evidence.

## Risks and rollback

Revert release documentation and version metadata together.

## Capability impact

- Update `specs/capabilities/sdd-workflow.md`.
