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

For contract changes, plan mode is optional and the user decides whether to
use it. When selected, the plan includes current-state evidence, goal, scope,
approach, affected files, test strategy, risks, and unresolved questions, and
can be adjusted before the formal change documents are created. Without plan
mode, the workflow proceeds directly through the formal change documents.

The AI must request confirmation before archiving a `DONE` change, after
presenting strict preflight and verification evidence. After archive,
`preflight CHANGE --for-commit` must pass before the AI presents the proposed
files. An explicit user request to commit authorizes staging and committing
after that preflight; no redundant commit confirmation is required. `git push`
is never implicit. These gates constrain the AI workflow only;
`scripts/spec.py` retains its existing non-interactive commands for scripts and
CI.

`preflight CHANGE` is a read-only strict validation and state report.
`preflight CHANGE --for-commit` additionally requires `ARCHIVED`; an active
`DONE` change must be archived first. Preflight never stages, commits, pushes,
or archives files.

Introduced by [000-sdd-bootstrap](../changes/archive/000-sdd-bootstrap/spec.md)
and refined by
[009-sdd-workflow-guardrails](../changes/archive/009-sdd-workflow-guardrails/spec.md)
and [011-sdd-human-gates](../changes/archive/011-sdd-human-gates/spec.md).
