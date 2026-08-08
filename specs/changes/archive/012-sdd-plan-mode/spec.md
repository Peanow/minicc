# 012-sdd-plan-mode — Optional Plan Mode

- Change type: behavior
- Created: 2026-08-08

## Why

The current SDD workflow requires a separate planning operation and a built-in
ask-user confirmation step. That step is only available when the user is in
plan mode, so the workflow cannot be followed consistently when the user
chooses another mode. Plan mode itself already provides the useful planning
surface and should remain a user choice.

## Goals

- Make plan mode optional and user-controlled.
- Remove the separate planning operation and its pre-implementation
  confirmation gate from the active SDD workflow.
- Preserve the explicit archive and commit handoff gates.

## Non-goals

- Change `scripts/spec.py` commands or their non-interactive interfaces.
- Remove the SDD specification, task, checklist, preflight, or archive
  requirements.
- Change application permissions or runtime behavior.

## Requirements

### R1: Plan mode is optional

The active SDD documentation states that the user decides whether to use plan
mode. When plan mode is selected, it can capture planning evidence before
implementation; when it is not selected, implementation follows the normal SDD
documents without an additional pre-implementation confirmation step.

### R2: Handoff gates remain explicit

The active SDD documentation continues to require explicit user confirmation
before archiving a `DONE` change and before staging and committing an archived
change after commit preflight. `git push` remains implicit-free.

### R3: Script compatibility is preserved

The existing `new`, `status`, `approve`, `check`, `preflight`, and `archive`
commands retain their current non-interactive interfaces and behavior.

## Acceptance scenarios

### AC1: Optional plan mode is documented

- Requirements: R1
- Given: the active SDD workflow documentation is read
- When: a user chooses whether to use plan mode
- Then: both the optional plan-mode path and the direct normal-SDD path are
  documented, without a separate pre-implementation confirmation operation

### AC2: Handoff gates remain documented

- Requirements: R2
- Given: a change reaches `DONE` or archived commit-preflight readiness
- When: the AI follows the documented handoff
- Then: archive and commit still require separate explicit confirmations

### AC3: Existing commands remain compatible

- Requirements: R3
- Given: an isolated repository with a valid change
- When: its existing lifecycle commands are run
- Then: they retain their current status, validation, preflight, and archive
  behavior without an added interactive prompt

## Compatibility and migration

This is a documentation and AI-workflow protocol change. Existing scripts and
CI callers continue to use the same commands and flags. Existing archived
changes retain their historical descriptions.

## Trace contract

- AC1: `tests/test_spec_workflow.py::test_sdd_workflow_documents_optional_plan_mode_and_human_gates`
  asserts optional plan mode and the absence of the removed planning gate in
  active workflow documents.
- AC2: The same test asserts the archive and commit confirmation wording and
  the no-implicit-push boundary.
- AC3: `tests/test_spec_workflow.py::test_lifecycle_and_archive` and the
  existing preflight tests assert unchanged script lifecycle behavior.

## Risks and rollback

The main risk is that users may skip useful planning details when they do not
choose plan mode. The SDD documents and strict validation still require formal
requirements, tasks, acceptance evidence, and capability updates. Rollback is
to restore the prior active workflow wording; no script or runtime migration
is needed.

## Capability impact

- Update `specs/capabilities/sdd-workflow.md` before archive.
