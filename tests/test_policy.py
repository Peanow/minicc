"""Tests for application-level execution policy."""

from corecoder.policy import Decision, ExecutionPolicy, PermissionMode


def test_read_only_allows_search_and_denies_writes(tmp_path):
    policy = ExecutionPolicy(PermissionMode.READ_ONLY, workspace=tmp_path)
    assert policy.evaluate("grep", {"pattern": "x"}).decision == Decision.ALLOW
    assert policy.evaluate(
        "write_file", {"file_path": "x.py"}
    ).decision == Decision.DENY


def test_workspace_write_rejects_outside_path(tmp_path):
    workspace = tmp_path / "repo"
    workspace.mkdir()
    policy = ExecutionPolicy("workspace-write", workspace=workspace)
    inside = policy.evaluate("edit_file", {"file_path": "src/app.py"})
    outside = policy.evaluate("edit_file", {"file_path": "../secret.txt"})
    assert inside.decision == Decision.ALLOW
    assert outside.decision == Decision.DENY


def test_workspace_write_rejects_symlink_escape(tmp_path):
    workspace = tmp_path / "repo"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)
    policy = ExecutionPolicy("workspace-write", workspace=workspace)
    result = policy.evaluate("write_file", {"file_path": "link/file.txt"})
    assert result.decision == Decision.DENY


def test_shell_requires_approval_in_workspace_write(tmp_path):
    denied = ExecutionPolicy("workspace-write", workspace=tmp_path)
    assert denied.authorize("bash", {"command": "pytest"}).decision == Decision.DENY

    approved = ExecutionPolicy(
        "workspace-write",
        workspace=tmp_path,
        approval_callback=lambda tool, arguments, reason: True,
    )
    decision = approved.authorize("bash", {"command": "pytest"})
    assert decision.decision == Decision.ALLOW
    assert "user approved" in decision.reason


def test_read_only_bash_has_small_allowlist(tmp_path):
    policy = ExecutionPolicy("read-only", workspace=tmp_path)
    assert policy.evaluate("bash", {"command": "git status"}).decision == Decision.ALLOW
    assert policy.evaluate("bash", {"command": "python app.py"}).decision == Decision.DENY
    assert policy.evaluate("bash", {"command": "ls | head"}).decision == Decision.DENY
