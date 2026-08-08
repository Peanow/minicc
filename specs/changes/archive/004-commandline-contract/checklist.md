# 004-commandline-contract checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: `tests/test_commandline.py::test_prompt_resolution_rejects_multiple_sources`
- [x] AC1 trace: input errors return before run-start emission.
- [x] AC2 pytest: `tests/test_commandline.py::test_removed_cli_entrypoints_are_rejected`
- [x] AC2 trace: rejected CLI arguments do not create a runtime trace.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/terminal.md`
- [x] Ready to archive.
