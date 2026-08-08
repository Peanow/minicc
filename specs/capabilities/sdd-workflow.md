# Lightweight SDD workflow

`AGENTS.md` is the single project-level AI workflow entry point. CoreCoder
stores proposed behavioral changes under `specs/changes/`; each change contains
`spec.md`, `tasks.md`, and `checklist.md`, with traceability from requirements
through acceptance scenarios and verification evidence. No project-level skill
file is required.

`scripts/spec.py` provides the supported workflow commands: `new`, `status`,
`approve`, `check`, `preflight`, and `archive`. Status is inferred from
approval and checkbox state. Strict validation checks ID integrity, R-to-AC
coverage, Given/When/Then scenarios, task mappings, pytest evidence, Trace
evidence, and capability evidence. A change can be archived only from `DONE`
and only when the cited capability file exists.

For contract changes, the AI workflow begins with a dialogue-based Explore.
The initial plan includes current-state evidence, goal, scope, approach,
affected files, test strategy, risks, and unresolved questions, and requires
the built-in ask-user confirmation (`确认并继续`, `需要调整计划`, or
`暂不实施`) before a change is created or implementation starts. The
confirmed plan is transferred into the formal change documents; no separate
Explore file or CLI command is part of the workflow.

The AI must request confirmation before archiving a `DONE` change, after
presenting strict preflight and verification evidence. After archive,
`preflight CHANGE --for-commit` must pass before the AI presents the proposed
files and requests commit confirmation. Commit confirmation is separate from
archive confirmation, and `git push` is never implicit. These gates constrain
the AI workflow only; `scripts/spec.py` retains its existing non-interactive
commands for scripts and CI.

`preflight CHANGE` is a read-only strict validation and state report.
`preflight CHANGE --for-commit` additionally requires `ARCHIVED`; an active
`DONE` change must be archived first. Preflight never stages, commits, pushes,
or archives files.

Introduced by [000-sdd-bootstrap](../changes/archive/000-sdd-bootstrap/spec.md)
and refined by
[009-sdd-workflow-guardrails](../changes/archive/009-sdd-workflow-guardrails/spec.md)
and [011-sdd-human-gates](../changes/archive/011-sdd-human-gates/spec.md).
