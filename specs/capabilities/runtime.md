# Runtime capabilities (0.4)

- `Agent.run(prompt, observer=...)` is the single task entry point.
- Each run emits the schema-v2 lifecycle events and returns task-local token,
  cost, changed-file, status, error, and trace data.
- `WorkspaceState` is shared by policy, prompt construction, Bash, and file
  tools; application permissions are not an operating-system sandbox.
- Tools declare effects and return `ToolResult`; undeclared effects require an
  interactive approval and are denied headlessly.
- Configuration loads optional `~/.corecoder/.env` before the existing
  project/parent `.env` fallback, while process environment variables remain
  authoritative. Runtime startup emits a redacted `config_loaded` Trace event
  with source metadata only; application permission checks are not an OS
  sandbox.
