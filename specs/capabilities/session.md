# Session capabilities (0.4)

- `AppPaths` scopes sessions, history, memory, and traces to a normalized Git
  root and an injectable application directory.
- Session schema v2 checkpoints are atomic, private (`0600` where supported),
  project-isolated, and never restore permission mode or credentials.
- Interactive turns persist complete successful checkpoints. Non-interactive
  runs are ephemeral unless `--save-session` is supplied.
- Interactive resume restores the checkpointed messages and displays the full
  persisted conversation in terminal scrollback; `/resume [ID]` selects the
  latest or a named project-local session.
