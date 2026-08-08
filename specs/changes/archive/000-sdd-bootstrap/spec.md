# 000-sdd-bootstrap — Lightweight SDD bootstrap

- Change type: tooling
- Created: 2026-08-08

## Why

Behavioral changes previously lacked a small, enforceable path from intent to
implementation evidence, which made review and completion ambiguous.

## Goals

- Establish a Markdown-first change workflow with no runtime dependencies.
- Make requirements, tasks, tests, and observable evidence traceable.
- Prevent incomplete or unrecorded changes from being archived.

## Non-goals

- Install Spec Kit, OpenSpec, or another external framework.
- Backfill specifications for every historical feature.
- add a database or service for workflow state.

## Requirements

### R1: Create and inspect change workspaces

The repository workflow creates monotonically numbered changes from templates
and reports a lifecycle state derived from their Markdown content.

### R2: Validate traceability before approval

The workflow rejects duplicate or unknown R/AC/T IDs, uncovered requirements,
incomplete Given/When/Then scenarios, and unresolved approved placeholders.

### R3: Archive only evidenced completed changes

Strict validation maps requirements and scenarios to tasks, pytest nodes, and
Trace assertions; archive additionally requires completed checkboxes and an
existing capability document.

## Acceptance scenarios

### AC1: Create a draft and infer its lifecycle

- Requirements: R1
- Given: the repository contains the three SDD templates
- When: a maintainer creates a change and progressively completes its markers
- Then: the workflow reports DRAFT, READY, IMPLEMENTING, VERIFYING, and DONE
  from document content without a separate status database

### AC2: Reject an invalid approved specification

- Requirements: R2
- Given: a change contains an invalid reference, duplicate ID, missing scenario
  step, or unresolved placeholder
- When: a maintainer checks or approves the change
- Then: the command exits unsuccessfully and identifies each validation error

### AC3: Preserve completed deltas with capability evidence

- Requirements: R3
- Given: all tasks and checklist items are complete and the cited capability
  document exists
- When: a maintainer archives the change
- Then: strict validation passes and the change moves to the archive; an
  incomplete change or missing capability evidence remains active

## Compatibility and migration

The workflow is additive and uses Python 3.10 standard-library APIs only.
Changes 000 through 002 may initially be checked as CI warnings; strict CI is
required from change 003 onward.

## Trace contract

- AC1: subprocess output and exit status expose every workflow state.
- AC2: stderr validation diagnostics expose rejected IDs and placeholders.
- AC3: archive output records the archived change and inferred ARCHIVED state.

The administration script runs outside the CoreCoder Agent runtime, so these
CLI observations replace runtime Trace events for this tooling-only change.

## Risks and rollback

Overly rigid parsing could discourage small changes. The format therefore uses
ordinary Markdown headings and checkboxes and reserves exemptions for docs,
spelling, and test data. Rollback is removal of the script and `specs/` tree;
it does not migrate runtime state.

## Capability impact

- Updated `specs/capabilities/sdd-workflow.md`.
