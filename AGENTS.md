# CoreCoder Development Guide

## Project

This repository is an experimental fork of upstream CoreCoder. Keep the
runtime small and readable while making model, context, memory, skill, policy,
and tracing behavior measurable.

## Commands

- Install: `uv pip install --python .venv/bin/python -e '.[dev]'`
- Test: `.venv/bin/python -m pytest -q`
- Compile: `.venv/bin/python -m compileall -q corecoder tests`
- Smoke CLI: `.venv/bin/python -m corecoder --help`

## Engineering rules

- Never commit `.env`, API keys, generated traces, sessions, or model files.
- Runtime state must be owned by an Agent instance, not module globals.
- Every new runtime behavior needs unit tests and an observable Trace event.
- Only tools explicitly marked `parallel_safe` may execute concurrently.
- Application permission checks are not an OS sandbox; document that boundary.
- Preserve compatibility helpers when replacing a public API.

## Specification-driven changes

- `AGENTS.md` is the only project-level AI workflow entry point; do not add a
  project `.agents/skills/` directory or depend on a project skill file.
- Before implementing a change, run `python scripts/spec.py status`. The user
  decides whether to work in plan mode; plan mode is optional. When plan mode
  is selected for public behavior, APIs, Trace schemas, permissions,
  concurrency, tools, context, memory, sessions, or Terminal UX, record
  current-state evidence, the goal, scope, proposed approach, affected files,
  test strategy, risks, and unresolved questions before implementation.
- If the user does not select plan mode, proceed with the same SDD documents
  and verification requirements without an additional planning confirmation
  step. If the user requests adjustments while planning, incorporate them
  before implementation. Spelling, documentation-only, and test-data-only
  edits may still skip a change specification when they do not alter a
  contract.
- Keep `spec.md`, `tasks.md`, and `checklist.md` traceable as
  `Requirement -> Acceptance Scenario -> Task -> pytest -> Trace assertion`.
- During implementation, keep tasks and evidence current. Every new runtime
  behavior needs pytest coverage and an observable Trace assertion.
- Before declaring a change done, run
  `python scripts/spec.py preflight CHANGE`, which performs strict validation
  and reports the inferred state. Update the affected
  `specs/capabilities/` document before archiving the change.

## Done means

Complete the change checklist and run the tests, compile check,
`python scripts/spec.py check --strict`, `git diff --check`, and a staged-diff
review for credentials and generated runtime state. When
`python scripts/spec.py preflight CHANGE` reports `DONE`, show the user the
validation evidence and request explicit confirmation before running
`python scripts/spec.py archive CHANGE`; do not archive autonomously. After
the user confirms and the change is archived, run
`python scripts/spec.py preflight CHANGE --for-commit`. When it is
strict-clean, show the archived status, intended files, diff summary, and
verification evidence. An explicit user request to commit authorizes staging
the intended files and running `git commit`; do not ask for a redundant
confirmation. A commit flow never includes `git push`.

Do not run `git commit`, `git commit --amend`, or `git push` without explicit
user authorization. Do not delete or overwrite important data without
explicit authorization. Application permission checks are not an OS sandbox.
