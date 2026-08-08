"""Tests for the hook system."""

import json
import os
import tempfile
from pathlib import Path

from corecoder.hooks import (
    HookConfig,
    HookEvent,
    HookMatcher,
    HookResult,
    _matches,
    _parse_json_output,
    load_hooks,
)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def test_matches_wildcard():
    assert _matches("*", "Bash") is True
    assert _matches("*", "Write") is True
    assert _matches("*", "") is True


def test_matches_exact():
    assert _matches("Bash", "Bash") is True
    assert _matches("Bash", "Write") is False


def test_matches_pipe_separated():
    assert _matches("Write|Edit", "Write") is True
    assert _matches("Write|Edit", "Edit") is True
    assert _matches("Write|Edit", "Bash") is False


# ---------------------------------------------------------------------------
# JSON parsing
# ---------------------------------------------------------------------------

def test_parse_json_output_valid():
    result = _parse_json_output('{"updated_input": {"file_path": "/new"}}')
    assert result == {"updated_input": {"file_path": "/new"}}


def test_parse_json_output_invalid():
    assert _parse_json_output("not json") is None
    assert _parse_json_output("") is None


def test_parse_json_output_non_dict():
    assert _parse_json_output("[1,2,3]") is None
    assert _parse_json_output('42') is None


# ---------------------------------------------------------------------------
# HookConfig.run — SessionStart
# ---------------------------------------------------------------------------

def test_session_start_hook():
    cfg = HookConfig(hooks={
        HookEvent.SessionStart: [
            HookMatcher(command="echo 'session started'"),
        ],
    })
    result = cfg.run(HookEvent.SessionStart)
    assert not result.blocked
    assert "session started" in result.message


# ---------------------------------------------------------------------------
# HookConfig.run — PreToolUse
# ---------------------------------------------------------------------------

def test_pre_tool_use_pass():
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(matcher="Bash", command="echo ok"),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Bash", tool_input={"command": "ls"})
    assert not result.blocked
    assert "ok" in result.message


def test_pre_tool_use_block():
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(matcher="Bash", command="echo 'blocked'; exit 2"),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Bash", tool_input={"command": "rm -rf /"})
    assert result.blocked is True
    assert "blocked" in result.message


def test_pre_tool_use_modify_input():
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(
                matcher="Write",
                command='echo \'{"updated_input": {"file_path": "/safe/path"}}\'',
            ),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Write", tool_input={"file_path": "/old/path"})
    assert not result.blocked
    assert result.updated_input == {"file_path": "/safe/path"}


def test_pre_tool_use_no_match():
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(matcher="Bash", command="echo 'should not run'; exit 2"),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Write", tool_input={})
    assert not result.blocked


def test_pre_tool_use_non_blocking_error():
    """Exit code != 0 and != 2 is a non-blocking error."""
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(matcher="*", command="echo 'oops' >&2; exit 1"),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Bash", tool_input={})
    assert not result.blocked


# ---------------------------------------------------------------------------
# HookConfig.run — PostToolUse
# ---------------------------------------------------------------------------

def test_post_tool_use_modify_output():
    cfg = HookConfig(hooks={
        HookEvent.PostToolUse: [
            HookMatcher(
                matcher="Bash",
                command='echo \'{"updated_output": "sanitized"}\'',
            ),
        ],
    })
    result = cfg.run(
        HookEvent.PostToolUse,
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_output="sensitive data",
    )
    assert not result.blocked
    assert result.updated_output == "sanitized"


def test_post_tool_use_block():
    cfg = HookConfig(hooks={
        HookEvent.PostToolUse: [
            HookMatcher(matcher="*", command="echo 'denied'; exit 2"),
        ],
    })
    result = cfg.run(
        HookEvent.PostToolUse,
        tool_name="Bash",
        tool_input={},
        tool_output="some output",
    )
    assert result.blocked is True


# ---------------------------------------------------------------------------
# HookConfig.run — Stop
# ---------------------------------------------------------------------------

def test_stop_hook():
    cfg = HookConfig(hooks={
        HookEvent.Stop: [
            HookMatcher(command="echo 'session done'"),
        ],
    })
    result = cfg.run(HookEvent.Stop, reason="done")
    assert not result.blocked
    assert "session done" in result.message


def test_stop_hook_block():
    """Stop hooks can block (though rarely useful)."""
    cfg = HookConfig(hooks={
        HookEvent.Stop: [
            HookMatcher(command="echo 'stop blocked'; exit 2"),
        ],
    })
    result = cfg.run(HookEvent.Stop, reason="done")
    assert result.blocked is True


# ---------------------------------------------------------------------------
# HookConfig.run — timeout
# ---------------------------------------------------------------------------

def test_hook_timeout():
    import sys
    cfg = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(
                matcher="*",
                command=f'"{sys.executable}" -c "import time; time.sleep(10)"',
                timeout=1,
            ),
        ],
    })
    result = cfg.run(HookEvent.PreToolUse, tool_name="Bash", tool_input={})
    assert not result.blocked
    assert "timed out" in result.message


# ---------------------------------------------------------------------------
# HookConfig.run — empty config
# ---------------------------------------------------------------------------

def test_empty_config_no_hooks():
    cfg = HookConfig()
    for event in HookEvent:
        result = cfg.run(event)
        assert not result.blocked
        assert result.message == ""


# ---------------------------------------------------------------------------
# load_hooks — file loading
# ---------------------------------------------------------------------------

def test_load_hooks_from_file():
    config = {
        "PreToolUse": [
            {"matcher": "Write|Edit", "command": "formatter.sh", "timeout": 30},
        ],
        "Stop": [
            {"matcher": "*", "command": "build.sh", "timeout": 120},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        corecoder_dir = Path(tmpdir) / ".corecoder"
        corecoder_dir.mkdir()
        (corecoder_dir / "hooks.json").write_text(json.dumps(config))

        hooks = load_hooks(cwd=tmpdir)
        assert len(hooks.hooks) == 2
        assert len(hooks.hooks[HookEvent.PreToolUse]) == 1
        assert hooks.hooks[HookEvent.PreToolUse][0].matcher == "Write|Edit"
        assert hooks.hooks[HookEvent.PreToolUse][0].timeout == 30
        assert len(hooks.hooks[HookEvent.Stop]) == 1
        assert hooks.hooks[HookEvent.Stop][0].command == "build.sh"


def test_load_hooks_no_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        hooks = load_hooks(cwd=tmpdir)
        assert len(hooks.hooks) == 0


def test_load_hooks_malformed_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        corecoder_dir = Path(tmpdir) / ".corecoder"
        corecoder_dir.mkdir()
        (corecoder_dir / "hooks.json").write_text("not json{{{")
        hooks = load_hooks(cwd=tmpdir)
        assert len(hooks.hooks) == 0  # graceful fallback


def test_load_hooks_unknown_event_ignored():
    config = {
        "UnknownEvent": [{"matcher": "*", "command": "echo hi"}],
        "PreToolUse": [{"matcher": "Bash", "command": "check.sh"}],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        corecoder_dir = Path(tmpdir) / ".corecoder"
        corecoder_dir.mkdir()
        (corecoder_dir / "hooks.json").write_text(json.dumps(config))

        hooks = load_hooks(cwd=tmpdir)
        assert HookEvent.PreToolUse in hooks.hooks
        assert len(hooks.hooks) == 1  # UnknownEvent ignored


def test_load_hooks_default_values():
    config = {
        "PreToolUse": [
            {"command": "check.sh"},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        corecoder_dir = Path(tmpdir) / ".corecoder"
        corecoder_dir.mkdir()
        (corecoder_dir / "hooks.json").write_text(json.dumps(config))

        hooks = load_hooks(cwd=tmpdir)
        h = hooks.hooks[HookEvent.PreToolUse][0]
        assert h.matcher == "*"   # default
        assert h.timeout == 60    # default


# ---------------------------------------------------------------------------
# Integration: Agent + hooks
# ---------------------------------------------------------------------------

def test_agent_default_no_hooks():
    """Agent without hooks arg works the same as before."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM
    llm = LLM(model="test", api_key="test")
    agent = Agent(llm=llm)
    assert agent.hooks.hooks == {}


def test_agent_with_hooks():
    """Agent accepts hooks and they affect tool execution."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM

    hooks = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(matcher="bash", command="echo 'blocked'; exit 2"),
        ],
    })
    llm = LLM(model="test", api_key="test")
    agent = Agent(llm=llm, hooks=hooks)

    # simulate a tool call through _exec_tool
    from corecoder.llm import ToolCall
    tc = ToolCall(id="test", name="bash", arguments={"command": "ls"})
    result = agent._exec_tool(tc)
    assert "Blocked by hook" in result


def test_agent_hook_modify_input():
    """PreToolUse hook can modify tool arguments."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM, ToolCall
    from corecoder.policy import ExecutionPolicy

    hooks = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(
                matcher="bash",
                command='echo \'{"updated_input": {"command": "echo safe"}}\'',
            ),
        ],
    })
    llm = LLM(model="test", api_key="test")
    agent = Agent(
        llm=llm,
        hooks=hooks,
        policy=ExecutionPolicy("full-access"),
    )

    tc = ToolCall(id="test", name="bash", arguments={"command": "rm -rf /"})
    result = agent._exec_tool(tc)
    # the command was modified to "echo safe" by the hook
    assert "safe" in result


def test_agent_rechecks_policy_after_hook_modifies_path(tmp_path):
    """A hook cannot redirect an allowed write outside the workspace."""
    from corecoder.agent import Agent
    from corecoder.llm import LLM, ToolCall
    from corecoder.policy import ExecutionPolicy
    from corecoder.tools.write import WriteFileTool

    outside = tmp_path.parent / "hook-escaped.txt"
    hooks = HookConfig(hooks={
        HookEvent.PreToolUse: [
            HookMatcher(
                matcher="write_file",
                command=(
                    "echo '{\"updated_input\": "
                    f"{{\"file_path\": \"{outside}\"}}}}'"
                ),
            ),
        ],
    })
    agent = Agent(
        llm=LLM(model="test", api_key="test"),
        tools=[WriteFileTool()],
        hooks=hooks,
        policy=ExecutionPolicy("workspace-write", workspace=tmp_path),
    )
    tc = ToolCall(
        id="test",
        name="write_file",
        arguments={"file_path": "inside.txt", "content": "data"},
    )
    result = agent._exec_tool(tc)
    assert "Blocked by policy" in result
    assert not outside.exists()
