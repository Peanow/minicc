# Lightweight SDD workflow

CoreCoder stores proposed behavioral changes under `specs/changes/`. Each
change contains `spec.md`, `tasks.md`, and `checklist.md`, with traceability
from requirements through acceptance scenarios and verification evidence.

`scripts/spec.py` provides the supported workflow commands: `new`, `status`,
`approve`, `check`, and `archive`. Status is inferred from approval and
checkbox state. Strict validation checks ID integrity, R-to-AC coverage,
Given/When/Then scenarios, task mappings, pytest evidence, Trace evidence, and
capability evidence. A change can be archived only from `DONE` and only when
the cited capability file exists.

Introduced by [000-sdd-bootstrap](../changes/archive/000-sdd-bootstrap/spec.md).
