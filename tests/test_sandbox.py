"""Workspace OS-sandbox integration and safe decision Trace coverage."""

import subprocess
from pathlib import Path

import pytest

from corecoder.policy import Decision, ExecutionPolicy
from corecoder.runtime.workspace import WorkspaceState
from corecoder.tools.bash import BashTool
from corecoder.tools.sandbox import SandboxExecutor
from corecoder.trace import InMemoryTraceSink


def _fake_backend(monkeypatch, *, deny_writes=False):
    calls = []
    real_run = subprocess.run

    monkeypatch.setattr(SandboxExecutor, "_find_backend", lambda _self: "fake-sandbox")

    def run(argv, **kwargs):
        calls.append(argv)
        command = argv[-1]
        profile = argv[2] if argv[0] == "fake-sandbox" else ""
        if command.startswith("cat ../") or command.startswith("cat /") or command == "cat link":
            return subprocess.CompletedProcess(argv, 1, "", "Operation not permitted")
        if deny_writes and argv[0] == "fake-sandbox" and ">" in command and "(allow file-write* (subpath" not in profile:
            return subprocess.CompletedProcess(argv, 1, "", "Operation not permitted")
        return real_run(["/bin/sh", "-c", command], **kwargs)

    monkeypatch.setattr("corecoder.tools.sandbox.subprocess.run", run)
    return calls


def _bash(workspace, trace=None):
    return BashTool(workspace, trace=trace)


def test_workspace_read_write_success(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    calls = _fake_backend(monkeypatch)
    bash = _bash(WorkspaceState(workspace))

    result = bash.execute(command="printf inside > result.txt")

    assert result.status.value == "success"
    assert (workspace / "result.txt").read_text() == "inside"
    command_call = calls[-1]
    assert command_call and command_call[0] == "fake-sandbox"
    assert str(workspace) in command_call[2]


def test_workspace_escape_is_denied(tmp_path, monkeypatch):
    workspace = tmp_path / "repo"
    outside = tmp_path / "outside.txt"
    workspace.mkdir()
    outside.write_text("secret")
    (workspace / "link").symlink_to(outside)
    calls = _fake_backend(monkeypatch)

    # The generated profile grants file access only to the physical workspace;
    # assert all three escape spellings are presented to that OS boundary.
    bash = _bash(WorkspaceState(workspace))
    for command in (
        "cat ../outside.txt",
        f"cat {outside}",
        "cat link",
    ):
        result = bash.execute(command=command)
        assert result.status.value == "error"
    assert all(
        str(workspace) in argv[2]
        for argv in calls
        if argv[0] == "fake-sandbox" and len(argv) > 4
    )
    assert outside.read_text() == "secret"


def test_network_defaults_to_deny(monkeypatch, tmp_path):
    calls = _fake_backend(monkeypatch)
    workspace = WorkspaceState(tmp_path)
    bash = _bash(workspace)

    bash.execute(command="printf ok")

    assert "(allow network*)" not in calls[-1][2]


def test_network_allow_does_not_bypass_policy(monkeypatch, tmp_path):
    _fake_backend(monkeypatch)
    policy = ExecutionPolicy("workspace-write", workspace=tmp_path)
    assert policy.authorize("bash", {"command": "curl https://example.com"}).decision == Decision.DENY

    bash = BashTool(WorkspaceState(tmp_path), network="allow")
    # The explicit setting changes only the OS profile, not policy.authorize.
    assert bash._sandbox.network == "allow"


def test_read_only_and_full_access_modes(monkeypatch, tmp_path):
    calls = _fake_backend(monkeypatch, deny_writes=True)
    read_only = BashTool(WorkspaceState(tmp_path), permission_mode="read-only")
    denied = read_only.execute(command="printf no > readonly.txt")
    assert denied.status.value == "error"
    assert not (tmp_path / "readonly.txt").exists()
    assert "(allow file-write* (subpath" not in calls[-1][2]

    full_access = BashTool(WorkspaceState(tmp_path), permission_mode="full-access")
    allowed = full_access.execute(command="printf yes > full.txt")
    assert allowed.status.value == "success"
    assert (tmp_path / "full.txt").read_text() == "yes"


def test_unavailable_backend_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(SandboxExecutor, "_find_backend", lambda _self: None)
    called = False

    def unexpected_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("sandbox-unavailable command must not start")

    monkeypatch.setattr("corecoder.tools.sandbox.subprocess.run", unexpected_run)
    bash = _bash(WorkspaceState(tmp_path))

    result = bash.execute(command="printf should-not-run")

    assert result.error_type == "SandboxUnavailable"
    assert called is False


def test_unavailable_backend_is_traced(monkeypatch, tmp_path):
    monkeypatch.setattr(SandboxExecutor, "_find_backend", lambda _self: None)
    trace = InMemoryTraceSink()
    bash = BashTool(WorkspaceState(tmp_path), trace=trace)

    bash.execute(command="printf SECRET_TOKEN")

    events = [event for event in trace.events if event["event"] == "sandbox_decision"]
    assert any(event["data"]["result"] == "backend_unavailable" for event in events)


def test_sandbox_trace_is_safe(monkeypatch, tmp_path):
    _fake_backend(monkeypatch)
    trace = InMemoryTraceSink()
    secret = "SECRET_TOKEN"
    bash = BashTool(WorkspaceState(tmp_path), trace=trace)

    bash.execute(command=f"printf {secret}")

    events = [event for event in trace.events if event["event"] == "sandbox_decision"]
    assert events
    safe_keys = {
        "stage", "backend", "workspace", "permission_mode", "network",
        "decision", "result", "exit_code", "error_type",
    }
    for event in events:
        assert set(event["data"]) <= safe_keys
        assert secret not in str(event)
        assert "command" not in event["data"]
