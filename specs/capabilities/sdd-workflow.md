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

`preflight CHANGE` is a read-only strict validation and state report.
`preflight CHANGE --for-commit` additionally requires `ARCHIVED`; an active
`DONE` change must be archived first. Preflight never stages, commits, pushes,
or archives files.

Introduced by [000-sdd-bootstrap](../changes/archive/000-sdd-bootstrap/spec.md)
and refined by
[009-sdd-workflow-guardrails](../changes/archive/009-sdd-workflow-guardrails/spec.md).
