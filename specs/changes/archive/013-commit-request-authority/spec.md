# 013-commit-request-authority — Commit Request Authority

- Change type: behavior
- Created: 2026-08-08

## Why

The active SDD instructions currently require a second confirmation after the
user has already explicitly requested a commit. This creates a redundant
interaction and incorrectly treats a direct user command as insufficient
authorization.

## Goals

- Treat an explicit user request to commit as sufficient commit authorization
  after the required archived preflight passes.
- Keep archive confirmation separate when archiving has not been explicitly
  requested.
- Preserve the no-implicit-push boundary and existing script interfaces.

## Non-goals

- Change `scripts/spec.py` commands or their non-interactive interfaces.
- Remove the archive confirmation gate.
- Add automatic `git push` behavior.

## Requirements

### R1: An explicit commit request authorizes commit

After `preflight CHANGE --for-commit` passes, an explicit user request to
commit authorizes staging the intended files and running `git commit` without a
second confirmation prompt.

### R2: Archive confirmation remains separate

When a `DONE` change has not been explicitly requested for archive, the AI
continues to present evidence and request confirmation before invoking
`spec.py archive`.

### R3: Script compatibility is preserved

The existing lifecycle commands retain their current non-interactive
interfaces, and `git push` remains outside the commit flow.

## Acceptance scenarios

### AC1: Commit does not ask twice

- Requirements: R1
- Given: an archived change passes `preflight CHANGE --for-commit`
- When: the user explicitly requests a commit
- Then: the AI may stage and commit directly without another confirmation

### AC2: Archive remains a distinct gate

- Requirements: R2
- Given: an active `DONE` change has not been explicitly requested for archive
- When: the AI reaches the archive handoff
- Then: it presents evidence and requests archive confirmation first

### AC3: Push and script behavior remain unchanged

- Requirements: R3
- Given: the repository workflow and lifecycle commands are used
- When: validation and commit handoff occur
- Then: `git push` is not implicit and script commands remain non-interactive

## Compatibility and migration

This changes only the AI collaboration protocol. Existing scripts, flags, and
archived change records remain compatible.

## Trace contract

- AC1: `tests/test_spec_workflow.py::test_sdd_workflow_documents_optional_plan_mode_and_human_gates`
  asserts explicit commit-request authority and the absence of the redundant
  confirmation wording.
- AC2: The same test asserts the archive confirmation wording remains.
- AC3: The same test asserts the no-implicit-push boundary; existing lifecycle
  tests assert unchanged script behavior.

## Risks and rollback

The main risk is committing when a user message is ambiguous. Only an explicit
commit request after archived preflight qualifies; ordinary discussion does
not. Rollback is to restore the prior commit-confirmation wording.

## Capability impact

- Update `specs/capabilities/sdd-workflow.md` before archive.
