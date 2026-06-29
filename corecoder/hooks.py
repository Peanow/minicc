"""Hook system - run user-defined commands at lifecycle events.

A minimal hook mechanism inspired by Claude Code's 27-event hook system,
distilled to 4 core events:

    SessionStart  — agent created, before first user message
    PreToolUse   — before a tool executes (can block or modify args)
    PostToolUse  — after a tool executes (can modify output)
    Stop          — before the agent returns its final response

Hooks are configured via ``.corecoder/hooks.json`` in the project root.
Each hook is a shell command that receives context via environment
variables and communicates back through exit codes and optional JSON
on stdout.

Exit code semantics (matching Claude Code's protocol):

    0  → pass (stdout may contain JSON modification instructions)
    2  → block (tool execution is prevented; message fed back to LLM)
    other → non-blocking error (stderr shown to user, execution continues)

The discovery strategy mirrors ``skills.py``: walk from *cwd* upward
to home looking for ``.corecoder/hooks.json``.  The closest match wins.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path


# ---------------------------------------------------------------------------
# Event enum
# ---------------------------------------------------------------------------

class HookEvent(Enum):
    SessionStart = "SessionStart"
    PreToolUse = "PreToolUse"
    PostToolUse = "PostToolUse"
    Stop = "Stop"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HookMatcher:
    """A single hook configuration entry."""
    matcher: str = "*"          # tool name match: "*" | "Bash" | "Write|Edit"
    command: str = ""           # shell command to execute
    timeout: int = 60           # seconds before the hook is killed


@dataclass
class HookResult:
    """Result from running all hooks for a single event."""
    blocked: bool = False               # any hook returned exit code 2
    message: str = ""                   # aggregated stdout / error text
    updated_input: dict | None = None   # PreToolUse: modified tool arguments
    updated_output: str | None = None   # PostToolUse: modified tool output


@dataclass
class HookConfig:
    """Loaded hook configuration, keyed by event."""
    hooks: dict[HookEvent, list[HookMatcher]] = field(default_factory=dict)
    source: Path | None = None          # where the config was loaded from

    def run(
        self,
        event: HookEvent,
        tool_name: str = "",
        tool_input: dict | None = None,
        tool_output: str = "",
        reason: str = "",
    ) -> HookResult:
        """Run all hooks registered for *event*.

        Returns an aggregated HookResult.  Hooks are executed serially
        (simple-first).  If any hook blocks (exit 2), remaining hooks
        are skipped and the block is returned immediately.
        """
        matchers = self.hooks.get(event, [])
        if not matchers:
            return HookResult()

        # filter by matcher
        matched = [h for h in matchers if _matches(h.matcher, tool_name)]
        if not matched:
            return HookResult()

        # build env vars for context injection
        env = _build_env(event, tool_name, tool_input, tool_output, reason)

        result = HookResult()
        for hook in matched:
            hook_result = _exec_hook(hook, env)
            # aggregate
            if hook_result.blocked:
                result.blocked = True
                result.message = hook_result.message
                return result  # stop on first block
            if hook_result.updated_input is not None:
                result.updated_input = hook_result.updated_input
            if hook_result.updated_output is not None:
                result.updated_output = hook_result.updated_output
            if hook_result.message and not result.message:
                result.message = hook_result.message

        return result


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def _matches(pattern: str, tool_name: str) -> bool:
    """Check if *tool_name* matches *pattern*.

    Patterns:
        "*"    → matches everything
        "Bash" → exact match
        "Write|Edit" → matches any pipe-separated option
    """
    if pattern == "*":
        return True
    options = [p.strip() for p in pattern.split("|")]
    return tool_name in options


# ---------------------------------------------------------------------------
# Environment variable injection
# ---------------------------------------------------------------------------

def _build_env(
    event: HookEvent,
    tool_name: str,
    tool_input: dict | None,
    tool_output: str,
    reason: str,
) -> dict[str, str]:
    """Build environment variables for hook subprocess."""
    env = dict(os.environ)
    if event == HookEvent.SessionStart:
        env["CORECODER_HOOK_EVENT"] = "SessionStart"
    elif event == HookEvent.PreToolUse:
        env["CORECODER_HOOK_EVENT"] = "PreToolUse"
        env["CORECODER_TOOL_NAME"] = tool_name
        env["CORECODER_TOOL_INPUT"] = json.dumps(tool_input or {})
    elif event == HookEvent.PostToolUse:
        env["CORECODER_HOOK_EVENT"] = "PostToolUse"
        env["CORECODER_TOOL_NAME"] = tool_name
        env["CORECODER_TOOL_INPUT"] = json.dumps(tool_input or {})
        env["CORECODER_TOOL_OUTPUT"] = tool_output
    elif event == HookEvent.Stop:
        env["CORECODER_HOOK_EVENT"] = "Stop"
        env["CORECODER_STOP_REASON"] = reason
    return env


# ---------------------------------------------------------------------------
# Hook execution
# ---------------------------------------------------------------------------

def _exec_hook(hook: HookMatcher, env: dict[str, str]) -> HookResult:
    """Execute a single hook command and return its result."""
    try:
        proc = subprocess.run(
            hook.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=hook.timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        # timeout → non-blocking, treat as pass
        return HookResult(message=f"Hook timed out after {hook.timeout}s")
    except Exception as e:
        return HookResult(message=f"Hook error: {e}")

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    # exit code 2 → block
    if proc.returncode == 2:
        msg = stdout or stderr or "Blocked by hook (exit 2)"
        return HookResult(blocked=True, message=msg)

    # non-zero (not 2) → non-blocking error, continue
    if proc.returncode != 0:
        err_msg = stderr or f"Hook exited with code {proc.returncode}"
        return HookResult(message=err_msg)

    # exit 0 → pass, try to parse JSON output
    result = HookResult()
    if stdout:
        parsed = _parse_json_output(stdout)
        if parsed is not None:
            result.updated_input = parsed.get("updated_input")
            result.updated_output = parsed.get("updated_output")
            if parsed.get("message"):
                result.message = parsed["message"]
        else:
            result.message = stdout
    return result


def _parse_json_output(stdout: str) -> dict | None:
    """Try to parse hook stdout as JSON.  Return None on failure."""
    try:
        data = json.loads(stdout)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Loading from .corecoder/hooks.json
# ---------------------------------------------------------------------------

_HOOKS_FILE = "hooks.json"
_CORECODER_DIR = ".corecoder"


def _find_hooks_file(cwd: Path) -> Path | None:
    """Walk from *cwd* upward to home, return the first ``.corecoder/hooks.json``."""
    home = Path.home()
    cur = cwd.resolve()
    while True:
        candidate = cur / _CORECODER_DIR / _HOOKS_FILE
        if candidate.is_file():
            return candidate
        if cur == home or cur == cur.parent:
            break
        cur = cur.parent
    return None


def load_hooks(cwd: str | Path | None = None) -> HookConfig:
    """Load hooks from ``.corecoder/hooks.json``.

    Returns an empty HookConfig when no config file exists.
    Malformed files are skipped with a warning printed to stderr.
    """
    start = Path(cwd) if cwd else Path.cwd()
    path = _find_hooks_file(start)
    if path is None:
        return HookConfig()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[hooks] Warning: failed to load {path}: {e}", file=sys.stderr)
        return HookConfig(source=path)

    if not isinstance(raw, dict):
        print(f"[hooks] Warning: {path} is not a JSON object, skipping", file=sys.stderr)
        return HookConfig(source=path)

    hooks: dict[HookEvent, list[HookMatcher]] = {}
    for key, entries in raw.items():
        try:
            event = HookEvent(key)
        except ValueError:
            # unknown event name, skip silently
            continue
        if not isinstance(entries, list):
            continue
        matchers: list[HookMatcher] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            matchers.append(HookMatcher(
                matcher=entry.get("matcher", "*"),
                command=entry.get("command", ""),
                timeout=int(entry.get("timeout", 60)),
            ))
        hooks[event] = matchers

    return HookConfig(hooks=hooks, source=path)
