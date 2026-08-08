# 011-sdd-human-gates — SDD Human Gates

- Change type: behavior
- Created: 2026-08-08

## Why

The repository workflow currently describes the document lifecycle and exposes
non-interactive commands, but it does not tell an AI when to pause for
clarification or for human approval of high-impact lifecycle transitions.
Adding those protocol gates makes the intended planning and handoff boundaries
explicit without changing the script interfaces.

## Goals

- Require a dialogue-based Explore before contract changes are opened or
  implemented.
- Require explicit archive confirmation after a change is strictly complete.
- Require explicit commit confirmation after archive and commit preflight.
- Keep the protocol readable in the project entry point, workflow README, and
  capability document.

## Non-goals

- Add an `explore.md` document, an `explore` CLI command, or a `handoff`
  command.
- Change the behavior or interface of `scripts/spec.py`.
- Add a runtime approval gate or change the application's permission model.
- Include `git push` in the commit handoff.

## Requirements

### R1: Explore precedes implementation

For a contract-changing request, the AI workflow presents an Explore summary
with current-state evidence, goal, scope, approach, affected files, test
strategy, risks, and unresolved questions, then waits for built-in ask-user
confirmation before creating a change or implementing it. The confirmation
choices are `确认并继续`, `需要调整计划`, and `暂不实施`; requested changes
must be incorporated before proceeding.

### R2: DONE requires archive confirmation

When `python scripts/spec.py preflight CHANGE` reports `DONE`, the AI workflow
shows the validation and verification evidence and asks the user to confirm
archiving. It does not invoke `python scripts/spec.py archive CHANGE` until the
user confirms.

### R3: Commit requires a separate confirmation

After archive, the AI workflow requires a passing
`python scripts/spec.py preflight CHANGE --for-commit`, shows the archived
status, intended files, diff summary, and verification evidence, and asks for
commit confirmation before staging and running `git commit`. The workflow
never implicitly runs `git push`.

### R4: Script compatibility is preserved

The existing `new`, `status`, `approve`, `check`, `preflight`, and `archive`
commands retain their current non-interactive interfaces. The new gates govern
the AI collaboration protocol rather than adding enforcement to the script.

## Acceptance scenarios

### AC1: Explore confirmation is required

- Requirements: R1
- Given: a request that changes a documented project contract
- When: the AI presents the initial Explore summary
- Then: it lists the required planning evidence and waits for one of the three
  ask-user choices before creating a change or implementing it

### AC2: DONE pauses before archive

- Requirements: R2
- Given: `preflight CHANGE` reports `DONE`
- When: the AI reaches the archive handoff
- Then: it presents validation evidence and waits for explicit archive
  confirmation before invoking `spec.py archive`

### AC3: Archive pauses before commit

- Requirements: R3
- Given: the change is `ARCHIVED` and `preflight CHANGE --for-commit` passes
- When: the AI reaches the commit handoff
- Then: it presents the proposed files and verification evidence and waits for
  explicit commit confirmation, with no implicit push

### AC4: Existing script commands remain compatible

- Requirements: R4
- Given: an isolated repository with a valid change
- When: its existing lifecycle commands are run
- Then: they retain their current status, validation, preflight, and archive
  behavior without an added interactive prompt

## Compatibility and migration

This is a documentation and AI-workflow protocol change. Existing scripts and
CI callers continue to use the same commands and flags. The new confirmation
steps apply to AI-led work only; a human or automation invoking a script
directly remains responsible for its own authorization.

## Trace contract

- AC1: `tests/test_spec_workflow.py::test_sdd_workflow_documents_explore_and_human_confirmation_gates`
  asserts the documented Explore gate, confirmation choices, archive/commit
  order, and push boundary.
- AC2: The same test asserts the `DONE` archive confirmation wording and the
  `preflight CHANGE --for-commit` handoff evidence boundary.
- AC3: The same test asserts separate commit confirmation and that push is not
  implicit.
- AC4: `tests/test_spec_workflow.py::test_lifecycle_and_archive` and the
  existing preflight tests assert the unchanged script lifecycle behavior.

## Risks and rollback

The main risk is that a future AI workflow may skip a prose gate. The
entry-point instructions and capability document repeat the lifecycle, while
the workflow test checks for the required protocol terms. Rollback is to
revert the documentation and test change; no script or runtime migration is
needed.

## Capability impact

- Update `specs/capabilities/sdd-workflow.md` before archive.
