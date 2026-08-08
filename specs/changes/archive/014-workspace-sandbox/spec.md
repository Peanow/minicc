# 014-workspace-sandbox — Workspace Sandbox

- Change type: behavior
- Created: 2026-08-08

## Why

Application permission checks currently decide whether a Bash call may run, but
the subprocess itself can still read, write, or connect outside the Agent
workspace.  `cwd` is also mutable state and must not become an authority
boundary.

## Goals

- Contain Agent-owned Bash subprocesses to the physical workspace root on
  macOS, with network denied by default.
- Preserve the existing permission modes, approval policy, command timeout,
  output, exit-code, and dangerous-command contracts.
- Make sandbox configuration, backend availability, and execution outcomes
  observable without recording command text or secrets.

## Non-goals

- Contain direct Python or subprocess calls made outside the Agent runtime.
- Replace application permission approvals or make `full-access` safe by
  default.
- Provide a silent unsandboxed fallback when the OS backend is unavailable.

## Requirements

### R1: Agent Bash execution is workspace-contained

An Agent-created Bash tool executes with the Agent startup workspace as its
physical filesystem boundary.  Its logical `cwd` selects only the starting
directory.  Parent traversal, absolute paths, and symlinks resolving outside
the workspace cannot read or write outside it.

### R2: Permission modes retain their security meaning

`workspace-write` permits workspace reads and writes, `read-only` permits
workspace reads but not writes, and `full-access` explicitly bypasses the OS
sandbox while retaining the existing dangerous-command check.

### R3: Network is denied unless explicitly configured

Bash OS sandbox network access defaults to `deny`.  `allow` can be selected by
CLI, environment, or `Config`, but does not bypass application policy approval.

### R4: Missing sandbox backends fail closed

When a sandbox-required Bash execution has no usable OS backend, it returns a
structured error and does not run the command.

### R5: Configuration and decisions are observable and non-sensitive

`CORECODER_SANDBOX_NETWORK` and `--sandbox-network allow|deny` feed the same
runtime configuration.  `sandbox_decision` Trace events record backend,
workspace, permission mode, network setting, lifecycle stage, and result, but
never command content, secrets, or arbitrary tool parameters.

## Acceptance scenarios

### AC1: Workspace access succeeds

- Requirements: R1, R2
- Given: an Agent Bash tool has a writable workspace and a workspace file
- When: it reads and writes using a relative path
- Then: the command succeeds and the file changes inside the workspace.

### AC2: Workspace escapes are blocked

- Requirements: R1
- Given: a workspace, an outside file, and a workspace symlink to that file
- When: Bash uses `../`, an absolute outside path, or the symlink
- Then: the OS sandbox blocks the access and the outside file is unchanged.

### AC3: Network defaults to deny

- Requirements: R3
- Given: a sandboxed Bash tool with default configuration
- When: it attempts a network connection
- Then: the OS sandbox denies the connection.

### AC4: Explicit network allow remains policy-controlled

- Requirements: R3
- Given: `sandbox_network=allow`
- When: a Bash network command is evaluated in workspace-write mode without
  approval
- Then: application policy still denies it; an approved call receives the OS
  network allowance.

### AC5: Read-only and full-access modes are distinct

- Requirements: R2
- Given: the same command under `read-only` and `full-access`
- When: it writes a workspace file
- Then: read-only blocks the write, while full-access may execute subject to
  dangerous-command checks.

### AC6: Backend absence fails closed

- Requirements: R4
- Given: a sandbox-required tool whose OS backend is unavailable
- When: it executes a harmless command
- Then: it returns `SandboxUnavailable` without starting a subprocess.

### AC7: Configuration sources are equivalent

- Requirements: R5
- Given: CLI, environment, and direct `Config` values
- When: the runtime is composed
- Then: the selected network setting reaches the Agent Bash sandbox.

### AC8: Trace decisions are safe

- Requirements: R5
- Given: a sandbox configuration and execution containing secret-like command
  arguments
- When: Trace events are emitted
- Then: `sandbox_decision` contains only the documented safe fields and no
  command, secret, or arbitrary parameter value.

## Compatibility and migration

Existing `BashTool` output and result contracts remain compatible.  Agent
runtime callers gain OS containment by default; direct, unbound legacy tool
instances retain their old behavior because they have no Agent startup
workspace to authorize.  `full-access` remains an explicit opt-out.

## Trace contract

- AC1/AC2: `tests/test_sandbox.py` asserts containment, read/write behavior,
  and escape denial through a fakeable sandbox backend.
- AC3/AC4: `tests/test_sandbox.py` and `tests/test_policy.py` assert network
  defaults and the independent policy approval boundary.
- AC5: `tests/test_sandbox.py` asserts mode-specific profile decisions.
- AC6: `tests/test_sandbox.py` asserts no subprocess call on backend absence.
- AC7: `tests/test_config.py` and `tests/test_commandline.py` assert env/CLI
  propagation.
- AC8: `tests/test_sandbox.py` asserts safe `sandbox_decision` Trace payloads.

## Risks and rollback

The primary risk is a platform-specific profile that is too permissive or
prevents required runtimes from starting.  The backend is isolated behind
`SandboxExecutor`, so profile rules can be tightened or rolled back without
changing policy or tool result APIs.  Unsupported platforms fail closed for
sandbox-required commands.

## Capability impact

- Update `specs/capabilities/runtime.md` before archive.
