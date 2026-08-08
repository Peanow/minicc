# 004-commandline-contract — Headless command contract

- Change type: behavior
- Status: archived

## Why

The former top-level flags mixed interactive and batch execution and produced
unstable output for shell pipelines.

## Goals

- Provide the new command tree, prompt-source exclusivity, output formats, and
  exit-code contract.

## Non-goals

- Implement the interactive renderer itself.

## Requirements

### R1: Make headless input and output deterministic

`run` accepts exactly one prompt source and supports pretty/plain/JSONL output
with a final `run_finished` record in JSONL mode.

### R2: Remove ambiguous legacy entry points

Removed top-level replay/eval and credential flags are rejected by the parser.

## Acceptance scenarios

### AC1: Reject multiple prompt sources

- Requirements: R1
- Given: a prompt argument and piped input are both present
- When: the run command resolves input
- Then: it exits with a parameter error instead of choosing one source

### AC2: Parse the command tree

- Requirements: R2
- Given: a removed legacy entry point is supplied
- When: the CLI parser runs
- Then: parsing exits with code 2

## Compatibility and migration

Library replay/evaluation functions remain importable; only the public CLI tree
changes.

## Trace contract

- AC1 pytest: `tests/test_commandline.py::test_prompt_resolution_rejects_multiple_sources`
- AC1 trace: invalid input emits no run trace and returns exit code 2.
- AC2 pytest: `tests/test_commandline.py::test_removed_cli_entrypoints_are_rejected`
- AC2 trace: parser rejection is a configuration/argument error, not a run event.

## Risks and rollback

Restore the previous parser facade while retaining the new handlers behind an
explicit command prefix.

## Capability impact

- Update `specs/capabilities/terminal.md`.
