# Terminal capabilities (0.4)

- One long-lived `prompt_toolkit.PromptSession` handles multiline input,
  history, completion, editor integration, Ctrl+C/Ctrl+D, and literal `//`
  slash escaping.
- The command registry owns help, aliases, argument errors, and completion for
  the documented slash commands.
- Rich renders model streaming, tool status, approval cards, and structured
  diffs; plain and JSONL adapters keep stdout/stderr deterministic.
- Interactive approval uses a prompt-toolkit selector with numbered choices,
  arrow-key navigation, a deny-by-default selection, and a details loop.
  Approval outcomes are recorded as `approval_decided` Trace events without
  copying tool arguments.
- The toolbar only reads cached state; optional Phoenix health checks occur
  before a prompt or through `/observe`.
