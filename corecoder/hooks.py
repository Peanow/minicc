"""Hook system - run user-defined commands at lifecycle events.

A minimal hook mechanism inspired by Claude Code's 27-event hook system,
distilled to 6 core events:

    SessionStart  — agent created, before first user message
    PreToolUse   — before a tool executes (can block or modify args)
    PostToolUse  — after a tool executes (can modify output)
    Stop          — before the agent returns its final response
    MemorySave   — compatibility event for explicit host integrations
    MemoryInject — compatibility event for explicit host integrations

The default Agent lifecycle does not dispatch MemorySave or MemoryInject.
Hosts that need either behavior may still register callbacks or invoke the
hook configuration directly.

Hooks come in two flavors:

    **Shell hooks** — configured via ``.corecoder/hooks.json``, run
    subprocess commands with context injected via environment variables.

    **Callback hooks** — registered programmatically via
    ``register_callback()``, run Python functions with direct access
    to agent state.  Used for memory management where shell hooks
    cannot access in-process data (conversation messages, agent state).

Shell hook exit code semantics (matching Claude Code's protocol):

    0  → pass (stdout may contain JSON modification instructions)
    2  → block (tool execution is prevented; message fed back to LLM)
    other → non-blocking error (stderr shown to user, execution continues)

Callback hooks are always non-blocking — they return data for the
caller to use but cannot prevent the triggering action.

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
from typing import Callable, Any


# ---------------------------------------------------------------------------
# Event enum
# ---------------------------------------------------------------------------

class HookEvent(Enum):
    SessionStart = "SessionStart"
    PreToolUse = "PreToolUse"
    PostToolUse = "PostToolUse"
    Stop = "Stop"
    MemorySave = "MemorySave"
    MemoryInject = "MemoryInject"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HookMatcher:
    """A single shell hook configuration entry."""
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
    data: Any = None                    # callback hook return value


@dataclass
class _CallbackEntry:
    """A Python callback registered for a hook event."""
    callback: Callable
    name: str = ""


@dataclass
class HookConfig:
    """Loaded hook configuration, keyed by event."""
    hooks: dict[HookEvent, list[HookMatcher]] = field(default_factory=dict)
    source: Path | None = None
    _callbacks: dict[HookEvent, list[_CallbackEntry]] = field(
        default_factory=dict, repr=False,
    )

    def register_callback(
        self,
        event: HookEvent,
        callback: Callable,
        name: str = "",
    ):
        """Register a Python callback for *event*.

        Callbacks run **before** shell hooks and have direct access
        to in-process state.  They cannot block execution.
        """
        if event not in self._callbacks:
            self._callbacks[event] = []
        self._callbacks[event].append(_CallbackEntry(
            callback=callback, name=name or callback.__name__,
        ))

    def run(
        self,
        event: HookEvent,
        tool_name: str = "",
        tool_input: dict | None = None,
        tool_output: str = "",
        reason: str = "",
        **kwargs,
    ) -> HookResult:
        """Run all hooks registered for *event*.

        Callback hooks execute first (in registration order), then
        shell hooks.  If any shell hook blocks (exit 2), remaining
        shell hooks are skipped.
        """
        result = HookResult()

        # 1. run callback hooks
        cb_entries = self._callbacks.get(event, [])
        for entry in cb_entries:
            try:
                cb_result = entry.callback(
                    event=event,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_output=tool_output,
                    reason=reason,
                    **kwargs,
                )
                if cb_result is not None:
                    result.data = cb_result
            except Exception as e:
                # callback errors are non-blocking
                print(f"[hooks] Callback {entry.name} error: {e}", file=sys.stderr)

        # 2. run shell hooks
        matchers = self.hooks.get(event, [])
        if not matchers:
            return result

        matched = [h for h in matchers if _matches(h.matcher, tool_name)]
        if not matched:
            return result

        env = _build_env(event, tool_name, tool_input, tool_output, reason)

        for hook in matched:
            hook_result = _exec_hook(hook, env)
            if hook_result.blocked:
                result.blocked = True
                result.message = hook_result.message
                return result
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
    """Check if *tool_name* matches *pattern*."""
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
    elif event == HookEvent.MemorySave:
        env["CORECODER_HOOK_EVENT"] = "MemorySave"
    elif event == HookEvent.MemoryInject:
        env["CORECODER_HOOK_EVENT"] = "MemoryInject"
    return env


# ---------------------------------------------------------------------------
# Hook execution
# ---------------------------------------------------------------------------

def _exec_hook(hook: HookMatcher, env: dict[str, str]) -> HookResult:
    """Execute a single shell hook command and return its result."""
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
        return HookResult(message=f"Hook timed out after {hook.timeout}s")
    except Exception as e:
        return HookResult(message=f"Hook error: {e}")

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()

    if proc.returncode == 2:
        msg = stdout or stderr or "Blocked by hook (exit 2)"
        return HookResult(blocked=True, message=msg)

    if proc.returncode != 0:
        err_msg = stderr or f"Hook exited with code {proc.returncode}"
        return HookResult(message=err_msg)

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
    """Try to parse hook stdout as JSON."""
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
    """Load hooks from ``.corecoder/hooks.json``."""
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
