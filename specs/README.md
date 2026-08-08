# Lightweight SDD workflow

CoreCoder uses a small, repository-local specification-driven development
workflow. `AGENTS.md` is the only project-level AI workflow entry point;
Markdown is the source of truth, and `scripts/spec.py` provides read-only
validation plus the document lifecycle commands. No project-level skill is
required.

Use a change specification for user-visible behavior, public APIs, Trace
schemas, permissions, concurrency, tools, context, memory, sessions, and
Terminal behavior. Typo fixes, documentation-only edits, and test-data-only
changes may skip it when they do not alter a contract.

## Lifecycle and human gates

Plan mode is optional for contract changes and the user decides whether to use
it. When selected, the plan records current-state evidence, the goal, scope,
approach, affected files, test strategy, risks, and unresolved questions, and
the user may adjust it before the change is opened. When plan mode is not
selected, the change can move directly into the normal SDD documents and
implementation flow.

The lifecycle is:

```text
optional plan mode -> write/approve change -> implement and verify
-> user confirms archive -> archive -> strict preflight for commit
-> user requests commit -> commit
```

When `preflight CHANGE` reports `DONE`, the AI must present the change and
verification evidence and wait for archive confirmation before invoking
`spec.py archive`. Once archived and `preflight CHANGE --for-commit` is
strict-clean, it must present the proposed commit contents. An explicit user
request to commit then authorizes staging and invoking `git commit`; no
redundant confirmation is required. `git push` is never implicit. These are AI
workflow gates; the script commands remain available to scripts and CI with
their existing non-interactive interfaces.

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
python scripts/spec.py preflight 001-terminal-input
python scripts/spec.py preflight 001-terminal-input --for-commit
python scripts/spec.py archive 001-terminal-input
```

Omit the change from `status` or `check` to process every active and archived
change. `--root PATH` can precede the command for tooling and isolated tests.

`new` assigns the next numeric prefix across active and archived changes.
Before `approve`, replace every `TBD` and `NEEDS CLARIFICATION`. Approval also
runs strict structural validation.

Run `status` before implementation and run `preflight CHANGE` before declaring
a change done; it performs strict validation and reports the inferred state
without modifying files. `preflight CHANGE --for-commit` additionally requires
the change to be archived. If an active change is `DONE`, request archive
confirmation before using `archive`. Neither preflight mode commits, stages,
pushes, or archives files.

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
