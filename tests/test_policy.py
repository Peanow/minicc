"""Tests for application-level execution policy."""

import pytest

from corecoder.policy import (
    Decision,
    ExecutionPolicy,
    PermissionMode,
    RiskClass,
)


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


def test_workspace_write_requires_approval_for_all_execution(tmp_path):
    denied = ExecutionPolicy("workspace-write", workspace=tmp_path)
    test_decision = denied.authorize("bash", {"command": "pytest -q"})
    assert test_decision.decision == Decision.DENY
    assert test_decision.risk == RiskClass.VALIDATION
    assert denied.authorize(
        "bash", {"command": "python app.py"}
    ).decision == Decision.DENY

    approved = ExecutionPolicy(
        "workspace-write",
        workspace=tmp_path,
        approval_callback=lambda tool, arguments, reason: True,
    )
    decision = approved.authorize("bash", {"command": "python app.py"})
    assert decision.decision == Decision.ALLOW
    assert "user approved" in decision.reason
    assert decision.risk == RiskClass.WORKSPACE_EXECUTION


def test_workspace_write_allows_classified_read_only_shell(tmp_path):
    policy = ExecutionPolicy("workspace-write", workspace=tmp_path)
    result = policy.authorize("bash", {"command": "git diff -- app.py"})

    assert result.decision == Decision.DENY
    assert result.risk == RiskClass.READ_ONLY


def test_read_only_bash_has_small_allowlist(tmp_path):
    policy = ExecutionPolicy("read-only", workspace=tmp_path)
    assert policy.evaluate("bash", {"command": "git status"}).decision == Decision.ALLOW
    assert policy.evaluate("bash", {"command": "python app.py"}).decision == Decision.DENY
    assert policy.evaluate("bash", {"command": "ls | head"}).decision == Decision.DENY


@pytest.mark.parametrize(
    ("command", "risk"),
    [
        ("rg TODO .", RiskClass.READ_ONLY),
        ("sed -n 1,20p app.py", RiskClass.READ_ONLY),
        ("sed -i s/old/new/ app.py", RiskClass.WORKSPACE_EXECUTION),
        ("python verify.py", RiskClass.WORKSPACE_EXECUTION),
        ("pytest -q", RiskClass.VALIDATION),
        ("python -m pytest -q", RiskClass.VALIDATION),
        ("python3 -m unittest", RiskClass.VALIDATION),
        ("git branch feature", RiskClass.WORKSPACE_EXECUTION),
        ("curl https://example.com", RiskClass.NETWORK),
        ("git pull", RiskClass.NETWORK),
        ("pip install package", RiskClass.NETWORK),
        ("npm view package", RiskClass.NETWORK),
        ("rm output.txt", RiskClass.DESTRUCTIVE),
        ("git reset --hard", RiskClass.DESTRUCTIVE),
        ("git branch -D old", RiskClass.DESTRUCTIVE),
        ("find . -delete", RiskClass.DESTRUCTIVE),
        ("find . -exec echo {} ;", RiskClass.SHELL_COMPOSITION),
        ("ls | head", RiskClass.SHELL_COMPOSITION),
        ("custom-tool --flag", RiskClass.UNKNOWN),
    ],
)
def test_shell_risk_classification(command, risk):
    assert ExecutionPolicy.classify_shell(command)[0] == risk
