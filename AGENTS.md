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

- Open a change under `specs/changes/` for public behavior, APIs, Trace schemas,
  permissions, concurrency, tools, context, memory, sessions, or Terminal UX.
- Keep `spec.md`, `tasks.md`, and `checklist.md` traceable as
  `Requirement -> Acceptance Scenario -> Task -> pytest -> Trace assertion`.
- Run `python scripts/spec.py check --strict` before declaring a change done.
- Update the affected `specs/capabilities/` document before archiving a change.
- Spelling, documentation-only, and test-data-only edits may skip a change when
  they do not alter a contract.

## Done means

Run the tests, compile check, `git diff --check`, and review the staged diff
for credentials before committing. For specified changes, also complete the
change checklist and archive only through `python scripts/spec.py archive`.
