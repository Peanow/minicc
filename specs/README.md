# Lightweight SDD workflow

CoreCoder uses a small, repository-local specification-driven development
workflow. Markdown is the source of truth; `scripts/spec.py` only creates,
checks, approves, and archives those documents.

Use a change specification for user-visible behavior, public APIs, Trace
schemas, permissions, concurrency, tools, context, memory, sessions, and
Terminal behavior. Typo fixes, documentation-only edits, and test-data-only
changes may skip it when they do not alter a contract.

## Documents and traceability

Every change owns three files:

- `spec.md` explains why the change exists and defines `R*` requirements and
  `AC*` Given/When/Then acceptance scenarios.
- `tasks.md` contains `T*` implementation tasks. Every task references at
  least one requirement and acceptance scenario.
- `checklist.md` records approval and verification evidence. Every acceptance
  scenario has a pytest node and a Trace assertion.

The required chain is:

```text
Requirement -> Acceptance Scenario -> Task -> pytest node -> Trace assertion
```

Current, accepted behavior belongs in `capabilities/`. A completed delta is
archived only after its capability document has been updated.

## Commands

Run commands from any directory inside this repository:

```bash
python scripts/spec.py new terminal-input
python scripts/spec.py status 001-terminal-input
python scripts/spec.py approve 001-terminal-input
python scripts/spec.py check 001-terminal-input --strict
python scripts/spec.py archive 001-terminal-input
```

Omit the change from `status` or `check` to process every active and archived
change. `--root PATH` can precede the command for tooling and isolated tests.

`new` assigns the next numeric prefix across active and archived changes.
Before `approve`, replace every `TBD` and `NEEDS CLARIFICATION`. Approval also
runs strict structural validation.

## Inferred states

No separate status field is edited:

- `DRAFT`: the specification approval checkbox is clear.
- `READY`: approved, with no completed implementation task.
- `IMPLEMENTING`: some but not all implementation tasks are complete.
- `VERIFYING`: all tasks are complete, but checklist evidence remains.
- `DONE`: every task and checklist item is checked.
- `ARCHIVED`: a valid `DONE` change was moved under `changes/archive/`.

`check --strict` additionally requires complete R/AC task coverage, one pytest
and Trace evidence entry per AC, and capability evidence. Evidence may remain
unchecked while work is in progress, but it must be concrete after approval.

## Review policy

Changes `000` through `002` are the workflow adoption window and may be wired
to CI as warnings. Starting with change `003`, CI should run:

```bash
python scripts/spec.py check --strict
```

`000-sdd-bootstrap` is archived as the bootstrapping exception: it documents
the workflow that was needed to validate itself.
