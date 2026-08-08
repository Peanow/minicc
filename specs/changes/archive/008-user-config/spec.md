# 008-user-config — User Config

- Change type: behavior
- Created: 2026-08-08

## Why

CoreCoder currently discovers only project-level dotenv files, which makes a
developer repeat credentials across projects and risks leaving them in a
repository checkout. A user-level file provides a local fallback while keeping
project and process overrides intact.

## Goals

- Load ``~/.corecoder/.env`` as an optional user-level configuration source.
- Preserve the existing project/parent ``.env`` lookup and make its values
  override user-level values without overriding process environment variables.
- Make startup configuration provenance observable without exposing secrets.

## Non-goals

- Do not change provider selection, model defaults, or the application
  permission boundary.
- Do not automatically add a credential file to the repository or emit its
  contents in logs, errors, or Trace.

## Requirements

### R1: Apply configuration precedence

At startup, process environment variables take precedence over project/parent
``.env`` values, which take precedence over ``~/.corecoder/.env`` values, with
existing defaults used when no source supplies a value. Missing, empty, or
unreadable user files are optional and do not make startup fail.

### R2: Provide safe startup provenance

Runtime initialization emits one ``config_loaded`` Trace event containing only
non-sensitive source metadata and whether an API key is configured.

### R3: Initialize a private user configuration file

The local configuration initializer copies all source assignments on first
creation, supplements only missing assignments when the target exists, and
creates/tightens the target to mode ``0600``.

## Acceptance scenarios

### AC1: Resolve user, project, and process configuration

- Requirements: R1
- Given: user and project dotenv files define overlapping settings
- When: ``Config.from_env`` loads configuration with a process override
- Then: the process value wins, the project value wins over the user value,
  and a user-only API key remains available

### AC2: Tolerate an absent user file

- Requirements: R1
- Given: no ``~/.corecoder/.env`` exists and a project ``.env`` exists
- When: configuration is loaded
- Then: project values and normal defaults are preserved without an error

### AC3: Record safe configuration provenance

- Requirements: R2
- Given: a user-level API key configures runtime initialization
- When: the runtime is assembled with JSONL Trace enabled
- Then: Trace contains ``config_loaded`` with ``api_key_source=user_env`` and
  the API key value is absent

### AC4: Create a private user file without overwriting settings

- Requirements: R3
- Given: a source dotenv file and either a missing or partially configured
  target
- When: the local initializer is called
- Then: the new file is ``0600`` and an existing setting is preserved while
  missing source assignments are added

## Compatibility and migration

Existing project and process configuration remains compatible. The new user
file is opt-in and can be removed without changing prior behavior. Existing
public ``Config`` construction remains valid; only additional non-sensitive
metadata fields and the ``initialize_user_env`` helper are provided.

## Trace contract

- AC1: ``Config`` precedence fields and ``api_key_source`` are asserted by the
  configuration tests.
- AC2: the missing-user-file test asserts project values and defaults.
- AC3: ``config_loaded`` is asserted in JSONL Trace and the secret is searched
  for in the complete trace text.
- AC4: initializer tests assert content preservation and mode ``0600``.

## Risks and rollback

The main risk is surprising environment persistence because dotenv loading
populates the process environment; this is the existing behavior and
``override=False`` preserves it. Rollback is a revert of the config/runtime
changes and removal of the user file; no repository credential file is needed.

## Capability impact

- Update ``specs/capabilities/runtime.md`` before archive.
