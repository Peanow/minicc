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
- Before implementing a change, run `python scripts/spec.py status` and open or
  update a change under `specs/changes/` for public behavior, APIs, Trace
  schemas, permissions, concurrency, tools, context, memory, sessions, or
  Terminal UX.
- Keep `spec.md`, `tasks.md`, and `checklist.md` traceable as
  `Requirement -> Acceptance Scenario -> Task -> pytest -> Trace assertion`.
- During implementation, keep tasks and evidence current. Every new runtime
  behavior needs pytest coverage and an observable Trace assertion.
- Before declaring a change done, run
  `python scripts/spec.py preflight CHANGE`, which performs strict validation
  and reports the inferred state. Update the affected
  `specs/capabilities/` document before archiving the change.
- Spelling, documentation-only, and test-data-only edits may skip a change when
  they do not alter a contract.

## Done means

Complete the change checklist and run the tests, compile check,
`python scripts/spec.py check --strict`, `git diff --check`, and a staged-diff
review for credentials and generated runtime state. A completed active change
must be archived with `python scripts/spec.py archive` before the commit
handoff; `python scripts/spec.py preflight CHANGE --for-commit` verifies that
the change is archived and strict-clean. If the user explicitly requests a
commit and a change is `DONE` but not archived, archive it first, then stage
the intended files and create one commit.

Do not run `git commit`, `git commit --amend`, or `git push` without explicit
user authorization. Do not delete or overwrite important data without
explicit authorization. Application permission checks are not an OS sandbox.
